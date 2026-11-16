// The control layer: Senior operates the screen the way a person does. It sees the visible,
// enabled controls by their accessible names, presses, types and picks, and reads the text on
// screen. Every action passes the guard in control-rules.ts first: some are blocked outright,
// some wait for the student's click on an on-screen prompt (AgentControls.tsx).
//
// This is the one part of the agent that touches the DOM. It reaches only what a person could
// reach: hidden screens, disabled controls and anything marked data-agent="off" do not exist here.

import {
  NOT_INSTRUCTIONS, PRE_END, PRE_START, SOFT, askText, capText, composeText, describeChange, matchName, normalize, rule,
  shorten, strictest, uniqueNames,
  type Action, type ControlFacts, type ControlKind, type Ruling, type Snapshot,
} from "./control-rules";

export interface ControlView { name: string; kind: ControlKind; state: string; guard?: "asks the student first" | "blocked" }
export interface ScreenView { screen: string; heading: string; controls: ControlView[]; more: number; waiting_for?: string }
export interface PressResult { pressed: boolean; now?: string; reason?: string; candidates?: string[] }
export interface TypeResult { typed: boolean; submitted: boolean; now?: string; reason?: string; candidates?: string[] }
export interface PickResult { picked: string | null; now?: string; reason?: string; candidates?: string[] }
export interface ReadResult { screen: string; part: string; text: string; cut?: string; note: string }

const SHOWN_CONTROLS = 60;
const SHOWN_NAME = 90;
const READ_CHARS = 1800;
const MAX_TYPED = 4000;

/** How the student answers a prompt. AgentControls.tsx supplies the prompt itself. */
export type Answer = "allow" | "deny" | "timeout";
type Asker = (what: string) => Promise<Answer>;
let asker: Asker | null = null;
let waitingFor: string | null = null;

/** Called once by AgentControls: how to put a question to the student. */
export function setAsker(next: Asker | null): void { asker = next; }

// ---------------------------------------------------------------------------------------------
// Seeing

const CONTROL = [
  "button", "a[href]", "input:not([type=hidden])", "textarea", "select", "summary",
  "[role=button]", "[role=link]", "[role=tab]", "[role=checkbox]", "[role=switch]", "[role=radio]",
  "[role=menuitem]", "[role=option]", "[role=textbox]", "[role=searchbox]", "[role=combobox]",
  "[contenteditable='']", "[contenteditable=true]",
].join(",");
const TEXT_INPUTS = new Set(["text", "search", "email", "url", "tel", "number", "password", "date", "time", "datetime-local", "month", "week", ""]);
const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "TEMPLATE", "NOSCRIPT", "HEAD"]);

/** A subtree a person cannot see or use: removed from view, hidden from assistive tech, inert, or off-limits to Senior. */
function hiddenSubtree(el: Element): boolean {
  if (SKIP_TAGS.has(el.tagName)) return true;
  if (el.getAttribute("data-agent") === "off") return true;
  if (el.getAttribute("aria-hidden") === "true" || el.hasAttribute("inert") || el.hasAttribute("hidden")) return true;
  return getComputedStyle(el).display === "none";
}

