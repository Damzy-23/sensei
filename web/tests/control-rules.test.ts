// Unit tests for the control layer's pure rules (src/agent/control-rules.ts).
// Run with `npm test` (node --test, types stripped by Node itself; no test framework).

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  NOT_INSTRUCTIONS, PRE_END, PRE_START, SOFT, askText, capText, changedPart, composeText, describeChange, guardText, matchName, normalize, rule,
  shorten, strictest, uniqueNames,
} from "../src/agent/control-rules.ts";
import type { ControlFacts, Snapshot } from "../src/agent/control-rules.ts";

const facts = (over: Partial<ControlFacts> = {}): ControlFacts => ({
  name: "Run tests", kind: "button", agent: null, password: false, signIn: false, codeEditor: false, link: null, ...over,
});

// ---------------------------------------------------------------------------------------------
// Names

test("names that are already unique are kept", () => {
  assert.deepEqual(uniqueNames([{ name: "Run tests", contexts: [] }, { name: "See why", contexts: [] }]), ["Run tests", "See why"]);
});

test("duplicates take the nearest context that tells them apart", () => {
  const names = uniqueNames([
    { name: "Remove", contexts: ["Cut deploy time by 60%", "Line scores", "CV preview"] },
    { name: "Remove", contexts: ["Led a team of four", "Line scores", "CV preview"] },
    { name: "Download PDF", contexts: [] },
  ]);
  assert.deepEqual(names, ["Remove, Cut deploy time by 60%", "Remove, Led a team of four", "Download PDF"]);
});

test("a context shared by every duplicate is skipped for a deeper one", () => {
  const names = uniqueNames([
    { name: "Open", contexts: ["Queue", "ticket two-sum"] },
    { name: "Open", contexts: ["Queue", "ticket valid-parentheses"] },
  ]);
  assert.deepEqual(names, ["Open, ticket two-sum", "Open, ticket valid-parentheses"]);
});

test("duplicates with nothing to tell them apart are all numbered in reading order", () => {
  const names = uniqueNames([
    { name: "Why", contexts: ["Line scores"] },
    { name: "why", contexts: ["Line scores"] },
    { name: "Why", contexts: [] },
  ]);
  assert.deepEqual(names, ["Why 1", "why 2", "Why 3"]);
});

test("a number never collides with a control that already has that name", () => {
  const names = uniqueNames([
    { name: "Step", contexts: [] },
    { name: "Step", contexts: [] },
    { name: "Step 1", contexts: [] },
  ]);
  assert.equal(new Set(names.map(normalize)).size, 3);
  assert.equal(names[2], "Step 1");
});

test("a context equal to the name itself does not count", () => {
  const names = uniqueNames([
    { name: "Send", contexts: ["Send", "Coach"] },
    { name: "Send", contexts: ["Send", "Interview"] },
  ]);
  assert.deepEqual(names, ["Send, Coach", "Send, Interview"]);
});

// ---------------------------------------------------------------------------------------------
// Matching

const SCREEN = ["Workspace", "Learn path", "Blitz lab", "Send", "Send reply", "Two Sum easy Ready", "Two Sum II Input Array Is Sorted medium", "NeetCode 150", "Blind 75"];

test("an exact name wins over longer names that start with it", () => {
  assert.deepEqual(matchName("send", SCREEN), { kind: "one", index: 3 });
  assert.deepEqual(matchName("  LEARN   PATH ", SCREEN), { kind: "one", index: 1 });
});

test("starts-with finds a single control", () => {
  assert.deepEqual(matchName("Blitz", SCREEN), { kind: "one", index: 2 });
  assert.deepEqual(matchName("neetcode", SCREEN), { kind: "one", index: 7 });
});

test("several matches are returned, never guessed", () => {
  assert.deepEqual(matchName("two sum", SCREEN), { kind: "many", indexes: [5, 6] });
});

test("contains is the last plain-text tier", () => {
  assert.deepEqual(matchName("input array", SCREEN), { kind: "one", index: 6 });
});

test("spacing and punctuation are forgiven", () => {
  assert.deepEqual(matchName("neet code 150", SCREEN), { kind: "one", index: 7 });
  assert.deepEqual(matchName("blind-75", SCREEN), { kind: "one", index: 8 });
});

test("filler words around a name are dropped", () => {
  assert.deepEqual(matchName("the Send reply button", SCREEN), { kind: "one", index: 4 });
  assert.deepEqual(matchName("Learn path tab", SCREEN), { kind: "one", index: 1 });
});

