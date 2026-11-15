// The glass: a transparent pane between Senior and the student, across the whole screen.
// Senior draws on it as it explains, the way a teacher writes on a glass board: each drawing
// goes up in order and stays up, strokes are drawn on, pointers glide when they move, and
// Senior can mark lines of the student's own code underneath. The student can still see and
// use the app through it. Everything here is driven by page tools (glass_array, glass_3d,
// glass_steps, glass_note, glass_clear, highlight_lines), so drawings go through the same
// registry, and the same limits, as every other action Senior takes.

import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useApp } from "../app-context";
import type { SceneKind, SceneSpec } from "./Scene3D";
import { invoke, onToolCall, registerTool } from "./tools";

// three.js only downloads the first time something is shown in 3D.
const Scene3D = lazy(() => import("./Scene3D"));
const SCENES: SceneKind[] = ["bars", "grid", "tree", "graph"];
const MAX_NODES = 31;
const MAX_CELLS = 16;
const MAX_ITEMS = 8; // what fits on the glass at a readable size; older drawings come off
const LOWER_AFTER_MS = 75_000; // a glass nobody is looking at lowers itself; nothing is lost
const FRESH_MS = 2600;
// The code editor's line geometry (web/src/components/CodeEditor.tsx).
const EDITOR_LINE = 22;
const EDITOR_PAD = 14;

export const LOOKS_LIKE_CODE = /```|^\s*(def |for .+ in .+:|while .+:|return\b|import )/m;

/** "0:left,4:right" -> {0: [left], 4: [right]}. Entries that do not parse are dropped. */
export function parsePointers(text: string, length: number): Map<number, string[]> {
  const out = new Map<number, string[]>();
  for (const part of text.split(",")) {
    const [index, label] = part.split(":").map((s) => s.trim());
    const i = Number(index);
    if (label && Number.isInteger(i) && i >= 0 && i < length) out.set(i, [...(out.get(i) ?? []), label]);
  }
  return out;
}

type Pointers = Map<number, string[]>;
interface ArrayItem { id: number; kind: "array"; values: string[]; pointers: Pointers; trail: number[]; caption: string; rev: number }
interface BarsItem { id: number; kind: "bars"; values: number[]; l: number | null; r: number | null; names: { l: string; r: string }; water: boolean; caption: string; rev: number }
interface SceneItem { id: number; kind: "scene"; spec: SceneSpec; caption: string }
interface StepsItem { id: number; kind: "steps"; title: string; steps: string[] }
interface NoteItem { id: number; kind: "note"; text: string }
interface EventItem { id: number; kind: "event"; title: string; when: string; url: string }
type Item = ArrayItem | BarsItem | SceneItem | StepsItem | NoteItem | EventItem;
interface CodeMark { from: number; to: number; note: string }

const stamp = (d: Date) =>
  `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}T${String(d.getHours()).padStart(2, "0")}${String(d.getMinutes()).padStart(2, "0")}00`;

/** A prefilled Google Calendar link. The student adds the event themselves; nothing is written for them. */
function calendarLink(title: string, start: Date, end: Date, details: string): string {
  const query = new URLSearchParams({ action: "TEMPLATE", text: title, dates: `${stamp(start)}/${stamp(end)}`, details });
  return `https://calendar.google.com/calendar/render?${query}`;
}

/** The glass is words and pictures. Code on it would bypass the coach's leak check. */
function refuseCode(...texts: string[]): void {
  if (texts.some((t) => LOOKS_LIKE_CODE.test(t))) throw new Error("The glass does not show code. Describe it in words.");
}

const sameValues = (a: readonly (string | number)[], b: readonly (string | number)[]) => a.length === b.length && a.every((v, i) => v === b[i]);
/** Animation delay for one stroke or line, so a drawing goes up in the order a hand would draw it. */
const after = (ms: number) => ({ "--d": `${ms}ms` }) as CSSProperties;

function findLast<T>(list: T[], test: (item: T) => boolean): number {
  for (let i = list.length - 1; i >= 0; i--) if (test(list[i])) return i;
  return -1;
}

