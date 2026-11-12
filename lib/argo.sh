#!/usr/bin/env bash
# Shared by the VPS installer and the Node container entry point.
ARGOSBX_STATE_DIR=${ARGOSBX_STATE_DIR:-$HOME/agsbx}
ARGOSBX_CLI_REV=3

argo_error() { printf 'Argo 配置错误：%s\n' "$*" >&2; return 1; }

argo_validate() {
    [ -n "${argo:-}" ] || return 0
    case "$argo" in vmpt|vwpt|vxpt) ;; *) argo_error 'argo 只能为 vmpt、vwpt 或 vxpt'; return 1 ;; esac
    [ "${!argo+x}" ] || { argo_error "请同时设置主协议 ${argo}（端口留空可自动生成）"; return 1; }
    local port_value=${!argo} label
    if [ -n "$port_value" ]; then
        [[ "$port_value" =~ ^[0-9]{1,5}$ ]] && (( 10#$port_value >= 1 && 10#$port_value <= 65535 )) || {
            argo_error '主协议端口必须为 1-65535'; return 1;
        }
    fi
    [ -n "${agn:-}" ] && [ -n "${agk:-}" ] || {
        argo_error '仅支持固定隧道；agn 域名和 agk Token 必须同时填写，不会申请随机隧道'; return 1;
    }
    [[ "$agn" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] && [[ "$agn" == *.* ]] || {
        argo_error 'agn 必须为完整域名，不含协议、路径或端口'; return 1;
    }
    local -a labels
    IFS=. read -r -a labels <<< "$agn"
    [ "${#agn}" -le 253 ] || { argo_error 'agn 域名过长'; return 1; }
    for label in "${labels[@]}"; do
        [[ "$label" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$ ]] || {
            argo_error 'agn 域名格式不正确'; return 1;
        }
    done
    case "$(printf '%s' "$agn" | tr '[:upper:]' '[:lower:]')" in *trycloudflare.com) argo_error '不支持 trycloudflare.com 随机隧道'; return 1 ;; esac
    [[ "$agk" =~ ^[A-Za-z0-9_+/=-]+$ ]] || { argo_error 'agk 必须只包含 Token 本身'; return 1; }
    agproto=${agproto:-${agqc:+quic}}
    agproto=${agproto:-quic}
    case "$agproto" in auto|http2|quic) ;; *) argo_error 'agproto 只能为 auto、http2 或 quic'; return 1 ;; esac
    export agproto
}

argo_require_python() {
    if ! command -v python3 >/dev/null 2>&1; then
        if [ "$EUID" -ne 0 ]; then
            argo_error 'XHTTP 增强配置需要 Python 3，请先安装 python3'; return 1
        elif command -v apt-get >/dev/null 2>&1; then
            apt-get update -qq && apt-get install -y python3 || return 1
        elif command -v apk >/dev/null 2>&1; then
            apk add --no-cache python3 || return 1
        elif command -v dnf >/dev/null 2>&1; then
            dnf install -y python3 || return 1
        else
            argo_error '请先安装 python3'; return 1
        fi
    fi
}

argo_component() {
    local name=$1
    case "$name" in xhttp_config.py|manage.py) ;; *) return 1 ;; esac
    local helper_dir
    helper_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
    if [ ! -s "$helper_dir/$name" ]; then
        local pending
        pending=$(mktemp "$helper_dir/component.XXXXXX") || return 1
        if (command -v curl >/dev/null 2>&1 && curl -fLsS --connect-timeout 10 --max-time 60 --retry 2 "$ARGOSBX_BASE/lib/$name" -o "$pending") ||
           (command -v wget >/dev/null 2>&1 && wget -T 30 -qO "$pending" "$ARGOSBX_BASE/lib/$name"); then
            mv "$pending" "$helper_dir/$name"
        else
            rm -f "$pending"; argo_error '无法下载 XHTTP 配置组件'; return 1
        fi
    fi
    printf '%s\n' "$helper_dir/$name"
}