/** Visible elements under `root`, in document (reading) order, never entering a hidden subtree. */
function visibleElements(root: Element): Element[] {
  const out: Element[] = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, {
    acceptNode: (node) => (hiddenSubtree(node as Element) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  for (let node = walker.nextNode(); node; node = walker.nextNode()) out.push(node as Element);
  return out;
}

function shown(el: Element): boolean {
  const box = el.getBoundingClientRect();
  if (box.width <= 0 || box.height <= 0) return false;
  const check = (el as HTMLElement & { checkVisibility?: (o: object) => boolean }).checkVisibility;
  // Not opacity: drawings and notes fade in from nothing, and they are there to be used.
  if (check) return check.call(el, { visibilityProperty: true });
  return getComputedStyle(el).visibility !== "hidden";
}

function enabled(el: Element): boolean {
  if (el.matches(":disabled")) return false;
  return !el.closest("[aria-disabled='true']");
}

/** No part of it hidden, from the root of the page down. */
function reachable(el: Element): boolean {
  for (let node: Element | null = el; node; node = node.parentElement) if (hiddenSubtree(node)) return false;
  return shown(el) && enabled(el);
}

/** An open modal dialog takes the whole screen: a person can only use what is in it. */
function modal(): HTMLElement | null {
  const open = [...document.querySelectorAll<HTMLElement>("[aria-modal='true']")].filter(shownDialog);
  return open[open.length - 1] ?? null;
}
/** Shown, with no hidden container above it. Enabled or not. */
function shownDialog(d: Element): boolean {
  for (let node: Element | null = d; node; node = node.parentElement) if (hiddenSubtree(node)) return false;
  return shown(d);
}

function mainContent(): HTMLElement | null {
  return [...document.querySelectorAll<HTMLElement>("main")].find(shownDialog) ?? null;
}

const clean = (text: string | null | undefined): string => (text ?? "").replace(/\s+/g, " ").trim();

/** Text of an element for a name: aria-labels and alt text count, hidden parts do not. `skip` leaves out one element (the control inside its own label). */
function nameText(node: Node, skip?: Element, root = true): string {
  if (node.nodeType === Node.TEXT_NODE) return (node as Text).data;
  if (!(node instanceof Element) || node === skip) return "";
  if (node.getAttribute("aria-hidden") === "true" || SKIP_TAGS.has(node.tagName)) return "";
  const display = getComputedStyle(node).display;
  if (display === "none") return "";
  const label = node.getAttribute("aria-label");
  if (label && !root) return ` ${label} `;
  if (node instanceof HTMLImageElement) return ` ${node.alt} `;
  if (node instanceof HTMLSelectElement || node instanceof HTMLTextAreaElement || node instanceof HTMLInputElement) return "";
  let text = "";
  node.childNodes.forEach((child) => { text += nameText(child, skip, false); });
  // Inline text runs on; a pill (inline-block) or a block is a separate word.
  return display === "inline" || display === "contents" ? text : ` ${text} `;
}

const isTextBox = (el: Element): el is HTMLInputElement | HTMLTextAreaElement =>
  el instanceof HTMLTextAreaElement || (el instanceof HTMLInputElement && TEXT_INPUTS.has(el.type));

/** The accessible name, the way assistive tech would read it: labelled-by, aria-label, its label, its own text, then title or placeholder. */
export function accessibleName(el: Element): string {
  const by = el.getAttribute("aria-labelledby");
  if (by) {
    const text = clean(by.split(/\s+/).map((id) => document.getElementById(id)).map((ref) => (ref ? nameText(ref) : "")).join(" "));
    if (text) return text;
  }
  const label = clean(el.getAttribute("aria-label"));
  if (label) return label;
  const labels = (el as HTMLInputElement).labels;
  if (labels && labels.length) {
    const text = clean([...labels].map((l) => nameText(l, el)).join(" "));
    if (text) return text;
  }
  if (el instanceof HTMLInputElement && ["button", "submit", "reset"].includes(el.type)) return clean(el.value) || el.type;
  if (!(el instanceof HTMLSelectElement) && !isTextBox(el)) {
    const text = clean(nameText(el));
    if (text) return text;
  }
  return clean(el.getAttribute("title")) || clean(el.getAttribute("placeholder")) || "";
}

function kindOf(el: Element): ControlKind {
  const role = el.getAttribute("role");
  const type = el instanceof HTMLInputElement ? el.type : "";
  if (role === "tab") return "tab";
  if (role === "link" || (el instanceof HTMLAnchorElement && el.hasAttribute("href"))) return "link";
  if (el instanceof HTMLSelectElement || role === "combobox" || role === "listbox" || role === "radio" || role === "option" || type === "radio") return "choice";
  if (role === "checkbox" || role === "switch" || type === "checkbox" || el.hasAttribute("aria-pressed")) return "toggle";
  if (isTextBox(el) || role === "textbox" || role === "searchbox" || (el as HTMLElement).isContentEditable) return "field";
  return "button";
}

const isCodeEditor = (el: Element): boolean => el.id === "code" || el.classList.contains("editor-input") || !!el.closest(".editor");

function stateOf(el: Element, kind: ControlKind): string {
  const parts: string[] = [];
  const pressed = el.getAttribute("aria-pressed");
  if (pressed === "true") parts.push("pressed"); else if (pressed === "false") parts.push("not pressed"); else if (pressed === "mixed") parts.push("partly pressed");
  const checked = el instanceof HTMLInputElement && (el.type === "checkbox" || el.type === "radio") ? String(el.checked) : el.getAttribute("aria-checked");
  if (checked === "true") parts.push("checked"); else if (checked === "false") parts.push("not checked");
  const selected = el.getAttribute("aria-selected");
  if (selected === "true") parts.push("selected"); else if (selected === "false" && kind === "tab") parts.push("not selected");
  const current = el.getAttribute("aria-current");
  if (current && current !== "false") parts.push("current");
  const expanded = el.getAttribute("aria-expanded");
  if (expanded) parts.push(expanded === "true" ? "open" : "closed");
  if (isTextBox(el)) {
    if (el instanceof HTMLInputElement && el.type === "password") parts.push("hidden");
    else if (isCodeEditor(el)) parts.push(`${el.value.split("\n").length} lines of code`);
    else parts.push(el.value ? `"${shorten(el.value, 40)}"` : "empty");
  } else if (el instanceof HTMLSelectElement) {
    parts.push(`"${shorten(el.selectedOptions[0]?.text ?? "", 40)}"`);
  }
  return parts.join(", ");
}

function linkFacts(el: Element): ControlFacts["link"] {
  const anchor = el.closest("a[href]") as HTMLAnchorElement | null;
  if (!anchor) return el.getAttribute("role") === "link" ? { stays: true, newTab: false, download: false } : null;
  const target = (anchor.getAttribute("target") ?? "").toLowerCase();
  const raw = anchor.getAttribute("href") ?? "";
  let stays = raw.startsWith("#");
  if (!stays) {
    try {
      const url = new URL(anchor.href, window.location.href);
      stays = url.origin === window.location.origin && url.pathname === window.location.pathname && url.search === window.location.search;
    } catch { stays = false; }
  }
  return { stays, newTab: target !== "" && target !== "_self" && target !== "_top" && target !== "_parent", download: anchor.hasAttribute("download") };
}

/** What the guard needs to know about one element. */
function factsOf(el: Element, name = accessibleName(el)): ControlFacts {
  const marked = el.closest("[data-agent]")?.getAttribute("data-agent");
  const form = (el as HTMLInputElement).form ?? el.closest("form");
  return {
    name,
    kind: kindOf(el),
    agent: marked === "off" || marked === "confirm" ? marked : null,
    password: el instanceof HTMLInputElement && (el.type === "password" || /password/i.test(el.autocomplete)),
    signIn: !!el.closest(".signin, [aria-label='Sign in']") || !!form?.querySelector("input[type=password]"),
    codeEditor: isCodeEditor(el),
    link: linkFacts(el),
  };
}

/** Everything a press on `el` would also reach: controls around it (a click bubbles up to them)
 *  and the control a surrounding label stands for. The strictest ruling among them wins. */
function rulingFor(el: Element, action: Action, name?: string): { ruling: Ruling; facts: ControlFacts } {
  const facts = factsOf(el, name);
  const rulings = [rule(facts, action)];
  if (action !== "scroll") {
    for (let up = el.parentElement; up; up = up.parentElement) {
      if (up.matches(CONTROL)) rulings.push(rule(factsOf(up), "press"));
      if (up instanceof HTMLLabelElement && up.control && up.control !== el) rulings.push(rule(factsOf(up.control), action === "type" ? "type" : "press"));
    }
  }
  return { ruling: strictest(rulings), facts };
}

interface Found { el: HTMLElement; name: string; base: string; kind: ControlKind; state: string }

/** The controls a person could use right now, in reading order, each with a unique name. */
function collect(): Found[] {
  const scope = modal() ?? document.body;
  const els = visibleElements(scope).filter((el) => el.matches(CONTROL) && shown(el) && enabled(el)) as HTMLElement[];
  const bases = els.map((el) => accessibleName(el));
  const kinds = els.map(kindOf);
  const fallback = bases.map((b, i) => b || `${kinds[i]} without a name`);
  const counts = new Map<string, number>();
  fallback.forEach((n) => counts.set(normalize(n), (counts.get(normalize(n)) ?? 0) + 1));
  const names = uniqueNames(fallback.map((name, i) => ({
    name, contexts: (counts.get(normalize(name)) ?? 0) > 1 ? contextsOf(els[i]) : [],
  })));
  return els.map((el, i) => ({ el, name: names[i], base: fallback[i], kind: kinds[i], state: stateOf(el, kinds[i]) }));
}

/** What surrounds a control, nearest first: a container's label, its heading, or its first words. */
function contextsOf(el: Element): string[] {
  const out: string[] = [];
  // A box is told apart by what is written in it ("Bullet text, Cut deploy time by 60%…").
  if (isTextBox(el) && !isCodeEditor(el) && el.type !== "password" && el.value.trim()) out.push(shorten(el.value, 40));
  for (let up = el.parentElement; up && up !== document.body && out.length < 6; up = up.parentElement) {
    const label = clean(up.getAttribute("aria-label"));
    if (label) { out.push(shorten(label, 40)); continue; }
    const heading = [...up.querySelectorAll("h1, h2, h3, h4, legend, figcaption")].find((h) => !el.contains(h) && !h.contains(el));
    if (heading && clean(heading.textContent)) { out.push(shorten(clean(heading.textContent), 40)); continue; }
    const lead = leadText(up, el);
    if (lead) out.push(lead);
  }
  return out;
}

/** The first words in a container that are not the control's own: a box's text, or a line with letters in it. */
function leadText(container: Element, control: Element): string | null {
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => {
      if (node instanceof Element) return node === control || hiddenSubtree(node) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if (node instanceof Element) {
      if (isTextBox(node) && node.value.trim() && !(node instanceof HTMLInputElement && node.type === "password")) return shorten(node.value, 40);
      continue;
    }
    const text = clean((node as Text).data);
    const inControl = (node.parentElement?.closest(CONTROL) ?? null);
    if (text.length >= 3 && /\p{L}/u.test(text) && (!inControl || !container.contains(inControl) || inControl === container)) return shorten(text, 40);
  }
  return null;
}

function screenName(): string {
  const dialog = modal();
  const current = document.querySelector("nav [aria-current='page']");
  const base = current ? clean(current.textContent) : clean(document.title) || "Senior";
  return dialog ? `${clean(dialog.getAttribute("aria-label")) || "A dialog"} (over ${base})` : base;
}

function headingNow(): string {
  const scope = modal() ?? mainContent();
  if (!scope) return "";
  const heading = [...scope.querySelectorAll("h1, h2")].find((h) => shownDialog(h));
  return heading ? clean(heading.textContent) : "";
}

const guardLabel = (ruling: Ruling): ControlView["guard"] =>
  ruling.verdict === "block" ? "blocked" : ruling.verdict === "confirm" ? "asks the student first" : undefined;

export function seeScreen(): ScreenView {
  const found = collect();
  // Long names (a ticket, a log row) are shown cut; a cut name still finds its control. Not when
  // cutting would make two names the same.
  const cut = found.map((f) => shorten(f.name, SHOWN_NAME));
  const counts = new Map<string, number>();
  cut.forEach((n) => counts.set(normalize(n), (counts.get(normalize(n)) ?? 0) + 1));
  const controls = found.slice(0, SHOWN_CONTROLS).map(({ el, name, base, kind, state }, i) => {
    const action: Action = kind === "field" ? "type" : kind === "choice" && el instanceof HTMLSelectElement ? "pick" : "press";
    const guard = guardLabel(rulingFor(el, action, base).ruling);
    const shownName = counts.get(normalize(cut[i])) === 1 ? cut[i] : name;
    return { name: shownName, kind, state, ...(guard ? { guard } : {}) };
  });
  return {
    screen: screenName(), heading: headingNow(), controls, more: Math.max(0, found.length - SHOWN_CONTROLS),
    ...(waitingFor ? { waiting_for: `The student is being asked: "${waitingFor}". Nothing else can be done until they answer.` } : {}),
  };
}

// ---------------------------------------------------------------------------------------------
// Finding the control a name means

type Resolved = { found: Found } | { candidates: string[] } | { missing: string };

function resolve(query: string, accept: (f: Found) => boolean = () => true): Resolved {
  const all = collect().filter(accept);
  const match = matchName(query, all.map((f) => f.name), all.map((f) => f.base));
  if (match.kind === "one") return { found: all[match.index] };
  if (match.kind === "many") return { candidates: match.indexes.slice(0, 12).map((i) => all[i].name) };
  return { missing: `No control named "${shorten(query, 60)}" is on the screen now. Call see_screen for the names.` };
}

// ---------------------------------------------------------------------------------------------
// Acting

const frame = () => new Promise<void>((done) => requestAnimationFrame(() => setTimeout(done, 0)));

/** Wait until the page has stopped changing for a moment, or at most `max` ms. */
function settle(quiet = 160, max = 1600): Promise<void> {
  return new Promise((done) => {
    let timer = window.setTimeout(finish, quiet);
    const stop = window.setTimeout(finish, max);
    const watch = new MutationObserver(() => { window.clearTimeout(timer); timer = window.setTimeout(finish, quiet); });
    watch.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true });
    function finish() { watch.disconnect(); window.clearTimeout(timer); window.clearTimeout(stop); done(); }
  });
}

