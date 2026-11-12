(function () {
  "use strict";
  const model = window.ArgosbxConnection,
    core = window.ArgosbxEnhanced;
  const $ = (id) => document.getElementById(id);
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const statuses = {
    pass: "通过",
    fail: "需处理",
    skip: "未检测",
    manual: "待验证",
  };
  const owners = { server: "服务器", argo: "固定 Argo", reality: "REALITY" };
  let current = {},
    method = "curl",
    routeSignatures = new Map(),
    editField = "",
    routeJSON = "",
    report = null,
    demo = false,
    filter = "all";

  async function copy(value) {
    try {
      await navigator.clipboard.writeText(value);
    } catch (_) {
      const input = el("textarea");
      input.value = value;
      input.style.cssText = "position:fixed;left:-10000px;top:0";
      document.body.append(input);
      input.select();
      const ok = document.execCommand("copy");
      input.remove();
      if (!ok) {
        $("assistant-feedback").textContent =
          "浏览器未允许复制，请手动选择文本或下载文件。";
        return false;
      }
    }
    $("assistant-feedback").textContent = "已复制。";
    return true;
  }
  function download(name, text) {
    const url = URL.createObjectURL(
      new Blob([text], { type: "application/json;charset=utf-8" }),
    );
    const link = el("a");
    link.href = url;
    link.download = name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function stageText(id, route) {
    if (route === "reality" && id === "client")
      return "REALITY 直连使用 TCP / HTTP/2。客户端需支持 XHTTP 和 VLESS ENC；实际连通性需要导入节点后验证。";
    if (route === "argo" && ["vwpt", "vmpt"].includes(current.argo)) {
      const ws = {
        client:
          "客户端使用 WebSocket + TLS 连接固定域名。隧道连接协议可单独选择 QUIC 或 HTTP/2。",
        edge: "客户端 TLS 在这里终止。固定域名需要正确路由到隧道，再由连接器转发至本机入站。",
        origin:
          "WebSocket 通过本机 HTTP 回源，服务端口必须与对应 Xray 入站一致。",
      };
      if (ws[id]) return ws[id];
    }
    return model.stages[id][1];
  }
  function inspect(id, field, route) {
    const stage = model.stages[id] || model.stages.client;
    $("map-detail-title").textContent = stage[0];
    $("map-detail-text").textContent = stageText(id, route);
    editField =
      field ||
      (id === "client" && route === "argo" && current.argo !== "vxpt"
        ? "argo"
        : stage[2]);
    $("map-inspector").hidden = false;
  }
  let previousRoutes = "",
    previousGuide = "";
  function renderRoutes() {
    const routes = model.routes(current),
      next = new Map(),
      changed = [];
    const signature = JSON.stringify(routes);
    if (signature === previousRoutes) return;
    previousRoutes = signature;
    $("route-canvas").replaceChildren();
    if (!routes.length)
      $("route-canvas").append(
        el(
          "p",
          "field-help",
          "链路图适用于 XHTTP REALITY 和固定 Argo；其他协议请参考项目文档。",
        ),
      );
    routes.forEach((route) => {
      const row = el("div", "route-row");
      row.append(el("div", "route-title", route.title));
      const track = el("div", "route-track");
      route.nodes.forEach((id, index) => {
        const button = el(
          "button",
          "route-node",
          id === "client" ? "客户端" : model.stages[id][0],
        );
        button.type = "button";
        button.dataset.stage = id;
        button.addEventListener("click", () =>
          inspect(
            id,
            route.id === "reality"
              ? "reality_mode"
              : id === "origin"
                ? current.argo
                : undefined,
            route.id,
          ),
        );
        track.append(button);
        if (route.links[index]) {
          const link = route.links[index],
            signature = link.text + "|" + link.detail;
          next.set(link.id, signature);
          const modified =
            routeSignatures.has(link.id) &&
            routeSignatures.get(link.id) !== signature;
          if (modified) changed.push(link.text);
          const connector = el(
            "button",
            "route-link" + (modified ? " changed" : ""),
          );
          connector.type = "button";
          connector.dataset.link = link.id;
          connector.append(
            el("strong", "", link.text),
            el("span", "route-arrow", "→"),
            el("small", "", link.detail),
          );
          connector.setAttribute(
            "aria-label",
            link.text + "，" + link.detail + "，查看对应配置",
          );
          connector.addEventListener("click", () => {
            $("map-detail-title").textContent = link.text + " · " + link.detail;
            const stage =
              link.id === "edge-tunnel"
                ? "tunnel"
                : link.id === "tunnel-origin"
                  ? "origin"
                  : route.id === "download"
                    ? "split"
                    : route.id === "reality"
                      ? "reality"
                      : "client";
            $("map-detail-text").textContent = stageText(stage, route.id);
            editField = link.field;
            $("map-inspector").hidden = false;
          });
          track.append(connector);
        }
      });
      row.append(track);
      $("route-canvas").append(row);
    });
    routeSignatures = next;
    if (changed.length)
      $("map-change").textContent =
        "刚刚更新：" + changed.join("、") + "。仅更新配置示意，尚未检测网络。";
    if (!routes.length || changed.length) $("map-inspector").hidden = true;
  }
  function renderGuide() {
    const guide = model.tunnelGuide(current, $("ca-path").value);
    const signature = JSON.stringify(guide);
    if (signature === previousGuide) return;
    previousGuide = signature;
    $("tunnel-disabled").hidden = guide.enabled;
    $("tunnel-content").hidden = !guide.enabled;
    $("tunnel-experiment").hidden = !guide.streaming;
    $("ca-path-field").hidden = !guide.streaming;
    $("tunnel-rows").replaceChildren();
    for (const row of guide.rows) {
      const item = el("div", "tunnel-row"),
        text = el("div");
      text.append(el("span", "", row.label), el("code", "", row.value));
      item.append(text);
      if (row.copy) {
        const button = el("button", "text-button", "复制");
        button.type = "button";
        button.setAttribute("aria-label", "复制 " + row.label);
        button.addEventListener("click", async () => {
          if (await copy(row.value)) {
            button.textContent = "已复制";
            setTimeout(() => {
              button.textContent = "复制";
            }, 1400);
          }
        });
        item.append(button);
      }
      $("tunnel-rows").append(item);
    }
    $("tunnel-missing").textContent = guide.missing.length
      ? "待完成：" + guide.missing.join("；")
      : "当前单条路由可复制或下载。";
    routeJSON = guide.ingress
      ? JSON.stringify(guide.ingress, null, 2) + "\n"
      : "";
    $("copy-ingress").disabled = $("download-ingress").disabled = !routeJSON;
  }
  function diagnosticCommand() {
    return (
      core.buildCommand({}, method, "doctor") +
      ' --report "$HOME/argosbx-diagnostics.json"' +
      ($("report-network").checked ? " --network" : "")
    );
  }
  function renderReport() {
    $("report-result").hidden = !report;
    if (!report) return;
    const counts = Object.fromEntries(
      Object.keys(statuses).map((status) => [
        status,
        report.checks.filter((c) => c.status === status).length,
      ]),
    );
    $("report-kind").textContent = demo
      ? "示例报告 · 非实际检测"
      : "导入的服务器报告";
    $("report-kind").classList.toggle("demo", demo);
    $("report-heading").textContent = counts.fail
      ? "有 " + counts.fail + " 项需要处理"
      : "已检测项通过，继续验证完整连接";
    $("report-meta").textContent =
      (demo
        ? "示例数据"
        : "生成于 " + new Date(report.generated_at).toLocaleString("zh-CN")) +
      " · " +
      (report.network_requested ? "已请求公网检查" : "未请求公网检查");
    $("report-counts").replaceChildren();
    for (const [status, count] of Object.entries(counts)) {
      const item = el("div", "report-count " + status);
      item.append(el("strong", "", count), el("span", "", statuses[status]));
      $("report-counts").append(item);
    }
    $("report-checks").replaceChildren();
    const visible = report.checks.filter(
      (c) => filter === "all" || c.profile === filter || c.profile === "server",
    );
    visible.forEach((check) => {
      const item = el("article", "report-check " + check.status);
      const title = el("div", "check-title");
      title.append(
        el("span", "check-status", statuses[check.status]),
        el("h4", "", model.checks[check.id][0]),
        el("small", "", owners[check.profile]),
      );
      item.append(title, el("p", "", model.guidance(check)));
      if (check.id === "cloudflare_route") {
        const link = el("a", "text-button", "打开固定隧道助手 ↗");
        link.href = "#tunnel-assistant";
        item.append(link);
      }
      $("report-checks").append(item);
    });
    document
      .querySelectorAll("[data-report-filter]")
      .forEach((button) =>
        button.setAttribute(
          "aria-pressed",
          String(button.dataset.reportFilter === filter),
        ),
      );
  }
  function importReport(text, isDemo = false) {
    try {
      report = model.readReport(text);
      demo = isDemo;
      filter = "all";
      $("report-error").textContent = "";
      renderReport();
    } catch (error) {
      report = null;
      renderReport();
      $("report-error").textContent = error.message;
    }
  }
  async function readFile(file) {
    if (!file) return;
    if (file.size > 262144) {
      report = null;
      renderReport();
      $("report-error").textContent =
        "文件超过 256 KB，请选择脚本导出的诊断 JSON。";
      return;
    }
    try {
      importReport(await file.text());
    } catch (_) {
      report = null;
      renderReport();
      $("report-error").textContent = "无法读取文件，请重新选择。";
    }
  }
  document.addEventListener("argosbx:change", (event) => {
    current = event.detail.values;
    method = event.detail.method;
    renderRoutes();
    renderGuide();
    $("diagnostic-command").textContent = diagnosticCommand();
  });
  $("map-edit").addEventListener("click", () =>
    document.dispatchEvent(
      new CustomEvent("argosbx:focus", { detail: editField }),
    ),
  );
  $("ca-path").addEventListener("input", renderGuide);
  $("copy-ingress").addEventListener("click", async () => {
    if (routeJSON && (await copy(routeJSON)))
      $("tunnel-missing").textContent =
        "已复制单条路由 JSON。请保留隧道中的其他路由。";
  });
  $("download-ingress").addEventListener("click", () => {
    if (routeJSON) download("xhttp-tunnel-route.json", routeJSON);
  });
  $("report-network").addEventListener("change", () => {
    $("diagnostic-command").textContent = diagnosticCommand();
  });
  $("copy-diagnostic").addEventListener("click", async () => {
    if (await copy(diagnosticCommand()))
      $("assistant-feedback").textContent =
        "诊断命令已复制，请在安装节点的服务器终端执行。";
  });
  $("choose-report").addEventListener("click", () => $("report-file").click());
  $("report-file").addEventListener("change", (event) => {
    readFile(event.target.files[0]);
    event.target.value = "";
  });
  for (const type of ["dragover", "dragenter"])
    $("report-drop").addEventListener(type, (event) => {
      event.preventDefault();
      $("report-drop").classList.add("dragging");
    });
  $("report-drop").addEventListener("dragleave", () =>
    $("report-drop").classList.remove("dragging"),
  );
  $("report-drop").addEventListener("drop", (event) => {
    event.preventDefault();
    $("report-drop").classList.remove("dragging");
    if (event.dataTransfer.files.length !== 1) {
      report = null;
      renderReport();
      $("report-error").textContent = "请一次选择一个诊断文件。";
      return;
    }
    readFile(event.dataTransfer.files[0]);
  });
  $("clear-report").addEventListener("click", () => {
    report = null;
    renderReport();
    $("report-error").textContent = "";
  });
  document.querySelectorAll("[data-report-filter]").forEach((button) =>
    button.addEventListener("click", () => {
      filter = button.dataset.reportFilter;
      renderReport();
    }),
  );
  $("demo-report").addEventListener("click", () =>
    importReport(
      JSON.stringify({
        schema: "argosbx.diagnostics",
        version: 1,
        generated_at: "2026-11-12T00:00:00+00:00",
        scope: "server",
        privacy: "redacted",
        network_requested: false,
        profiles: [
          {
            id: "argo",
            mode: "stream-up",
            alpn: "h2",
            split: false,
            origin_tls: true,
          },
        ],
        checks: [
          { id: "installation", profile: "server", status: "pass", code: "ok" },
          {
            id: "server_config",
            profile: "server",
            status: "pass",
            code: "ok",
          },
          {
            id: "origin",
            profile: "argo",
            status: "fail",
            code: "origin_unreachable",
          },
          {
            id: "origin_certificate",
            profile: "argo",
            status: "fail",
            code: "certificate_invalid",
          },
          {
            id: "public_dns",
            profile: "argo",
            status: "skip",
            code: "network_disabled",
          },
          {
            id: "cloudflare_route",
            profile: "argo",
            status: "manual",
            code: "remote_unverified",
          },
          {
            id: "client_connection",
            profile: "argo",
            status: "manual",
            code: "client_required",
          },
        ],
      }),
      true,
    ),
  );
  if (matchMedia("(max-width:580px)").matches) $("connection-map").open = false;
})();
