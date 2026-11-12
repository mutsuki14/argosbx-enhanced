/* UI state lives in this page only; only the theme preference is persisted. */
(function () {
  "use strict";
  const core = window.ArgosbxEnhanced;
  const $ = (id) => document.getElementById(id);
  const all = (selector) => [...document.querySelectorAll(selector)];
  const form = $("config-form");
  let profile = "reality",
    method = "curl",
    action = "",
    command = "",
    activeTab = "basic",
    toastTimer;
  const touched = new Set();
  const icon = (name) =>
    '<svg class="icon" aria-hidden="true"><use href="#i-' + name + '"/></svg>';
  const input = (id, label, placeholder, full) =>
    '<div class="field' +
    (full ? " full" : "") +
    '"><label for="' +
    id +
    '">' +
    label +
    '</label><input id="' +
    id +
    '" data-var placeholder="' +
    placeholder +
    '" spellcheck="false"></div>';
  const select = (id, label, options) =>
    '<div class="field"><label for="' +
    id +
    '">' +
    label +
    '</label><select id="' +
    id +
    '" data-var>' +
    options
      .map((o) => '<option value="' + o[0] + '">' + o[1] + "</option>")
      .join("") +
    "</select></div>";

  function enhancement(name) {
    const reality = name === "reality",
      p = reality ? "reality_" : "xhttp_";
    const modes = reality
      ? [
          ["stream-one", "stream-one · 默认"],
          ["stream-up", "stream-up"],
          ["packet-up", "packet-up"],
        ]
      : [
          ["packet-up", "packet-up · 默认"],
          ["stream-up", "stream-up · 实验性"],
          ["stream-one", "stream-one · 实验性"],
        ];
    return (
      '<div id="enhance-' +
      name +
      '" class="enhance-block">' +
      '<div class="field-grid">' +
      select(p + "mode", "XHTTP 传输模式", modes) +
      select(
        p + "alpn",
        "客户端 HTTP 版本",
        reality
          ? [["h2", "HTTP/2"]]
          : [
              ["h2", "HTTP/2 · 默认"],
              ["h3", "HTTP/3"],
            ],
      ) +
      "</div>" +
      '<div class="info-note experimental" id="' +
      p +
      'stream-note" hidden><span>i</span><p>流式 Argo 为实验性。需配置 HTTPS 回源、HTTP/2 to origin、CA Pool 与域名 gRPC。stream-one 不能同时启用下行分离。</p></div>' +
      '<div class="section-mini-title">连接复用 <span>XMUX</span></div><div class="field-grid"><div class="field full"><label for="' +
      p +
      'xmux-preset">复用方案</label><select id="' +
      p +
      'xmux-preset" data-xmux="' +
      p +
      '"><option value="balanced">均衡 · 默认 16–32 并发</option><option value="low-reuse">低复用 · 4–8 并发</option><option value="connections">固定连接 · 4 条连接</option><option value="custom">自定义 JSON</option></select><small>控制连接复用与生命周期，效果取决于网络和客户端。</small></div><div class="field full" id="' +
      p +
      'xmux-editor" hidden><label for="' +
      p +
      'xmux">XMUX 参数</label><textarea class="mono" id="' +
      p +
      'xmux" data-var spellcheck="false" placeholder=\'{"maxConcurrency":"16-32"}\'></textarea></div></div>' +
      '<div class="section-mini-title">传输伪装 <span>FINALMASK</span></div><div class="field-grid">' +
      select(p + "finalmask", "TLS 握手分片", [
        ["off", "关闭 · 默认"],
        ["tls-fragment", "开启 TLS 分片"],
      ]) +
      input(p + "path", "XHTTP 路径", "留空自动生成随机路径") +
      "</div>" +
      '<p class="field-help">分片不等于加速，可能增加延迟。开启后请导入完整客户端 JSON。</p>' +
      '<div class="field-grid" id="' +
      p +
      'fragments" hidden>' +
      input(p + "fragment_length", "分片长度 / 字节", "100-200") +
      input(p + "fragment_interval", "分片间隔 / 毫秒", "0-1") +
      input(p + "fragment_count", "最大分片数量", "2-3") +
      "</div>" +
      '<details class="disclosure"><summary>HTTP 填充与分包 <span>进阶</span></summary><div class="field-grid">' +
      input(p + "padding_bytes", "HTTP 填充 / 字节", "100-1000") +
      input(p + "max_post_bytes", "每次 POST 上限 / 字节", "1000000") +
      input(p + "min_post_interval_ms", "POST 最小间隔 / 毫秒", "30") +
      (reality
        ? ""
        : input(p + "address", "连接地址 / 优选 IP", "默认固定隧道域名")) +
      '</div><p class="field-help">POST 参数用于 packet-up。留空使用脚本默认值。</p></details>' +
      (reality
        ? ""
        : '<div class="disclosure"><div class="section-mini-title toggle-line"><label for="split-enabled">上下行分离<small>上行走 Argo，下行使用另一条线路。</small></label><input id="split-enabled" class="toggle" type="checkbox"></div><div id="split-fields" hidden><div class="field-grid">' +
          input(p + "download_address", "下行地址", "另一 CDN 域名或直连 IP") +
          input(p + "download_port", "下行端口", "443") +
          input(
            p + "download_servername",
            "下行 TLS 域名 / SNI",
            "IP 下行时必须填写证书域名",
          ) +
          input(p + "download_host", "下行 HTTP Host", "默认与 TLS 域名相同") +
          select(p + "download_alpn", "下行 HTTP 版本", [
            ["h2", "HTTP/2"],
            ["h3", "HTTP/3"],
          ]) +
          select(p + "download_finalmask", "下行 TLS 分片", [
            ["off", "关闭"],
            ["tls-fragment", "开启 TLS 分片"],
          ]) +
          '</div><p class="field-help">上下行须抵达同一 XHTTP 入站，使用相同路径。这里只生成配置，不会创建下行线路。</p></div></div>') +
      "</div>"
    );
  }

  $("enhancement-fields").innerHTML =
    enhancement("reality") + enhancement("argo");
  $("protocol-list").innerHTML = core.protocols
    .map(
      ([key, label, group]) =>
        '<div class="protocol-row"><label><input type="checkbox" data-proto="' +
        key +
        '"' +
        (["xhpt", "vxpt"].includes(key) ? " checked" : "") +
        "><span>" +
        label +
        "<small>" +
        group +
        "</small></span></label>" +
        (["xhpt", "vxpt"].includes(key)
          ? '<button type="button" class="port-link" data-focus-port="' +
            key +
            '">端口 <span id="port-summary-' +
            key +
            '"></span> ↗</button>'
          : '<input id="port-' +
            key +
            '" data-port="' +
            key +
            '" data-extra-port placeholder="随机端口" inputmode="numeric" aria-label="' +
            label +
            ' 端口">') +
        "</div>",
    )
    .join("");

  function checked(key) {
    return document.querySelector('[data-proto="' + key + '"]').checked;
  }
  function enabledProfiles() {
    return {
      reality: checked("xhpt"),
      argo: $("argo").value === "vxpt" && checked("vxpt"),
    };
  }
  function setPressed(nodes, attr, current) {
    nodes.forEach((node) => {
      const selected = node.dataset[attr] === current;
      node.classList.toggle("active", selected);
      node.setAttribute("aria-pressed", String(selected));
    });
  }
  function tab(name, focus) {
    activeTab = name;
    all("[data-tab]").forEach((button) => {
      const selected = button.dataset.tab === name;
      button.classList.toggle("active", selected);
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    all(".tab-panel").forEach((panel) => {
      panel.hidden = panel.id !== "panel-" + name;
    });
    if (focus) $("tab-" + name).focus();
  }
  function sync() {
    const profiles = enabledProfiles(),
      argo = !!$("argo").value;
    const hasReality = checked("xhpt") || checked("vlpt") || checked("arpt");
    if (!profiles[profile]) profile = profiles.reality ? "reality" : "argo";
    $("reality-connection").hidden = !hasReality;
    $("argo-connection").hidden = !argo;
    $("reality_address").closest(".field").hidden = !profiles.reality;
    $("port-xhpt").closest(".field").hidden = !profiles.reality;
    // The same vxpt field is also editable when the user selects a direct XHTTP node.
    if (!argo && checked("vxpt")) $("argo-connection").hidden = false;
    ["agn", "agk", "agproto"].forEach((id) => {
      $(id).disabled = !argo;
      $(id).closest(".field").hidden = !argo;
    });
    $("port-vxpt").closest(".field").hidden =
      argo && $("argo").value !== "vxpt";
    $("argo-connection").querySelector("h4").textContent = argo
      ? "固定 Argo 隧道"
      : "XHTTP 直连";
    const tunnelNote = $("argo-connection").querySelector(".info-note");
    tunnelNote.hidden = !argo;
    tunnelNote.querySelector("p").textContent =
      $("argo").value === "vxpt"
        ? "仅支持固定隧道。选择流式模式后，还需调整 Cloudflare 回源设置。"
        : "仅支持固定隧道。回源端口请在“更多设置”的对应协议中填写。";
    $("reality_address").disabled = !profiles.reality;
    $("reym").disabled = !hasReality;
    $("hyjpt").disabled = !checked("hypt");
    $("cfip").disabled = !["vxpt", "vwpt", "vmpt", "xcpt"].some(checked);
    $("cdnym").disabled = !["vxpt", "vwpt", "vmpt"].some(checked);
    $("subid").disabled = $("sub").value !== "y";
    $("subpt").disabled = $("sub").value !== "y";
    all("[data-profile]").forEach((button) => {
      button.disabled = !profiles[button.dataset.profile];
    });
    setPressed(all("[data-profile]"), "profile", profile);
    $("enhancement-empty").hidden = profiles.reality || profiles.argo;
    for (const name of ["reality", "argo"]) {
      const p = name === "reality" ? "reality_" : "xhttp_",
        active = profiles[name];
      $("enhance-" + name).hidden = profile !== name || !active;
      const split = name === "argo" && $("split-enabled").checked;
      const mask = $(p + "finalmask").value === "tls-fragment";
      all("#enhance-" + name + " [data-var]").forEach((el) => {
        el.disabled =
          !active ||
          (el.id.includes("_download_") && !split) ||
          (el.id.includes("_fragment_") && !mask);
      });
      $(p + "xmux-editor").hidden = $(p + "xmux-preset").value !== "custom";
      $(p + "fragments").hidden = !mask;
      $(p + "stream-note").hidden =
        name === "reality" || $(p + "mode").value === "packet-up";
    }
    $("split-fields").hidden = !$("split-enabled").checked;
    for (const key of ["xhpt", "vxpt"])
      $("port-summary-" + key).textContent = $("port-" + key).value || "随机";
    const selected = core.protocols
      .filter(([key]) => checked(key))
      .map((p) => p[0]);
    let preset = "";
    if (
      selected.length === 2 &&
      checked("xhpt") &&
      checked("vxpt") &&
      $("argo").value === "vxpt"
    )
      preset = "dual";
    else if (selected.length === 1 && checked("xhpt") && !argo)
      preset = "reality";
    else if (
      selected.length === 1 &&
      checked("vxpt") &&
      $("argo").value === "vxpt"
    )
      preset = "argo";
    setPressed(all("[data-preset]"), "preset", preset);
    $("custom-notice").hidden = !!preset;
    return selected;
  }
  function values() {
    const result = {};
    core.protocols.forEach(([key]) => {
      if (checked(key)) result[key] = $("port-" + key).value.trim();
    });
    all("[data-var]").forEach((el) => {
      if (!el.disabled && el.value.trim() !== "")
        result[el.id] = el.value.trim();
    });
    if ($("argo").value === "vxpt")
      result.xhttp_download_address = $("split-enabled").checked
        ? $("xhttp_download_address").value.trim()
        : "";
    return result;
  }
  function focusField(field) {
    const el = $(field) || $("port-" + field);
    if (!el) {
      tab("advanced", true);
      return;
    }
    if (
      field.startsWith("xhttp_") ||
      (field.startsWith("reality_") && field !== "reality_address")
    ) {
      profile = field.startsWith("reality_") ? "reality" : "argo";
      sync();
    }
    const panel = el.closest(".tab-panel");
    if (panel) tab(panel.id.replace("panel-", ""));
    for (let node = el.parentElement; node; node = node.parentElement)
      if (node.tagName === "DETAILS") node.open = true;
    if (el.id.endsWith("_xmux")) {
      $(el.id.replace("xmux", "xmux-preset")).value = "custom";
      $(el.id + "-editor").hidden = false;
    }
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    el.focus({ preventScroll: true });
  }
  function render() {
    const selected = sync(),
      v = values(),
      management = action !== "" && action !== "rep";
    let errors = management ? [] : core.issues(v);
    if (!management && selected.length === 0)
      errors.unshift({ field: "argo", message: "请至少选择一种部署协议。" });
    if (
      !management &&
      $("split-enabled").checked &&
      enabledProfiles().argo &&
      !v.xhttp_download_address
    )
      errors.push({
        field: "xhttp_download_address",
        message: "开启上下行分离后，请填写下行地址。",
      });
    const outgoing = management
      ? action === "list" && v.ippz
        ? { ippz: v.ippz }
        : {}
      : v;
    command = errors.length ? "" : core.buildCommand(outgoing, method, action);
    const display = { ...outgoing };
    if (display.agk) display.agk = "<已隐藏的 Token>";
    if (display.uuid) display.uuid = "<已隐藏的 UUID / 密码>";
    if (display.subid) display.subid = "<已隐藏的订阅密码>";
    $("output").value = command
      ? core
          .buildCommand(display, method, action)
          .replace(/ (bash <\()/, " " + String.fromCharCode(92, 10) + "$1")
      : "";
    $("output").placeholder =
      "# " +
      (errors[0]?.message || "请选择部署方案。") +
      "\n# 完成配置后自动生成命令";
    $("copy").disabled = $("download").disabled = !command;
    $("copy").querySelector("span").textContent = management
      ? "复制管理命令"
      : action === "rep"
        ? "复制重配命令"
        : "复制部署命令";
    $("command-label").textContent = command
      ? action
        ? "agsbx · " + action
        : "准备好，开始连接。"
      : "你的连接，即将就绪";
    $("status-text").textContent = errors.length
      ? "还有 " + errors.length + " 项需要填写或调整"
      : "配置已就绪，可以复制";
    $("preview-status").classList.toggle("ready", !errors.length);
    $("validation-count").textContent = errors.length
      ? errors.length + " 项待完成"
      : "已通过";
    $("node-count").textContent = management
      ? "管理命令"
      : selected.length + " 个节点";
    $("enc-summary").textContent = ["xhpt", "vxpt", "vwpt"].some(checked)
      ? "已开启"
      : "依所选协议";
    $("secret-note").hidden =
      !command || !["agk", "uuid", "subid"].some((k) => outgoing[k]);
    $("secret-note").textContent =
      "预览已隐藏 Token、UUID 和订阅密码；复制或下载包含完整值。";
    $("return-install").hidden = !action;
    $("issue-list").replaceChildren();
    all("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
    errors.forEach((error) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "issue-button";
      button.textContent = error.message;
      button.addEventListener("click", () => focusField(error.field));
      $("issue-list").append(button);
      const el = $(error.field) || $("port-" + error.field);
      if (el && touched.has(el.id)) el.setAttribute("aria-invalid", "true");
    });
    $("connection-summary").replaceChildren();
    for (const [key, title, glyph, p] of [
      ["xhpt", "REALITY 直连", "shield", "reality_"],
      [
        "vxpt",
        $("argo").value === "vxpt" ? "固定 Argo 隧道" : "XHTTP 直连",
        "cloud",
        "xhttp_",
      ],
    ]) {
      if (!checked(key)) continue;
      const item = document.createElement("div");
      item.className = "connection-item";
      item.innerHTML =
        icon(glyph) +
        '<div><strong></strong><p></p></div><span class="connection-badge"></span>';
      item.querySelector("strong").textContent = title;
      item.querySelector("p").textContent =
        (v[p + "mode"] || (key === "xhpt" ? "stream-one" : "packet-up")) +
        " / " +
        (v[p + "alpn"] || "h2").toUpperCase();
      item.querySelector(".connection-badge").textContent = v[key]
        ? ":" + v[key]
        : "随机端口";
      $("connection-summary").append(item);
    }
    const extra = selected.filter((k) => !["xhpt", "vxpt"].includes(k));
    if (extra.length) {
      const line = document.createElement("p");
      line.className = "field-help";
      line.textContent =
        "附加协议：" +
        extra.map((k) => core.protocols.find((p) => p[0] === k)[1]).join("、");
      $("connection-summary").append(line);
    }
  }

  function preset(name) {
    all("[data-proto]").forEach((el) => {
      el.checked =
        name === "dual"
          ? ["xhpt", "vxpt"].includes(el.dataset.proto)
          : el.dataset.proto === (name === "reality" ? "xhpt" : "vxpt");
    });
    $("argo").value = name === "reality" ? "" : "vxpt";
    if (!$("port-xhpt").value) $("port-xhpt").value = "443";
    if (!$("port-vxpt").value) $("port-vxpt").value = "8080";
    action = "";
    render();
  }
  function toast(message) {
    clearTimeout(toastTimer);
    $("toast").textContent = message;
    $("toast").classList.add("visible");
    toastTimer = setTimeout(() => $("toast").classList.remove("visible"), 3000);
  }
  function defaultForm() {
    form.reset();
    touched.clear();
    action = "";
    profile = "reality";
    $("agk").type = "password";
    $("token-toggle").textContent = "显示";
    $("token-toggle").setAttribute("aria-label", "显示 Token");
    all("[data-xmux]").forEach((el) => {
      $(el.dataset.xmux + "xmux").value = "";
    });
    preset("dual");
    tab("basic");
  }

  form.addEventListener("submit", (event) => event.preventDefault());
  form.addEventListener("input", (event) => {
    const el = event.target;
    touched.add(el.id);
    if (el.dataset.port && el.value.trim())
      document.querySelector('[data-proto="' + el.dataset.port + '"]').checked =
        true;
    action = "";
    render();
  });
  form.addEventListener("change", (event) => {
    const el = event.target;
    if (el.id === "argo" && el.value)
      document.querySelector('[data-proto="' + el.value + '"]').checked = true;
    if (el.dataset.proto && !el.checked && $("argo").value === el.dataset.proto)
      $("argo").value = "";
    if (el.dataset.xmux && el.value !== "custom")
      $(el.dataset.xmux + "xmux").value = core.xmuxPresets[el.value];
    action = "";
    render();
  });
  all("[data-preset]").forEach((button) =>
    button.addEventListener("click", () => preset(button.dataset.preset)),
  );
  all("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => tab(button.dataset.tab));
    button.addEventListener("keydown", (event) => {
      const names = ["basic", "enhance", "advanced"],
        index = names.indexOf(activeTab);
      const next =
        event.key === "ArrowRight"
          ? (index + 1) % 3
          : event.key === "ArrowLeft"
            ? (index + 2) % 3
            : event.key === "Home"
              ? 0
              : event.key === "End"
                ? 2
                : -1;
      if (next !== -1) {
        event.preventDefault();
        tab(names[next], true);
      }
    });
  });
  all("[data-next]").forEach((button) =>
    button.addEventListener("click", () => {
      tab(button.dataset.next, true);
      $("config-form").scrollIntoView({ block: "start", behavior: "smooth" });
    }),
  );
  all("[data-profile]").forEach((button) =>
    button.addEventListener("click", () => {
      profile = button.dataset.profile;
      render();
    }),
  );
  all("[data-focus-port]").forEach((button) =>
    button.addEventListener("click", () =>
      focusField("port-" + button.dataset.focusPort),
    ),
  );
  all("[data-method]").forEach((button) =>
    button.addEventListener("click", () => {
      method = button.dataset.method;
      setPressed(all("[data-method]"), "method", method);
      render();
    }),
  );
  $("token-toggle").addEventListener("click", () => {
    const hidden = $("agk").type === "password";
    $("agk").type = hidden ? "text" : "password";
    $("token-toggle").textContent = hidden ? "隐藏" : "显示";
    $("token-toggle").setAttribute(
      "aria-label",
      hidden ? "隐藏 Token" : "显示 Token",
    );
  });
  $("generate-uuid").addEventListener("click", () => {
    $("uuid").value = crypto.randomUUID();
    action = "";
    render();
    toast("已生成新的 UUID");
  });
  $("copy").addEventListener("click", async () => {
    if (!command) return;
    try {
      await navigator.clipboard.writeText(command);
      toast("已复制完整命令，可粘贴到服务器终端");
    } catch (_) {
      const original = $("output").value;
      $("output").value = command;
      $("output").focus();
      $("output").select();
      const ok = document.execCommand("copy");
      $("output").value = original;
      toast(
        ok ? "已复制完整命令" : "复制受浏览器限制，请使用下载按钮保存完整命令",
      );
    }
  });
  $("download").addEventListener("click", () => {
    if (!command) return;
    const url = URL.createObjectURL(
      new Blob(["#!/usr/bin/env bash\n" + command + "\n"], {
        type: "text/x-shellscript;charset=utf-8",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "argosbx-" + (action || "install") + ".sh";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("已下载命令文件，包含你填写的完整配置");
  });
  all("[data-command]").forEach((button) =>
    button.addEventListener("click", () => {
      action = button.dataset.command;
      render();
      $("preview").scrollIntoView({ block: "start", behavior: "smooth" });
      toast(
        action === "rep"
          ? "已生成重配命令，请保留所有需要的协议"
          : "已切换为 " + action + " 管理命令",
      );
    }),
  );
  $("return-install").addEventListener("click", () => {
    action = "";
    render();
  });
  $("reset").addEventListener("click", () => $("reset-dialog").showModal());
  $("reset-cancel").addEventListener("click", () => $("reset-dialog").close());
  $("reset-confirm").addEventListener("click", () => {
    defaultForm();
    $("reset-dialog").close();
    toast("已恢复双节点默认配置");
  });
  $("import-open").addEventListener("click", () => {
    $("import-error").textContent = "";
    $("import-dialog").showModal();
    $("import-text").focus();
  });
  for (const id of ["import-close", "import-cancel"])
    $(id).addEventListener("click", () => $("import-dialog").close());
  $("import-apply").addEventListener("click", () => {
    const text = $("import-text").value,
      parsed = core.parseAssignments(text);
    const recognized = Object.keys(parsed).filter((key) =>
      core.keys.includes(key),
    );
    if (!recognized.length) {
      $("import-error").textContent =
        "没有找到可识别的配置参数，请粘贴完整的部署命令。";
      return;
    }
    // Do not silently discard parameters that this form cannot represent.
    const unknown = Object.keys(parsed).filter(
      (key) => !core.keys.includes(key),
    );
    if (unknown.length) {
      $("import-error").textContent =
        "暂不支持这些参数，未导入：" + unknown.join("、");
      return;
    }
    const invalidSelect = recognized.find(
      (key) =>
        $(key)?.tagName === "SELECT" &&
        ![...$(key).options].some((o) => o.value === parsed[key]),
    );
    if (invalidSelect) {
      $("import-error").textContent =
        invalidSelect + " 的值不受支持，未修改当前配置。";
      return;
    }
    defaultForm();
    all("[data-proto]").forEach((el) => {
      el.checked = Object.hasOwn(parsed, el.dataset.proto);
    });
    all("[data-var]").forEach((el) => {
      if (Object.hasOwn(parsed, el.id)) el.value = parsed[el.id];
      else if (el.tagName !== "SELECT") el.value = "";
    });
    core.protocols.forEach(([key]) => {
      $("port-" + key).value = parsed[key] || "";
    });
    $("argo").value = parsed.argo || "";
    if ($("argo").value)
      document.querySelector('[data-proto="' + $("argo").value + '"]').checked =
        true;
    $("split-enabled").checked =
      !!parsed.xhttp_download_address ||
      ["port", "servername", "host"].some(
        (field) => parsed["xhttp_download_" + field],
      ) ||
      parsed.xhttp_download_finalmask === "tls-fragment";
    for (const p of ["xhttp_", "reality_"])
      if (parsed[p + "xmux"]) $(p + "xmux-preset").value = "custom";
    method = /\bwget\b/.test(text) ? "wget" : "curl";
    setPressed(all("[data-method]"), "method", method);
    action = /\)\s+rep\s*$/.test(text.trim()) ? "rep" : "";
    recognized.forEach((key) => touched.add($(key) ? key : "port-" + key));
    render();
    $("import-text").value = "";
    $("import-dialog").close();
    tab("basic");
    toast("已导入配置，请核对参数检查结果");
  });
  function theme(value) {
    document.documentElement.dataset.theme = value;
    $("theme-toggle").setAttribute(
      "aria-label",
      value === "dark" ? "切换浅色模式" : "切换深色模式",
    );
    document.querySelector('meta[name="theme-color"]').content =
      value === "dark" ? "#161c18" : "#f5f6f3";
  }
  let savedTheme = "light";
  try {
    savedTheme = localStorage.getItem("argosbx-theme") || "light";
  } catch (_) {
    /* Private browsing may disable storage. */
  }
  theme(savedTheme === "dark" ? "dark" : "light");
  $("theme-toggle").addEventListener("click", () => {
    const value =
      document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    theme(value);
    try {
      localStorage.setItem("argosbx-theme", value);
    } catch (_) {
      /* The page remains usable without persistence. */
    }
  });
  all(".nav-link").forEach((link) =>
    link.addEventListener("click", () => {
      all(".nav-link").forEach((item) =>
        item.classList.toggle("active", item === link),
      );
    }),
  );
  render();
})();