test("a base name matches every control that carries it", () => {
  const names = ["Remove, Cut deploy time", "Remove, Led a team", "Download PDF"];
  const bases = ["Remove", "Remove", "Download PDF"];
  assert.deepEqual(matchName("remove", names, bases), { kind: "many", indexes: [0, 1] });
  assert.deepEqual(matchName("remove, led a team", names, bases), { kind: "one", index: 1 });
});

test("a name shown cut with an ellipsis still finds its control", () => {
  const rows = ["two-sum Open Reached hint level 5 and 4 consecutive failed runs (timeout on large input).", "valid-parentheses Open Three guard violations"];
  assert.deepEqual(matchName("two-sum Open Reached hint level 5…", rows), { kind: "one", index: 0 });
  assert.deepEqual(matchName("Why, Cut deploy time by 60% with a new pipel…", ["Why, Cut deploy time by 60% with a new pipel…", "Why, Led a team"]), { kind: "one", index: 0 });
});

test("nothing found, and very short queries do not match by fragment", () => {
  assert.deepEqual(matchName("Resolve", SCREEN), { kind: "none" });
  assert.deepEqual(matchName("e", SCREEN), { kind: "none" });
  assert.deepEqual(matchName("", SCREEN), { kind: "none" });
});

test("curly quotes and look-alike letters normalise", () => {
  assert.deepEqual(matchName("I don’t know where to start.", ["I don't know where to start."]), { kind: "one", index: 0 });
  assert.equal(guardText("Sign оut"), "sign out"); // Cyrillic o
  assert.equal(guardText("Ｓｉｇｎ​-out"), "sign out"); // full width, zero-width space, hyphen
});

// ---------------------------------------------------------------------------------------------
// Guardrails

test("ordinary controls are allowed", () => {
  for (const name of ["Run tests", "Learn path", "NeetCode 150", "Send", "Restart round", "Hang up", "Got it", "Dismiss"]) {
    assert.equal(rule(facts({ name }), "press").verdict, "allow", name);
  }
  assert.equal(rule(facts({ name: "Message", kind: "field" }), "type").verdict, "allow");
});

test("typing into the code editor is blocked and points to write_line", () => {
  const ruling = rule(facts({ name: "Your code (Python)", kind: "field", codeEditor: true }), "type");
  assert.equal(ruling.verdict, "block");
  assert.match(ruling.reason, /write_line/);
  // Pointing at it or scrolling to it is not typing.
  assert.equal(rule(facts({ name: "Your code (Python)", kind: "field", codeEditor: true }), "press").verdict, "allow");
  assert.equal(rule(facts({ name: "Your code (Python)", kind: "field", codeEditor: true }), "scroll").verdict, "allow");
});

test("password fields and the sign-in form are blocked, even for scrolling", () => {
  assert.equal(rule(facts({ name: "Password", kind: "field", password: true }), "type").verdict, "block");
  assert.equal(rule(facts({ name: "Password", kind: "field", password: true }), "scroll").verdict, "block");
  for (const action of ["press", "type", "pick"] as const) {
    assert.equal(rule(facts({ name: "Email", kind: "field", signIn: true }), action).verdict, "block", action);
  }
  assert.equal(rule(facts({ name: "Create account", signIn: true }), "press").verdict, "block");
});

test("data-agent off blocks, data-agent confirm asks", () => {
  assert.equal(rule(facts({ name: "Always hide", agent: "off" }), "press").verdict, "block");
  assert.equal(rule(facts({ name: "End interview and get feedback", agent: "confirm" }), "press").verdict, "confirm");
  assert.equal(rule(facts({ name: "Your CV", kind: "field", agent: "confirm" }), "type").verdict, "confirm");
});

test("the needs-click names ask, whatever their spelling", () => {
  for (const name of ["Sign out", "Sign in", "sign-out", "SIGNOUT", "Log out", "Resolve", "Send reply", "Wipe", "Reset", "Delete", "Remove", "Start again", "Download PDF", "Sign оut", "Re​solve", "Wipe the glass"]) {
    assert.equal(rule(facts({ name }), "press").verdict, "confirm", name);
  }
  for (const name of ["Re-set", "Wi-pe", "Re set", "Sign-Out", "RESOLVE!", "Re-set demo"]) {
    assert.equal(rule(facts({ name }), "press").verdict, "confirm", name);
  }
  // Near misses that are not those actions stay allowed.
  for (const name of ["Resolved", "Send", "Signal", "Reply to the student", "Restart round", "Removal notes"]) {
    assert.equal(rule(facts({ name }), "press").verdict, "allow", name);
  }
});