/** What a screen reader hears when a drawing goes up. */
function describe(item: Item): string {
  if (item.kind === "array") {
    const pointers = [...item.pointers].map(([i, names]) => `${names.join(" and ")} at index ${i}`).join(", ");
    return `Senior drew the list ${item.values.join(", ")}${pointers ? `, with ${pointers}` : ""}. ${item.caption}`;
  }
  if (item.kind === "bars") return `Senior drew bars of height ${item.values.join(", ")}${item.l !== null && item.r !== null ? `, with ${item.names.l} at ${item.l} and ${item.names.r} at ${item.r}` : ""}. ${item.caption}`;
  if (item.kind === "scene") return `Senior drew a ${item.spec.scene} in 3D. ${item.caption}`;
  if (item.kind === "steps") return `Senior wrote: ${item.title}. ${item.steps.join(". ")}`;
  if (item.kind === "note") return `Senior wrote: ${item.text}`;
  return `Senior offered a practice session: ${item.title}, ${item.when}`;
}

function ArrayDrawing({ item }: { item: ArrayItem }) {
  const n = item.values.length;
  const size = n <= 8 ? 68 : n <= 12 ? 54 : 44;
  const gap = 10;
  const width = n * size + (n - 1) * gap;
  const top = 22;
  const x = (i: number) => i * (size + gap);
  const labels = [...item.pointers].flatMap(([index, names]) => names.map((name, k) => ({ index, name, k })));
  return (
    <svg className="gb-svg" viewBox={`-6 0 ${width + 12} ${top + size + 64}`} width={width + 12} role="img" aria-label={describe(item)}>
      <g className="gb-rough">
        {item.values.map((_, i) => (
          <rect key={i} className={`ink gb-cell ${item.pointers.has(i) ? "on" : ""}`} pathLength={1} style={after(i * 70)}
            x={x(i)} y={top} width={size} height={size} rx={14} />
        ))}
      </g>
      {item.values.map((value, i) => (
        <g key={i} className="write" style={after(i * 70 + 180)}>
          <text className="gb-idx" x={x(i) + size / 2} y={12}>{i}</text>
          <text className="gb-val" x={x(i) + size / 2} y={top + size / 2} style={{ fontSize: size > 60 ? 24 : 18 }}>{value}</text>
        </g>
      ))}
      {/* Where a pointer used to be: a faint mark, like a teacher's earlier dots along the row. */}
      {item.trail.map((index, k) => <circle key={`${index}-${k}`} className="gb-ghost" cx={x(index) + size / 2} cy={top + size + 10} r={3.5} />)}
      {labels.map(({ index, name, k }) => (
        <g key={name} className="gb-ptr" style={{ transform: `translate(${x(index) + size / 2}px, ${top + size + 8 + k * 20}px)` }}>
          <g className="write" style={after(n * 70 + 260)}>
            {k === 0 && <path className="gb-arrow" d="M0 16 L0 3 M-5.5 9 L0 3 L5.5 9" />}
            <text className="gb-ptr-name" x={0} y={36}>{name}</text>
          </g>
        </g>
      ))}
    </svg>
  );
}

function BarsDrawing({ item }: { item: BarsItem }) {
  const [l, setL] = useState(item.l);
  const [r, setR] = useState(item.r);
  const [best, setBest] = useState(0);
  const [inThree, setInThree] = useState(false);
  // Senior redrawing the same bars with the pointers somewhere new moves them here.
  useEffect(() => { setL(item.l); setR(item.r); }, [item.rev, item.l, item.r]);

  const n = item.values.length;
  const max = Math.max(1, ...item.values);
  const paired = l !== null && r !== null && r > l;
  const area = paired ? (r - l) * Math.min(item.values[l], item.values[r]) : null;
  useEffect(() => { if (area !== null) setBest((b) => Math.max(b, area)); }, [area]);

  // As on the design's glass wall: clicking a bar moves whichever pointer is nearer.
  const pick = (i: number) => {
    if (l === null || r === null) return;
    const nearerLeft = Math.abs(i - l) <= Math.abs(i - r);
    if (nearerLeft && i < r) setL(i);
    else if (!nearerLeft && i > l) setR(i);
  };

  const spec = useMemo<SceneSpec>(() => {
    const pointers: Pointers = new Map();
    if (l !== null) pointers.set(l, [item.names.l]);
    if (r !== null) pointers.set(r, [...(pointers.get(r) ?? []), item.names.r]);
    return { scene: "bars", values: item.values.map(String), pointers, water: item.water && l !== null && r !== null && r > l ? [l, r] : null, highlight: new Set(), edges: [] };
  }, [item.values, item.names, item.water, l, r]);

  return (
    <div className="gb-bars">
      {inThree ? (
        <Suspense fallback={<div className="glass-3d glass-3d-loading">Drawing in 3D…</div>}>
          <Scene3D spec={spec} caption="" />
        </Suspense>
      ) : (
        <div className="gb-chart" role="group" aria-label={describe(item)}>
          <div className="gb-chart-in">
            {item.water && paired && (
              <div className="gb-water" aria-hidden="true"
                style={{ left: `${((l + 0.5) / n) * 100}%`, width: `${((r - l) / n) * 100}%`, height: `${(Math.min(item.values[l], item.values[r]) / max) * 100}%` }} />
            )}
            {item.values.map((value, i) => {
              const tag = i === l ? item.names.l : i === r ? item.names.r : "";
              return (
                <button key={i} className={`gb-bar ${tag ? "on" : ""}`} style={{ ...after(i * 70), height: `${Math.max(4, (value / max) * 100)}%` }}
                  onClick={() => pick(i)} aria-label={`Bar ${i}, height ${value}${tag ? `, ${tag} pointer` : ""}`}>
                  <span className="gb-bar-val">{value}</span>
                  <span className="gb-bar-idx">{i}</span>
                  {tag && <span className="gb-bar-tag">{tag}</span>}
                </button>
              );
            })}
          </div>
        </div>
      )}
      <div className="gb-read">
        {paired && area !== null
          ? <span>{item.names.l}={l} {item.names.r}={r} · area {area} · best you have tried <b>{best}</b></span>
          : <span>{n} bars</span>}
        <button className="gb-btn" aria-pressed={inThree} onClick={() => setInThree((v) => !v)}>{inThree ? "Flat" : "View in 3D"}</button>
      </div>
    </div>
  );
}

