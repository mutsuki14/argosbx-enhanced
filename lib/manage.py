#!/usr/bin/env python3
"""Interactive setup and local management. No shell evaluation or Cloudflare API writes."""
import argparse
import contextlib
import fcntl
import getpass
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request

import xhttp_config as xhttp

PROTOCOLS = 'vlpt vmpt vwpt hypt tupt xhpt vxpt anpt arpt sspt sopt nvpt xupt xcpt'.split()
FILES = ('xr.json', 'xhttp-options.json', 'xhttp-client.json', 'xhttp-uri.txt',
         'xhttp-tunnel-ingress.json', 'xhttp-origin.crt', 'xhttp-origin.key', 'jh.txt', 'jhsub.txt')


def read(path, default=''):
    return path.read_text().strip() if path.exists() else default


def fixed_tunnel(domain, token, port):
    xhttp.host(domain, '固定隧道域名')
    try:
        ipaddress.ip_address(domain)
    except ValueError:
        pass
    else:
        raise ValueError('固定隧道需要域名，不能填写 IP')
    xhttp.require('.' in domain and not domain.lower().endswith('trycloudflare.com'), '只支持固定隧道域名')
    xhttp.require(bool(re.fullmatch(r'[A-Za-z0-9_+/=-]+', token)), '请填写固定隧道 Token 本身')
    xhttp.require(str(port).isdigit() and 1 <= int(port) <= 65535, '端口须为 1–65535')


def installed(directory):
    return any((directory / f).exists() for f in ('xr.json', 'sb.json'))


def active_config(directory):
    xhttp.require((directory / 'xhttp-options.json').exists(), '尚未安装增强 XHTTP；首次安装请运行 agsbx setup')
    config = json.loads((directory / 'xr.json').read_text())
    inbound = next((i for i in config['inbounds'] if i.get('tag') == 'vless-xhttp'), None)
    xhttp.require(inbound is not None, '未找到增强 XHTTP 入站')
    return config, inbound, xhttp.saved_options(directory, {})


def pids(directory, binary, config=None):
    """Match an owned executable and its config, never a broad process-name substring."""
    found = []
    for entry in Path('/proc').glob('[0-9]*'):
        try:
            if entry.stat().st_uid != os.geteuid():
                continue
            if (entry / 'exe').resolve() != (directory / binary).resolve():
                continue
            args = (entry / 'cmdline').read_bytes().decode().split('\0')
            if config and str(directory / config) not in args:
                continue
            found.append(int(entry.name))
        except (OSError, UnicodeError):
            continue
    return found


