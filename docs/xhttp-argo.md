# 固定 Argo + XHTTP 增强版

支持 `VLESS + XHTTP + 固定 Cloudflare Tunnel + TLS + VLESS Encryption`，并可组合客户端 HTTP/3、cloudflared QUIC、XMUX、上下行分离和 TLS 分片。

## 快速开始

1. 在 Cloudflare Zero Trust 创建**固定隧道**并取得 Token。
2. 为隧道配置公开主机名，例如 `up.example.com`。服务类型为 **HTTP**，地址为 `127.0.0.1:8080`。域名须由该隧道提供服务并有有效的 Cloudflare 边缘证书。
3. 在 Linux 服务器运行，替换域名和 Token：

```bash
vxpt=8080 argo=vxpt agn=up.example.com agk='你的固定隧道Token' \
  bash <(curl -fLsS https://raw.githubusercontent.com/mutsuki14/argosbx-enhanced/main/argosbx.sh)
```

`vxpt` 是本机回源端口，必须与第二步一致。VLESS ENC 密钥与随机 XHTTP 路径自动生成。这个入站仅监听 `127.0.0.1`，无需向公网开放 8080。cloudflared 与 Xray 必须位于同一主机/网络命名空间。

客户端至 Cloudflare 使用 TLS；cloudflared 至本机 Xray 使用 HTTP。VLESS ENC 是客户端至 Xray 的另一层加密，不会因为 TLS 在 Cloudflare 终止而消失。服务器不需要为这个回环 HTTP 端口配置 TLS 证书。

安装器使用官方 Xray **v26.11.9**，验证下载文件的 SHA-256。客户端也请使用支持这些字段的 Xray 版本；FinalMask 以 v26.11.9 验证。已有旧 Xray 可以先运行 `agsbx upx`。Python 3 是配置生成依赖；root 安装时会尝试安装，非 root 需要预先准备。

固定隧道缺少域名或 Token 会立即报错，**不会申请或恢复 `trycloudflare.com` 随机隧道**。WS/Vmess 的 Argo 入口同样遵守这一要求。

## 导入客户端

运行 `agsbx list` 会重新生成：

| 文件 | 用途 |
| --- | --- |
| `~/agsbx/xhttp-client.json` | 完整 Xray 客户端配置，含本机 `127.0.0.1:10808` SOCKS 入口 |
| `~/agsbx/xhttp-uri.txt` | 支持 `extra` 的客户端可导入的 VLESS URI |
| `~/agsbx/jh.txt` | 普通聚合订阅；存在完整 URI 时自动加入 |
| `~/agsbx/xhttp-options.json` | 保存模式、路径和高级配置，重启及 `list` 不会丢失 |

**启用任一方向的 FinalMask 时只导出 JSON，`xhttp-uri.txt` 留空**。普通 VLESS URI 无统一的顶层 `streamSettings.finalmask` 字段，不能把缺少分片设置的 URI 当作完整配置。Clash/Mihomo/Sing-box 的原有订阅不会被塞入不兼容的高级 Xray 节点；请使用 Xray 自定义 JSON 导入。

## 组合参数

在快速开始的命令前增加以下环境变量即可；修改已安装配置时，在完整命令末尾加 `rep`。`rep` 会重建协议，须带上要保留的其它协议参数。XHTTP 高级选项省略时保留旧值，显式 `xhttp_download_address=''` 并清空对应下行参数可关闭分离，`xhttp_finalmask=off` 可关闭分片。

| 参数 | 默认 | 作用 |
| --- | --- | --- |
| `agproto` | `quic` | cloudflared 至 Cloudflare：`quic` / `http2` / `auto` |
| `xhttp_alpn` | `h2` | 客户端至边缘：`h2` / `h3` |
| `xhttp_mode` | `packet-up` | 内置 HTTP 回源仅支持这个模式，拒绝 `auto` / `stream-up` / `stream-one` |
| `xhttp_address` | 固定隧道域名 | 优选地址或 IP；不改变正确的 Host/SNI |
| `xhttp_path` | 随机生成并保存 | 自定义 `/path`；仅支持字母、数字、`/`、`_`、`-` |
| `xhttp_xmux` | 下述默认值 | XMUX JSON 对象；部分覆盖仍补齐其它限制 |
| `xhttp_finalmask` | `off` | `off` / `tls-fragment`，仅用于 H2 |
| `xhttp_download_address` | 空，不分离 | 下行域名或 IP |
| `xhttp_download_port` | `443` | 下行 TLS 端口 |
| `xhttp_download_servername` | 下行域名 | 下行 SNI/证书名称；地址为 IP 时必填 |
| `xhttp_download_host` | 下行 SNI | 下行 HTTP Host |
| `xhttp_download_alpn` | `h2` | 下行 `h2` / `h3` |
| `xhttp_download_finalmask` | `off` | 下行 H2 可独立启用 `tls-fragment` |

### HTTP/3 + QUIC

```bash
xhttp_alpn=h3 agproto=quic vxpt=8080 argo=vxpt \
  agn=up.example.com agk='你的固定隧道Token' \
  bash <(curl -fLsS https://raw.githubusercontent.com/mutsuki14/argosbx-enhanced/main/argosbx.sh)
```