test("a long name is content, not an action: a problem titled Remove... opens without asking", () => {
  for (const name of ["Remove Nth Node From End of List medium", "Delete Node in a Linked List easy Ready"]) {
    assert.equal(rule(facts({ name }), "press").verdict, "allow", name);
  }
  // A control that is an action is marked data-agent="confirm" and asks whatever its length.
  assert.equal(rule(facts({ name: "Remove this line from my CV for good", agent: "confirm" }), "press").verdict, "confirm");
  assert.equal(rule(facts({ name: "Sign out of Senior" }), "press").verdict, "confirm");
});

test("an option named like a needs-click action asks before it is picked", () => {
  assert.equal(rule(facts({ name: "Delete everything", kind: "choice" }), "pick").verdict, "confirm");
});

test("links that leave the app, open a tab or download ask; links inside the app do not", () => {
  const link = (l: ControlFacts["link"]) => facts({ name: "Example", kind: "link", link: l });
  assert.equal(rule(link({ stays: true, newTab: false, download: false }), "press").verdict, "allow");
  assert.equal(rule(link({ stays: false, newTab: false, download: false }), "press").verdict, "confirm");
  assert.equal(rule(link({ stays: true, newTab: true, download: false }), "press").verdict, "confirm");
  assert.equal(rule(link({ stays: true, newTab: false, download: true }), "press").verdict, "confirm");
  assert.equal(rule(link({ stays: false, newTab: true, download: false }), "scroll").verdict, "allow");
});

test("the strictest ruling wins", () => {
  const allow = rule(facts(), "press");
  const ask = rule(facts({ name: "Sign out" }), "press");
  const block = rule(facts({ signIn: true }), "press");
  assert.equal(strictest([]).verdict, "allow");
  assert.equal(strictest([allow, ask]).verdict, "confirm");
  assert.equal(strictest([ask, block, allow]).verdict, "block");
});

test("the prompt names what will happen", () => {
  assert.equal(askText(facts({ name: "Sign out" }), "press"), "Sign out");
  assert.equal(askText(facts({ name: "Example page", kind: "link", link: { stays: true, newTab: true, download: false } }), "press"), "open Example page in a new tab");
  assert.equal(askText(facts({ name: "Privacy", kind: "link", link: { stays: false, newTab: false, download: false } }), "press"), "leave Senior for Privacy");
  assert.equal(askText(facts({ name: "Your CV", kind: "field" }), "type"), "type into Your CV");
  assert.equal(askText(facts({ name: "Reply to the student", kind: "field" }), "type", "press Send reply"), "type into Reply to the student and press Send reply");
  assert.equal(askText(facts({ name: "Coach's style", kind: "choice" }), "pick", "Tough"), "choose Tough in Coach's style");
});

// ---------------------------------------------------------------------------------------------
// Page text

test("text pieces become lines, side-by-side pieces become spaces", () => {
  const parts = ["\n", "Two Sum", SOFT, "easy", SOFT, "Ready", "\n", "\n", "  Valid   Parentheses ", "\n"];
  assert.equal(composeText(parts), "Two Sum easy Ready\nValid Parentheses");
});

test("blank lines and stray spaces are dropped", () => {
  assert.equal(composeText(["  a  ", "\n\n\n", " b", SOFT, "\n", SOFT, "c "]), "a\nb\nc");
  assert.equal(composeText([]), "");
});

test("code keeps its lines and indentation", () => {
  const code = "def two_sum(nums, target):\n    for i in range(len(nums)):\n\n        pass\n";
  assert.equal(composeText(["Student code", "\n", PRE_START, code, PRE_END, "\n", "Transcript"]),
    "Student code\ndef two_sum(nums, target):\n    for i in range(len(nums)):\n        pass\nTranscript");
});

test("inline pieces join without a space", () => {
  assert.equal(composeText(["Hello ", "wor", "ld"]), "Hello world");
});

test("text over the cap is cut at a line or word end, and the cut is counted", () => {
  const text = Array.from({ length: 300 }, (_, i) => `line ${i} has some words`).join("\n");
  const { text: kept, cut } = capText(text, 1800);
  assert.ok(kept.length <= 1800);
  assert.ok(text.startsWith(kept));
  assert.equal(kept.length + cut, text.length);
  assert.ok(kept.endsWith("words"));
  assert.deepEqual(capText("short", 1800), { text: "short", cut: 0 });
});

