const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const { quote, parseAssignments, validate } = require("../generator-enhanced");
const values = [
  "",
  "simple",
  '{"maxConcurrency":"16-32"}',
  "a'b",
  "$(echo INJECTED)",
  "`echo INJECTED`",
  'a"b\\c',
];
for (const value of values) {
  const assignment = `arg=${quote(value)}`;
  assert.equal(parseAssignments(assignment).arg, value);
  assert.equal(
    execFileSync("bash", ["-c", assignment + '; printf "%s" "$arg"'], {
      encoding: "utf8",
    }),
    value,
  );
}
const valid = {
  argo: "vxpt",
  vxpt: "8080",
  agn: "up.example.com",
  agk: "eyTest",
  xhttp_alpn: "h2",
};
assert.equal(validate(valid), "");
for (const invalid of [
  { agk: "" },
  { agn: "a.trycloudflare.com" },
  { xhttp_alpn: "h3", xhttp_finalmask: "tls-fragment" },
  { xhttp_xmux: "[]" },
  { xhttp_xmux: '{"maxConcurrency":2,"maxConnections":2}' },
  { xhttp_download_port: "443" },
  { xhttp_mode: "auto" },
  { xhttp_mode: "stream-up", xhttp_alpn: "h3" },
  { xhttp_mode: "stream-one", xhttp_alpn: "h3" },
  { xhttp_mode: "stream-one", xhttp_download_address: "down.example.com" },
]) {
  assert.notEqual(validate({ ...valid, ...invalid }), "");
}
for (const xhttp_mode of ["packet-up", "stream-up", "stream-one"]) {
  assert.equal(validate({ ...valid, xhttp_mode }), "");
  assert.equal(
    parseAssignments(`xhttp_mode=${quote(xhttp_mode)}`).xhttp_mode,
    xhttp_mode,
  );
}
assert.equal(
  validate({
    ...valid,
    xhttp_mode: "stream-up",
    xhttp_download_address: "down.example.com",
  }),
  "",
);
console.log("Generator validation, JSON roundtrip and shell quoting passed.");

// The web presets must produce the same independent profiles as the installer.
const core = require("../generator-enhanced");
const reality = {
  xhpt: "443",
  reality_mode: "stream-one",
  reality_alpn: "h2",
  reym: "www.microsoft.com",
};
assert.equal(validate(reality), "");
assert.notEqual(validate({ ...reality, reality_alpn: "h3" }), "");
assert.notEqual(
  validate({
    ...reality,
    vxpt: "443",
    argo: "vxpt",
    agn: "up.example.com",
    agk: "eyTest",
  }),
  "",
);
assert.notEqual(validate({ ...valid, agn: "127.0.0.1" }), "");
assert.notEqual(validate({ ...valid, agn: "bad..example.com" }), "");
assert.notEqual(validate({ ...valid, vxpt: "65536" }), "");
assert.notEqual(
  validate({ ...valid, xhttp_download_address: "192.0.2.1" }),
  "",
);
assert.equal(
  validate({
    ...valid,
    xhttp_download_address: "192.0.2.1",
    xhttp_download_servername: "down.example.com",
  }),
  "",
);
assert.equal(
  validate({
    ...valid,
    xhttp_xmux: '{"maxConcurrency":"0","maxConnections":4}',
  }),
  "",
);
for (const xhttp_xmux of [
  '{"unknown":1}',
  '{"hKeepAlivePeriod":"2"}',
  '{"maxConcurrency":"32-16"}',
  '{"maxConcurrency":true}',
])
  assert.notEqual(validate({ ...valid, xhttp_xmux }), "");
for (const [field, good, bad] of [
  ["padding_bytes", "0-65536", "0-65537"],
  ["max_post_bytes", "1-16000000", "0"],
  ["min_post_interval_ms", "0-60000", "-1"],
  ["fragment_length", "1-65536", "0"],
  ["fragment_interval", "0-1000", "1001"],
  ["fragment_count", "1-1000", "0"],
]) {
  assert.equal(validate({ ...valid, ["xhttp_" + field]: good }), "");
  assert.notEqual(validate({ ...valid, ["xhttp_" + field]: bad }), "");
}
const combinations = [];
for (const mode of ["packet-up", "stream-up", "stream-one"]) {
  for (const [name, xmux] of Object.entries(core.xmuxPresets)) {
    const env = {
      ...valid,
      ...reality,
      xhttp_mode: mode,
      reality_mode: mode,
      xhttp_xmux: xmux || "{}",
      reality_xmux: xmux || "{}",
      xhttp_finalmask: "tls-fragment",
      reality_finalmask: "tls-fragment",
      xhttp_path: "/test-argo",
      reality_path: "/test-reality",
      xhttp_padding_bytes: "500-1000",
    };
    combinations.push(env);
    assert.equal(validate(env), "", name + "/" + mode);
    for (const method of ["curl", "wget"]) {
      const command = core.buildCommand(env, method);
      assert.deepEqual(parseAssignments(command), env);
      assert.match(command, /mutsuki14\/argosbx-enhanced\/main\/argosbx.sh/);
      assert.ok(command.includes(method));
    }
  }
}
// Validate actual browser output against the Python installer's owning schema.
execFileSync(
  "python3",
  [
    "-c",
    'import json,sys; sys.path.insert(0,"lib"); import xhttp_config as x; cases=json.load(sys.stdin); [(x.options(v,profile="argo"),x.options(v,profile="reality")) for v in cases]',
  ],
  {
    cwd: require("node:path").resolve(__dirname, ".."),
    input: JSON.stringify(combinations),
  },
);
assert.ok(
  !core
    .buildCommand({ not_an_option: "injected", ...reality })
    .includes("not_an_option"),
);
assert.throws(() => core.buildCommand(reality, "curl", ";bad"));
assert.match(core.buildCommand({}, "curl", "doctor"), /\) doctor$/);
console.log(
  "Dual profiles, preset/backend compatibility, port/range/host validation and command builder passed.",
);