argo_python() {
    argo_require_python || return 1
    local component
    component=$(argo_component xhttp_config.py) || return 1
    python3 "$component" "$@"
}

argo_manage() {
    if { [ "${1:-}" = setup ] || [ "${1:-}" = xhttp ] || [ "${1:-}" = tune ]; } && [ ! -t 0 ]; then
        echo '安装向导需要交互终端；自动部署请继续使用环境变量命令，运行 agsbx help 查看示例。' >&2
        return 1
    fi
    if [ "${1:-}" = setup ] || [ "${1:-}" = xhttp ] || [ "${1:-}" = upgrade ]; then
        argo_require_python || return 1
    elif ! command -v python3 >/dev/null 2>&1; then
        printf '此命令需要 Python 3；首次安装请运行 agsbx setup。\n' >&2
        return 1
    fi
    local component
    argo_component xhttp_config.py >/dev/null || return 1
    component=$(argo_component manage.py) || return 1
    ARGOSBX_STATE_DIR="$ARGOSBX_STATE_DIR" python3 "$component" "$@"
}

agsbx_help() {
    cat <<'HELP'
Argosbx Enhanced — 固定 Argo / XHTTP

  agsbx                         打开菜单（终端中）
  agsbx setup [--dry-run]        首次安装向导；Token 输入不显示
  agsbx xhttp [--dry-run]        XHTTP 专区：REALITY / 固定 Argo / 双节点搭建
  agsbx tune --profile reality   调整已安装节点的 XMUX、FinalMask 等参数
    --profile argo              调整固定 Argo 节点（默认）
  agsbx status                  查看本机状态，不显示凭据
  agsbx upgrade                 更新管理脚本，保留节点配置
  agsbx doctor [--network]       检查配置、进程、回源；可选公网 TLS 检查
  agsbx doctor --report ~/argosbx-diagnostics.json
                                导出脱敏报告，默认检查已安装的两种 XHTTP 节点
  agsbx mode stream-up           保留其他协议，切换为 H2 流式上行
  agsbx mode stream-one --disable-split
                                关闭分离，切换为 H2 单请求双向流
  agsbx mode packet-up --alpn h2 恢复分包传输
    可加 --dry-run 预览，--finalmask off|tls-fragment 调整上行分片
  agsbx tunnel                  查看 Cloudflare 应填写的回源设置
  agsbx export [目标文件]        导出 JSON，默认 ./xhttp-client.json
    --profile reality           导出 REALITY 节点，默认 ./xhttp-reality-client.json
  agsbx export --uri            显示分享链接（FinalMask 请用 JSON）
  agsbx logs [--lines 50]        查看脱敏日志
  agsbx list / res               原有节点列表 / 重启全部服务
  agsbx upx / ups / upa          更新 Xray / Sing-box / cloudflared
  agsbx rep                      按完整环境变量重建协议
  agsbx del                      卸载服务和配置
  agsbx help                     显示此帮助

原环境变量安装方式继续支持：
  vxpt=8080 argo=vxpt agn=up.example.com agk='TOKEN' bash argosbx.sh
stream-up/one 为实验性支持，切换后仍需同步 Cloudflare 回源设置。
HELP
}

