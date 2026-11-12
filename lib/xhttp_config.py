#!/usr/bin/env python3
"""Fixed-tunnel XHTTP configuration and lossless Xray client export (stdlib only)."""
import copy
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import subprocess
import sys
import platform
import tempfile
import urllib.request
import zipfile
from urllib.parse import quote, urlencode


XMUX = {"maxConcurrency": "16-32", "maxConnections": 0,
        "cMaxReuseTimes": 0, "hMaxRequestTimes": "600-900",
        "hMaxReusableSecs": "1800-3000", "hKeepAlivePeriod": 0}
FRAGMENT = {"tcp": [{"type": "fragment", "settings": {
    "packets": "tlshello", "lengths": ["100-200"],
    "delays": ["0-1"], "maxSplit": "2-3"}}]}
FIELDS = ("mode", "alpn", "path", "xmux", "finalmask", "address",
          "download_address", "download_port", "download_servername",
          "download_host", "download_alpn", "download_finalmask")
XRAY_VERSION = "v26.11.9"
STREAM_MODES = ("stream-up", "stream-one")
XRAY_ARCHIVES = {
    "x86_64": ("64", "b651f7e1d9966ee2c1b1ee1bf8b52c72771824d3065dce96bbc8bcc19ed95f82"),
    "aarch64": ("arm64-v8a", "64ed6858982a7f5eb85d88b811089063bd4f17561f4c8f44e0f1dc8e6f6430be"),
    "arm64": ("arm64-v8a", "64ed6858982a7f5eb85d88b811089063bd4f17561f4c8f44e0f1dc8e6f6430be"),
}


def install_xray(directory):
    require(platform.system() == "Linux", "安装脚本仅用于 Linux")
    require(platform.machine() in XRAY_ARCHIVES, "不支持的 CPU 架构")
    arch, expected = XRAY_ARCHIVES[platform.machine()]
    url = "https://github.com/XTLS/Xray-core/releases/download/" + XRAY_VERSION + "/Xray-linux-" + arch + ".zip"
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = response.read()
    require(hashlib.sha256(payload).hexdigest() == expected, "Xray 下载校验失败")
    target = Path(directory) / "xray"
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        binary = archive.read("xray")
    pending = target.with_suffix(".tmp")
    pending.write_bytes(binary)
    pending.chmod(0o700)
    pending.replace(target)
    print("已安装官方 Xray " + XRAY_VERSION + "（SHA-256 已验证）")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def host(value, field):
    require(isinstance(value, str) and bool(value), field + " 不能为空")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        require(len(value) <= 253 and all(re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", part)
            for part in value.split(".")), field + " 必须为域名或 IP（不含协议、端口、方括号）")
    return value


def value_range(value, field, negative=False):
    if negative and isinstance(value, int) and not isinstance(value, bool):
        require(-1 <= value <= 2147483647, field + " 超出范围")
        return (value, value)
    require(not isinstance(value, bool) and isinstance(value, (str, int)), field + " 必须为整数或范围")
    require(re.fullmatch(r"\d+(?:-\d+)?", str(value)) is not None, field + " 必须为非负整数或范围")
    parts = [int(x) for x in str(value).split("-")]
    require(0 <= parts[0] <= parts[-1] <= 2147483647, field + " 范围无效")
    return parts[0], parts[-1]


