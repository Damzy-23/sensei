// The proctor's rules, checked with made-up readings and a made-up clock. Run: npm test

import assert from "node:assert/strict";
import { test } from "node:test";
import { loadTs } from "./load-ts.mjs";

const { start, step, PROMPTS, LIMIT_MS, GRACE_MS, COOLDOWN_MS, PROMPT_GAP_MS, CLEAR_MS, STALL_MS } =
  await loadTs(new URL("./rules.ts", import.meta.url));

const FINE = { facing: true, hands: 2 };
const AWAY = { facing: false, hands: 2 };
const NO_HANDS = { facing: true, hands: 0 };
const ONE_HAND = { facing: true, hands: 1 };
const GONE = { facing: false, hands: 0 };
const TICK = 100;

/** Feed `reading` every 100 ms from `from` up to and including `to`. Returns the state and every reminder with its time. */
function run(state, reading, from, to) {
  const reminders = [];
  for (let now = from; now <= to; now += TICK) {
    const result = step(state, typeof reading === "function" ? reading(now) : reading, now);
    state = result.state;
    if (result.reminder) reminders.push({ at: now, ...result.reminder });
  }
  return { state, reminders };
}

/** Ten quiet seconds with everything in view, so the tests below start after the grace period. */
const settled = () => run(start(0), FINE, 0, 9900).state;

test("the limits are the ones the candidate is told about", () => {
  assert.equal(LIMIT_MS.eyes_off_screen, 3000);
  assert.equal(LIMIT_MS.hands_not_visible, 5000);
  assert.equal(GRACE_MS, 3000);
  assert.equal(COOLDOWN_MS, 20_000);
  assert.equal(PROMPTS.eyes_off_screen, "Eyes on the screen, please.");
  assert.equal(PROMPTS.hands_not_visible, "Let me see both hands, please.");
});

test("a candidate who is facing the screen with both hands in view is never reminded", () => {
  assert.deepEqual(run(start(0), FINE, 0, 120_000).reminders, []);
});

test("looking away for more than 3 s brings the eyes reminder, once", () => {
  const { reminders } = run(settled(), AWAY, 10_000, 14_000);
  assert.deepEqual(reminders, [{ at: 13_100, rule: "eyes_off_screen", text: "Eyes on the screen, please.", seconds: 3.1 }]);
});

test("exactly 3 s is not more than 3 s", () => {
  assert.deepEqual(run(settled(), AWAY, 10_000, 13_000).reminders, []);
});

test("fewer than two hands for more than 5 s brings the hands reminder", () => {
  for (const reading of [NO_HANDS, ONE_HAND]) {
    const early = run(settled(), reading, 10_000, 15_000);
    assert.deepEqual(early.reminders, [], "nothing at exactly 5 s");
    const { reminders } = run(early.state, reading, 15_100, 16_000);
    assert.deepEqual(reminders, [{ at: 15_100, rule: "hands_not_visible", text: "Let me see both hands, please.", seconds: 5.1 }]);
  }
});

test("nothing is said in the first 3 s after turning on", () => {
  assert.deepEqual(run(start(0), GONE, 0, GRACE_MS - TICK).reminders, []);
  // Away from the very first reading: the reminder comes just after the limit.
  const first = run(start(0), GONE, 0, 4000).reminders[0];
  assert.deepEqual([first.rule, first.at], ["eyes_off_screen", 3100]);
});

test("the grace period holds back a reminder that is already due", () => {
  // Turned on at t = 0, but the first reading only arrives at 2.5 s, already away. A reading
  // from before the proctor started cannot exist, so build the case directly: away since 0.
  const state = { ...start(0), startedAt: 4000, lastAt: 3900, watch: { ...start(0).watch, eyes_off_screen: { since: 0, fineSince: null, remindedAt: null } } };
  const during = run(state, AWAY, 4000, 4000 + GRACE_MS - TICK);
  assert.deepEqual(during.reminders, [], "due on the limit alone, but still settling");
  const after = run(during.state, AWAY, 4000 + GRACE_MS, 4000 + GRACE_MS);
  assert.equal(after.reminders.length, 1);
});

test("the same reminder is not repeated for 20 s", () => {
  const { reminders } = run(settled(), AWAY, 10_000, 60_000);
  assert.deepEqual(reminders.map((r) => [r.rule, r.at, r.seconds]), [
    ["eyes_off_screen", 13_100, 3.1], ["eyes_off_screen", 33_100, 23.1], ["eyes_off_screen", 53_100, 43.1],
  ]);
});

test("the cooldown outlives a glance back at the screen", () => {
  const first = run(settled(), AWAY, 10_000, 13_100); // reminded at 13.1 s
  assert.equal(first.reminders.length, 1);
  const back = run(first.state, FINE, 13_200, 15_000); // looks back
  const again = run(back.state, AWAY, 15_100, 33_000); // away again from 15.1 s, and stays away
  assert.deepEqual(again.reminders, [], "still inside 20 s of the first reminder");
  const later = run(again.state, AWAY, 33_100, 34_000);
  assert.deepEqual(later.reminders.map((r) => [r.at, r.seconds]), [[33_100, 18]], "counted from the second time they looked away");
});

