"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

function fixture() {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), "don-kolfix-install-"));
  const repo = path.join(temp, "repo");
  const home = path.join(temp, "home");
  const script = path.join(repo, "tools", "install-mafia.mjs");
  const source = path.join(repo, "dist", "scripts", "kolfix");
  const destination = path.join(home, ".kolmafia", "scripts", "kolfix");
  fs.mkdirSync(path.dirname(script), { recursive: true });
  fs.mkdirSync(source, { recursive: true });
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.copyFileSync(path.join("tools", "install-mafia.mjs"), script);
  return { temp, repo, home, script, source, destination };
}
function run(fixtureData, ...args) {
  return spawnSync(process.execPath, [fixtureData.script, ...args], {
    cwd: fixtureData.repo,
    env: { ...process.env, HOME: fixtureData.home },
    encoding: "utf8",
  });
}
function scenario(label, action) {
  const f = fixture();
  try {
    action(f);
    console.log("PASS: " + label);
  } finally {
    fs.rmSync(f.temp, { recursive: true, force: true });
  }
}
scenario("correct symlink is accepted without rewrite", (f) => {
  fs.symlinkSync(f.source, f.destination);
  const before = fs.readlinkSync(f.destination);
  const result = run(f);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /already linked/);
  assert.equal(fs.readlinkSync(f.destination), before);
});
scenario("wrong symlink is preserved", (f) => {
  const other = path.join(f.temp, "other");
  fs.mkdirSync(other);
  fs.symlinkSync(other, f.destination);
  const result = run(f);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Refusing to replace/);
  assert.equal(fs.readlinkSync(f.destination), other);
});
scenario("broken symlink is preserved", (f) => {
  const gone = path.join(f.temp, "does-not-exist");
  fs.symlinkSync(gone, f.destination);
  const result = run(f);
  assert.equal(result.status, 1);
  assert.equal(fs.readlinkSync(f.destination), gone);
});
scenario("actual directory is preserved", (f) => {
  fs.mkdirSync(f.destination);
  const result = run(f);
  assert.equal(result.status, 1);
  assert.ok(fs.statSync(f.destination).isDirectory());
});
scenario("check-only on absent entry does not install", (f) => {
  const result = run(f, "--check");
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /No installed kolfix entry/);
  assert.equal(fs.existsSync(f.destination), false);
});
scenario("missing build output refuses install", (f) => {
  fs.rmSync(f.source, { recursive: true });
  const result = run(f);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Missing build output/);
});
console.log("6 safe installer scenarios passed, no real KoLmafia files touched.");