def options(env, previous=None):
    opts = dict(previous or {})
    if env.get("xhttp_download_address") == "":
        for key in list(opts):
            if key.startswith("download_"):
                del opts[key]
    for field in FIELDS:
        key = "xhttp_" + field
        if key in env:
            opts[field] = env[key]
    opts.setdefault("mode", "packet-up")
    opts.setdefault("alpn", "h2")
    opts.setdefault("path", "/" + secrets.token_hex(16))
    opts.setdefault("xmux", copy.deepcopy(XMUX))
    opts.setdefault("finalmask", "off")
    opts.setdefault("download_alpn", "h2")
    opts.setdefault("download_finalmask", "off")
    require(opts["mode"] in ("packet-up", *STREAM_MODES),
            "xhttp_mode 只能为 packet-up、stream-up 或 stream-one")
    require(opts["alpn"] in ("h2", "h3"), "xhttp_alpn 只能为 h2 或 h3")
    if opts["mode"] in STREAM_MODES:
        require(opts["alpn"] == "h2", "固定 Argo 流式模式要求客户端使用 h2；H3 请使用 packet-up")
    require(opts["mode"] != "stream-one" or not opts.get("download_address"),
            "stream-one 在同一请求中双向传输，不能配置上下行分离；请清空 xhttp_download_address 或使用 stream-up")
    require(re.fullmatch(r"/[A-Za-z0-9/_-]{1,200}", opts["path"]) is not None,
            "xhttp_path 必须以 / 开头，仅含字母、数字、/、_、-，最多 201 字符")
    if isinstance(opts["xmux"], str):
        opts["xmux"] = json.loads(opts["xmux"])
    require(isinstance(opts["xmux"], dict), "xhttp_xmux 必须为 JSON 对象")
    require(not set(opts["xmux"]) - set(XMUX), "xhttp_xmux 含未知字段")
    # Supplying one field disables core defaults: explicitly fill the others.
    xmux = dict(XMUX)
    xmux.update(opts["xmux"])
    if "maxConnections" in opts["xmux"] and "maxConcurrency" not in opts["xmux"]:
        xmux["maxConcurrency"] = 0
    ranges = {k: value_range(v, k, k == "hKeepAlivePeriod") for k, v in xmux.items()}
    require(not (ranges["maxConnections"][1] and ranges["maxConcurrency"][1]),
            "XMUX maxConnections 与 maxConcurrency 不能同时非零")
    require(isinstance(xmux["hKeepAlivePeriod"], int), "hKeepAlivePeriod 必须为整数")
    opts["xmux"] = xmux
    if opts.get("address"):
        host(opts["address"], "xhttp_address")
    for prefix in ("", "download_"):
        mask = opts[prefix + "finalmask"]
        require(mask in ("off", "tls-fragment"), "FinalMask 只支持 off 或 tls-fragment")
        require(opts[prefix + "alpn"] in ("h2", "h3"), prefix + "alpn 只能为 h2 或 h3")
        require(mask == "off" or opts[prefix + "alpn"] == "h2",
                "TLS 分片仅支持 TCP/H2，不能与同一方向的 H3 同用")
    if opts.get("download_address"):
        address = host(opts["download_address"], "xhttp_download_address")
        sni = opts.get("download_servername") or address
        try:
            ipaddress.ip_address(sni)
        except ValueError:
            pass
        else:
            raise ValueError("下行地址为 IP 时必须填写证书域名 xhttp_download_servername")
        opts["download_servername"] = host(sni, "xhttp_download_servername")
        opts["download_host"] = host(opts.get("download_host") or sni, "xhttp_download_host")
        port = str(opts.get("download_port") or 443)
        require(port.isdigit() and 1 <= int(port) <= 65535, "下行端口必须为 1-65535")
        opts["download_port"] = int(port)
    else:
        require(not any(opts.get(k) for k in ("download_port", "download_host", "download_servername"))
                and opts["download_finalmask"] == "off", "下行设置需要 xhttp_download_address")
    return opts


def write_private(path, content):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(content)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def json_file(path, value):
    write_private(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def saved_options(directory, env):
    saved = Path(directory) / "xhttp-options.json"
    return options(env, json.loads(saved.read_text()) if saved.exists() else None)


def origin_certificate(directory):
    """Persist a loopback-only self-signed trust anchor; never disable TLS verification."""
    directory = Path(directory).resolve()
    cert, key = directory / "xhttp-origin.crt", directory / "xhttp-origin.key"
    require(cert.exists() == key.exists(), "本机回源证书或私钥缺失，请恢复 xhttp-origin.crt/key 后重试")
    if cert.exists():
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert), str(key))
        current = subprocess.run(["openssl", "x509", "-checkend", "86400", "-noout", "-in", str(cert)],
                                 capture_output=True)
        if current.returncode == 0:
            subprocess.run(["openssl", "verify", "-CAfile", str(cert), "-verify_hostname", "localhost",
                            "-purpose", "sslserver", str(cert)], check=True, capture_output=True)
            cert.chmod(0o600)
            key.chmod(0o600)
            return cert, key
    with tempfile.TemporaryDirectory(prefix=".xhttp-tls-", dir=directory) as temporary:
        pending_cert, pending_key = Path(temporary) / "cert.pem", Path(temporary) / "key.pem"
        subprocess.run(["openssl", "req", "-new", "-x509", "-newkey", "ec",
            "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-sha256", "-days", "3650",
            "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,digitalSignature,keyCertSign",
            "-addext", "extendedKeyUsage=serverAuth",
            "-keyout", str(pending_key), "-out", str(pending_cert)], check=True, capture_output=True)
        write_private(key, pending_key.read_text())
        write_private(cert, pending_cert.read_text())
    return cert, key