agsbx_menu() {
    [ -t 0 ] || { echo '菜单需要交互终端；运行 agsbx help 查看命令。' >&2; return 2; }
    local choice profile
    while :; do
        printf '\nArgosbx Enhanced\n1) 固定 Argo 安装向导  2) 查看状态  3) 切换传输方案\n4) 检查连接配置  5) Cloudflare 回源设置\n6) 导出客户端 JSON  7) 查看日志  8) 完整帮助\n9) 更新管理脚本  10) XHTTP 一键搭建与增强（REALITY / Argo / 双节点）\n0) 退出\n'
        read -r -p '请选择 [0]：' choice || return 0
        case "${choice:-0}" in
            0) return 0 ;;
            1) argo_manage setup ;;
            2) argo_manage status ;;
            3)
                printf '1) H2 分包  2) H3 分包（关闭上行分片）\n3) H2 stream-up  4) H2 stream-one（关闭下行分离）\n'
                read -r -p '选择方案 [返回]：' profile || return 0
                case "$profile" in
                    1) argo_manage mode packet-up --alpn h2 ;;
                    2) argo_manage mode packet-up --alpn h3 --finalmask off ;;
                    3) argo_manage mode stream-up ;;
                    4) argo_manage mode stream-one --disable-split ;;
                    '') ;;
                    *) echo '请输入 1–4。' ;;
                esac ;;
            4) argo_manage doctor ;;
            5) argo_manage tunnel ;;
            6) argo_manage export ;;
            7) argo_manage logs ;;
            8) agsbx_help ;;
            9) argo_manage upgrade ;;
            10) argo_manage xhttp ;;
            *) echo '请输入菜单中的数字。' ;;
        esac
    done
}

argo_cli_dispatch() {
    case "${1:-}" in
        help|-h|--help) agsbx_help; exit 0 ;;
        menu) agsbx_menu; exit $? ;;
        setup|xhttp|tune|upgrade|status|doctor|mode|tunnel|export|logs) argo_manage "$@"; exit $? ;;
        list|rep|res|upx|ups|upa|del) return 0 ;;
        '')
            local variable
            for variable in vlpt vmpt vwpt hypt tupt xhpt vxpt anpt arpt sspt sopt nvpt xupt xcpt; do
                [ -z "${!variable+x}" ] || return 0
            done
            if [ -t 0 ]; then agsbx_menu; exit $?; else agsbx_help; exit 0; fi ;;
        *) printf '未知命令：%s。运行 agsbx help 查看用法。\n' "$1" >&2; exit 2 ;;
    esac
}

argo_preflight() {
    argo_validate || return 1
    if [ "${argo:-}" = vxpt ]; then
        # Validate the effective saved + requested configuration before rep stops services.
        argo_python validate "$ARGOSBX_STATE_DIR" || return 1
    fi
    if [ -n "${xhpt+x}" ]; then
        argo_python validate-reality "$ARGOSBX_STATE_DIR" || return 1
    fi
    case "${1:-}" in
        upa) argo_saved || return 1 ;;
        res) [ ! -f "$ARGOSBX_STATE_DIR/argoport.log" ] || argo_saved || return 1 ;;
    esac
}

argo_saved() {
    local saved_domain
    saved_domain=$(cat "$ARGOSBX_STATE_DIR/sbargoym.log" 2>/dev/null)
    [ -n "$saved_domain" ] && [ -s "$ARGOSBX_STATE_DIR/sbargotoken.log" ] || {
        argo_error '缺少固定隧道配置；请设置 agn、agk 后重新部署，旧随机隧道不会恢复'; return 1;
    }
    case "$(printf '%s' "$saved_domain" | tr '[:upper:]' '[:lower:]')" in *trycloudflare.com) argo_error '不恢复随机隧道'; return 1 ;; esac
}

argo_launcher() {
    argo_saved || return 1
    # Credentials never appear in a unit, process argument, cron line, or node listing.
    chmod 600 "$ARGOSBX_STATE_DIR/sbargotoken.log"
    cat > "$ARGOSBX_STATE_DIR/argo-run" <<'ARGO_RUN'
#!/usr/bin/env bash
set -eu
directory=$(cd -- "$(dirname -- "$0")" && pwd)
[[ -s "$directory/sbargoym.log" && -s "$directory/sbargotoken.log" ]] || {
    echo '缺少固定隧道域名或 Token；拒绝启动随机隧道' >&2; exit 1;
}
domain=$(cat "$directory/sbargoym.log")
case "$(printf '%s' "$domain" | tr '[:upper:]' '[:lower:]')" in *trycloudflare.com) echo '不支持随机隧道' >&2; exit 1 ;; esac
protocol=$(cat "$directory/cftupr.log")
case "$protocol" in quic|http2|auto) ;; *) echo '无效隧道协议' >&2; exit 1 ;; esac
exec "$directory/cloudflared" tunnel --no-autoupdate --edge-ip-version auto \
    --protocol "$protocol" run --token-file "$directory/sbargotoken.log"
