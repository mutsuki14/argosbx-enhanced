#!/usr/bin/env bash
# Shared by the VPS installer and the Node container entry point.
ARGOSBX_STATE_DIR=${ARGOSBX_STATE_DIR:-$HOME/agsbx}

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

argo_python() {
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
    local helper_dir
    helper_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
    if [ ! -s "$helper_dir/xhttp_config.py" ]; then
        local pending
        pending=$(mktemp "$helper_dir/xhttp.XXXXXX") || return 1
        if (command -v curl >/dev/null 2>&1 && curl -fLsS --retry 2 "$ARGOSBX_BASE/lib/xhttp_config.py" -o "$pending") ||
           (command -v wget >/dev/null 2>&1 && wget -qO "$pending" "$ARGOSBX_BASE/lib/xhttp_config.py"); then
            mv "$pending" "$helper_dir/xhttp_config.py"
        else
            rm -f "$pending"; argo_error '无法下载 XHTTP 配置组件'; return 1
        fi
    fi
    python3 "$helper_dir/xhttp_config.py" "$@"
}

argo_preflight() {
    argo_validate || return 1
    if [ "${argo:-}" = vxpt ]; then
        # Validate the effective saved + requested configuration before rep stops services.
        argo_python validate "$ARGOSBX_STATE_DIR" || return 1
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
    [ "${argo:-}" = vxpt ] || return 0
    argo_python configure "$ARGOSBX_STATE_DIR" || return 1
    "$ARGOSBX_STATE_DIR/xray" run -test -c "$ARGOSBX_STATE_DIR/xr.json" || {
        argo_error 'Xray 配置校验失败，请升级到支持 XHTTP 和 VLESS ENC 的内核'; return 1;
    }
}

argo_xhttp_export() {
    local summary
    summary=$(argo_python export "$ARGOSBX_STATE_DIR") || return 1
    # Validate the actual generated client, including FinalMask, before sharing it.
    "$ARGOSBX_STATE_DIR/xray" run -test -c "$ARGOSBX_STATE_DIR/xhttp-client.json" >/dev/null || {
        argo_error '客户端配置校验失败，请升级 Xray 内核（FinalMask 需要支持该功能的版本）'; return 1;
    }
    printf '%s\n' "$summary"
    cat "$ARGOSBX_STATE_DIR/xhttp-uri.txt" >> "$1"
}