const regionIds = new WeakMap<Element, number>();
let regionCount = 0;

/** Alerts, status lines and live regions now on screen, each keyed by the element itself. */
function notices(): Snapshot["notices"] {
  const regions = [...document.querySelectorAll("[role=alert], [role=status], [role=log], [aria-live]:not([aria-live=off])")]
    .filter((el) => !el.closest("[data-agent='off']") && !el.parentElement?.closest("[role=alert], [role=status], [role=log], [aria-live]") && shownDialog(el));
  return regions.map((el) => {
    if (!regionIds.has(el)) regionIds.set(el, regionCount++);
    // A region kept for screen readers only still says what happened (the glass describes its drawing there).
    const text = readText(el) || clean(el.textContent);
    return { key: String(regionIds.get(el)), text: text.slice(0, 20000), alert: el.getAttribute("role") === "alert" };
  });
}

function snapshot(): { snap: Snapshot; found: Found[] } {
  const found = collect();
  const dialog = modal();
  return {
    found,
    snap: {
      screen: screenName(), heading: headingNow(), dialog: dialog ? clean(dialog.getAttribute("aria-label")) || "A dialog" : null,
      controls: found.map(({ name, state }) => ({ name, state })), notices: notices(),
    },
  };
}

/** One action at a time, and none while the student is being asked about another. */
let queue: Promise<unknown> = Promise.resolve();
function exclusive<T>(work: () => Promise<T>): Promise<T> {
  if (waitingFor) return Promise.reject(new Error(`Senior is waiting for the student to answer: "${waitingFor}". Wait for that first.`));
  const run = queue.then(work, work);
  queue = run.catch(() => undefined);
  return run;
}

