/* Pure, dependency-free command builder shared with the browser and Node tests. */
(function (root) {
  "use strict";
  const fields = [
    "mode",
    "alpn",
    "path",
    "xmux",
    "finalmask",
    "address",
    "padding_bytes",
    "max_post_bytes",
    "min_post_interval_ms",
    "fragment_length",
    "fragment_interval",
    "fragment_count",
    "download_address",
    "download_port",
    "download_servername",
    "download_host",
    "download_alpn",
    "download_finalmask",
  ];
  const xhttpFields = fields.map((field) => "xhttp_" + field);
  const realityFields = fields
    .filter((field) => !field.startsWith("download_"))
    .map((field) => "reality_" + field);
  const protocols = [
    ["xhpt", "VLESS · XHTTP · REALITY · ENC", "Xray"],
    ["vxpt", "VLESS · XHTTP · ENC", "Xray"],
    ["vlpt", "VLESS · TCP · REALITY · Vision", "Xray"],
    ["vwpt", "VLESS · WebSocket · ENC", "Xray"],
    ["xupt", "VLESS · XHTTP · TLS · H3", "Xray"],
    ["xcpt", "VLESS · XHTTP · TLS · H2/H3", "Xray"],
    ["tupt", "TUIC", "Sing-box"],
    ["anpt", "AnyTLS", "Sing-box"],
    ["nvpt", "NaiveProxy", "Sing-box"],
    ["arpt", "AnyTLS · REALITY", "Sing-box"],
    ["sspt", "Shadowsocks 2022", "Sing-box"],
    ["hypt", "Hysteria2", "自动内核"],
    ["vmpt", "VMess · WebSocket", "自动内核"],
    ["sopt", "SOCKS5", "自动内核"],
  ];
  const globalFields = [
    "uuid",
    "reym",
    "cfip",
    "alns",
    "hyjpt",
    "cdnym",
    "name",
    "warp",
    "ippz",
    "oap",
    "sub",
    "subid",
    "subpt",
    "argo",
    "agn",
    "agk",
    "agproto",
  ];
  const keys = [
    ...protocols.map((p) => p[0]),
    ...globalFields,
    ...realityFields,
    ...xhttpFields,
  ];
  const xmuxPresets = {
    balanced: "",
    "low-reuse": '{"maxConcurrency":"4-8","cMaxReuseTimes":"64-128"}',
    connections: '{"maxConcurrency":0,"maxConnections":4}',
  };
  const scriptURL =
    "https://raw.githubusercontent.com/mutsuki14/argosbx-enhanced/main/argosbx.sh";
  const actions = [
    "",
    "rep",
    "list",
    "status",
    "doctor",
    "res",
    "upx",
    "ups",
    "upa",
    "export",
    "xhttp",
    "del",
  ];

  function quote(value) {
    return "'" + String(value).replace(/'/g, "'\\''") + "'";
  }
  function isIP(value) {
    if (/^(?:\d{1,3}\.){3}\d{1,3}$/.test(value))
      return value.split(".").every((n) => +n <= 255);
    if (!value.includes(":") || /[^a-f\d:]/i.test(value)) return false;
    try {
      return new URL("http://[" + value + "]").hostname.startsWith("[");
    } catch (_) {
      return false;
    }
  }
  function host(value) {
    return (
      isIP(value) ||
      (value.length <= 253 &&
        value
          .split(".")
          .every((p) => /^[a-z\d](?:[a-z\d-]{0,61}[a-z\d])?$/i.test(p)))
    );
  }
  function range(value, floor = 0, ceiling = 2147483647) {
    if (
      !["string", "number"].includes(typeof value) ||
      !/^\d+(?:-\d+)?$/.test(String(value))
    )
      return false;
    const parts = String(value).split("-").map(Number);
    return (
      parts[0] >= floor &&
      parts[0] <= parts[parts.length - 1] &&
      parts[parts.length - 1] <= ceiling
    );
  }
  function issues(v) {
    const errors = [],
      add = (field, message) => errors.push({ field, message });
    const port = (field) => {
      if (
        v[field] &&
        (!/^\d+$/.test(v[field]) || +v[field] < 1 || +v[field] > 65535)
      )
        add(field, "端口须为 1–65535 之间的整数。");
    };
    protocols.forEach(([key]) => port(key));
    port("subpt");
    if (v.xhpt && v.vxpt && +v.xhpt === +v.vxpt)
      add("vxpt", "REALITY 与 Argo 的监听端口不能相同。");
    if (v.reym && !host(v.reym))
      add("reym", "REALITY 目标域名不能包含协议、端口或路径。");
    if (Object.hasOwn(v, "nvpt") && v.alns !== "y")
      add("alns", "NaiveProxy 需要开启域名 / IP 证书 TLS。");
    if (v.argo) {
      if (!["vxpt", "vwpt", "vmpt"].includes(v.argo))
        add("argo", "请选择支持的固定隧道协议。");
      if (!v.agn) add("agn", "请填写固定隧道域名。");
      else if (!host(v.agn) || !v.agn.includes(".") || isIP(v.agn))
        add("agn", "固定隧道需要域名，不能包含协议、端口或路径。");
      else if (/(^|\.)trycloudflare\.com$/i.test(v.agn))
        add("agn", "只支持固定隧道，不支持免费随机域名。");
      if (!v.agk) add("agk", "请填写固定隧道 Token。");
      else if (!/^[a-z\d_+/=-]+$/i.test(v.agk))
        add("agk", "请只填写 Token 本身，不含启动命令。");
      if (v.agproto && !["quic", "http2", "auto"].includes(v.agproto))
        add("agproto", "隧道传输请选择 QUIC、HTTP/2 或自动。");
    }
    for (const prefix of ["reality_", "xhttp_"]) {
      if (prefix === "reality_" ? !Object.hasOwn(v, "xhpt") : v.argo !== "vxpt")
        continue;
      const reality = prefix === "reality_",
        get = (field) => v[prefix + field],
        fail = (f, m) => add(prefix + f, m);
      const mode = get("mode") || (reality ? "stream-one" : "packet-up"),
        alpn = get("alpn") || "h2";
      if (!["packet-up", "stream-up", "stream-one"].includes(mode))
        fail("mode", "请选择 packet-up、stream-up 或 stream-one。");
      if (!["h2", "h3"].includes(alpn))
        fail("alpn", "HTTP 版本须为 H2 或 H3。");
      if (reality && alpn !== "h2") fail("alpn", "REALITY 直连使用 HTTP/2。");
      else if (mode !== "packet-up" && alpn === "h3")
        fail("alpn", "流式模式需要 HTTP/2；HTTP/3 请搭配 packet-up。");
      if (mode === "stream-one" && get("download_address"))
        fail(
          "download_address",
          "stream-one 不支持上下行分离，请改为 stream-up 或关闭分离。",
        );
      if (get("path") && !/^\/[a-z\d/_-]{1,200}$/i.test(get("path")))
        fail("path", "路径以 / 开头，仅含字母、数字、/、_、-，最多 201 字符。");
      for (const f of [
        "address",
        "download_address",
        "download_servername",
        "download_host",
      ]) {
        if (get(f) && !host(get(f)))
          fail(f, "请填写域名或 IP，不含协议、端口或路径。");
      }
      for (const direction of ["", "download_"]) {
        const mask = get(direction + "finalmask") || "off";
        if (!["off", "tls-fragment"].includes(mask))
          fail(direction + "finalmask", "请选择关闭或 TLS 分片。");
        if (mask === "tls-fragment" && get(direction + "alpn") === "h3")
          fail(
            direction + "finalmask",
            "同一方向的 TLS 分片不能与 HTTP/3 同用。",
          );
      }
      if (
        !get("download_address") &&
        ["port", "servername", "host", "finalmask"].some(
          (f) => get("download_" + f) && get("download_" + f) !== "off",
        )
      )
        fail("download_address", "请先填写下行地址。");
      if (
        get("download_address") &&
        isIP(get("download_servername") || get("download_address"))
      )
        fail(
          "download_servername",
          "下行地址为 IP 时，必须填写证书对应的 TLS 域名。",
        );
      port(prefix + "download_port");
      for (const [f, low, high] of [
        ["padding_bytes", 0, 65536],
        ["max_post_bytes", 1, 16000000],
        ["min_post_interval_ms", 0, 60000],
        ["fragment_length", 1, 65536],
        ["fragment_interval", 0, 1000],
        ["fragment_count", 1, 1000],
      ]) {
        if (get(f) && !range(get(f), low, high))
          fail(f, `请输入 ${low}–${high} 内的整数或递增范围。`);
      }
      if (get("xmux")) {
        try {
          const xmux = JSON.parse(get("xmux"));
          if (!xmux || Array.isArray(xmux) || typeof xmux !== "object")
            throw new Error();
          const allowed = [
            "maxConcurrency",
            "maxConnections",
            "cMaxReuseTimes",
            "hMaxRequestTimes",
            "hMaxReusableSecs",
            "hKeepAlivePeriod",
          ];
          if (Object.keys(xmux).some((k) => !allowed.includes(k)))
            fail("xmux", "XMUX 含有未支持的参数，请检查字段名。");
          if (
            Object.entries(xmux).some(([k, value]) =>
              k === "hKeepAlivePeriod"
                ? !Number.isInteger(value) || value < -1 || value > 2147483647
                : !range(value),
            )
          )
            fail("xmux", "XMUX 参数须为有效整数或递增范围；保活周期须为整数。");
          const nonzero = (value) =>
            String(value || "0")
              .split("-")
              .some((n) => +n > 0);
          if (nonzero(xmux.maxConcurrency) && nonzero(xmux.maxConnections))
            fail("xmux", "XMUX 并发限制和连接数限制只能启用一个。");
        } catch (_) {
          fail("xmux", "XMUX 需要合法的 JSON 对象。");
        }
      }
    }
    return errors;
  }
  function validate(values) {
    return issues(values)[0]?.message || "";
  }
  function buildCommand(values, method = "curl", action = "") {
    if (!["curl", "wget"].includes(method) || !actions.includes(action))
      throw new Error("Unsupported command");
    const assignments = keys
      .filter((k) => Object.hasOwn(values, k))
      .map((k) => `${k}=${quote(values[k])}`);
    const fetch =
      method === "wget" ? `wget -qO- ${scriptURL}` : `curl -fLsS ${scriptURL}`;
    return [...assignments, `bash <(${fetch})`, action]
      .filter(Boolean)
      .join(" ");
  }
  // Read literal assignments only. Pasted commands are never executed.
  function parseAssignments(text) {
    const result = {},
      pattern = /\b([A-Za-z_]\w*)\s*=\s*/g;
    let match;
    while ((match = pattern.exec(text))) {
      let i = pattern.lastIndex,
        value = "",
        mode = "";
      for (; i < text.length; i++) {
        const c = text[i];
        if (!mode && /\s/.test(c)) break;
        if (c === "'" && mode !== '"') {
          mode = mode ? "" : "'";
          continue;
        }
        if (c === '"' && mode !== "'") {
          mode = mode ? "" : '"';
          continue;
        }
        if (c === "\\" && mode !== "'" && i + 1 < text.length) {
          value += text[++i];
          continue;
        }
        value += c;
      }
      result[match[1]] = value;
      pattern.lastIndex = i;
    }
    return result;
  }
  const api = {
    fields,
    xhttpFields,
    realityFields,
    protocols,
    globalFields,
    keys,
    actions,
    xmuxPresets,
    quote,
    issues,
    validate,
    buildCommand,
    parseAssignments,
  };
  if (typeof module !== "undefined") module.exports = api;
  else root.ArgosbxEnhanced = api;
})(typeof window !== "undefined" ? window : globalThis);
