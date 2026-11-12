# 固定 Argo + XHTTP 增强版

支持 `VLESS + XHTTP + 固定 Cloudflare Tunnel + TLS + VLESS Encryption`，并可组合客户端 HTTP/3、cloudflared QUIC、XMUX、上下行分离和 TLS 分片。模式包含默认的 `packet-up` 和实验性的 `stream-up` / `stream-one`。

## 快速开始

1. 在 Cloudflare Zero Trust 创建**固定隧道**并取得 Token。
2. 为隧道配置公开主机名，例如 `up.example.com`。服务类型为 **HTTP**，地址为 `127.0.0.1:8080`。域名须由该隧道提供服务并有有效的 Cloudflare 边缘证书。
3. 在 Linux 服务器运行，替换域名和 Token：

```bash
vxpt=8080 argo=vxpt agn=up.example.com agk='你的固定隧道Token' \
  bash <(curl -fLsS https://raw.githubusercontent.com/mutsuki14/argosbx-enhanced/main/argosbx.sh)
```

`vxpt` 是本机回源端口，必须与第二步一致。VLESS ENC 密钥与随机 XHTTP 路径自动生成。这个入站仅监听 `127.0.0.1`，无需向公网开放 8080。cloudflared 与 Xray 必须位于同一主机/网络命名空间。

上述默认 `packet-up` 方案中，客户端至 Cloudflare 使用 TLS，cloudflared 至本机 Xray 使用 HTTP。VLESS ENC 是客户端至 Xray 的另一层加密，不会因为 TLS 在 Cloudflare 终止而消失。流式模式则会为这个回环端口生成证书并启用 HTTPS / H2，见下文。

安装器使用官方 Xray **v26.11.9**，验证下载文件的 SHA-256。客户端也请使用支持这些字段的 Xray 版本；FinalMask 以 v26.11.9 验证。已有旧 Xray 可以先运行 `agsbx upx`。Python 3 是配置生成依赖；root 安装时会尝试安装，非 root 需要预先准备。

固定隧道缺少域名或 Token 会立即报错，**不会申请或恢复 `trycloudflare.com` 随机隧道**。WS/Vmess 的 Argo 入口同样遵守这一要求。

## stream-up 与 stream-one

两种模式都使用流式上行。`stream-up` 用两个请求分别承载上下行，允许 `downloadSettings`；`stream-one` 用同一个请求双向收发，**不能配置下行分离**。本固定 Argo 方案的流式客户端限定为 H2；H3 继续使用 `packet-up`。

```bash
xhttp_mode=stream-up xhttp_alpn=h2 \
  vxpt=8080 argo=vxpt agn=up.example.com agk='你的固定隧道Token' \
  bash <(curl -fLsS https://raw.githubusercontent.com/mutsuki14/argosbx-enhanced/main/argosbx.sh)
```

将 `xhttp_mode=stream-up` 改为 `xhttp_mode=stream-one` 可使用单请求双向流。修改已有安装时追加 `rep`，并保留其他协议参数；若之前存在下行分离配置，切换 `stream-one` 时显式传入 `xhttp_download_address=''`。

主脚本和 Node 容器会自动：

1. 通过 OpenSSL 生成仅用于本机回源的自签证书 `~/agsbx/xhttp-origin.crt` 与私钥 `~/agsbx/xhttp-origin.key`；重配复用有效证书，临近过期时重新生成。
2. 将同一回环端口切换为 TLS，ALPN 为 `h2`，不需要额外安装反向代理。
3. 保留客户端 gRPC 请求头（`noGRPCHeader=false`）；在 `stream-one` 服务端设置 `noSSEHeader=true`，避免以 SSE 内容类型回应双向请求。
4. 导出 `~/agsbx/xhttp-tunnel-ingress.json`，提示远端固定隧道所需的回源配置。

**必须在 Cloudflare 同步修改这条公开主机名的配置**。以 root 部署且 `vxpt=8080` 为例，导出的路由片段为：

```json
{
  "hostname": "up.example.com",
  "service": "https://127.0.0.1:8080",
  "originRequest": {
    "http2Origin": true,
    "noTLSVerify": false,
    "originServerName": "localhost",
    "matchSNItoHost": false,
    "caPool": "/root/agsbx/xhttp-origin.crt"
  }
}
```

在固定隧道的 Routes / 公开主机名设置中，服务选 HTTPS，开启 **HTTP/2 to origin**，Origin Server Name 填 `localhost`，关闭 **Match SNI to Host**，CA Pool 填部署输出的绝对路径。**Disable TLS certificate verification 保持关闭**。非 root 安装的路径不同；容器须填写容器内路径。只修改对应路由，不要用这个片段替换整个隧道配置。

还需在该域名的 Network 设置中开启 gRPC。Tunnel Token 只用于运行连接器；脚本不会将其当作账户 API Token，也不会自动修改远端路由或域名设置。保存设置后，重新导入生成的客户端 JSON 并实际连接。

本方案补齐了流式模式所需的本机 HTTPS / H2 链路，但 Cloudflare 官方仍注明**公开主机名上的 gRPC 不在支持范围内**。Xray 的 gRPC 请求头兼容技巧不等于 Cloudflare 对其提供保障；两种模式均标为实验性。若仍然不通，可以回退 `xhttp_mode=packet-up`，并将远端服务改回 HTTP、关闭 HTTP/2 to origin。