/** Put a question to the student. Resolves with their answer; only one question is ever open. */
async function askStudent(what: string): Promise<Answer> {
  if (!asker) throw new Error("Senior cannot ask the student right now, so this was not done.");
  if (waitingFor) throw new Error(`Senior is already waiting for the student to answer: "${waitingFor}".`);
  waitingFor = what;
  try { return await asker(what); } finally { waitingFor = null; }
}

const NO: Record<Exclude<Answer, "allow">, string> = { deny: "The student said not now.", timeout: "No answer." };

/** Still the same control, still usable, after the wait for the student. */
function unchanged(el: HTMLElement, base: string): boolean {
  return el.isConnected && reachable(el) && accessibleName(el) === base;
}

function whatNow(before: Snapshot, found: Found, after: { snap: Snapshot; found: Found[] }): string {
  const same = after.found.find((f) => f.el === found.el);
  if (same) return describeChange(before, after.snap, { name: found.name, state: found.state, nowName: same.name, nowState: same.state });
  // Still on screen but disabled while it works ("Running…"), or gone.
  const busy = found.el.isConnected && shownDialog(found.el);
  return describeChange(before, after.snap, { name: found.name, state: found.state, nowName: busy ? accessibleName(found.el) || found.name : null, nowState: busy ? "unavailable for now" : "" });
}

