/* Pure helpers shared by the browser command generator and its tests. */
(function (root) {
  const xhttpFields = ['xhttp_mode', 'xhttp_alpn', 'xhttp_path', 'xhttp_xmux',
    'xhttp_finalmask', 'xhttp_address', 'xhttp_download_address', 'xhttp_download_port',
    'xhttp_download_servername', 'xhttp_download_host', 'xhttp_download_alpn',
    'xhttp_download_finalmask'];

  function quote(value) {
    return "'" + String(value).replace(/'/g, "'\\''") + "'";
  }

  function validate(values) {
    if (!values.argo) return '';
    if (!values.agn || !values.agk) return '固定隧道必须同时填写域名和 Token。';
    if (!/^[a-z\d](?:[a-z\d.-]*[a-z\d])?$/i.test(values.agn) || !values.agn.includes('.'))
      return '固定隧道域名不能包含协议、端口或路径。';
    if (/trycloudflare\.com$/i.test(values.agn)) return '不支持免费随机隧道。';
    if (!/^[a-z\d_+/=-]+$/i.test(values.agk)) return '请只填写 Token 本身。';
    if (values.argo !== 'vxpt') return '';
    const mode = values.xhttp_mode || 'packet-up';
    if (!['packet-up', 'stream-up', 'stream-one'].includes(mode))
      return '请选择 packet-up、stream-up 或 stream-one。';
    if (mode !== 'packet-up' && values.xhttp_alpn === 'h3')
      return '固定 Argo 的流式模式请使用 HTTP/2；HTTP/3 请使用 packet-up。';
    if (mode === 'stream-one' && values.xhttp_download_address)
      return 'stream-one 使用同一请求双向传输；请清空下行地址或选择 stream-up。';
    if (values.xhttp_path && !/^\/[a-z\d/_-]{1,200}$/i.test(values.xhttp_path))
      return '路径须以 / 开头，仅含字母、数字、/、_、-。';
    for (const prefix of ['', 'download_']) {
      if (values['xhttp_' + prefix + 'finalmask'] === 'tls-fragment' &&
          values['xhttp_' + prefix + 'alpn'] === 'h3')
        return '同一方向的 TLS 分片不能与 HTTP/3 同用。';
    }
    if (!values.xhttp_download_address && ['port', 'servername', 'host', 'finalmask'].some(
      field => values['xhttp_download_' + field] && values['xhttp_download_' + field] !== 'off'))
      return '请先填写下行地址。';
    if (values.xhttp_download_port && (!/^\d+$/.test(values.xhttp_download_port) ||
        +values.xhttp_download_port < 1 || +values.xhttp_download_port > 65535))
      return '下行端口须在 1–65535 之间。';
    if (values.xhttp_xmux) {
      try {
        const xmux = JSON.parse(values.xhttp_xmux);
        if (!xmux || Array.isArray(xmux) || typeof xmux !== 'object') throw new Error();
        if (xmux.maxConnections && xmux.maxConcurrency) return 'XMUX 两种连接限制只能启用一个。';
      } catch (_) { return 'XMUX 需要合法的 JSON 对象。'; }
    }
    return '';
  }

  // Parse literal assignments for editing; never execute the pasted shell text.
  function parseAssignments(text) {
    const result = {};
    const pattern = /\b([A-Za-z_]\w*)\s*=\s*/g;
    let match;
    while ((match = pattern.exec(text))) {
      let i = pattern.lastIndex, value = '', mode = '';
      for (; i < text.length; i++) {
        const c = text[i];
        if (!mode && /\s/.test(c)) break;
        if (c === "'" && mode !== '"') { mode = mode ? '' : "'"; continue; }
        if (c === '"' && mode !== "'") { mode = mode ? '' : '"'; continue; }
        if (c === '\\' && mode !== "'" && i + 1 < text.length) { value += text[++i]; continue; }
        value += c;
      }
      result[match[1]] = value;
      pattern.lastIndex = i;
    }
    return result;
  }

  const api = {xhttpFields, quote, validate, parseAssignments};
  if (typeof module !== 'undefined') module.exports = api;
  else root.ArgosbxEnhanced = api;
})(typeof window !== 'undefined' ? window : globalThis);
