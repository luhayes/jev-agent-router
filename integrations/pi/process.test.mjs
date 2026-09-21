import test from "node:test";
import assert from "node:assert/strict";
import { runCli } from "./process.mjs";

test("real Python CLI returns a clearly synthetic core decision", { skip: !process.env.JEV_TEST_CLI }, async () => {
  const data = await runCli({ state: "test", criteria: { a: "A", b: "B" }, instructions: "Choose" }, undefined,
    { command: process.env.JEV_TEST_CLI, args: ["--test-only-offline"] });
  assert.equal(data.test_only, true);
  assert.equal(data.decision.label, "a");
  assert.equal(data.decision.origin, "jev");
});

test("JSON stdin is not interpreted by a shell", async () => {
  const payload = { state: "$(touch /tmp/SHOULD_NOT_EXIST); secret", criteria: { a: "A" }, instructions: "Select" };
  const value = await runCli(payload, undefined, { command: process.execPath, args: ["-e", "process.stdin.pipe(process.stdout)"], timeoutMs: 2000 });
  assert.deepEqual(value, payload);
});
test("timeout kills a non-cooperative child", async () => {
  await assert.rejects(runCli({}, undefined, { command: process.execPath, args: ["-e", "process.on('SIGTERM',()=>{}); setInterval(()=>{},1000)"], timeoutMs: 100 }), /timed out/);
});
test("abort cancels a running child", async () => {
  const controller = new AbortController();
  const promise = runCli({}, controller.signal, { command: process.execPath, args: ["-e", "setInterval(()=>{},1000)"], timeoutMs: 2000 });
  controller.abort();
  await assert.rejects(promise, /cancelled/);
});
test("pre-aborted signals never spawn", async () => {
  await assert.rejects(runCli({}, AbortSignal.abort(), { command: "/not/a/command" }), /cancelled/);
});
test("stderr and process errors do not echo secrets", async () => {
  await assert.rejects(runCli({}, undefined, { command: process.execPath, args: ["-e", "process.stderr.write('SECRET'); process.exit(1)"] }), error => !error.message.includes("SECRET"));
});