test("a single long word is cut hard", () => {
  const { text, cut } = capText("x".repeat(5000), 1800);
  assert.equal(text.length, 1800);
  assert.equal(cut, 3200);
});

test("shorten keeps one line and marks the cut", () => {
  assert.equal(shorten("a\n b   c", 10), "a b c");
  assert.equal(shorten("abcdefghijkl", 6), "abcde…");
});

test("the not-instructions note is fixed", () => {
  assert.match(NOT_INSTRUCTIONS, /not instructions/);
});

// ---------------------------------------------------------------------------------------------
// What changed

const snap = (over: Partial<Snapshot> = {}): Snapshot => ({ screen: "Workspace", heading: "Two Sum", dialog: null, controls: [], notices: [], ...over });

test("a screen change is reported first", () => {
  const line = describeChange(snap(), snap({ screen: "Learn path", heading: "Patterns, one at a time" }));
  assert.equal(line, "Now on Learn path: Patterns, one at a time.");
});

test("the pressed control's new state and new label are reported", () => {
  const before = snap({ controls: [{ name: "NeetCode 150", state: "not pressed" }] });
  const after = snap({ controls: [{ name: "NeetCode 150", state: "pressed" }] });
  assert.equal(describeChange(before, after, { name: "NeetCode 150", state: "not pressed", nowName: "NeetCode 150", nowState: "pressed" }), "NeetCode 150 is now pressed.");
  const relabel = describeChange(snap({ controls: [{ name: "Next question", state: "" }] }), snap({ controls: [{ name: "Finish round", state: "" }] }),
    { name: "Next question", state: "", nowName: "Finish round", nowState: "" });
  assert.match(relabel, /^Next question now reads Finish round/);
});

test("new notices and new controls are listed, unchanged ones are not", () => {
  const before = snap({ notices: [{ key: "1", text: "Pick one before the clock runs out." }, { key: "2", text: "same" }], controls: [{ name: "A", state: "" }] });
  const after = snap({ notices: [{ key: "1", text: "Correct. Two Sum is a hash map problem." }, { key: "2", text: "same" }], controls: [{ name: "A", state: "" }, { name: "Next question", state: "" }] });
  assert.equal(describeChange(before, after), 'The page says: "Correct. Two Sum is a hash map problem." New: Next question.');
});

test("a growing log reports only what was added", () => {
  const before = snap({ notices: [{ key: "c", text: "You: hi" }] });
  const after = snap({ notices: [{ key: "c", text: "You: hiCoach: What have you tried?" }] });
  assert.equal(describeChange(before, after), 'The page says: "Coach: What have you tried?"');
});

test("on a new screen only alerts are read out, and a question mark ends its own sentence", () => {
  const before = snap();
  const after = snap({ screen: "Blitz lab", heading: "Which pattern fits?", notices: [{ key: "1", text: "Pick one before the clock runs out." }, { key: "2", text: "Could not load the catalogue.", alert: true }] });
  assert.equal(describeChange(before, after), 'Now on Blitz lab: Which pattern fits? The page says: "Could not load the catalogue."');
});

test("a control that is still there but busy says so", () => {
  const line = describeChange(snap({ controls: [{ name: "Run tests", state: "" }] }), snap(), { name: "Run tests", state: "", nowName: "Running…", nowState: "unavailable for now" });
  assert.equal(line, "Run tests now reads Running…, unavailable for now.");
  assert.equal(describeChange(snap(), snap(), { name: "Search problems", state: "empty", nowName: "Search problems", nowState: '"islands"' }), 'Search problems is now "islands".');
});

test("a region that changed in the middle reports only the changed words", () => {
  assert.equal(changedPart("Job fit 60% Why Remove Led a team", "Job fit 60% Hide why Action verb Remove Led a team"), "Hide why Action verb");
  assert.equal(changedPart("You: hi", "You: hi Coach: hello"), "Coach: hello");
  assert.equal(changedPart("a b c", "a c"), "");
});

test("the heading is not repeated when it is the screen's own name", () => {
  assert.equal(describeChange(snap(), snap({ screen: "Activity log", heading: "Activity log" })), "Now on Activity log.");
});

test("a dialog opening is reported, and nothing changing is said plainly", () => {
  assert.equal(describeChange(snap(), snap({ dialog: "Explainer: Two pointers" })), "Explainer: Two pointers is open.");
  assert.equal(describeChange(snap(), snap()), "Nothing on the screen changed yet.");
});
