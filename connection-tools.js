/* Shared, dependency-free models. No network requests and no stored credentials. */
(function (root) {
  "use strict";
  const stages = {
    client: [
      "客户端",
      "连接从支持 XHTTP 与 VLESS ENC 的客户端发起。这里配置的是客户端 HTTP 版本，与隧道连接协议相互独立。",
      "xhttp_alpn",
    ],
    edge: [
      "Cloudflare 边缘",
      "客户端 TLS 在这里终止。固定域名需要正确路由到隧道；VLESS ENC 继续保护到 Xray 的数据。",
      "agn",
    ],
    tunnel: [
      "cloudflared",
      "运行在服务器上的连接器。QUIC / UDP 或 HTTP/2 / TCP 控制它与 Cloudflare 之间的连接。",
      "agproto",
    ],
    origin: [
      "Xray 回源",
      "packet-up 使用本机 HTTP 回源；流式模式使用 HTTPS + HTTP/2。回源端口必须与 Xray 监听端口一致。",
      "vxpt",
    ],
    reality: [
      "REALITY 直连",
      "客户端通过 TCP / HTTP/2 连接服务器的 REALITY 入站。需要放行监听端口，并在客户端导入匹配的配置。",
      "reality_mode",
    ],
    split: [
      "独立下行",
      "下行通过指定地址回到同一个 XHTTP 入站，路径必须一致。网页不会创建这条线路；需要自行配置并用客户端验证。",
      "xhttp_download_address",
    ],
  };
  const checks = {
    installation: [
      "安装与配置文件",
      "已找到可读取的 Xray 配置。",
      "确认当前用户已安装节点；使用安装时的账户执行诊断。",
    ],
    server_config: [
      "Xray 服务端配置",
      "Xray 内核接受当前服务端配置。",
      "查看 agsbx logs，核对配置和内核版本；不要直接重建整个节点。",
    ],
    xray_process: [
      "Xray 进程",
      "检测到本安装目录的 Xray 进程。",
      "先查看 agsbx logs；确认配置正确后，再用 agsbx res 重启。",
    ],
    profile_config: [
      "节点增强配置",
      "可以读取并解析该节点的增强参数。",
      "确认已安装该类 XHTTP 节点，并检查模式、路径和增强参数是否有效。",
    ],
    client_config: [
      "导出的客户端配置",
      "Xray 内核接受导出的客户端 JSON。",
      "重新运行 agsbx export 导出对应节点，核对客户端内核支持的功能。",
    ],
    origin: [
      "本机监听与回源",
      "本机端口可连接；启用 TLS 的回源同时通过证书与 H2 检查。",
      "查看 Xray 日志、端口占用和监听配置；TLS 回源还需检查证书与 HTTP/2。",
    ],
    fixed_tunnel: [
      "固定隧道参数",
      "域名、Token 格式和端口符合固定隧道要求，未验证 Token 的远端有效性。",
      "核对固定域名、Tunnel Token 和端口，不能使用 trycloudflare.com 随机域名。",
    ],
    cloudflared_process: [
      "cloudflared 进程",
      "检测到本安装目录的连接器进程，不代表远端隧道已就绪。",
      "查看 agsbx logs 及 Cloudflare 隧道状态，确认 Token 和连接器运行情况。",
    ],
    origin_certificate: [
      "本机回源证书",
      "OpenSSL 可读取证书，且证书尚未过期。",
      "检查本机回源证书是否存在、可读取且未过期，以及 OpenSSL 是否已安装。",
    ],
    public_dns: [
      "公网域名 DNS",
      "服务器可以解析固定隧道域名。",
      "核对 Cloudflare DNS 记录和服务器的 DNS 解析；此检查不代表客户端网络可达。",
    ],
    public_tls: [
      "公网 TCP / TLS",
      "服务器可连接域名 TCP/443，且通过系统信任链验证 TLS 证书。",
      "核对域名证书、TCP/443 可达性和 Cloudflare 公开路由；查看域名 DNS 是否正确。",
    ],
    cloudflare_route: [
      "Cloudflare 远端设置",
      "",
      "打开固定隧道助手，逐项核对公开主机名、Service 和回源设置；流式模式仍需实际测试。",
    ],
    reality_target: [
      "REALITY 目标站",
      "",
      "从服务器核对目标站的 TLS 1.3 / H2 支持情况，以及 REALITY 公网端口是否放行。",
    ],
    http3: [
      "客户端 HTTP/3",
      "",
      "用实际客户端验证 H3 / UDP 可达性；服务器上的 TCP/TLS 检查不能代替此项。",
    ],
    split_route: [
      "独立下行线路",
      "",
      "核对下行地址、证书、Host 与路径，确保回到同一 XHTTP 入站，再测试实际传输。",
    ],
    client_connection: [
      "客户端端到端连接",
      "",
      "导入对应客户端配置，测试连接与数据传输。服务器本地检查不等于完整链路已连通。",
    ],
  };
  const codes = [
    "ok",
    "timeout",
    "not_installed",
    "config_invalid",
    "not_running",
    "unsupported_platform",
    "profile_missing",
    "origin_unreachable",
    "tunnel_invalid",
    "certificate_invalid",
    "dns_failed",
    "public_tls_failed",
    "dependency_failed",
    "network_disabled",
    "remote_unverified",
    "client_required",
  ];
  const validHost = (v) =>
    typeof v === "string" &&
    v.length <= 253 &&
    v.includes(".") &&
    !/^\d+(?:\.\d+){3}$/.test(v) &&
    v.split(".").every((x) => /^[a-z\d](?:[a-z\d-]{0,61}[a-z\d])?$/i.test(x)) &&
    !v.toLowerCase().endsWith("trycloudflare.com");
  const validPort = (v) =>
    /^\d+$/.test(String(v)) && Number(v) >= 1 && Number(v) <= 65535;

  function routes(v) {
    const result = [];
    if (Object.hasOwn(v, "xhpt"))
      result.push({
        id: "reality",
        title: "REALITY 直连",
        nodes: ["client", "reality"],
        links: [
          {
            id: "reality-client",
            text: "TCP · H2 · REALITY",
            detail: v.reality_mode || "stream-one",
            field: "reality_mode",
          },
        ],
      });
    if (["vxpt", "vwpt", "vmpt"].includes(v.argo)) {
      const xhttp = v.argo === "vxpt",
        stream = xhttp && ["stream-up", "stream-one"].includes(v.xhttp_mode);
      result.push({
        id: "argo",
        title: "固定 Argo" + (xhttp ? "" : " · WebSocket"),
        nodes: ["client", "edge", "tunnel", "origin"],
        links: [
          {
            id: "client-edge",
            text: xhttp
              ? (v.xhttp_alpn || "h2").toUpperCase() + " · TLS"
              : "WebSocket · TLS",
            detail: xhttp ? v.xhttp_mode || "packet-up" : "WS",
            field: xhttp ? "xhttp_alpn" : "argo",
          },
          {
            id: "edge-tunnel",
            text: {
              quic: "QUIC · UDP",
              http2: "HTTP/2 · TCP",
              auto: "自动 · 可回退",
            }[v.agproto || "quic"],
            detail: "隧道连接",
            field: "agproto",
          },
          {
            id: "tunnel-origin",
            text: stream ? "HTTPS · H2" : "HTTP",
            detail: validPort(v[v.argo])
              ? "127.0.0.1:" + v[v.argo]
              : "回源端口待确认",
            field: v.argo,
          },
        ],
      });
      if (xhttp && v.xhttp_download_address)
        result.push({
          id: "download",
          title: "独立下行（需自行部署）",
          nodes: ["client", "split", "origin"],
          links: [
            {
              id: "client-download",
              text: (v.xhttp_download_alpn || "h2").toUpperCase() + " · TLS",
              detail: "下行线路",
              field: "xhttp_download_address",
            },
            {
              id: "download-origin",
              text: "相同路径",
              detail: "同一 XHTTP 入站",
              field: "xhttp_path",
            },
          ],
        });
    }
    return result;
  }

  function tunnelGuide(v, caPath = "") {
    const enabled = ["vxpt", "vwpt", "vmpt"].includes(v.argo);
    if (!enabled)
      return {
        enabled: false,
        rows: [],
        missing: [],
        ingress: null,
        streaming: false,
      };
    const streaming =
      v.argo === "vxpt" && ["stream-up", "stream-one"].includes(v.xhttp_mode);
    const domain = validHost(v.agn) ? v.agn : "",
      port = validPort(v[v.argo]) ? String(v[v.argo]) : "";
    const ca = caPath.trim(),
      caValid = ca.startsWith("/") && !/[\0\r\n]/.test(ca) && ca.length < 4096;
    const missing = [];
    if (!domain) missing.push("填写有效的固定隧道域名");
    if (!port) missing.push("填入实际回源端口；随机端口需在安装后确认");
    if (streaming && !caValid)
      missing.push("填入 agsbx tunnel 输出的 CA Pool 绝对路径");
    const service = port
      ? (streaming ? "https" : "http") + "://127.0.0.1:" + port
      : "";
    const rows = [
      {
        label: "公开主机名 / Public hostname",
        value: domain || "待填写固定域名",
        copy: !!domain,
      },
      {
        label: "Service",
        value: service || "安装后确认实际回源端口",
        copy: !!service,
      },
      {
        label: "HTTP/2 to origin",
        value: streaming ? "开启 / true" : "关闭 / false",
        copy: false,
      },
      {
        label: "No TLS Verify",
        value: "关闭 / false（保留证书校验）",
        copy: false,
      },
    ];
    const originRequest = { http2Origin: streaming, noTLSVerify: false };
    if (streaming) {
      rows.push(
        { label: "Origin Server Name", value: "localhost", copy: true },
        { label: "Match SNI to Host", value: "关闭 / false", copy: false },
        {
          label: "CA Pool",
          value: caValid ? ca : "复制 agsbx tunnel 输出中的绝对路径",
          copy: caValid,
        },
        {
          label: "域名 Network → gRPC",
          value: "开启；公开隧道的流式兼容性需实测",
          copy: false,
        },
      );
      Object.assign(originRequest, {
        originServerName: "localhost",
        matchSNItoHost: false,
        caPool: ca,
      });
    }
    return {
      enabled: true,
      streaming,
      rows,
      missing,
      ingress: missing.length
        ? null
        : { hostname: domain, service, originRequest },
    };
  }

  function readReport(text) {
    if (typeof text !== "string" || text.length > 262144)
      throw new Error("报告过大，请选择 256 KB 以内的诊断 JSON。");
    let report;
    try {
      report = JSON.parse(text);
    } catch (_) {
      throw new Error("无法解析 JSON，请导入脚本导出的诊断报告。");
    }
    const plain = (x) => x && typeof x === "object" && !Array.isArray(x);
    const exact = (x, allowed) =>
      plain(x) && Object.keys(x).every((k) => allowed.includes(k));
    const bad = () => {
      throw new Error("报告结构或版本不受支持，请重新运行本项目的诊断命令。");
    };
    if (
      !exact(report, [
        "schema",
        "version",
        "generated_at",
        "scope",
        "privacy",
        "network_requested",
        "profiles",
        "checks",
      ]) ||
      report.schema !== "argosbx.diagnostics" ||
      report.version !== 1 ||
      report.scope !== "server" ||
      report.privacy !== "redacted" ||
      typeof report.network_requested !== "boolean" ||
      typeof report.generated_at !== "string" ||
      !/^\d{4}-\d\d-\d\dT/.test(report.generated_at) ||
      !Number.isFinite(Date.parse(report.generated_at)) ||
      !Array.isArray(report.profiles) ||
      report.profiles.length > 2 ||
      !Array.isArray(report.checks) ||
      !report.checks.length ||
      report.checks.length > 40
    )
      bad();
    const seenProfiles = new Set(),
      seenChecks = new Set();
    for (const profile of report.profiles) {
      if (
        !exact(profile, ["id", "mode", "alpn", "split", "origin_tls"]) ||
        !["argo", "reality"].includes(profile.id) ||
        seenProfiles.has(profile.id) ||
        !["packet-up", "stream-up", "stream-one"].includes(profile.mode) ||
        !["h2", "h3"].includes(profile.alpn) ||
        typeof profile.split !== "boolean" ||
        typeof profile.origin_tls !== "boolean"
      )
        bad();
      seenProfiles.add(profile.id);
    }
    for (const check of report.checks) {
      if (
        !exact(check, ["id", "profile", "status", "code"]) ||
        !Object.hasOwn(checks, check.id) ||
        !["server", "argo", "reality"].includes(check.profile) ||
        !["pass", "fail", "skip", "manual"].includes(check.status) ||
        !codes.includes(check.code) ||
        seenChecks.has(check.profile + "/" + check.id) ||
        (check.status === "pass" && check.code !== "ok")
      )
        bad();
      seenChecks.add(check.profile + "/" + check.id);
    }
    if (!seenChecks.has("server/installation")) bad();
    return report;
  }
  function guidance(check) {
    if (check.status === "pass") return checks[check.id][1];
    if (check.code === "timeout")
      return "检查超时。请确认网络和进程状态，稍后重新生成报告。";
    if (check.code === "unsupported_platform")
      return "当前系统不支持 Linux 进程检查，请在实际部署的 Linux 服务器上执行。";
    if (check.code === "network_disabled")
      return "此次未进行公网测试。按需勾选“额外检查公网域名”后重新生成报告。";
    if (check.code === "dependency_failed")
      return "前置检查未通过；先修复固定隧道参数或 DNS 问题。";
    return checks[check.id][2];
  }
  const api = { stages, checks, routes, tunnelGuide, readReport, guidance };
  if (typeof module !== "undefined") module.exports = api;
  else root.ArgosbxConnection = api;
})(typeof window !== "undefined" ? window : globalThis);