export function press({ control }: { control: string }): Promise<PressResult> {
  return exclusive(async () => {
    const hit = resolve(String(control ?? ""));
    if ("missing" in hit) throw new Error(hit.missing);
    if ("candidates" in hit) return { pressed: false, reason: "Several controls match. Say which one.", candidates: hit.candidates };
    const found = hit.found;
    const { ruling, facts } = rulingFor(found.el, "press", found.base);
    if (ruling.verdict === "block") throw new Error(ruling.reason);
    if (ruling.verdict === "confirm") {
      const answer = await askStudent(askText({ ...facts, name: found.name }, "press"));
      if (answer !== "allow") return { pressed: false, reason: NO[answer] };
      if (!unchanged(found.el, found.base) || rulingFor(found.el, "press", found.base).ruling.verdict === "block") {
        return { pressed: false, reason: "The control changed while the student was deciding, so nothing was pressed." };
      }
    }
    const before = snapshot().snap;
    found.el.scrollIntoView({ block: "nearest", inline: "nearest" });
    if (found.kind === "field" || found.el instanceof HTMLSelectElement) found.el.focus();
    else found.el.click();
    await settle();
    return { pressed: true, now: whatNow(before, found, snapshot()) };
  });
}

/** Set a box's text the way typing does, so React sees it: the native setter, then input and change events. */
function typeText(el: HTMLInputElement | HTMLTextAreaElement, text: string): void {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  el.focus();
  if (setter) setter.call(el, text); else el.value = text;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

function submitterOf(form: HTMLFormElement): HTMLElement | null {
  return form.querySelector<HTMLElement>("button[type=submit], button:not([type]), input[type=submit]");
}

/** What sending from a box could set off: its form's submit button, or, outside a form, the
 *  buttons that follow it in its own group (a page may send on Enter without a form). The guard
 *  rules on all of them. */
function sendTargets(el: HTMLInputElement | HTMLTextAreaElement): HTMLElement[] {
  if (el.form) { const button = submitterOf(el.form); return button ? [button] : []; }
  for (let up = el.parentElement, depth = 0; up && depth < 2; up = up.parentElement, depth++) {
    const buttons = [...up.querySelectorAll<HTMLElement>("button, [role=button], input[type=submit]")]
      .filter((b) => !b.closest("[data-agent='off']") && (el.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0);
    if (buttons.length) return buttons;
  }
  return [];
}

export function typeInto({ control, text, submit }: { control: string; text: string; submit: string }): Promise<TypeResult> {
  return exclusive(async () => {
    const hit = resolve(String(control ?? ""), (f) => f.kind === "field");
    if ("missing" in hit) {
      // Name the reason when the name is a control that is not a box, or a box Senior may not touch.
      const other = resolve(String(control ?? ""));
      if ("found" in other) {
        const { ruling } = rulingFor(other.found.el, "type", other.found.base);
        if (ruling.verdict === "block") throw new Error(ruling.reason);
        throw new Error(`${other.found.name} is a ${other.found.kind}, not a text box.`);
      }
      throw new Error(hit.missing.replace("No control", "No text box"));
    }
    if ("candidates" in hit) return { typed: false, submitted: false, reason: "Several boxes match. Say which one.", candidates: hit.candidates };
    const { el, base, name } = hit.found;
    if (!isTextBox(el)) throw new Error(`Senior can only type into plain text boxes; ${name} is not one.`);
    const sending = /^(yes|true|y|1|submit|send)$/i.test(String(submit ?? "").trim());
    const typing = rulingFor(el, "type", base);
    const form = el.form;
    const targets = sending ? sendTargets(el) : [];
    const sendRulings = targets.map((t) => rulingFor(t, "press").ruling);
    const sendRuling = strictest(sendRulings);
    const ruling = strictest([typing.ruling, sendRuling]);
    if (ruling.verdict === "block") throw new Error(ruling.reason);
    if (ruling.verdict === "confirm") {
      const asking = targets.find((_, i) => sendRulings[i].verdict !== "allow");
      const then = asking ? `press ${accessibleName(asking)}` : sending ? "send it" : "";
      const answer = await askStudent(askText({ ...typing.facts, name }, "type", then));
      if (answer !== "allow") return { typed: false, submitted: false, reason: NO[answer] };
      if (!unchanged(el, base)) return { typed: false, submitted: false, reason: "The box changed while the student was deciding, so nothing was typed." };
    }
    const value = String(text ?? "");
    const limit = Math.min(MAX_TYPED, el.maxLength > 0 ? el.maxLength : MAX_TYPED);
    const before = snapshot().snap;
    el.scrollIntoView({ block: "nearest", inline: "nearest" });
    typeText(el, value.slice(0, limit));
    await frame();
    let submitted = false;
    let reason: string | undefined;
    if (sending) {
      // Enter, as a person would press it. A box that sends on Enter handles it; otherwise its form is submitted.
      const enter = new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true });
      const unhandled = el.dispatchEvent(enter);
      el.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true }));
      if (!unhandled) submitted = true;
      else if (form && el instanceof HTMLInputElement) {
        await frame();
        const button = submitterOf(form);
        if (button && !enabled(button)) reason = `${accessibleName(button)} is not available yet, so nothing was sent.`;
        else { form.requestSubmit(button && button.matches("button, input[type=submit]") ? button : undefined); submitted = true; }
      } else reason = "Enter does nothing in this box: it acts as you type, or it has its own button to press.";
    }
    await settle();
    const after = snapshot();
    const now = whatNow(before, hit.found, after);
    const cut = value.length > limit ? ` Only the first ${limit} characters fit.` : "";
    return { typed: true, submitted, now: now + cut, ...(reason ? { reason } : {}) };
  });
}

