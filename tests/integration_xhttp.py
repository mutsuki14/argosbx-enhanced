"""Real Xray ENC transfer, H2 reverse proxy/split/FinalMask and native H3.

Run with XRAY_BINARY and TEST_PROXY_BINARY. Does not access Cloudflare or a VPS.
"""
import hashlib
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time

from test_xhttp import xhttp, ConfigTests


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_tcp(number):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", number), timeout=.2):
                return
        except OSError:
            time.sleep(.05)
    raise RuntimeError("Listener did not start")


class Echo(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        data = self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def main():
    xray = os.environ["XRAY_BINARY"]
    fixture = os.environ["TEST_PROXY_BINARY"]
    ConfigTests.setUpClass()
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        cert, key = directory / "cert.pem", directory / "key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=up.example.com", "-addext", "subjectAltName=DNS:up.example.com,DNS:down.example.com",
            "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)
        echo = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Echo)
        threading.Thread(target=echo.serve_forever, daemon=True).start()
        try:
            for name, env in [
                ("h2-packet", {}),
                ("h2-fragment", {"xhttp_finalmask": "tls-fragment"}),
                ("split", {"xhttp_download_address": "down.example.com"}),
                ("split-fragment", {"xhttp_download_address": "down.example.com", "xhttp_download_finalmask": "tls-fragment"}),
                ("h3", {"xhttp_alpn": "h3"}),
            ]:
                processes = []
                handles = []
                case = directory / name
                case.mkdir()
                test = ConfigTests()
                test.setUp()
                try:
                    client = test.produce(env)
                    server = json.loads((test.directory / "xr.json").read_text())
                    origin_port, socks_port = port(), port()
                    server["inbounds"] = server["inbounds"][:1]
                    server["inbounds"][0]["port"] = origin_port
                    # Xray defaults reject private destinations; allow only this test echo endpoint.
                    server["outbounds"][0]["settings"] = {"finalRules": [{"action": "allow",
                        "network": "tcp", "ip": ["127.0.0.1"], "port": echo.server_port}]}
                    def launch(args, label):
                        log = open(case / (label + ".log"), "w+")
                        handles.append(log)
                        process = subprocess.Popen(args, stdout=log, stderr=log)
                        processes.append(process)
                        return process
                    stream = client["outbounds"][0]["streamSettings"]
                    if name == "h3":
                        server["inbounds"][0]["streamSettings"].update(security="tls", tlsSettings={
                            "alpn": ["h3"], "certificates": [{"certificateFile": str(cert), "keyFile": str(key)}]})
                        upload_port = origin_port
                    else:
                        ready = case / "proxy.json"
                        launch([fixture, "http://127.0.0.1:" + str(origin_port), str(cert), str(key), str(ready)], "proxy")
                        deadline = time.monotonic() + 8
                        while not ready.exists() and time.monotonic() < deadline:
                            time.sleep(.05)
                        addresses = json.loads(ready.read_text())
                        upload_port, down_port = [int(a.rsplit(":", 1)[1]) for a in addresses]
                    client["inbounds"][0]["port"] = socks_port
                    client["outbounds"][0]["settings"]["vnext"][0].update(address="127.0.0.1", port=upload_port)
                    stream["tlsSettings"]["certificates"] = [{"certificateFile": str(cert), "usage": "verify"}]
                    if "downloadSettings" in stream["xhttpSettings"]["extra"]:
                        down = stream["xhttpSettings"]["extra"]["downloadSettings"]
                        down.update(address="127.0.0.1", port=down_port)
                        down["tlsSettings"]["certificates"] = [{"certificateFile": str(cert), "usage": "verify"}]
                    for label, config in [("server", server), ("client", client)]:
                        path = case / (label + ".json")
                        path.write_text(json.dumps(config))
                        launch([xray, "run", "-c", str(path)], label)
                        if label == "server" and name != "h3":
                            wait_tcp(origin_port)
                        if label == "client":
                            wait_tcp(socks_port)
                    payload = os.urandom(256 * 1024)
                    result = subprocess.run(["curl", "--silent", "--show-error", "--fail", "--noproxy", "",
                        "--socks5-hostname", "127.0.0.1:" + str(socks_port), "--max-time", "15",
                        "--data-binary", "@-", "http://127.0.0.1:" + str(echo.server_port) + "/echo"],
                        input=payload, capture_output=True)
                    assert result.returncode == 0, result.stderr.decode()
                    assert hashlib.sha256(payload).digest() == hashlib.sha256(result.stdout).digest(), "Transfer mismatch"
                    if name != "h3":
                        assert "HTTP/2.0" in (case / "proxy.log").read_text()
                    print(name + ": 256 KiB ENC upload/download passed, TLS verification enabled", flush=True)
                except Exception:
                    for handle in handles:
                        handle.flush()
                        handle.seek(0)
                        print(handle.read())
                    raise
                finally:
                    for process in reversed(processes):
                        process.terminate()
                    for process in processes:
                        process.wait(timeout=5)
                    for handle in handles:
                        handle.close()
                    test.doCleanups()
        finally:
            echo.shutdown()
            echo.server_close()


if __name__ == "__main__":
    main()