function Drawing({ item }: { item: Item }) {
  if (item.kind === "array") return <ArrayDrawing item={item} />;
  if (item.kind === "bars") return <BarsDrawing item={item} />;
  if (item.kind === "scene") {
    return (
      <Suspense fallback={<div className="glass-3d glass-3d-loading">Drawing in 3D…</div>}>
        <Scene3D spec={item.spec} caption="" />
      </Suspense>
    );
  }
  if (item.kind === "steps") {
    return (
      <div className="gb-steps">
        {item.title && <div className="gb-title write-line">{item.title}</div>}
        <ol>
          {item.steps.map((step, i) => (
            <li key={i} className="write-line" style={after(300 + i * 420)}><span className="gb-num">{i + 1}</span><span>{step}</span></li>
          ))}
        </ol>
      </div>
    );
  }
  if (item.kind === "note") return <p className="gb-note write-line">{item.text}</p>;
  return (
    <div className="gb-event">
      <div className="gb-title">{item.title}</div>
      <div className="muted">{item.when}</div>
      <a className="btn-primary" href={item.url} target="_blank" rel="noreferrer">Add to Google Calendar</a>
    </div>
  );
}

/** Where the marked lines of the student's code are on screen right now, or null if they are not visible. */
function measureMark(mark: CodeMark, glass: HTMLElement | null): { x: number; y: number; w: number; h: number } | null {
  const editor = document.getElementById("code") as HTMLTextAreaElement | null;
  if (!editor || !glass) return null;
  const box = editor.getBoundingClientRect();
  if (box.width === 0) return null;
  const origin = glass.getBoundingClientRect(); // marks are drawn in the glass's own coordinates
  const top = box.top + EDITOR_PAD + (mark.from - 1) * EDITOR_LINE - editor.scrollTop;
  const y1 = Math.max(top, box.top);
  const y2 = Math.min(top + (mark.to - mark.from + 1) * EDITOR_LINE, box.bottom);
  if (y2 <= y1) return null;
  return { x: box.left - origin.left + 6, y: y1 - origin.top - 3, w: Math.min(box.width - 12, 720), h: y2 - y1 + 6 };
}

