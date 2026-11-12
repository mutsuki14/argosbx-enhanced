"use strict";
const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const path = require("node:path");
const model = require("../connection-tools.js");
const root = path.resolve(__dirname, "..");
const values = {
  xhpt: "443",
  vxpt: "8080",
  argo: "vxpt",
  agn: "up.example.com",
  xhttp_mode: "packet-up",
  xhttp_alpn: "h3",
  agproto: "http2",
};
const links = Object.fromEntries(
  model
    .routes(values)
    .flatMap((r) => r.links)
    .map((l) => [l.id, l.text]),
);
assert.equal(links["reality-client"], "TCP · H2 · REALITY");
assert.equal(links["client-edge"], "H3 · TLS");
assert.equal(links["edge-tunnel"], "HTTP/2 · TCP");
assert.equal(links["tunnel-origin"], "HTTP");
assert.equal(
  model.routes({ ...values, xhttp_mode: "stream-up", xhttp_alpn: "h2" })[1]
    .links[2].text,
  "HTTPS · H2",
);
assert.equal(
  model.routes({ ...values, xhttp_download_address: "down.example.com" })[2].id,
  "download",
);
assert.equal(model.routes({ ...values, argo: "" }).length, 1);
assert.deepEqual(model.routes({}), []);
assert.equal(
  model.routes({ argo: "vwpt", vwpt: "8080" })[0].links[0].text,
  "WebSocket · TLS",
);
assert.equal(
  model.routes({ ...values, vxpt: "" })[1].links[2].detail,
  "回源端口待确认",
);

for (const mode of ["packet-up", "stream-up", "stream-one"]) {
  // Compare the browser's route to the actual server exporter, using an isolated fixture.
  const server = JSON.parse(
    execFileSync(
      "python3",
      [
        "-c",
        String.raw`
import json,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'lib'))
import xhttp_config as x
with tempfile.TemporaryDirectory() as temp:
    d=Path(temp)
    (d/'sbargoym.log').write_text('up.example.com')
    (d/'xr.json').write_text(json.dumps({'inbounds':[{'tag':'vless-xhttp','port':8080,'streamSettings':{'security':'tls' if sys.argv[1]!='packet-up' else 'none'}}]}))
    print(json.dumps(x.tunnel_ingress(d)))
`,
        mode,
      ],
      { cwd: root, encoding: "utf8" },
    ),
  );
  const guide = model.tunnelGuide(
    { ...values, xhttp_mode: mode },
    server.originRequest.caPool || "",
  );
  assert.deepEqual(guide.ingress, server);
  assert.equal(guide.streaming, mode !== "packet-up");
}
assert.equal(model.tunnelGuide({ ...values, argo: "" }).enabled, false);
for (const domain of [
  "",
  "x.trycloudflare.com",
  "192.0.2.1",
  "https://up.example.com",
  "a..example.com",
  "-a.example.com",
]) {
  assert.equal(
    model.tunnelGuide({ ...values, agn: domain }).ingress,
    null,
    domain,
  );
}
for (const port of ["", "0", "65536", "80;touch", "NaN"])
  assert.equal(model.tunnelGuide({ ...values, vxpt: port }).ingress, null);
for (const ca of ["", "relative.crt", "/tmp/a\nb", "/tmp/a\0b"]) {
  assert.equal(
    model.tunnelGuide({ ...values, xhttp_mode: "stream-one" }, ca).ingress,
    null,
  );
}
assert.equal(
  model.tunnelGuide(
    { ...values, xhttp_mode: "stream-one" },
    "/home/user/agsbx/xhttp-origin.crt",
  ).ingress.originRequest.noTLSVerify,
  false,
);
const ws = model.tunnelGuide({
  argo: "vwpt",
  vwpt: "8081",
  agn: "ws.example.com",
  xhttp_mode: "stream-one",
});
assert.equal(ws.ingress.service, "http://127.0.0.1:8081");
assert.equal(ws.streaming, false);

const base = {
  schema: "argosbx.diagnostics",
  version: 1,
  generated_at: "2026-11-12T08:00:00+00:00",
  scope: "server",
  privacy: "redacted",
  network_requested: false,
  profiles: [
    {
      id: "argo",
      mode: "packet-up",
      alpn: "h3",
      split: false,
      origin_tls: false,
    },
  ],
  checks: [
    { id: "installation", profile: "server", status: "pass", code: "ok" },
    { id: "http3", profile: "argo", status: "manual", code: "client_required" },
  ],
};
assert.deepEqual(model.readReport(JSON.stringify(base)), base);
const invalid = [
  null,
  [],
  {},
  { ...base, version: 2 },
  { ...base, token: "secret" },
  { ...base, generated_at: "<script>alert(1)</script>" },
  { ...base, checks: [] },
  { ...base, checks: base.checks.slice(1) },
  { ...base, checks: [...base.checks, base.checks[0]] },
  { ...base, profiles: [...base.profiles, base.profiles[0]] },
  { ...base, profiles: [{ ...base.profiles[0], ip: "192.0.2.1" }] },
  { ...base, profiles: [{ ...base.profiles[0], mode: "auto" }] },
  ...[
    { id: "arbitrary" },
    { profile: "unknown" },
    { status: "green" },
    { code: "error with secret" },
    { code: "timeout" },
    { log: "secret" },
  ].map((change) => ({ ...base, checks: [{ ...base.checks[0], ...change }] })),
];
for (const report of invalid)
  assert.throws(() => model.readReport(JSON.stringify(report)));
assert.throws(() => model.readReport("bad json"), /JSON/);
assert.throws(() => model.readReport(" ".repeat(262145)), /256 KB/);
assert.match(
  model.guidance({
    id: "public_dns",
    status: "skip",
    code: "network_disabled",
  }),
  /未进行公网/,
);
assert.match(
  model.guidance({ id: "origin", status: "fail", code: "timeout" }),
  /超时/,
);
assert.match(
  model.guidance({
    id: "cloudflare_route",
    status: "manual",
    code: "remote_unverified",
  }),
  /逐项核对/,
);
console.log(
  "Connection models, server route parity and strict diagnostic import checks passed.",
);
