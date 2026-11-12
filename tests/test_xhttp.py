import contextlib
import base64
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
import platform
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("xhttp", ROOT / "lib/xhttp_config.py")
xhttp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xhttp)


class OptionsTests(unittest.TestCase):
    def test_default_and_stable_path(self):
        first = xhttp.options({})
        self.assertEqual(first["mode"], "packet-up")
        self.assertEqual(first["alpn"], "h2")
        self.assertEqual(first["xmux"], xhttp.XMUX)
        self.assertEqual(xhttp.options({}, first), first)
        self.assertNotEqual(xhttp.options({})["path"], first["path"])

    def test_invalid_combinations(self):
        for env in [
            {"xhttp_alpn": "h3", "xhttp_finalmask": "tls-fragment"},
            {"xhttp_mode": "stream-one", "xhttp_download_address": "down.example.com"},
            {"xhttp_mode": "stream-one", "xhttp_alpn": "h3"},
            {"xhttp_mode": "auto"},
            {"xhttp_mode": "stream-up", "xhttp_alpn": "h3"},
            {"xhttp_path": '/bad"path'},
            {"xhttp_xmux": '{"maxConcurrency":16,"maxConnections":2}'},
            {"xhttp_xmux": '{"maxConcurrency":"32-16"}'},
            {"xhttp_xmux": '{"hKeepAlivePeriod":"1-5"}'},
            {"xhttp_xmux": '{"unknown":10}'},
            {"xhttp_xmux": '[]'},
            {"xhttp_xmux": '{"maxConcurrency":true}'},
            {"xhttp_download_address": "192.0.2.1"},
            {"xhttp_download_address": "down.example.com", "xhttp_download_port": "65536"},
            {"xhttp_download_port": "443"},
            {"xhttp_address": "https://example.com/path"},
            {"xhttp_download_address": "down.example.com", "xhttp_download_alpn": "h3",
             "xhttp_download_finalmask": "tls-fragment"},
        ]:
            with self.subTest(env=env), self.assertRaises(ValueError):
                xhttp.options(env)

    def test_streaming_modes_and_saved_conflicts(self):
        for mode in xhttp.STREAM_MODES:
            self.assertEqual(xhttp.options({"xhttp_mode": mode})["mode"], mode)
        saved = xhttp.options({"xhttp_download_address": "down.example.com"})
        with self.assertRaisesRegex(ValueError, "stream-one"):
            xhttp.options({"xhttp_mode": "stream-one"}, saved)
        cleared = xhttp.options({"xhttp_mode": "stream-one", "xhttp_download_address": ""}, saved)
        self.assertFalse(cleared.get("download_address"))

    def test_xmux_partial_overrides_preserve_limits(self):
        actual = xhttp.options({"xhttp_xmux": '{"maxConnections":2}'})["xmux"]
        self.assertEqual(actual["maxConcurrency"], 0)
        self.assertEqual(actual["maxConnections"], 2)
        self.assertEqual(actual["hMaxRequestTimes"], "600-900")

    def test_disable_saved_download(self):
        previous = xhttp.options({"xhttp_download_address": "down.example.com",
                                  "xhttp_download_finalmask": "tls-fragment"})
        updated = xhttp.options({"xhttp_download_address": ""}, previous)
        self.assertFalse(updated.get("download_address"))
        self.assertEqual(updated["download_finalmask"], "off")

    def test_h3_upload_with_masked_h2_download(self):
        opts = xhttp.options({"xhttp_alpn": "h3", "xhttp_download_address": "192.0.2.10",
            "xhttp_download_servername": "down.example.com", "xhttp_download_finalmask": "tls-fragment"})
        stream = xhttp.stream(opts, "up.example.com")
        down = stream["xhttpSettings"]["extra"]["downloadSettings"]
        self.assertNotIn("finalmask", stream)
        self.assertEqual(down["finalmask"], xhttp.FRAGMENT)
        self.assertEqual(down["xhttpSettings"]["path"], stream["xhttpSettings"]["path"])
        self.assertEqual(down["tlsSettings"]["serverName"], "down.example.com")


class ConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.xray = os.environ.get("XRAY_BINARY")
        if cls.xray:
            keys = subprocess.check_output([cls.xray, "vlessenc"], text=True)
            cls.decryption = re.findall(r'"decryption": "([^"]+)"', keys)[1]
            cls.encryption = re.findall(r'"encryption": "([^"]+)"', keys)[1]
        else:
            cls.decryption = "mlkem768x25519plus.native.600s.test"
            cls.encryption = "mlkem768x25519plus.native.0rtt.test"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        (self.directory / "xrk").mkdir()
        (self.directory / "xrk/enkey").write_text(self.encryption)
        (self.directory / "sbargoym.log").write_text("up.example.com")
        self.original = {"inbounds": [{"tag": "vless-xhttp", "listen": "::", "port": 18080,
            "protocol": "vless", "settings": {"clients": [{
                "id": "797024ab-d2a8-41ed-91d8-b615917fcac5", "flow": "xtls-rprx-vision"}],
                "decryption": self.decryption}, "streamSettings": {"network": "xhttp"}},
            {"tag": "unrelated", "listen": "127.0.0.1", "port": 18081, "protocol": "socks"}],
            "outbounds": [{"protocol": "freedom"}]}
        (self.directory / "xr.json").write_text(json.dumps(self.original))

    def produce(self, env):
        xhttp.configure(self.directory, env)
        with contextlib.redirect_stdout(io.StringIO()):
            xhttp.export(self.directory)
        return json.loads((self.directory / "xhttp-client.json").read_text())

    def test_roundtrip_and_private_files(self):
        client = self.produce({"xhttp_address": "2001:db8::1", "xhttp_path": "/some-path"})
        server = json.loads((self.directory / "xr.json").read_text())
        self.assertEqual(server["inbounds"][1], self.original["inbounds"][1])
        self.assertEqual(server["inbounds"][0]["listen"], "127.0.0.1")
        self.assertNotIn("flow", server["inbounds"][0]["settings"]["clients"][0])
        uri = urlsplit((self.directory / "xhttp-uri.txt").read_text().strip())
        self.assertEqual(uri.hostname, "2001:db8::1")
        query = parse_qs(uri.query)
        stream = client["outbounds"][0]["streamSettings"]
        self.assertEqual(json.loads(query["extra"][0]), stream["xhttpSettings"]["extra"])
        self.assertEqual(query["encryption"][0], self.encryption)
        self.assertEqual(query["path"], ["/some-path"])
        for file in ["xr.json", "xhttp-options.json", "xhttp-client.json", "xhttp-uri.txt"]:
            self.assertEqual((self.directory / file).stat().st_mode & 0o777, 0o600)

    def test_mask_has_no_lossy_uri(self):
        client = self.produce({"xhttp_finalmask": "tls-fragment"})
        self.assertIn("finalmask", client["outbounds"][0]["streamSettings"])
        self.assertEqual((self.directory / "xhttp-uri.txt").read_text(), "")

    def test_invalid_update_preserves_current_config(self):
        self.produce({})
        before = (self.directory / "xr.json").read_bytes()
        with self.assertRaises(ValueError):
            xhttp.configure(self.directory, {"xhttp_xmux": "bad json"})
        self.assertEqual((self.directory / "xr.json").read_bytes(), before)

    def test_streaming_origin_export_and_switch_back(self):
        original_certificate = None
        for mode in xhttp.STREAM_MODES:
            client = self.produce({"xhttp_mode": mode})
            server = json.loads((self.directory / "xr.json").read_text())["inbounds"][0]["streamSettings"]
            self.assertEqual(server["security"], "tls")
            self.assertEqual(server["tlsSettings"]["alpn"], ["h2"])
            self.assertEqual(server["xhttpSettings"]["extra"]["noSSEHeader"], mode == "stream-one")
            self.assertFalse(client["outbounds"][0]["streamSettings"]["xhttpSettings"]["extra"]["noGRPCHeader"])
            query = parse_qs(urlsplit((self.directory / "xhttp-uri.txt").read_text().strip()).query)
            self.assertEqual(query["mode"], [mode])
            self.assertFalse(json.loads(query["extra"][0])["noGRPCHeader"])
            ingress = json.loads((self.directory / "xhttp-tunnel-ingress.json").read_text())
            self.assertEqual(ingress["service"], "https://127.0.0.1:18080")
            self.assertEqual(ingress["originRequest"], {"http2Origin": True, "noTLSVerify": False,
                "originServerName": "localhost", "matchSNItoHost": False,
                "caPool": str(self.directory.resolve() / "xhttp-origin.crt")})
            for filename in ("xhttp-origin.crt", "xhttp-origin.key", "xhttp-tunnel-ingress.json"):
                self.assertEqual((self.directory / filename).stat().st_mode & 0o777, 0o600)
            certificate = (self.directory / "xhttp-origin.crt").read_bytes()
            if original_certificate:
                self.assertEqual(certificate, original_certificate)
            original_certificate = certificate
        self.produce({"xhttp_mode": "packet-up"})
        server = json.loads((self.directory / "xr.json").read_text())["inbounds"][0]["streamSettings"]
        self.assertEqual(server["security"], "none")
        self.assertNotIn("tlsSettings", server)
        ingress = json.loads((self.directory / "xhttp-tunnel-ingress.json").read_text())
        self.assertEqual(ingress["service"], "http://127.0.0.1:18080")
        self.assertEqual(ingress["originRequest"], {"http2Origin": False, "noTLSVerify": False})

    def test_incomplete_origin_credentials_preserve_current_config(self):
        self.produce({"xhttp_mode": "stream-up"})
        before = (self.directory / "xr.json").read_bytes()
        (self.directory / "xhttp-origin.key").unlink()
        with self.assertRaisesRegex(ValueError, "私钥缺失"):
            self.produce({"xhttp_mode": "stream-one"})
        self.assertEqual((self.directory / "xr.json").read_bytes(), before)

    def test_core_accepts_all_combinations(self):
        if not self.xray:
            self.skipTest("Set XRAY_BINARY for real core validation")
        combinations = [{}, {"xhttp_alpn": "h3"},
            {"xhttp_xmux": '{"maxConnections":2}'}, {"xhttp_finalmask": "tls-fragment"},
            {"xhttp_download_address": "down.example.com"},
            {"xhttp_alpn": "h3", "xhttp_download_address": "down.example.com",
             "xhttp_download_finalmask": "tls-fragment"},
            {"xhttp_mode": "stream-up"}, {"xhttp_mode": "stream-one"},
            {"xhttp_mode": "stream-up", "xhttp_download_address": "down.example.com",
             "xhttp_finalmask": "tls-fragment", "xhttp_download_finalmask": "tls-fragment"},
            {"xhttp_mode": "stream-one", "xhttp_finalmask": "tls-fragment"}]
        for env in combinations:
            with self.subTest(env=env):
                (self.directory / "xhttp-options.json").unlink(missing_ok=True)
                self.produce(env)
                for file in ["xr.json", "xhttp-client.json"]:
                    result = subprocess.run([self.xray, "run", "-test", "-c", str(self.directory / file)],
                                            text=True, capture_output=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_real_installer_templates(self):
        if not self.xray or platform.system() != "Linux":
            self.skipTest("Linux installer rendering is checked in CI with XRAY_BINARY")
        (self.directory / "xray").symlink_to(self.xray)
        (self.directory / "xrk/dekey").write_text(self.decryption)
        for entry, mode in ((entry, mode) for entry in [ROOT / "argosbx.sh", ROOT / "container/nodejs/start.sh"]
                            for mode in ("packet-up", *xhttp.STREAM_MODES)):
            with self.subTest(entry=entry, mode=mode):
                source = entry.read_text()
                fragments = []
                for start, end in [("insuuid(){", "installxray(){"), ("installxray(){", "installsb(){"),
                                   ("xrsbout(){", "ins(){")]:
                    fragments.append(source[source.index(start):source.index(end)])
                functions = "\n".join(fragments).replace("$HOME/agsbx", "$ARGOSBX_STATE_DIR")
                env = dict(os.environ, ARGOSBX_STATE_DIR=str(self.directory), argo="vxpt", vxp="yes",
                    vxpt="18080", port_vx="18080", uuid="797024ab-d2a8-41ed-91d8-b615917fcac5",
                    pvk=base64.b64encode(bytes(range(32))).decode(), wpv6="2606:4700:110::1", res="[1,2,3]",
                    xip='"0.0.0.0/0", "::/0"', x1outtag="direct", x2outtag="direct", xsdns="8.8.8.8",
                    xendip="162.159.192.1", xryx="ForceIPv4", wxryx="ForceIPv4", xhttp_mode=mode)
                script = 'source "$1"\n' + functions + '\nnohup(){ :; }; pidof(){ return 1; }; installxray; xrsbout'
                result = subprocess.run(["bash", "-c", script, "test", str(ROOT / "lib/argo.sh")],
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads((self.directory / "xr.json").read_text())["inbounds"][0]["listen"],
                                 "127.0.0.1")
                actual = json.loads((self.directory / "xr.json").read_text())["inbounds"][0]
                self.assertEqual(actual["streamSettings"]["security"], "none" if mode == "packet-up" else "tls")


class FixedTunnelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def shell(self, command, **variables):
        env = {k: v for k, v in os.environ.items() if k not in ("argo", "agn", "agk", "agproto", "agqc", "vxpt")}
        env.update(ARGOSBX_STATE_DIR=str(self.directory), **variables)
        return subprocess.run(["bash", "-c", 'source "$1"; ' + command, "test", str(ROOT / "lib/argo.sh")],
                              env=env, capture_output=True, text=True)

    def test_missing_or_temporary_credentials_rejected(self):
        for values in [dict(argo="vxpt", vxpt="8080"), dict(argo="vxpt", vxpt="", agn="up.example.com"),
                       dict(argo="vxpt", vxpt="", agn="a.TRYCLOUDFLARE.com", agk="eytest"),
                       dict(argo="bad", agn="up.example.com", agk="eytest"),
                       dict(argo="vxpt", vxpt="", agn="up.example.com", agk="eytest", agproto="bad"),
                       dict(argo="vxpt", agn="up.example.com", agk="eytest")]:
            with self.subTest(values=values):
                self.assertNotEqual(self.shell("argo_validate", **values).returncode, 0)

    def test_launcher_and_restart_never_fall_back(self):
        result = self.shell("argo_store", argo="vxpt", vxpt="8080", agn="up.example.com", agk="eyTestToken", agproto="quic")
        self.assertEqual(result.returncode, 0, result.stderr)
        launcher = self.directory / "argo-run"
        self.assertNotIn("eyTestToken", launcher.read_text())
        self.assertEqual((self.directory / "sbargotoken.log").stat().st_mode & 0o777, 0o600)
        fake = self.directory / "cloudflared"
        fake.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        fake.chmod(0o700)
        called = subprocess.check_output([str(launcher)], text=True)
        self.assertIn("--token-file\n", called)
        self.assertIn("quic\n", called)
        self.assertNotIn("eyTestToken", called)
        (self.directory / "sbargotoken.log").unlink()
        self.assertNotEqual(subprocess.run([str(launcher)], capture_output=True).returncode, 0)
        self.assertNotEqual(self.shell("argo_restart").returncode, 0)

    def test_no_quick_tunnel_in_any_entrypoint(self):
        for file in [ROOT / "argosbx.sh", ROOT / "container/nodejs/start.sh", ROOT / "lib/argo.sh"]:
            self.assertNotIn("tunnel --url", file.read_text())
            subprocess.run(["bash", "-n", str(file)], check=True)

    def test_saved_conflict_rejected_in_preflight(self):
        xhttp.json_file(self.directory / "xhttp-options.json",
                       xhttp.options({"xhttp_download_address": "down.example.com"}))
        env = dict(argo="vxpt", vxpt="8080", agn="up.example.com", agk="eyTestToken", xhttp_mode="stream-one")
        result = self.shell("argo_preflight rep", **env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stream-one", result.stderr)
        result = self.shell("argo_preflight rep", **env, xhttp_download_address="")
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