ARGO_RUN
    chmod 700 "$ARGOSBX_STATE_DIR/argo-run"
}

argo_store() {
    argo_validate || return 1
    (umask 077; printf '%s\n' "$agn" > "$ARGOSBX_STATE_DIR/sbargoym.log"
     printf '%s\n' "$agk" > "$ARGOSBX_STATE_DIR/sbargotoken.log"
     printf '%s\n' "$agproto" > "$ARGOSBX_STATE_DIR/cftupr.log")
    argo_launcher
}

argo_restart() {
    argo_launcher || return 1
    if pidof systemd >/dev/null 2>&1 && [ "$EUID" -eq 0 ]; then
        systemctl restart argo
    elif command -v rc-service >/dev/null 2>&1 && [ "$EUID" -eq 0 ]; then
        rc-service argo restart
    else
        nohup "$ARGOSBX_STATE_DIR/argo-run" >> "$ARGOSBX_STATE_DIR/argo.log" 2>&1 &
    fi
}

argo_origin_hint() {
    if [ "${argo:-}" = vxpt ]; then
        argo_python origin-info "$ARGOSBX_STATE_DIR"
    else
        printf '请在 Cloudflare 将 %s 指向 http://127.0.0.1:%s\n' "$agn" "$argoport"
    fi
}

argo_xhttp_configure() {
    local configured=0
    if [ "${argo:-}" = vxpt ]; then
        argo_python configure "$ARGOSBX_STATE_DIR" || return 1
        configured=1
    fi
    if grep -q '"tag":"xhttp-reality"' "$ARGOSBX_STATE_DIR/xr.json" ||
       grep -q '"tag": "xhttp-reality"' "$ARGOSBX_STATE_DIR/xr.json"; then
        argo_python configure-reality "$ARGOSBX_STATE_DIR" || return 1
        configured=1
    fi
    [ "$configured" = 1 ] || return 0
    "$ARGOSBX_STATE_DIR/xray" run -test -c "$ARGOSBX_STATE_DIR/xr.json" || {
        argo_error 'Xray 配置校验失败，请升级到支持 XHTTP 和 VLESS ENC 的内核'; return 1;
    }
}

argo_reality_export() {
    local summary
    summary=$(argo_python export-reality "$ARGOSBX_STATE_DIR") || return 1
    "$ARGOSBX_STATE_DIR/xray" run -test -c "$ARGOSBX_STATE_DIR/xhttp-reality-client.json" >/dev/null || return 1
    printf '%s\n' "$summary"
    argo_python subscribe-reality "$ARGOSBX_STATE_DIR" "$1" "$ARGOSBX_STATE_DIR/jh.txt"
}

argo_xhttp_export() {
    local summary
    summary=$(argo_python export "$ARGOSBX_STATE_DIR") || return 1
    # Validate the actual generated client, including FinalMask, before sharing it.
    "$ARGOSBX_STATE_DIR/xray" run -test -c "$ARGOSBX_STATE_DIR/xhttp-client.json" >/dev/null || {
        argo_error '客户端配置校验失败，请升级 Xray 内核（FinalMask 需要支持该功能的版本）'; return 1;
    }
    printf '%s\n' "$summary"
    argo_python subscribe "$ARGOSBX_STATE_DIR" "$1" "$ARGOSBX_STATE_DIR/jh.txt"
}