export function pickOption({ control, option }: { control: string; option: string }): Promise<PickResult> {
  return exclusive(async () => {
    const hit = resolve(String(control ?? ""), (f) => f.el instanceof HTMLSelectElement);
    if ("missing" in hit) throw new Error(hit.missing.replace("No control", "No drop-down list"));
    if ("candidates" in hit) return { picked: null, reason: "Several lists match. Say which one.", candidates: hit.candidates };
    const select = hit.found.el as HTMLSelectElement;
    const options = [...select.options].filter((o) => !o.disabled);
    const match = matchName(String(option ?? ""), options.map((o) => clean(o.text)));
    if (match.kind === "none") return { picked: null, reason: `No option like "${shorten(String(option ?? ""), 60)}". The options are: ${options.map((o) => clean(o.text)).slice(0, 12).join(", ")}.` };
    if (match.kind === "many") return { picked: null, reason: "Several options match. Say which one.", candidates: match.indexes.map((i) => clean(options[i].text)) };
    const chosen = options[match.index];
    const { ruling, facts } = rulingFor(select, "pick", hit.found.base);
    const optionRuling = rule({ ...facts, name: clean(chosen.text) }, "pick");
    const worst = strictest([ruling, optionRuling]);
    if (worst.verdict === "block") throw new Error(worst.reason);
    if (worst.verdict === "confirm") {
      const answer = await askStudent(askText({ ...facts, name: hit.found.name }, "pick", clean(chosen.text)));
      if (answer !== "allow") return { picked: null, reason: NO[answer] };
      if (!unchanged(select, hit.found.base) || !chosen.isConnected) return { picked: null, reason: "The list changed while the student was deciding, so nothing was chosen." };
    }
    const before = snapshot().snap;
    select.scrollIntoView({ block: "nearest", inline: "nearest" });
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
    select.focus();
    if (setter) setter.call(select, chosen.value); else select.value = chosen.value;
    select.dispatchEvent(new Event("input", { bubbles: true }));
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await settle();
    return { picked: clean(chosen.text), now: whatNow(before, hit.found, snapshot()) };
  });
}