这是两段独立连接：`xhttp_alpn=h3` 不会配置 cloudflared，`agproto=quic` 也不会让客户端自动使用 H3。域名的 Cloudflare 边缘须支持 HTTP/3；客户端网络须允许相应 UDP，服务器须能连接 Cloudflare Tunnel 的 UDP 7844。UDP 不通可显式改用 H2/HTTP2；`agproto=auto` 允许 cloudflared 自动回退，而 `quic` 不会被脚本改成 TCP。

### XMUX

```bash
xhttp_xmux='{"maxConcurrency":"8-16","hMaxRequestTimes":"600-900","hMaxReusableSecs":"1800-3000"}'
```

把这一项放入同一条部署命令，单独执行赋值不会导出给后续进程。默认值：

```json
{
  "maxConcurrency": "16-32",
  "maxConnections": 0,
  "cMaxReuseTimes": 0,
  "hMaxRequestTimes": "600-900",
  "hMaxReusableSecs": "1800-3000",
  "hKeepAlivePeriod": 0
}
```

`maxConcurrency` 与 `maxConnections` 不能同时非零。不要再开启客户端通用 `mux.cool`。参数影响连接复用方式，不能保证特定网络的速度或抗识别效果。

### 上行固定 Argo，下行直连/另一 CDN

增加 `xhttp_download_address=down.example.com`。若连接直连 IP，另加 `xhttp_download_servername=down.example.com`。程序在 `downloadSettings` 中写入独立 TLS、Host、ALPN、XMUX，且保证上下行使用同一路径。

**两个入口必须最终到达同一个 Xray 进程中的同一个 XHTTP 入站**。不能仅用同 UUID 在另一台服务器再开一个 Xray，也不能把两条线路分配给不同副本。另一 CDN/直连域名须有有效证书，并反向代理到上面同一个 `127.0.0.1:8080`。

例如在同机 Caddy 中为直连域名配置（域名解析、证书签发和防火墙由部署者准备）：

```caddyfile
down.example.com {
    reverse_proxy 127.0.0.1:8080 {
        flush_interval -1
    }
}
```

整个随机路径都必须原样透传，不能缓存 XHTTP 请求/响应，不能增加登录页或验证码。若经另一 CDN，该 CDN 同样须支持持续流式响应。脚本不会代你创建第二个域名、证书或外部 CDN。配置下行地址只生成客户端设置，无法单凭地址证明这条线路已可用。

### FinalMask

增加 `xhttp_finalmask=tls-fragment`，对客户端发往 Cloudflare 的 TLS ClientHello 分片，使用真实的 `streamSettings.finalmask.tcp` 配置。它保留合法 TLS 流，可通过 HTTPS 边缘；不向 Argo 回源的明文 HTTP 监听器增加同款伪装。

H3 使用 UDP，不能在同一方向叠加 TCP TLS 分片。可以组合 **上行 H3 + 下行 H2 分片**。本实现不会对 Cloudflare 不认识的自定义 TCP 头、UDP 混淆或任意伪装协议宣称兼容。不能任意填写不属于该 HTTPS 服务的 SNI 作为“伪装域名”；证书校验保持开启。

## 容器

增强版须从本仓库构建，原来的 `ygkkk/argosbx` 镜像不包含这里的修改：

```bash
docker build -f container/nodejs/Dockerfile -t argosbx-enhanced .
docker run -d --name argosbx-enhanced --restart unless-stopped \
  -e uuid='你的UUID' -e vxpt=8080 -e argo=vxpt \
  -e agn=up.example.com -e agk='你的固定隧道Token' \
  -p 3000:3000 -v argosbx-data:/root/agsbx argosbx-enhanced
```

Node 入口与主脚本共享配置生成器；初始化失败时容器退出。原订阅路径为 `/<UUID>`，完整配置为 `/<UUID>/xhttp.json`。这些路径含节点凭据，请自行限制访问。此容器中 Cloudflare 回源仍为 `http://127.0.0.1:8080`，不是网页服务的 3000 端口。

仓库保留的 SAP 批量部署脚本是旧版流程，使用原作者镜像，只适用于原有协议；不提供本增强版 XHTTP 组合。其 Argo 配置也必须提供固定域名和 Token。

## 验证范围

自动测试覆盖配置生成、URL 编码、XMUX 冲突、凭据缺失、禁止随机隧道、Token 文件权限及固定启动器。使用真实 Xray v26.11.9 校验服务端和客户端配置；本地 H2 反向代理、H3、FinalMask、上下行分离均测试加密双向传输，保持 TLS 证书校验开启。

本地反向代理测试发现 `stream-up` 在默认 HTTP/1.1 回源链路无法完成传输，因此内置方案固定使用 `packet-up`。流式上行需要另外设计 HTTP/2 回源，未在本版本提供。

这些测试不等同于真实 Cloudflare 域名、目标运营商网络的连通性或测速；部署后需检查 Tunnel 日志并用客户端实际连接。安装日志只报告连接器启动，不会把“填了域名”误报为端到端成功。

参考：[XHTTP 官方说明](https://github.com/XTLS/Xray-core/discussions/4113)、[FinalMask 官方配置](https://xtls.github.io/config/transports/finalmask.html)、[Cloudflare 隧道运行参数](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/)。
