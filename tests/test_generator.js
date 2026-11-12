const assert = require('node:assert/strict');
const {execFileSync} = require('node:child_process');
const {quote, parseAssignments, validate} = require('../generator-enhanced');
const values = ["", "simple", '{"maxConcurrency":"16-32"}', "a'b", '$(echo INJECTED)', '`echo INJECTED`', 'a"b\\c'];
for (const value of values) {
  const assignment = `arg=${quote(value)}`;
  assert.equal(parseAssignments(assignment).arg, value);
  assert.equal(execFileSync('bash', ['-c', assignment + '; printf "%s" "$arg"'], {encoding:'utf8'}), value);
}
const valid = {argo:'vxpt', vxpt:'8080', agn:'up.example.com', agk:'eyTest', xhttp_alpn:'h2'};
assert.equal(validate(valid), '');
for (const invalid of [{agk:''}, {agn:'a.trycloudflare.com'}, {xhttp_alpn:'h3', xhttp_finalmask:'tls-fragment'},
  {xhttp_xmux:'[]'}, {xhttp_xmux:'{"maxConcurrency":2,"maxConnections":2}'}, {xhttp_download_port:'443'}]) {
  assert.notEqual(validate({...valid, ...invalid}), '');
}
console.log('Generator validation, JSON roundtrip and shell quoting passed.');