def tunnel_ingress(directory):
    """Export one remote route, not a replacement for the tunnel's other ingress rules."""
    directory = Path(directory)
    domain = host((directory / "sbargoym.log").read_text().strip(), "固定隧道域名")
    require(not domain.lower().endswith("trycloudflare.com"), "不支持随机隧道")
    config = json.loads((directory / "xr.json").read_text())
    inbound = next(x for x in config["inbounds"] if x.get("tag") == "vless-xhttp")
    tls = inbound["streamSettings"].get("security") == "tls"
    ingress = {"hostname": domain,
               "service": ("https" if tls else "http") + "://127.0.0.1:" + str(inbound["port"]),
               "originRequest": {"http2Origin": tls, "noTLSVerify": False}}
    if tls:
        ingress["originRequest"].update(originServerName="localhost", matchSNItoHost=False,
                                      caPool=str((directory / "xhttp-origin.crt").resolve()))
    json_file(directory / "xhttp-tunnel-ingress.json", ingress)
    return ingress


def origin_info(directory):
    ingress = tunnel_ingress(directory)
    print("请在 Cloudflare 将 " + ingress["hostname"] + " 指向 " + ingress["service"])
    if ingress["originRequest"]["http2Origin"]:
        print("流式模式：开启 HTTP/2 to origin，Origin Server Name=localhost，关闭 Match SNI to Host；保持 TLS 校验开启。")
        print("CA Pool=" + ingress["originRequest"]["caPool"])
        print("还需在域名设置中启用 gRPC；公开 Tunnel 的流式兼容性属于实验性支持，须实际验证。")
    print("回源参数文件：" + str(Path(directory) / "xhttp-tunnel-ingress.json") + "（需自行应用到 Cloudflare，此文件不会自动更新远程配置）")


def stream(opts, domain, download=False):
    prefix = "download_" if download else ""
    result = {"network": "xhttp", "security": "tls", "tlsSettings": {
        "serverName": opts["download_servername"] if download else domain,
        "alpn": [opts[prefix + "alpn"]], "allowInsecure": False},
        "xhttpSettings": {"host": opts["download_host"] if download else domain,
                          "path": opts["path"],
                          "mode": "auto" if download else opts["mode"],
                          "extra": {"xmux": copy.deepcopy(opts["xmux"])}}}
    if opts[prefix + "alpn"] == "h2":
        result["tlsSettings"]["fingerprint"] = "chrome"
    if not download and opts["mode"] in STREAM_MODES:
        result["xhttpSettings"]["extra"]["noGRPCHeader"] = False
    if opts[prefix + "finalmask"] == "tls-fragment":
        result["finalmask"] = copy.deepcopy(FRAGMENT)
    if download:
        result.update(address=opts["download_address"], port=opts["download_port"])
    elif opts.get("download_address"):
        result["xhttpSettings"]["extra"]["downloadSettings"] = stream(opts, domain, True)
    return result