// ---------------------------------------------------------------------------------------------
// Reading

/** Hidden from sight but kept for screen readers (.sr-only): left out of what the screen shows. */
function visuallyHidden(el: Element, style: CSSStyleDeclaration): boolean {
  return el.classList.contains("sr-only") || (style.position === "absolute" && (style.clip.startsWith("rect(0") || style.clipPath.includes("inset(50%")));
}

/** The text a person sees in `root`, in reading order. Boxes read as [name: text]; markup never comes through. */
function readText(root: Element): string {
  const parts: string[] = [];
  const visit = (node: Node, sideBySide: boolean, keepBreaks: boolean) => {
    if (node.nodeType === Node.TEXT_NODE) { const data = (node as Text).data; parts.push(keepBreaks ? data : data.replace(/\n/g, " ")); return; }
    if (!(node instanceof Element) || hiddenSubtree(node)) return;
    const style = getComputedStyle(node);
    if (visuallyHidden(node, style) || style.visibility === "hidden") return;
    if (node.tagName === "BR") { parts.push("\n"); return; }
    if (isTextBox(node) || node instanceof HTMLSelectElement) {
      const name = shorten(accessibleName(node) || "box", 40);
      const value = node instanceof HTMLSelectElement ? node.selectedOptions[0]?.text ?? ""
        : node instanceof HTMLInputElement && node.type === "password" ? "(hidden)"
        : isCodeEditor(node) ? `(${node.value.split("\n").length} lines of code; read_code reads them)`
        : node.value ? shorten(node.value, 300) : "(empty)";
      parts.push(`${SOFT}[${name}: ${value}]${SOFT}`);
      return;
    }
    if (node instanceof HTMLImageElement) { if (node.alt) parts.push(` ${node.alt} `); return; }
    if (node.tagName === "CANVAS" || node.tagName === "VIDEO" || node.tagName === "IFRAME") return;
    if (node instanceof SVGElement) {
      const words = [...node.querySelectorAll("text, title")].filter((t) => !t.closest("[aria-hidden='true']")).map((t) => clean(t.textContent)).filter(Boolean);
      if (node.tagName.toLowerCase() === "svg" && words.length && node.getAttribute("aria-hidden") !== "true") parts.push(`${SOFT}${words.join(" ")}${SOFT}`);
      return;
    }
    if (node.tagName === "PRE" || style.whiteSpace === "pre") {
      // Code and JSON keep their lines and indentation.
      parts.push("\n", PRE_START, node.textContent ?? "", PRE_END, "\n");
      return;
    }
    // Inline text runs on; a pill or chip (inline-block) sits apart; a block starts a new line,
    // unless its container lays its children side by side.
    const edge = style.display === "inline" || style.display === "contents" ? ""
      : style.display.startsWith("inline") || sideBySide ? SOFT : "\n";
    const row = (style.display.endsWith("flex") && !style.flexDirection.startsWith("column")) || style.display.endsWith("grid");
    parts.push(edge);
    const breaks = style.whiteSpace.startsWith("pre") || style.whiteSpace === "break-spaces";
    node.childNodes.forEach((child) => visit(child, row, breaks));
    parts.push(edge);
  };
  visit(root, false, false);
  return composeText(parts);
}