def checked_core(directory, config):
    binary = directory / 'xray'
    xhttp.require(binary.is_file(), '找不到 Xray，请先安装或运行 agsbx upx')
    result = subprocess.run([str(binary), 'run', '-test', '-c', str(config)], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError('Xray 配置校验失败，未应用修改；请核对参数及内核版本（agsbx upx）')


def probe_origin(inbound, directory):
    with socket.create_connection(('127.0.0.1', int(inbound['port'])), timeout=3) as conn:
        if inbound['streamSettings'].get('security') == 'tls':
            context = ssl.create_default_context(cafile=str(directory / 'xhttp-origin.crt'))
            context.set_alpn_protocols(['h2'])
            with context.wrap_socket(conn, server_hostname='localhost') as secure:
                xhttp.require(secure.selected_alpn_protocol() == 'h2', '本机回源没有协商到 HTTP/2')


def restart_xray(directory):
    xhttp.require(sys.platform.startswith('linux'), '重启服务仅适用于 Linux；可用 --dry-run 预览')
    config = json.loads((directory / 'xr.json').read_text())
    inbound = next(i for i in config['inbounds'] if i.get('tag') == 'vless-xhttp')
    unit = Path('/etc/systemd/system/xr.service')
    rc = Path('/etc/init.d/xray')
    process = None
    if os.geteuid() == 0 and unit.exists() and str(directory / 'xray') in unit.read_text() and Path('/run/systemd/system').exists():
        subprocess.run(['systemctl', 'restart', 'xr'], check=True, capture_output=True, timeout=30)
    elif os.geteuid() == 0 and rc.exists() and str(directory / 'xray') in rc.read_text() and shutil.which('rc-service'):
        subprocess.run(['rc-service', 'xray', 'restart'], check=True, capture_output=True, timeout=30)
    else:
        for pid in pids(directory, 'xray', 'xr.json'):
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 5
        while pids(directory, 'xray', 'xr.json') and time.monotonic() < deadline:
            time.sleep(.1)
        xhttp.require(not pids(directory, 'xray', 'xr.json'), '旧 Xray 未能退出，请检查 agsbx logs')
        log_path = directory / 'xray.log'
        fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, 'ab') as log:
            process = subprocess.Popen([str(directory / 'xray'), 'run', '-c', str(directory / 'xr.json')],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if process and process.poll() is not None:
            raise ValueError('Xray 启动失败，请检查 agsbx logs')
        try:
            probe_origin(inbound, directory)
            return
        except (OSError, ValueError):
            time.sleep(.15)
    raise ValueError('Xray 回源端口未就绪，请检查 agsbx logs')


def masked(directory, text):
    for file in ('sbargotoken.log', 'uuid', 'xrk/enkey', 'xrk/dekey'):
        secret = read(directory / file)
        if secret:
            text = text.replace(secret, '<已隐藏>')
    text = re.sub(r'(?i)(--token(?:=|\s+))\S+', r'\1<已隐藏>', text)
    return text


def status(directory):
    print('Argosbx Enhanced')
    if not installed(directory):
        print('尚未安装。运行 agsbx setup 开始配置。')
        return
    for binary, label, config in [('xray', 'Xray', 'xr.json'), ('sing-box', 'Sing-box', 'sb.json'),
                                  ('cloudflared', '固定 Argo', None)]:
        if (directory / binary).exists():
            live = pids(directory, binary, config)
            print(f'{label}：' + ('运行中' if live else '未检测到运行进程'))
    if (directory / 'xhttp-options.json').exists():
        _, inbound, opts = active_config(directory)
        print(f"XHTTP：{opts['mode']} / {opts['alpn']}，下行分离：" + ('开启' if opts.get('download_address') else '关闭'))
        print('固定域名：' + read(directory / 'sbargoym.log'))
        scheme = 'https' if inbound['streamSettings'].get('security') == 'tls' else 'http'
        print(f"本机回源：{scheme}://127.0.0.1:{inbound['port']}")
        print('客户端文件：' + str(directory / 'xhttp-client.json'))
    print('检查连接：agsbx doctor    查看日志：agsbx logs')


def doctor(directory, network=False):
    _, inbound, opts = active_config(directory)
    failures = 0
    checks = [
        ('固定隧道配置', lambda: fixed_tunnel(read(directory / 'sbargoym.log'), read(directory / 'sbargotoken.log'), inbound['port'])),
        ('Xray 服务端配置', lambda: checked_core(directory, directory / 'xr.json')),
        ('客户端配置', lambda: checked_core(directory, directory / 'xhttp-client.json')),
        ('本机 HTTPS / H2 回源' if opts['mode'] in xhttp.STREAM_MODES else '本机回源端口', lambda: probe_origin(inbound, directory)),
    ]
    for label, check in checks:
        try:
            check()
            print('[通过] ' + label)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            failures += 1
            print('[失败] ' + label + '：' + masked(directory, str(error)))
    if not pids(directory, 'cloudflared'):
        failures += 1
        print('[失败] 未检测到当前用户的 cloudflared 进程；运行 agsbx res，或查看 agsbx logs。')
    if network:
        domain = read(directory / 'sbargoym.log')
        try:
            context = ssl.create_default_context()
            context.set_alpn_protocols(['h2', 'http/1.1'])
            with socket.create_connection((domain, 443), timeout=5) as conn:
                with context.wrap_socket(conn, server_hostname=domain):
                    print('[通过] 公网域名 TCP/443 与 TLS 证书（不代表 H3 或 VLESS 已连通）')
        except (OSError, ValueError) as error:
            failures += 1
            print('[失败] 公网域名检查：' + masked(directory, str(error)))
    print('Cloudflare 远端路由需要人工核对；agsbx tunnel 显示应填写的值。')
    if opts['mode'] in xhttp.STREAM_MODES:
        print('流式模式仍为实验性：确认 HTTPS、HTTP/2 to origin、CA Pool 和域名 gRPC 已配置。')
    return 1 if failures else 0


def change_mode(directory, mode, alpn=None, disable_split=False, dry_run=False, finalmask=None):
    _, inbound, previous = active_config(directory)
    env = {'xhttp_mode': mode}
    if alpn:
        env['xhttp_alpn'] = alpn
    elif mode in xhttp.STREAM_MODES:
        env['xhttp_alpn'] = 'h2'
    if disable_split:
        env['xhttp_download_address'] = ''
    if finalmask:
        env['xhttp_finalmask'] = finalmask
    opts = xhttp.options(env, previous)
    fixed_tunnel(read(directory / 'sbargoym.log'), read(directory / 'sbargotoken.log'), inbound['port'])
    print(f"传输方案：{previous['mode']} / {previous['alpn']} → {opts['mode']} / {opts['alpn']}")
    print('下行分离：' + (opts.get('download_address') or '关闭') + '；上行 TLS 分片：' + opts['finalmask'])
    print('保留 UUID、端口、密钥、路径、其他入站与出站规则。')
    if dry_run:
        print('仅预览，未修改配置或重启服务。')
        return
    if opts == previous:
        print('当前已使用该方案，无需修改。')
        return
    xhttp.require(sys.platform.startswith('linux'), '应用模式仅适用于 Linux；可用 --dry-run 预览')
    with open(directory / '.manage.lock', 'w') as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('另一个管理操作正在进行，请稍后重试') from None
        # Re-read under the lock; the previous snapshot may have changed while waiting.
        config, _, current = active_config(directory)
        xhttp.require(current == previous, '配置刚刚发生变化，请重新执行命令')
        before = {name: (directory / name).read_bytes() if (directory / name).exists() else None for name in FILES}
        committed = False
        backup = None
        try:
            candidate = xhttp.server_config(config, opts, directory)
            with tempfile.TemporaryDirectory(prefix='.mode-', dir=directory) as temporary:
                stage = Path(temporary)
                (stage / 'xrk').mkdir()
                for file in ('xrk/enkey', 'sbargoym.log'):
                    xhttp.write_private(stage / file, (directory / file).read_text())
                xhttp.json_file(stage / 'xr.json', candidate)
                xhttp.json_file(stage / 'xhttp-options.json', opts)
                with contextlib.redirect_stdout(io.StringIO()):
                    xhttp.export(stage)
                checked_core(directory, stage / 'xr.json')
                checked_core(directory, stage / 'xhttp-client.json')
                backup = directory / 'backups' / (time.strftime('%Y%m%d-%H%M%S') + '-' + os.urandom(3).hex())
                backup.mkdir(parents=True, mode=0o700)
                for name, content in before.items():
                    if content is not None:
                        xhttp.write_private(backup / name, content.decode())
                committed = True
                for name in ('xr.json', 'xhttp-options.json', 'xhttp-client.json', 'xhttp-uri.txt'):
                    xhttp.write_private(directory / name, (stage / name).read_text())
                xhttp.tunnel_ingress(directory)
                for name in ('jh.txt', 'jhsub.txt'):
                    if (directory / name).exists() or name == 'jh.txt':
                        xhttp.update_subscription(directory / name, read(directory / 'xhttp-uri.txt'))
                restart_xray(directory)
        except BaseException:
            for name, content in before.items():
                if content is None:
                    (directory / name).unlink(missing_ok=True)
                else:
                    xhttp.write_private(directory / name, content.decode())
            if committed:
                try:
                    restart_xray(directory)
                    print('新方案启动失败，已恢复原配置并重启原服务。', file=sys.stderr)
                except (OSError, ValueError, subprocess.SubprocessError):
                    print('已恢复原配置，但服务未能重启；请运行 agsbx logs 排查。', file=sys.stderr)
            raise
    print('已应用；备份目录：' + str(backup))
    xhttp.origin_info(directory)
    print('请重新导入客户端配置；Cloudflare 回源设置不会自动更改。')


def export_client(directory, destination=None, uri=False):
    active_config(directory)
    with contextlib.redirect_stdout(io.StringIO()):
        xhttp.export(directory)
    checked_core(directory, directory / 'xhttp-client.json')
    content = read(directory / ('xhttp-uri.txt' if uri else 'xhttp-client.json'))
    xhttp.require(bool(content), 'FinalMask 不能完整导出为链接，请运行 agsbx export 导出 JSON')
    if uri and not destination:
        print(content)
    else:
        destination = Path(destination or 'xhttp-client.json').expanduser().absolute()
        xhttp.require(destination.parent.is_dir(), '目标目录不存在：' + str(destination.parent))
        protected = set(FILES) - {'xhttp-client.json', 'xhttp-uri.txt'}
        protected.update(('sb.json', 'sbargotoken.log', 'sbargoym.log', 'uuid', 'xrk/enkey', 'xrk/dekey'))
        xhttp.require(destination.resolve() not in {(directory / name).resolve() for name in protected},
                      '导出目标不能覆盖服务端配置或凭据，请换一个文件名')
        xhttp.write_private(destination, content + '\n')
        print('已导出：' + str(destination) + '（包含节点凭据，请私下保存）')


def logs(directory, lines):
    found = False
    for name in ('argo.log', 'xray.log'):
        path = directory / name
        if path.exists():
            found = True
            with path.open(errors='replace') as stream:
                from collections import deque
                print('--- ' + name + ' ---')
                print(masked(directory, ''.join(deque(stream, maxlen=lines))))
    if Path('/run/systemd/system').exists() and shutil.which('journalctl'):
        result = subprocess.run(['journalctl', '-u', 'argo', '-u', 'xr', '-n', str(lines), '--no-pager'],
                                capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            found = True
            print(masked(directory, result.stdout))
    if not found:
        print('暂无可读日志。检查服务是否启动；OpenRC 环境也可查看系统日志。')


def prompt(label, default='', secret=False):
    suffix = (' [回车保留]' if secret else f' [{default}]') if default else ''
    return (getpass.getpass(label + suffix + '：') if secret else input(label + suffix + '：')).strip() or default


def upgrade(directory, bin_directory=None):
    """Validate a complete manager bundle before replacing any installed script."""
    bin_directory = bin_directory or Path.home() / 'bin'
    base = os.environ.get('ARGOSBX_BASE', 'https://raw.githubusercontent.com/mutsuki14/argosbx-enhanced/main')
    bundle = {}
    for name in ('argosbx.sh', 'lib/argo.sh', 'lib/xhttp_config.py', 'lib/manage.py'):
        with urllib.request.urlopen(base + '/' + name, timeout=30) as response:
            text = response.read().decode('utf-8')
        xhttp.require(bool(text.strip()), '下载的脚本为空：' + name)
        if name.endswith('.sh'):
            subprocess.run(['bash', '-n'], input=text, text=True, check=True, capture_output=True)
        else:
            compile(text, name, 'exec')
        target = bin_directory / 'agsbx' if name == 'argosbx.sh' else directory / name
        bundle[target] = text
    before = {target: target.read_bytes() if target.exists() else None for target in bundle}
    try:
        for target, text in bundle.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            xhttp.write_private(target, text)
            if target == bin_directory / 'agsbx':
                target.chmod(0o700)
    except OSError:
        for target, data in before.items():
            if data is not None:
                xhttp.write_private(target, data.decode())
                if target == bin_directory / 'agsbx':
                    target.chmod(0o700)
            else:
                target.unlink(missing_ok=True)
        raise
    print('管理脚本已更新，节点配置和内核保持不变。')
    print('打开菜单：bash "' + str(bin_directory / 'agsbx') + '"')


def setup(directory, dry_run=False):
    xhttp.require(sys.stdin.isatty(), '安装向导需要交互终端；自动部署请继续使用环境变量命令，运行 agsbx help 查看示例')
    xhttp.require(not installed(directory), '已存在安装。切换模式请运行 agsbx mode；重建所有协议仍使用完整参数 + rep')
    print('安装固定 Argo + VLESS XHTTP。请先准备固定隧道域名和 Token。')
    domain, token, port = os.environ.get('agn', ''), os.environ.get('agk', ''), '8080'
    while True:
        domain = prompt('固定隧道域名', domain)
        token = prompt('Tunnel Token（输入不显示）', token, secret=True)
        port = prompt('本机回源端口', port)
        try:
            fixed_tunnel(domain, token, port)
            break
        except ValueError as error:
            print(str(error) + '，请重新填写。')
    print('1) H2 / packet-up（默认）  2) H3 / packet-up  3) stream-up（实验性）  4) stream-one（实验性）')
    profiles = {'1': ('packet-up', 'h2'), '2': ('packet-up', 'h3'), '3': ('stream-up', 'h2'), '4': ('stream-one', 'h2')}
    choice = prompt('选择传输方案', '1')
    while choice not in profiles:
        choice = prompt('请输入 1–4', '1')
    mode, alpn = profiles[choice]
    env = dict(os.environ)
    for name in PROTOCOLS + ['warp', 'alns', 'cfip', 'hyjpt', 'cdnym', 'sub', 'subid', 'subpt', 'oap']:
        env.pop(name, None)
    for name in list(env):
        if name.startswith('xhttp_'):
            env.pop(name)
    env.update(vxpt=port, argo='vxpt', agn=domain, agk=token, agproto='quic', xhttp_mode=mode, xhttp_alpn=alpn)
    print(f'即将部署：{domain} / 本机端口 {port} / {mode} / {alpn} / 固定隧道 QUIC；Token 已隐藏。')
    if mode in xhttp.STREAM_MODES:
        print('流式方案还需在 Cloudflare 开启 HTTPS / HTTP2 回源并填写部署后生成的 CA Pool。')
    if dry_run:
        print('仅预览，未安装。')
        return 0
    xhttp.require(sys.platform.startswith('linux'), '安装仅适用于 Linux')
    if prompt('开始安装？输入 y 继续', 'n').lower() != 'y':
        print('已取消。')
        return 0
    with tempfile.TemporaryDirectory(prefix='argosbx-setup-') as temporary:
        entry = Path(os.environ.get('ARGOSBX_ENTRY', ''))
        if not entry.is_file() or not stat.S_ISREG(entry.stat().st_mode):
            entry = Path(temporary) / 'argosbx.sh'
            base = os.environ.get('ARGOSBX_BASE', 'https://raw.githubusercontent.com/mutsuki14/argosbx-enhanced/main')
            with urllib.request.urlopen(base + '/argosbx.sh', timeout=30) as response:
                entry.write_bytes(response.read())
        return subprocess.run(['bash', str(entry)], env=env).returncode


def main():
    parser = argparse.ArgumentParser(description='Argosbx 本地管理')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    commands.add_parser('upgrade')
    commands.add_parser('tunnel')
    wizard = commands.add_parser('setup')
    wizard.add_argument('--dry-run', action='store_true')
    check = commands.add_parser('doctor')
    check.add_argument('--network', action='store_true', help='额外检查公网域名 TCP/443 和证书')
    mode = commands.add_parser('mode')
    mode.add_argument('mode', choices=('packet-up', *xhttp.STREAM_MODES))
    mode.add_argument('--alpn', choices=('h2', 'h3'))
    mode.add_argument('--disable-split', action='store_true')
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--finalmask', choices=('off', 'tls-fragment'))
    export = commands.add_parser('export')
    export.add_argument('destination', nargs='?')
    export.add_argument('--uri', action='store_true')
    log = commands.add_parser('logs')
    log.add_argument('--lines', type=int, default=30)
    args = parser.parse_args()
    directory = Path(os.environ.get('ARGOSBX_STATE_DIR', str(Path.home() / 'agsbx'))).expanduser().absolute()
    try:
        if args.command == 'status':
            status(directory)
        elif args.command == 'upgrade':
            upgrade(directory)
        elif args.command == 'setup':
            return setup(directory, args.dry_run)
        elif args.command == 'doctor':
            return doctor(directory, args.network)
        elif args.command == 'tunnel':
            active_config(directory)
            xhttp.origin_info(directory)
        elif args.command == 'mode':
            change_mode(directory, args.mode, args.alpn, args.disable_split, args.dry_run, args.finalmask)
        elif args.command == 'export':
            export_client(directory, args.destination, args.uri)
        elif args.command == 'logs':
            xhttp.require(1 <= args.lines <= 1000, '日志行数须为 1–1000')
            logs(directory, args.lines)
        return 0
    except (EOFError, KeyboardInterrupt):
        print('\n已取消。', file=sys.stderr)
        return 130
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, StopIteration, SyntaxError) as error:
        print('操作未完成：' + masked(directory, str(error)), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