def configure(directory, env):
    directory = Path(directory)
    saved = directory / "xhttp-options.json"
    opts = saved_options(directory, env)
    config_file = directory / "xr.json"
    config = json.loads(config_file.read_text())
    inbound = next((x for x in config["inbounds"] if x.get("tag") == "vless-xhttp"), None)
    require(inbound is not None, "未找到 vless-xhttp 入站")
    require(inbound["settings"].get("decryption", "none") not in ("", "none"), "VLESS ENC 密钥生成失败")
    inbound["listen"] = "127.0.0.1"
    for client in inbound["settings"]["clients"]:
        client.pop("flow", None)
    inbound["streamSettings"] = {"network": "xhttp", "security": "none",
        "xhttpSettings": {"path": opts["path"], "mode": "auto"}}
    if opts["mode"] in STREAM_MODES:
        cert, key = origin_certificate(directory)
        inbound["streamSettings"].update(security="tls", tlsSettings={
            "alpn": ["h2"], "minVersion": "1.2",
            "certificates": [{"certificateFile": str(cert), "keyFile": str(key)}]})
        # A single bidirectional gRPC-like request must not receive an SSE content type.
        inbound["streamSettings"]["xhttpSettings"]["extra"] = {
            "noSSEHeader": opts["mode"] == "stream-one"}
    json_file(config_file, config)
    json_file(saved, opts)


def export(directory):
    directory = Path(directory)
    opts = options({}, json.loads((directory / "xhttp-options.json").read_text()))
    domain = host((directory / "sbargoym.log").read_text().strip(), "固定隧道域名")
    require(not domain.lower().endswith("trycloudflare.com"), "不支持随机隧道")
    config = json.loads((directory / "xr.json").read_text())
    inbound = next(x for x in config["inbounds"] if x.get("tag") == "vless-xhttp")
    uid = inbound["settings"]["clients"][0]["id"]
    encryption = (directory / "xrk/enkey").read_text().strip()
    require(encryption.startswith("mlkem768x25519plus."), "缺少有效的 VLESS ENC 客户端密钥")
    settings = stream(opts, domain)
    address = opts.get("address") or domain
    name = "vless-xhttp-argo-tls-enc"
    outbound = {"tag": name, "protocol": "vless", "settings": {"vnext": [{
        "address": address, "port": 443, "users": [{"id": uid, "encryption": encryption}]}]},
        "streamSettings": settings}
    client = {"log": {"loglevel": "warning"}, "inbounds": [{"tag": "socks-in",
        "listen": "127.0.0.1", "port": 10808, "protocol": "socks",
        "settings": {"auth": "noauth", "udp": True}}], "outbounds": [outbound]}
    json_file(directory / "xhttp-client.json", client)
    query = {"encryption": encryption, "security": "tls", "sni": domain,
             "alpn": opts["alpn"], "type": "xhttp", "host": domain,
             "path": opts["path"], "mode": opts["mode"],
             "extra": json.dumps(settings["xhttpSettings"]["extra"], separators=(",", ":"))}
    if opts["alpn"] == "h2":
        query["fp"] = "chrome"
    # No standardized share-URI field carries streamSettings.finalmask.
    # Never advertise a degraded link as the requested masked combination.
    if opts["finalmask"] != "off" or opts["download_finalmask"] != "off":
        write_private(directory / "xhttp-uri.txt", "")
        print("FinalMask 已启用，请导入 xhttp-client.json；普通 URI 无法完整携带此配置。")
    else:
        authority = "[" + address + "]" if ":" in address else address
        uri = "vless://" + uid + "@" + authority + ":443?" + urlencode(query, quote_via=quote) + "#" + name
        write_private(directory / "xhttp-uri.txt", uri + "\n")
        print(uri)
    print("完整 Xray 客户端配置：" + str(directory / "xhttp-client.json"))
    origin_info(directory)


def main():
    try:
        command = sys.argv[1]
        if command == "validate":
            saved_options(sys.argv[2], os.environ) if len(sys.argv) > 2 else options(os.environ)
        elif command == "configure":
            configure(sys.argv[2], os.environ)
        elif command == "export":
            export(sys.argv[2])
        elif command == "origin-info":
            origin_info(sys.argv[2])
        elif command == "install-xray":
            install_xray(sys.argv[2])
        else:
            raise ValueError("未知命令")
    except (ValueError, OSError, KeyError, StopIteration, IndexError, subprocess.CalledProcessError) as error:
        print("XHTTP 配置错误：" + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