test("the timer starts again when the condition clears", () => {
  const away = run(settled(), AWAY, 10_000, 12_500); // 2.5 s away: not yet due
  const back = run(away.state, FINE, 12_600, 12_600 + CLEAR_MS); // back for long enough to count
  const second = run(back.state, AWAY, 13_300, 16_300); // exactly 3 s away again
  assert.deepEqual([...away.reminders, ...back.reminders, ...second.reminders], []);
  const due = run(second.state, AWAY, 16_400, 16_400);
  assert.deepEqual(due.reminders.map((r) => r.seconds), [3.1]);
});

test("a candidate who has just looked back is not reminded", () => {
  // Away for 2.9 s, back at 12.9 s. At 13.1 s the old timer has not been cleared yet (it waits
  // CLEAR_MS to be sure they are back), so the limit alone would call this due.
  const away = run(settled(), AWAY, 10_000, 12_800).state;
  assert.deepEqual(run(away, FINE, 12_900, 20_000).reminders, []);
});

test("one good frame in the middle of looking away does not restart the timer", () => {
  const flicker = (now) => (now === 11_500 ? FINE : AWAY);
  const { reminders } = run(settled(), flicker, 10_000, 14_000);
  assert.deepEqual(reminders.map((r) => r.at), [13_100]);
});

test("two reminders never arrive together", () => {
  // Neither a face nor hands from the start: both rules become due.
  const { reminders } = run(start(0), GONE, 0, 60_000);
  for (let i = 1; i < reminders.length; i += 1) {
    assert.ok(reminders[i].at - reminders[i - 1].at >= PROMPT_GAP_MS, `${reminders[i - 1].at} then ${reminders[i].at}`);
  }
  // Eyes first; hands wait until the banner is free; each keeps its own 20 s cooldown.
  assert.deepEqual(reminders.slice(0, 4).map((r) => [r.rule, r.at]), [
    ["eyes_off_screen", 3100], ["hands_not_visible", 9100], ["eyes_off_screen", 23_100], ["hands_not_visible", 29_100],
  ]);
});

test("when both are due at the same moment, eyes go first", () => {
  // Hands gone at 10 s, face gone at 12 s: at 15.1 s both have been over their limits since the same reading.
  const handsGone = run(settled(), NO_HANDS, 10_000, 11_900).state;
  const { reminders } = run(handsGone, GONE, 12_000, 22_000);
  assert.deepEqual(reminders.map((r) => [r.rule, r.at]), [["eyes_off_screen", 15_100], ["hands_not_visible", 21_100]]);
});

test("time the proctor could not see does not count", () => {
  // Away for 2 s, then the tab is hidden for a minute (no readings), then readings resume.
  const away = run(settled(), AWAY, 10_000, 12_000).state;
  const resumeAt = 72_000;
  assert.ok(resumeAt - 12_000 > STALL_MS);
  const resumed = run(away, AWAY, resumeAt, resumeAt + 3000);
  assert.deepEqual(resumed.reminders, [], "not reminded for a minute it was not watching");
  const due = run(resumed.state, AWAY, resumeAt + 3100, resumeAt + 3100);
  assert.deepEqual(due.reminders.map((r) => r.seconds), [3.1]);
});

test("a pause does not shorten the cooldown", () => {
  const first = run(settled(), AWAY, 10_000, 13_100); // reminded at 13.1 s
  assert.equal(first.reminders.length, 1);
  // The tab is hidden for 5 s. Back at 18.1 s, and still looking away.
  const back = run(first.state, AWAY, 18_100, 33_000);
  assert.deepEqual(back.reminders, [], "still inside 20 s of the reminder at 13.1 s");
  const due = run(back.state, AWAY, 33_100, 33_200);
  assert.deepEqual(due.reminders.map((r) => [r.at, r.seconds]), [[33_100, 15]], "counted from coming back, not from before the pause");
});

test("a pause does not let two reminders run together", () => {
  // Eyes reminder at 3.1 s with no hands in view either; the tab is hidden at once and shown again 2.1 s later.
  const first = run(start(0), GONE, 0, 3100);
  assert.deepEqual(first.reminders.map((r) => r.rule), ["eyes_off_screen"]);
  const { reminders } = run(first.state, GONE, 5200, 30_000);
  assert.ok(reminders.length > 0);
  assert.ok(reminders[0].at - 3100 >= PROMPT_GAP_MS, `next reminder at ${reminders[0].at}`);
});

test("a short pause between readings is not a restart", () => {
  const away = run(settled(), AWAY, 10_000, 11_000).state;
  const { reminders } = run(away, AWAY, 11_000 + STALL_MS, 11_000 + STALL_MS + 200); // a 2 s hiccup, then on
  assert.deepEqual(reminders.map((r) => [r.at, r.seconds]), [[13_100, 3.1]], "still counted from when they first looked away");
});

test("step does not change the state it is given", () => {
  const state = start(0);
  const frozen = JSON.stringify(state);
  step(state, GONE, 5000);
  assert.equal(JSON.stringify(state), frozen);
});
