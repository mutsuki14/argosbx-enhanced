import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_manage import manage, ROOT, fixture_module
from test_suite import add_reality


class DiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_module.ConfigTests.setUpClass()

    def setUp(self):
        self.fixture = fixture_module.ConfigTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.directory = self.fixture.directory
        self.fixture.produce({})
        (self.directory / 'sbargotoken.log').write_text('eySecretNeverExportThisToken')
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(patch.object(manage.sys, 'platform', 'linux'))
        self.patches.enter_context(patch.object(manage, 'checked_core'))
        self.patches.enter_context(patch.object(manage, 'probe_origin'))
        self.patches.enter_context(patch.object(manage, 'pids', return_value=[123]))
        self.network = self.patches.enter_context(patch.object(manage, 'probe_public_host'))
        self.certificate = self.patches.enter_context(patch.object(manage, 'probe_origin_certificate'))

    def checks(self, report):
        return {c['profile'] + '/' + c['id']: c for c in report['checks']}

    def snapshot(self):
        return {str(p.relative_to(self.directory)):p.read_bytes()
                for p in self.directory.rglob('*') if p.is_file()}

    def assert_browser_accepts(self, report):
        result = subprocess.run(['node', '-e', "require('./connection-tools').readReport(require('fs').readFileSync(0,'utf8'))"],
                                input=json.dumps(report), text=True, cwd=ROOT, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_read_only_redacted_and_network_opt_in(self):
        before = self.snapshot()
        report = manage.diagnostic_report(self.directory)
        checks = self.checks(report)
        self.assertEqual(before, self.snapshot())
        self.network.assert_not_called()
        self.certificate.assert_not_called()
        self.assertEqual(checks['argo/public_dns']['status'], 'skip')
        self.assertEqual(checks['argo/cloudflare_route']['status'], 'manual')
        self.assertEqual(checks['argo/client_connection']['status'], 'manual')
        text = json.dumps(report)
        for secret in ['eySecretNeverExportThisToken', 'up.example.com', str(self.directory),
                       '797024ab-d2a8-41ed-91d8-b615917fcac5', self.fixture.encryption, '127.0.0.1']:
            self.assertNotIn(secret, text)
        self.assert_browser_accepts(report)

    def test_public_failure_does_not_leak_exception_or_probe_tls(self):
        self.network.side_effect = ValueError('secret: up.example.com 192.0.2.5 token123')
        report = manage.diagnostic_report(self.directory, network=True)
        checks = self.checks(report)
        self.network.assert_called_once_with('up.example.com')
        self.assertEqual(checks['argo/public_dns']['code'], 'dns_failed')
        self.assertEqual(checks['argo/public_tls']['code'], 'dependency_failed')
        self.assertNotIn('token123', json.dumps(report))
        self.assert_browser_accepts(report)

    def test_network_success_runs_dns_then_tls(self):
        report = manage.diagnostic_report(self.directory, network=True)
        self.assertEqual([call.args for call in self.network.call_args_list],
                         [('up.example.com',), ('up.example.com', True)])
        self.assertEqual(self.checks(report)['argo/public_tls']['status'], 'pass')

    def test_timeout_has_fixed_code(self):
        self.network.side_effect = subprocess.TimeoutExpired('sensitive command', 8)
        report = manage.diagnostic_report(self.directory, network=True)
        self.assertEqual(self.checks(report)['argo/public_dns']['code'], 'timeout')
        self.assertNotIn('sensitive', json.dumps(report))

    def test_invalid_tunnel_prevents_network(self):
        (self.directory / 'sbargoym.log').write_text('random.trycloudflare.com')
        report = manage.diagnostic_report(self.directory, network=True)
        self.network.assert_not_called()
        self.assertEqual(self.checks(report)['argo/fixed_tunnel']['status'], 'fail')
        self.assertEqual(self.checks(report)['argo/public_dns']['code'], 'dependency_failed')

    def test_streaming_origin_and_certificate_errors_are_independent(self):
        self.fixture.produce({'xhttp_mode':'stream-up'})
        self.certificate.side_effect = ValueError('private path /secrets/key')
        with patch.object(manage, 'probe_origin', side_effect=OSError('sensitive error')):
            report = manage.diagnostic_report(self.directory)
        checks = self.checks(report)
        self.assertEqual(checks['argo/origin']['status'], 'fail')
        self.assertEqual(checks['argo/origin_certificate']['status'], 'fail')
        self.assertTrue(report['profiles'][0]['origin_tls'])
        self.assertNotIn('/secrets', json.dumps(report))
        self.assert_browser_accepts(report)

    def test_client_h3_and_split_are_manual_checks(self):
        self.fixture.produce({'xhttp_alpn':'h3','xhttp_download_address':'down.example.com'})
        report = manage.diagnostic_report(self.directory, network=True)
        checks = self.checks(report)
        for key in ['http3','split_route','client_connection']:
            self.assertEqual(checks['argo/' + key]['status'], 'manual')
        self.assert_browser_accepts(report)

    def test_missing_corrupt_and_unexpected_configuration_still_exports(self):
        target = self.directory / 'xr.json'
        target.unlink()
        report = manage.diagnostic_report(self.directory)
        self.assertEqual(report['checks'][0]['code'], 'not_installed')
        self.assert_browser_accepts(report)
        for broken in ['not-json', '[]', '{"inbounds":null}', '{"inbounds":[null]}']:
            with self.subTest(broken=broken):
                target.write_text(broken)
                report = manage.diagnostic_report(self.directory)
                self.assertEqual(report['checks'][0]['code'], 'config_invalid')
                self.assert_browser_accepts(report)
        target.write_text('{"inbounds":[{"tag":"vless-xhttp","streamSettings":null}]}')
        self.assertEqual(self.checks(manage.diagnostic_report(self.directory))['argo/profile_config']['status'], 'fail')

    def test_default_report_covers_both_profiles_and_can_select_one(self):
        add_reality(self.directory, self.fixture.xray)
        fixture_module.xhttp.configure(self.directory, {}, 'reality')
        with contextlib.redirect_stdout(io.StringIO()):
            fixture_module.xhttp.export(self.directory, 'reality')
        before = self.snapshot()
        report = manage.diagnostic_report(self.directory)
        self.assertEqual({p['id'] for p in report['profiles']}, {'argo','reality'})
        self.assertEqual(self.checks(report)['reality/reality_target']['status'], 'manual')
        self.assertEqual(before, self.snapshot())
        self.assert_browser_accepts(report)
        selected = manage.diagnostic_report(self.directory, network=True, profile='reality')
        self.assertEqual([p['id'] for p in selected['profiles']], ['reality'])
        self.network.assert_not_called()
        self.assertFalse(any(c['profile']=='argo' for c in selected['checks']))

    def test_absent_profile_and_unsupported_process_checks(self):
        report = manage.diagnostic_report(self.directory, profile='reality')
        self.assertEqual(self.checks(report)['reality/profile_config']['status'], 'fail')
        self.assert_browser_accepts(report)
        with patch.object(manage.sys, 'platform', 'darwin'):
            report = manage.diagnostic_report(self.directory)
        self.assertEqual(self.checks(report)['server/xray_process']['code'], 'unsupported_platform')

    def test_private_atomic_file_and_protected_destinations(self):
        report = manage.diagnostic_report(self.directory)
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stderr(io.StringIO()):
            output = Path(temp) / 'report.json'
            self.assertEqual(manage.save_diagnostic_report(self.directory, report, str(output)), 0)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(output.read_text()), report)
            self.assertEqual(manage.save_diagnostic_report(self.directory, report, str(output)), 0)
            output.write_text('unrelated content')
            with self.assertRaisesRegex(ValueError, '不是诊断报告'):
                manage.save_diagnostic_report(self.directory, report, str(output))
            self.assertEqual(output.read_text(), 'unrelated content')
            link = Path(temp) / 'link.json'
            link.symlink_to(output)
            with self.assertRaisesRegex(ValueError, '符号链接'):
                manage.save_diagnostic_report(self.directory, report, str(link))
            with self.assertRaisesRegex(ValueError, '配置目录之外'):
                manage.save_diagnostic_report(self.directory, report, str(self.directory / 'xr.json'))

    def test_failure_report_is_saved_and_stdout_is_pure_json(self):
        (self.directory / 'xr.json').unlink()
        report = manage.diagnostic_report(self.directory)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = manage.save_diagnostic_report(self.directory, report, '-')
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(output.getvalue()), report)
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stderr(io.StringIO()):
            path = Path(temp) / 'report.json'
            self.assertEqual(manage.save_diagnostic_report(self.directory, report, str(path)), 1)
            self.assertTrue(path.exists())

    def test_cli_without_installation_generates_parseable_report(self):
        entries = [['python3', str(ROOT/'lib/manage.py')], ['bash', str(ROOT/'argosbx.sh')]]
        for entry in entries:
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as temp:
                result = subprocess.run([*entry, 'doctor', '--report'],
                                        capture_output=True, text=True, env={**os.environ, 'ARGOSBX_STATE_DIR':temp})
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stderr, '')
                report = json.loads(result.stdout)
                self.assertEqual(report['checks'][0]['code'], 'not_installed')
                self.assertEqual(list(Path(temp).iterdir()), [])
                self.assert_browser_accepts(report)



if __name__ == '__main__':
    unittest.main()