参考：[Cloudflare HTTP/2 回源](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/origin-parameters/#http2origin)、[Cloudflare gRPC 限制](https://developers.cloudflare.com/network/grpc-connections/)、[Xray 流式模式说明](https://github.com/XTLS/Xray-core/discussions/4113)。

## 导入客户端

运行 `agsbx list` 会重新生成：

| 文件 | 用途 |
| --- | --- |
| `~/agsbx/xhttp-client.json` | 完整 Xray 客户端配置，含本机 `127.0.0.1:10808` SOCKS 入口 |
| `~/agsbx/xhttp-uri.txt` | 支持 `extra` 的客户端可导入的 VLESS URI |
| `~/agsbx/jh.txt` | 普通聚合订阅；存在完整 URI 时自动加入 |
| `~/agsbx/xhttp-options.json` | 保存模式、路径和高级配置，重启及 `list` 不会丢失 |
| `~/agsbx/xhttp-tunnel-ingress.json` | 单条固定隧道路由的回源设置，需自行应用到 Cloudflare |

**启用任一方向的 FinalMask 时只导出 JSON，`xhttp-uri.txt` 留空**。普通 VLESS URI 无统一的顶层 `streamSettings.finalmask` 字段，不能把缺少分片设置的 URI 当作完整配置。Clash/Mihomo/Sing-box 的原有订阅不会被塞入不兼容的高级 Xray 节点；请使用 Xray 自定义 JSON 导入。

## 组合参数

在快速开始的命令前增加以下环境变量即可；修改已安装配置时，在完整命令末尾加 `rep`。`rep` 会重建协议，须带上要保留的其它协议参数。XHTTP 高级选项省略时保留旧值，显式 `xhttp_download_address=''` 并清空对应下行参数可关闭分离，`xhttp_finalmask=off` 可关闭分片。

| 参数 | 默认 | 作用 |
| --- | --- | --- |
| `agproto` | `quic` | cloudflared 至 Cloudflare：`quic` / `http2` / `auto` |
| `xhttp_alpn` | `h2` | 客户端至边缘：`h2` / `h3` |
| `xhttp_mode` | `packet-up` | `packet-up` 使用 HTTP 回源；`stream-up` / `stream-one` 使用 HTTPS / H2 回源；不接受 `auto` |
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

`packet-up` 可在同机 Caddy 中为直连域名配置如下（域名解析、证书签发和防火墙由部署者准备）：

```caddyfile
down.example.com {
    reverse_proxy 127.0.0.1:8080 {
        flush_interval -1
    }
}
```

整个随机路径都必须原样透传，不能缓存 XHTTP 请求/响应，不能增加登录页或验证码。若经另一 CDN，该 CDN 同样须支持持续流式响应。脚本不会代你创建第二个域名、证书或外部 CDN。配置下行地址只生成客户端设置，无法单凭地址证明这条线路已可用。

### 流式分离的下行回源

`stream-up` 将同一 Xray 入站切换为 HTTPS，因此下行反向代理也必须同步改为 HTTPS / H2，不能继续明文回源。以下使用支持 `tls_trust_pool` 的 Caddy：

```caddyfile
down.example.com {
    reverse_proxy https://127.0.0.1:8080 {
        flush_interval -1
        transport http {
            versions 2
            tls_server_name localhost
            tls_trust_pool file /etc/caddy/xhttp-origin.crt
        }
    }
}
```

将生成的 **`xhttp-origin.crt` 公开证书**复制到示例路径并让 Caddy 服务用户可读；私钥仍只保留在 Xray 配置目录。回源证书更换后同步更新此副本并重载 Caddy。该证书只用于本机回源信任，客户端验证的仍是 `down.example.com` 的公网证书。[Caddy 回源 TLS 文档](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#the-http-transport)。

`stream-one` 没有独立下行请求，不能使用上述分离方案。

### FinalMask

增加 `xhttp_finalmask=tls-fragment`，对客户端发往 Cloudflare 的 TLS ClientHello 分片，使用真实的 `streamSettings.finalmask.tcp` 配置。它保留合法 TLS 流，可通过 HTTPS 边缘；不向 Argo 的本机回源连接增加同款分片。三种模式的 H2 客户端均可使用。

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

Node 入口与主脚本共享配置生成器；初始化失败时容器退出。原订阅路径为 `/<UUID>`，完整配置为 `/<UUID>/xhttp.json`。这些路径含节点凭据，请自行限制访问。默认回源为 `http://127.0.0.1:8080`；通过 `-e xhttp_mode=stream-up` 或 `stream-one` 启用流式模式时，改为 HTTPS 并应用上面的 HTTP/2 回源设置，CA Pool 填 `/root/agsbx/xhttp-origin.crt`。回源不使用网页服务的 3000 端口。

仓库保留的 SAP 批量部署脚本是旧版流程，使用原作者镜像，只适用于原有协议；不提供本增强版 XHTTP 组合。其 Argo 配置也必须提供固定域名和 Token。

## 验证范围

自动测试覆盖配置生成、URL 编码、XMUX 冲突、凭据缺失、禁止随机隧道、证书和 Token 文件权限及固定启动器。使用真实 Xray v26.11.9 校验服务端和客户端配置；三种模式、本地 H2 反向代理、H3、FinalMask、上下行分离均测试加密传输，保持客户端与回源的 TLS 证书校验开启。

流式测试的代理要求回源实际协商到 HTTP/2，避免把 HTTP/1.1 降级误判为成功。除整段上传下载外，还测试服务端先发送数据、客户端收到每段响应后才发送下一段，确保请求未结束时也能双向传输。`stream-one` 与分离冲突会在停止原服务前结合已保存参数检查。

这些测试不等同于真实 Cloudflare 域名、目标运营商网络的连通性或测速；部署后需检查 Tunnel 日志并用客户端实际连接。安装日志只报告连接器启动，不会把“填了域名”误报为端到端成功。

参考：[XHTTP 官方说明](https://github.com/XTLS/Xray-core/discussions/4113)、[FinalMask 官方配置](https://xtls.github.io/config/transports/finalmask.html)、[Cloudflare 隧道运行参数](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/run-parameters/)。