export function Glass() {
  const { page, problemId, sessionId } = useApp();
  const [items, setItems] = useState<Item[]>([]);
  const [up, setUp] = useState(false);
  const [wiping, setWiping] = useState(false);
  const [freshId, setFreshId] = useState<number | null>(null);
  const [mark, setMark] = useState<CodeMark | null>(null);
  // The glass shows one layer at a time: Senior's drawings, or its marks on the student's code
  // (with the pane clear, so the code underneath stays sharp and editable).
  const [layer, setLayer] = useState<"drawings" | "code">("drawings");
  const [markBox, setMarkBox] = useState<ReturnType<typeof measureMark>>(null);
  const [keepClear, setKeepClear] = useState(12); // px kept clear on the right, so the coach's words stay readable
  const [activity, setActivity] = useState(0);
  const nextId = useRef(0);
  const board = useRef<Item[]>([]); // what is on the glass right now, readable inside tool handlers
  const looking = useRef(false);
  const newest = useRef<HTMLElement | null>(null);
  const root = useRef<HTMLElement | null>(null);

  const commit = useCallback((next: Item[]) => { board.current = next; setItems(next); }, []);

  const raise = useCallback((id: number | null) => {
    setUp(true);
    setActivity((n) => n + 1);
    if (id !== null) setFreshId(id);
  }, []);

  const wipe = useCallback(() => {
    setWiping(true);
    window.setTimeout(() => { commit([]); setMark(null); setWiping(false); setUp(false); }, 420);
  }, [commit]);

  // A new problem or a new session starts with a clean glass.
  useEffect(() => { commit([]); setMark(null); setUp(false); }, [problemId, sessionId, commit]);

  useEffect(() => {
    const put = (make: (id: number) => Item) => {
      const id = nextId.current++;
      commit([...board.current, make(id)].slice(-MAX_ITEMS));
      setLayer("drawings");
      raise(id);
      return { drawn: 1 };
    };
    /** Replace the drawing at `at` with a moved copy, keeping its place on the glass. */
    const redraw = (at: number, updated: Item) => {
      commit([...board.current.slice(0, at), updated, ...board.current.slice(at + 1)]);
      setLayer("drawings");
      raise(updated.id);
      return { drawn: 1 };
    };
    const cleanups = [
      registerTool("glass_array", ({ values, pointers, caption }) => {
        if (!Array.isArray(values) || values.length === 0) throw new Error("values must be a non-empty list.");
        if (values.length > MAX_CELLS) throw new Error(`Draw at most ${MAX_CELLS} cells.`);
        refuseCode(caption ?? "");
        const cells = values.map(String);
        const next = parsePointers(pointers ?? "", cells.length);
        // The same list again with the pointers somewhere new: move them on the drawing that is
        // already up, and leave a mark where they were, instead of drawing the list a second time.
        const at = findLast(board.current, (it) => it.kind === "array" && sameValues(it.values, cells));
        if (at >= 0) {
          const old = board.current[at] as ArrayItem;
          const left = [...old.pointers.keys()].filter((i) => !next.has(i));
          return redraw(at, { ...old, pointers: next, trail: [...old.trail, ...left].slice(-8), caption: caption || old.caption, rev: old.rev + 1 });
        }
        return put((id) => ({ id, kind: "array", values: cells, pointers: next, trail: [], caption: caption ?? "", rev: 0 }));
      }),
      registerTool("glass_steps", ({ title, steps }) => {
        if (!Array.isArray(steps) || steps.length === 0) throw new Error("steps must be a non-empty list.");
        refuseCode(title ?? "", ...steps.map(String));
        return put((id) => ({ id, kind: "steps", title: title ?? "", steps: steps.map(String).slice(0, 6) }));
      }),
      registerTool("glass_note", ({ text }) => {
        if (!text?.trim()) throw new Error("text is empty.");
        refuseCode(text);
        return put((id) => ({ id, kind: "note", text }));
      }),
      registerTool("glass_3d", ({ scene, values, pointers, water, highlight, edges, caption }) => {
        if (!SCENES.includes(scene)) throw new Error(`scene must be one of ${SCENES.join(", ")}.`);
        if (!Array.isArray(values) || values.length === 0) throw new Error("values must be a non-empty list.");
        if (values.length > MAX_NODES) throw new Error(`Draw at most ${MAX_NODES} values.`);
        refuseCode(caption ?? "");
        const cells = values.map(String);
        const marks = parsePointers(pointers ?? "", cells.length);
        const span = /^\s*(\d+)\s*-\s*(\d+)\s*$/.exec(water ?? "");
        const numbers = cells.map(Number);
        if (scene === "bars" && numbers.every((v) => Number.isFinite(v) && v >= 0) && numbers.length <= MAX_CELLS) {
          // Bars are drawn flat on the glass, where the student can move the pointers; 3D is one click away.
          const pointed = [...marks.keys()].sort((a, b) => a - b);
          const ends = span ? [Number(span[1]), Number(span[2])].sort((a, b) => a - b) : pointed.length > 1 ? [pointed[0], pointed[pointed.length - 1]] : [pointed[0] ?? null, null];
          const l = ends[0] !== null && ends[0] < numbers.length ? ends[0] : null;
          const r = ends[1] !== null && ends[1] < numbers.length ? ends[1] : null;
          const names = { l: (l !== null && marks.get(l)?.[0]) || "left", r: (r !== null && marks.get(r)?.slice(-1)[0]) || "right" };
          const at = findLast(board.current, (it) => it.kind === "bars" && sameValues(it.values, numbers));
          if (at >= 0) {
            const old = board.current[at] as BarsItem;
            return redraw(at, { ...old, l, r, names, water: Boolean(span) || old.water, caption: caption || old.caption, rev: old.rev + 1 });
          }
          return put((id) => ({ id, kind: "bars", values: numbers, l, r, names, water: Boolean(span), caption: caption ?? "", rev: 0 }));
        }
        const pairs = (edges ?? "").split(",").map((e) => e.split("-").map((v) => Number(v.trim())))
          .filter((p): p is [number, number] => p.length === 2 && p.every((v) => Number.isInteger(v) && v >= 0 && v < cells.length));
        const spec: SceneSpec = {
          scene, values: cells, pointers: marks,
          water: span ? [Number(span[1]), Number(span[2])] : null,
          highlight: new Set((highlight ?? "").split(",").map((h) => h.trim()).filter(Boolean)),
          edges: pairs,
        };
        return put((id) => ({ id, kind: "scene", spec, caption: caption ?? "" }));
      }),
      registerTool("glass_clear", () => { wipe(); return {}; }),
      registerTool("propose_calendar_event", ({ title, start, minutes, details }) => {
        const begins = new Date(start);
        if (!title?.trim()) throw new Error("title is empty.");
        if (Number.isNaN(begins.getTime())) throw new Error("start must look like 2026-11-16T18:30.");
        if (!Number.isFinite(minutes) || minutes < 15 || minutes > 240) throw new Error("minutes must be between 15 and 240.");
        const ends = new Date(begins.getTime() + minutes * 60_000);
        const when = `${begins.toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}, ${minutes} min`;
        put((id) => ({ id, kind: "event", title, when, url: calendarLink(title, begins, ends, details ?? "") }));
        return { offered: true as const, start: begins.toISOString(), end: ends.toISOString() };
      }),
    ];
    return () => cleanups.forEach((off) => off());
  }, [raise, wipe, commit]);

  // When Senior points at lines of the student's code, mark them on the glass, over the code itself.
  useEffect(() => onToolCall((call) => {
    if (call.name === "highlight_lines" && call.ok) {
      const { from, to, note } = call.args as CodeMark;
      setMark({ from, to, note });
      setLayer("code");
      document.getElementById("code")?.scrollIntoView({ block: "nearest" });
      raise(null);
    }
    if (call.name === "clear_highlight") { setMark(null); setLayer("drawings"); }
  }), [raise]);

  useEffect(() => {
    if (!mark) { setMarkBox(null); return; }
    const place = () => setMarkBox(measureMark(mark, root.current));
    place();
    const timer = window.setInterval(place, 200); // the editor scrolls and the page reflows under the glass
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { window.clearInterval(timer); window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [mark, page]);

  // The newest drawing glows for a moment, then settles like the rest.
  useEffect(() => {
    if (freshId === null) return;
    const timer = window.setTimeout(() => setFreshId(null), FRESH_MS);
    return () => window.clearTimeout(timer);
  }, [freshId, activity]);

  useEffect(() => { newest.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [items.length]);

  // Nobody should have to put the glass away by hand: it lowers itself when it has been quiet
  // for a while, when the student goes back to typing code, or on Escape. Nothing is wiped.
  useEffect(() => {
    if (!up) return;
    const timer = window.setTimeout(() => { if (!looking.current) setUp(false); }, LOWER_AFTER_MS);
    const onKey = (event: KeyboardEvent) => {
      // Typing code under the drawings puts the glass away; typing on marked code is the point of the mark.
      const typingCode = layer === "drawings" && (event.target as HTMLElement | null)?.id === "code" && event.key.length === 1;
      if (event.key === "Escape" || typingCode) setUp(false);
    };
    window.addEventListener("keydown", onKey);
    return () => { window.clearTimeout(timer); window.removeEventListener("keydown", onKey); };
  }, [up, activity, layer]);

  // On the Workspace, on a wide screen, the pane stops short of the coach's column, so the
  // student reads Senior's words beside the drawing, like a class with a board.
  useEffect(() => {
    if (!up) return;
    const measure = () => {
      const coach = document.querySelector<HTMLElement>(".row-wrap > section.card");
      const box = coach?.getBoundingClientRect();
      const beside = page === "workspace" && box && box.width > 0 && window.innerWidth >= 1100 && box.left > window.innerWidth * 0.45;
      setKeepClear(beside ? Math.round(window.innerWidth - box.left + 8) : 12);
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [up, page, items.length]);

  const onCode = mark !== null && (layer === "code" || items.length === 0);
  const shown = up && (items.length > 0 || mark !== null);
  const last = items[items.length - 1];

  return (
    <aside ref={root} className={`gb ${shown ? "up" : ""}`} aria-label="Glass">
      <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
        <defs>
          {/* A slight wobble, so strokes read as drawn by hand rather than printed. */}
          <filter id="gb-rough" x="-10%" y="-10%" width="120%" height="120%">
            <feTurbulence type="fractalNoise" baseFrequency="0.03" numOctaves="2" seed="7" result="noise" />
            <feDisplacementMap in="SourceGraphic" in2="noise" scale="2.4" />
          </filter>
        </defs>
      </svg>

      <div className={`gb-pane ${onCode ? "clear" : ""}`} style={{ right: onCode ? 12 : keepClear }} aria-hidden={!shown}
        onPointerEnter={() => { looking.current = true; }}
        onPointerLeave={() => { looking.current = false; setActivity((n) => n + 1); }}>
        <span className="gb-tick tl" /><span className="gb-tick tr" /><span className="gb-tick bl" /><span className="gb-tick br" />
        <div className="gb-head">
          <span className="gb-live" />
          <span className="gb-name">Glass</span>
          <span className="gb-sub">{onCode ? "Senior marked your code" : "Senior and you share this plane"}</span>
        </div>
        {shown && !onCode && (
          <div className="gb-ctl">
            {mark && <button className="gb-btn" onClick={() => setLayer("code")}>Show the marked code</button>}
            <button className="gb-btn" onClick={wipe}>Wipe</button>
            <button className="gb-btn" onClick={() => setUp(false)}>Lower</button>
          </div>
        )}
        <div className={`gb-board ${wiping ? "wiping" : ""} ${onCode ? "away" : ""}`}>
          <div className="gb-flow">
            {items.map((item, i) => (
              <figure key={item.id} ref={i === items.length - 1 ? newest : undefined} data-kind={item.kind}
                className={`gb-item ${item.id === freshId ? "fresh" : ""}`}>
                <span className="gb-order" aria-hidden="true">{i + 1}</span>
                <Drawing item={item} />
                {"caption" in item && item.caption && <figcaption className="gb-cap write-line" style={after(700)}>{item.caption}</figcaption>}
              </figure>
            ))}
          </div>
        </div>
      </div>

      {shown && onCode && mark && markBox && (
        <>
          <svg className="gb-marks" aria-hidden="true">
            <g className="gb-rough">
              <rect key={`${mark.from}-${mark.to}`} className="ink gb-mark" pathLength={1} x={markBox.x} y={markBox.y} width={markBox.w} height={markBox.h} rx={9} />
            </g>
          </svg>
          {/* The note sits under the marked lines, with its own way out, so nothing covers the rest of the app. */}
          <div className="gb-mark-note write" style={{ left: markBox.x + 4, top: markBox.y + markBox.h + 12, maxWidth: Math.max(260, Math.min(markBox.w, 560)) }}>
            <span>{mark.note || `Senior marked ${mark.from === mark.to ? `line ${mark.from}` : `lines ${mark.from} to ${mark.to}`} of your code.`}</span>
            <span className="gb-mark-actions">
              {items.length > 0 && <button className="gb-btn" onClick={() => setLayer("drawings")}>Back to the drawings ({items.length})</button>}
              <button className="gb-btn" onClick={() => { void invoke("clear_highlight", {}); if (items.length === 0) setUp(false); }}>Got it</button>
            </span>
          </div>
        </>
      )}

      {!shown && (items.length > 0 || mark !== null) && (
        <button className="gb-tab" onClick={() => raise(null)} aria-label={`Raise the glass: ${items.length} drawing${items.length === 1 ? "" : "s"} on it`}>
          <span className="gb-live" />Glass<span className="mono">{items.length}</span>
        </button>
      )}

      <div className="sr-only" aria-live="polite">{last ? describe(last) : ""}</div>
    </aside>
  );
}
