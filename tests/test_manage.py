import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

import test_xhttp as fixture_module

ROOT, xhttp = fixture_module.ROOT, fixture_module.xhttp

spec = importlib.util.spec_from_file_location('manage', ROOT / 'lib/manage.py')
import sys
sys.path.insert(0, str(ROOT / 'lib'))
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


class ManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture_module.ConfigTests.setUpClass()

    def setUp(self):
        self.fixture = fixture_module.ConfigTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.directory = self.fixture.directory
        self.fixture.produce({})
        (self.directory / 'sbargotoken.log').write_text('eySecretTestToken')
        (self.directory / 'uuid').write_text('797024ab-d2a8-41ed-91d8-b615917fcac5')
        if self.fixture.xray:
            (self.directory / 'xray').symlink_to(self.fixture.xray)
        self.output = io.StringIO()
        self.capture = contextlib.redirect_stdout(self.output)
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)

    def snapshot(self):
        return {name: (self.directory / name).read_bytes() if (self.directory / name).exists() else None
                for name in manage.FILES}

    def test_dry_run_is_read_only(self):
        before = self.snapshot()
        with patch.object(manage, 'restart_xray') as restart:
            manage.change_mode(self.directory, 'stream-up', dry_run=True)
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.directory / '.manage.lock').exists())
        restart.assert_not_called()
        self.assertNotIn('eySecretTestToken', self.output.getvalue())

    def test_switch_preserves_protocols_and_refreshes_subscriptions(self):
        old = json.loads((self.directory / 'xr.json').read_text())
        previous_uri = (self.directory / 'xhttp-uri.txt').read_text()
        for name in ('jh.txt', 'jhsub.txt'):
            (self.directory / name).write_text('trojan://unrelated@example.com:443\n' + previous_uri * 2)
        with patch.object(manage.sys, 'platform', 'linux'), patch.object(manage, 'checked_core'), patch.object(manage, 'restart_xray') as restart:
            manage.change_mode(self.directory, 'stream-up')
        restart.assert_called_once_with(self.directory)
        current = json.loads((self.directory / 'xr.json').read_text())
        self.assertEqual(current['inbounds'][1:], old['inbounds'][1:])
        self.assertEqual(current['outbounds'], old['outbounds'])
        self.assertEqual(current['inbounds'][0]['settings'], old['inbounds'][0]['settings'])
        self.assertEqual(current['inbounds'][0]['port'], old['inbounds'][0]['port'])
        self.assertEqual(current['inbounds'][0]['streamSettings']['security'], 'tls')
        self.assertEqual((self.directory / 'sbargotoken.log').read_text(), 'eySecretTestToken')
        for name in ('jh.txt', 'jhsub.txt'):
            lines = (self.directory / name).read_text().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertTrue(lines[0].startswith('trojan://'))
            self.assertIn('mode=stream-up', lines[1])
        backup = next((self.directory / 'backups').iterdir())
        self.assertEqual(json.loads((backup / 'xr.json').read_text()), old)
        self.assertEqual((backup / 'xr.json').stat().st_mode & 0o777, 0o600)
        self.assertIn(str(self.directory.resolve() / 'xhttp-origin.crt'),
                      (self.directory / 'xhttp-tunnel-ingress.json').read_text())

    def test_validation_failure_keeps_live_files(self):
        before = self.snapshot()
        with patch.object(manage.sys, 'platform', 'linux'), patch.object(manage, 'checked_core', side_effect=ValueError('invalid core')), patch.object(manage, 'restart_xray') as restart:
            with self.assertRaisesRegex(ValueError, 'invalid core'):
                manage.change_mode(self.directory, 'stream-up')
        self.assertEqual(before, self.snapshot())
        restart.assert_not_called()

    def test_restart_failure_rolls_back_and_restarts_old_config(self):
        before = self.snapshot()
        with patch.object(manage.sys, 'platform', 'linux'), patch.object(manage, 'checked_core'), patch.object(manage, 'restart_xray', side_effect=[ValueError('start failed'), None]) as restart:
            with self.assertRaisesRegex(ValueError, 'start failed'):
                manage.change_mode(self.directory, 'stream-one')
        self.assertEqual(before, self.snapshot())
        self.assertEqual(restart.call_count, 2)

    def test_split_and_h3_require_explicit_compatible_choice(self):
        self.fixture.produce({'xhttp_download_address': 'down.example.com'})
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'stream-one'):
            manage.change_mode(self.directory, 'stream-one', dry_run=True)
        self.assertEqual(before, self.snapshot())
        manage.change_mode(self.directory, 'stream-one', disable_split=True, dry_run=True)
        with self.assertRaisesRegex(ValueError, 'h2'):
            manage.change_mode(self.directory, 'stream-up', alpn='h3', dry_run=True)
        self.fixture.produce({'xhttp_finalmask': 'tls-fragment'})
        with self.assertRaises(ValueError):
            manage.change_mode(self.directory, 'packet-up', alpn='h3', dry_run=True)
        manage.change_mode(self.directory, 'packet-up', alpn='h3', finalmask='off', dry_run=True)

    def test_status_and_doctor_hide_credentials(self):
        manage.status(self.directory)
        with patch.object(manage, 'checked_core'), patch.object(manage, 'probe_origin'), patch.object(manage, 'pids', return_value=[123]):
            self.assertEqual(manage.doctor(self.directory), 0)
        for secret in ('eySecretTestToken', self.fixture.encryption, read_uuid(self.directory)):
            self.assertNotIn(secret, self.output.getvalue())
        with patch.object(manage, 'checked_core'), patch.object(manage, 'probe_origin', side_effect=OSError('connection refused')), patch.object(manage, 'pids', return_value=[]):
            self.assertEqual(manage.doctor(self.directory), 1)
        self.assertIn('connection refused', self.output.getvalue())

    def test_export_and_masked_uri(self):
        destination = self.directory / 'download.json'
        with patch.object(manage, 'checked_core'):
            manage.export_client(self.directory, str(destination))
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(destination.read_text())['outbounds'][0]['protocol'], 'vless')
        original = (self.directory / 'xr.json').read_bytes()
        with patch.object(manage, 'checked_core'), self.assertRaisesRegex(ValueError, '不能覆盖'):
            manage.export_client(self.directory, str(self.directory / 'xr.json'))
        self.assertEqual((self.directory / 'xr.json').read_bytes(), original)
        self.fixture.produce({'xhttp_finalmask': 'tls-fragment'})
        with patch.object(manage, 'checked_core'), self.assertRaisesRegex(ValueError, 'FinalMask'):
            manage.export_client(self.directory, uri=True)

    def test_logs_redact_token_and_node_secrets(self):
        text = 'run --token eySecretTestToken\n' + self.fixture.encryption
        (self.directory / 'argo.log').write_text(text)
        with patch.object(manage.shutil, 'which', return_value=None):
            manage.logs(self.directory, 30)
        self.assertNotIn('eySecretTestToken', self.output.getvalue())
        self.assertNotIn(self.fixture.encryption, self.output.getvalue())

    def test_wizard_preview_does_not_install_or_echo_token(self):
        target = self.directory / 'new-install'
        with patch.object(manage.sys.stdin, 'isatty', return_value=True), patch('builtins.input', side_effect=['up.example.com', '', '3']), patch.object(manage.getpass, 'getpass', return_value='eySecretTestToken'), patch.object(manage.subprocess, 'run') as run:
            self.assertEqual(manage.setup(target, dry_run=True), 0)
        self.assertFalse(target.exists())
        run.assert_not_called()
        self.assertIn('stream-up', self.output.getvalue())
        self.assertNotIn('eySecretTestToken', self.output.getvalue())

    def test_upgrade_preserves_configs_and_validates_before_writing(self):
        before = self.snapshot()
        target_bin = self.directory / 'bin'
        def source(url, timeout):
            name = url.split('/main/')[-1]
            return io.BytesIO((ROOT / name).read_bytes())
        with patch.dict(os.environ, {'ARGOSBX_BASE': 'https://test.invalid/main'}), patch.object(manage.urllib.request, 'urlopen', side_effect=source):
            manage.upgrade(self.directory, target_bin)
        self.assertEqual(before, self.snapshot())
        self.assertEqual((target_bin / 'agsbx').read_bytes(), (ROOT / 'argosbx.sh').read_bytes())
        self.assertEqual((target_bin / 'agsbx').stat().st_mode & 0o777, 0o700)
        existing = (target_bin / 'agsbx').read_bytes()
        def broken(url, timeout):
            return io.BytesIO(b'if then' if url.endswith('argo.sh') else b'#!/bin/bash\necho update\n')
        with patch.object(manage.urllib.request, 'urlopen', side_effect=broken), self.assertRaises(subprocess.CalledProcessError):
            manage.upgrade(self.directory, target_bin)
        self.assertEqual((target_bin / 'agsbx').read_bytes(), existing)
        self.assertEqual(before, self.snapshot())

    def test_real_core_switch_and_restart(self):
        if not self.fixture.xray or not sys.platform.startswith('linux'):
            self.skipTest('Real restart is validated on Linux CI with XRAY_BINARY')
        config = json.loads((self.directory / 'xr.json').read_text())
        for inbound in config['inbounds']:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                inbound['port'] = probe.getsockname()[1]
        xhttp.json_file(self.directory / 'xr.json', config)
        process = subprocess.Popen([str(self.directory / 'xray'), 'run', '-c', str(self.directory / 'xr.json')],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                try:
                    manage.probe_origin(config['inbounds'][0], self.directory)
                    break
                except OSError:
                    time.sleep(.1)
            manage.change_mode(self.directory, 'stream-up')
            current = json.loads((self.directory / 'xr.json').read_text())
            manage.probe_origin(current['inbounds'][0], self.directory)
            self.assertEqual(current['inbounds'][1:], config['inbounds'][1:])
            manage.change_mode(self.directory, 'packet-up')
            self.assertEqual(json.loads((self.directory / 'xr.json').read_text())['inbounds'][0]['streamSettings']['security'], 'none')
        finally:
            for pid in manage.pids(self.directory, 'xray', 'xr.json'):
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            process.wait(timeout=5)


def read_uuid(directory):
    return (directory / 'uuid').read_text()


class EntryTests(unittest.TestCase):
    def test_help_unknown_and_noninteractive_do_not_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = {k: v for k, v in os.environ.items() if k not in manage.PROTOCOLS}
            env['ARGOSBX_STATE_DIR'] = temporary
            for args, status in [([], 0), (['help'], 0), (['--help'], 0), (['nonsense'], 2), (['setup'], 1)]:
                result = subprocess.run(['bash', str(ROOT / 'argosbx.sh'), *args], env=env,
                                        cwd=temporary, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, status, result.stdout + result.stderr)
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_pty_wizard_hidden_token_and_defaults(self):
        import pty
        with tempfile.TemporaryDirectory() as temporary:
            pid, fd = pty.fork()
            if pid == 0:
                env = {k: v for k, v in os.environ.items() if k not in manage.PROTOCOLS}
                env['ARGOSBX_STATE_DIR'] = temporary
                os.execvpe('bash', ['bash', str(ROOT / 'argosbx.sh'), 'setup', '--dry-run'], env)
            output = b''
            try:
                for expected, reply in [('固定隧道域名', 'up.example.com\n'), ('输入不显示', 'eyHiddenInTerminal\n'),
                                        ('本机回源端口', '\n'), ('选择传输方案', '\n')]:
                    deadline = time.monotonic() + 10
                    part = b''
                    while expected.encode() not in part:
                        self.assertLess(time.monotonic(), deadline, output.decode(errors='replace'))
                        if select.select([fd], [], [], .1)[0]:
                            data = os.read(fd, 4096)
                            self.assertTrue(data)
                            part += data
                            output += data
                    os.write(fd, reply.encode())
                while select.select([fd], [], [], 5)[0]:
                    try:
                        data = os.read(fd, 4096)
                    except OSError:
                        break
                    if not data:
                        break
                    output += data
                _, status = os.waitpid(pid, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 0, output.decode(errors='replace'))
                self.assertIn('仅预览'.encode(), output)
                self.assertNotIn(b'eyHiddenInTerminal', output)
                self.assertEqual(list(Path(temporary).iterdir()), [])
            finally:
                os.close(fd)
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