const SECTION = "main, section, article, aside, form, nav, figure, fieldset, li, [role=region], [role=group], [role=dialog], [role=alertdialog], [role=log], [role=tabpanel]";

/** The parts of the screen that can be read on their own: labelled regions and anything under a heading. */
function parts(): { name: string; el: Element }[] {
  const scope = modal() ?? document.body;
  const out: { name: string; el: Element }[] = [];
  for (const el of visibleElements(scope)) {
    if (el.matches(SECTION)) {
      const label = clean(el.getAttribute("aria-label"));
      if (label) out.push({ name: label, el });
    }
    if (/^H[1-4]$/.test(el.tagName) && clean(el.textContent)) {
      const box = el.closest(SECTION) ?? el.parentElement;
      if (box) out.push({ name: clean(el.textContent), el: box });
    }
  }
  return out;
}

export function readScreen({ part }: { part: string }): ReadResult {
  const wanted = String(part ?? "").trim();
  let root: Element | null = modal() ?? mainContent();
  let label = root ? clean(root.getAttribute("aria-label")) || "The main part of the screen" : "The whole screen";
  if (wanted) {
    const all = parts();
    const match = matchName(wanted, all.map((p) => p.name));
    if (match.kind === "none") {
      const names = [...new Set(all.map((p) => shorten(p.name, 40)))].slice(0, 16);
      throw new Error(`No part called "${shorten(wanted, 60)}" is on the screen. Parts: ${names.join(", ")}.`);
    }
    const pick = match.kind === "one" ? match.index : match.indexes[0];
    root = all[pick].el;
    label = all[pick].name;
  }
  const { text, cut } = capText(readText(root ?? document.body), READ_CHARS);
  return {
    screen: screenName(), part: label, text,
    ...(cut ? { cut: `About ${cut} more characters are not included. Read a smaller part by its heading to see them.` } : {}),
    note: NOT_INSTRUCTIONS,
  };
}

export function scrollTo({ control }: { control: string }): Promise<{ scrolled_to: string }> {
  return exclusive(async () => {
    const hit = resolve(String(control ?? ""));
    let target: Element | null = null;
    let name = "";
    if ("found" in hit) { target = hit.found.el; name = hit.found.name; }
    else if ("candidates" in hit) throw new Error(`Several controls match: ${hit.candidates.join("; ")}. Say which one.`);
    else {
      const all = parts();
      const match = matchName(String(control ?? ""), all.map((p) => p.name));
      if (match.kind === "none") throw new Error(hit.missing);
      const pick = match.kind === "one" ? match.index : match.indexes[0];
      target = all[pick].el; name = all[pick].name;
    }
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    target.scrollIntoView({ block: "center", inline: "nearest", behavior: still ? "auto" : "smooth" });
    return { scrolled_to: name };
  });
}
