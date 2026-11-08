import { test } from "node:test";
import assert from "node:assert/strict";
import { startPolling } from "../src/polling.js";

const wait = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

test("a stopped device ignores late responses even when the transport cannot abort", async () => {
  let finish;
  let signal;
  const results = [];
  const stop = startPolling({
    load: (requestSignal) => { signal = requestSignal; return new Promise((resolve) => { finish = resolve; }); },
    onResult: (result) => results.push(result), onError: assert.fail, interval: 1,
  });
  stop();
  finish("old-device");
  await wait(10);
  assert.equal(signal.aborted, true);
  assert.deepEqual(results, []);
});

test("polling never overlaps requests and pauses subsequent batches", async () => {
  let calls = 0;
  let finish;
  let paused = false;
  const stop = startPolling({
    load: () => { calls += 1; return new Promise((resolve) => { finish = resolve; }); },
    onResult: () => {}, onError: assert.fail, interval: 5, canPoll: () => !paused,
  });
  try {
    await wait(20);
    assert.equal(calls, 1);
    paused = true;
    finish("complete");
    await wait(20);
    assert.equal(calls, 1);
    paused = false;
    await wait(20);
    assert.equal(calls, 2);
  } finally { stop(); }
});
