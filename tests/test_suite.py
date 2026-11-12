import contextlib
import copy
import io
import json
import os
import signal
import socket
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import test_xhttp as fixtures
import test_manage as management

xhttp, manage = fixtures.xhttp, management.manage


def add_reality(directory, xray):
    if xray:
        values = dict(line.split(':', 1) for line in subprocess.check_output([xray, 'x25519'], text=True).splitlines() if ':' in line)
        private = values['PrivateKey'].strip()
        public = next(value.strip() for key, value in values.items() if key.startswith('Password'))
    else:
        private, public = 'A' * 43, 'B' * 43
    xhttp.write_private(directory / 'xrk/private_key', private)
    xhttp.write_private(directory / 'xrk/public_key', public)
    xhttp.write_private(directory / 'xrk/short_id', '1234abcd')
    xhttp.write_private(directory / 'server_ip.log', '[2001:db8::10]')
    server = json.loads((directory / 'xr.json').read_text())
    inbound = copy.deepcopy(server['inbounds'][0])
    inbound.update(tag='xhttp-reality', port=18443, listen='::')
    inbound['streamSettings'] = {'network': 'xhttp', 'security': 'reality',
        'realitySettings': {'target': 'www.microsoft.com:443', 'serverNames': ['www.microsoft.com'],
                            'privateKey': private, 'shortIds': ['1234abcd']},
        'xhttpSettings': {'path': '/legacy', 'mode': 'auto'}}
    server['inbounds'].append(inbound)
    xhttp.json_file(directory / 'xr.json', server)


class SuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ConfigTests.setUpClass()

    def setUp(self):
        self.fixture = fixtures.ConfigTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.directory = self.fixture.directory
        self.fixture.produce({})
        add_reality(self.directory, self.fixture.xray)
        self.output = io.StringIO()
        capture = contextlib.redirect_stdout(self.output)
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def produce(self, env=None):
        xhttp.configure(self.directory, env or {}, 'reality')
        xhttp.export(self.directory, 'reality')
        return json.loads((self.directory / 'xhttp-reality-client.json').read_text())

    def test_reality_export_is_complete_and_isolated(self):
        argo_before = (self.directory / 'xhttp-options.json').read_bytes()
        server_before = json.loads((self.directory / 'xr.json').read_text())
        client = self.produce({'reality_path': '/reality-test'})
        server = json.loads((self.directory / 'xr.json').read_text())
        self.assertEqual(server['inbounds'][:-1], server_before['inbounds'][:-1])
        self.assertEqual((self.directory / 'xhttp-options.json').read_bytes(), argo_before)
        inbound = server['inbounds'][-1]
        self.assertEqual(inbound['listen'], '::')
        self.assertNotIn('flow', inbound['settings']['clients'][0])
        outbound = client['outbounds'][0]
        stream = outbound['streamSettings']
        self.assertEqual(stream['security'], 'reality')
        self.assertNotIn('tlsSettings', stream)
        self.assertNotIn('privateKey', stream['realitySettings'])
        self.assertEqual(stream['xhttpSettings']['mode'], 'stream-one')
        self.assertEqual(outbound['settings']['vnext'][0]['address'], '2001:db8::10')
        uri = urlsplit((self.directory / 'xhttp-reality-uri.txt').read_text().strip())
        query = parse_qs(uri.query)
        self.assertEqual(uri.hostname, '2001:db8::10')
        self.assertEqual(uri.port, 18443)
        self.assertEqual(query['pbk'][0], stream['realitySettings']['password'])
        self.assertEqual(query['path'], ['/reality-test'])
        self.assertEqual(json.loads(query['extra'][0]), stream['xhttpSettings']['extra'])
        for name in ('xhttp-reality-options.json', 'xhttp-reality-client.json', 'xrk/private_key'):
            self.assertEqual((self.directory / name).stat().st_mode & 0o777, 0o600)

    def test_real_core_accepts_modes_and_custom_enhancements(self):
        if not self.fixture.xray:
            self.skipTest('XRAY_BINARY required')
        for mode in ('packet-up', 'stream-up', 'stream-one'):
            for mask in ('off', 'tls-fragment'):
                with self.subTest(mode=mode, mask=mask):
                    client = self.produce({'reality_mode': mode, 'reality_finalmask': mask,
                        'reality_xmux': json.dumps(xhttp.XMUX_PRESETS['low-reuse']),
                        'reality_padding_bytes': '100-200', 'reality_max_post_bytes': '524288',
                        'reality_min_post_interval_ms': '10-20', 'reality_fragment_length': '50-100',
                        'reality_fragment_interval': '1-2', 'reality_fragment_count': '3-4'})
                    for name in ('xr.json', 'xhttp-reality-client.json'):
                        result = subprocess.run([self.fixture.xray, 'run', '-test', '-c', str(self.directory / name)], capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    stream = client['outbounds'][0]['streamSettings']
                    self.assertEqual(stream['xhttpSettings']['extra']['scMaxEachPostBytes'], '524288')
                    if mask != 'off':
                        self.assertEqual((self.directory / 'xhttp-reality-uri.txt').read_text(), '')
                        self.assertEqual(stream['finalmask']['tcp'][0]['settings']['lengths'], ['50-100'])

    def test_invalid_profiles_and_ranges(self):
        for values, profile in [({'reality_alpn': 'h3'}, 'reality'),
                ({'reality_download_address': 'down.example.com'}, 'reality'),
                ({'xhttp_padding_bytes': '-1'}, 'argo'), ({'xhttp_max_post_bytes': '0'}, 'argo'),
                ({'xhttp_min_post_interval_ms': '20-10'}, 'argo'),
                ({'xhttp_fragment_count': '1001'}, 'argo'), ({'reality_fragment_length': '0'}, 'reality')]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                xhttp.options(values, profile=profile)

    def test_legacy_reality_tuning_preserves_argo_and_removes_lossy_link(self):
        before = (self.directory / 'xhttp-client.json').read_bytes()
        argo_uri = (self.directory / 'xhttp-uri.txt').read_text()
        (self.directory / 'jhsub.txt').write_text(argo_uri + 'vless://797024ab-d2a8-41ed-91d8-b615917fcac5@198.51.100.10:18443?security=reality&type=xhttp#old-vl-xhttp-reality-enc-host\n')
        with patch.object(manage.sys, 'platform', 'linux'), patch.object(manage, 'checked_core'), patch.object(manage, 'restart_xray'):
            manage.change_mode(self.directory, 'packet-up', profile='reality',
                               updates={'reality_xmux': '{"maxConnections":4}', 'reality_finalmask': 'tls-fragment'})
        self.assertEqual((self.directory / 'xhttp-client.json').read_bytes(), before)
        self.assertEqual((self.directory / 'jhsub.txt').read_text(), argo_uri)
        client = json.loads((self.directory / 'xhttp-reality-client.json').read_text())
        self.assertEqual(client['outbounds'][0]['streamSettings']['xhttpSettings']['path'], '/legacy')
        self.assertIn('finalmask', client['outbounds'][0]['streamSettings'])
        with patch.object(manage, 'checked_core'):
            manage.export_client(self.directory, str(self.directory / 'reality-download.json'), profile='reality')

    def test_dual_wizard_passes_independent_validated_options(self):
        inputs = ['198.51.100.10', '', '', 'up.example.com', '', '',
                  '', '2', '2', 'n', '', '3', '1', 'n', 'y']
        with patch.object(manage.sys.stdin, 'isatty', return_value=True), patch.object(manage.sys, 'platform', 'linux'), \
             patch('builtins.input', side_effect=inputs), patch.object(manage.getpass, 'getpass', return_value='eyHiddenToken'), \
             patch.dict(os.environ, {'vmpt': '12345', 'argo': 'vmpt', 'xhttp_alpn': 'h3'}), \
             patch.object(manage, 'run_installer', return_value=0) as install:
            self.assertEqual(manage.suite_setup(self.directory / 'new', stack='both'), 0)
        env = install.call_args.args[0]
        self.assertEqual((env['xhpt'], env['vxpt'], env['argo']), ('443', '8080', 'vxpt'))
        self.assertEqual((env['reality_mode'], env['xhttp_mode']), ('stream-one', 'packet-up'))
        self.assertEqual(env['reality_finalmask'], 'tls-fragment')
        self.assertEqual(json.loads(env['xhttp_xmux'])['maxConnections'], 4)
        self.assertNotIn('vmpt', env)
        self.assertNotIn('eyHiddenToken', self.output.getvalue())

    def test_tuning_preview_keeps_files_and_services(self):
        self.produce()
        before = (self.directory / 'xr.json').read_bytes()
        with patch.object(manage.sys.stdin, 'isatty', return_value=True), \
             patch('builtins.input', side_effect=['2', '1', '2', 'n']), patch.object(manage, 'restart_xray') as restart:
            manage.tune(self.directory, 'reality', dry_run=True)
        self.assertEqual((self.directory / 'xr.json').read_bytes(), before)
        restart.assert_not_called()
        self.assertIn('仅预览', self.output.getvalue())

    def test_reality_only_cli_selects_profile(self):
        if not self.fixture.xray:
            self.skipTest('XRAY_BINARY required')
        self.produce()
        server = json.loads((self.directory / 'xr.json').read_text())
        server['inbounds'] = [i for i in server['inbounds'] if i['tag'] != 'vless-xhttp']
        xhttp.json_file(self.directory / 'xr.json', server)
        (self.directory / 'xray').symlink_to(self.fixture.xray)
        destination = self.directory / 'output.json'
        result = subprocess.run(['bash', str(fixtures.ROOT / 'argosbx.sh'), 'export', str(destination)],
            env=dict(os.environ, ARGOSBX_STATE_DIR=str(self.directory)), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(destination.read_text())['outbounds'][0]['streamSettings']['security'], 'reality')

    def test_real_restart_preserves_both_listeners(self):
        if not self.fixture.xray or not sys.platform.startswith('linux'):
            self.skipTest('Real restart requires Linux and XRAY_BINARY')
        self.produce()
        (self.directory / 'xray').symlink_to(self.fixture.xray)
        server = json.loads((self.directory / 'xr.json').read_text())
        for inbound in server['inbounds']:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                inbound['port'] = probe.getsockname()[1]
        xhttp.json_file(self.directory / 'xr.json', server)
        process = subprocess.Popen([str(self.directory / 'xray'), 'run', '-c', str(self.directory / 'xr.json')],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                try:
                    manage.probe_origin(server['inbounds'][-1], self.directory)
                    break
                except OSError:
                    time.sleep(.1)
            manage.change_mode(self.directory, 'packet-up', profile='reality', finalmask='tls-fragment')
            current = json.loads((self.directory / 'xr.json').read_text())
            self.assertEqual(current['inbounds'][:-1], server['inbounds'][:-1])
            for inbound in current['inbounds']:
                manage.probe_origin(inbound, self.directory)
        finally:
            for pid in manage.pids(self.directory, 'xray', 'xr.json'):
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            process.wait(timeout=5)
