import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  ApiError, getMentorMessages, getProblem, getState, getTrace, getTrack, postRun, sendMessage,
  type Mode, type Problem, type ProblemDetail, type SessionState, type TraceNode,
} from "../api";
import { registerTool, type PageSnapshot } from "../agent/tools";
import { MODE_COLOR, useApp } from "../app-context";
import { entryPoint, runCode, runTests, type TestResult } from "../runner";
import { CodeEditor, RichText } from "../components/CodeEditor";
import { patternName } from "../labels";

type Bubble = { id: number; kind: "student" | "coach" | "mentor" | "notice"; text: string; meta?: string };

// What each rung allows; mirrors app/prompts/hint_coach.md.
const LADDER = [
  { level: 1, title: "Clarify the goal", sub: "Restate it, or an input you missed" },
  { level: 2, title: "Name the area", sub: "A data structure or technique, as a question" },
  { level: 3, title: "The key insight", sub: "A leading question" },
  { level: 4, title: "The approach", sub: "In plain words, no code" },
  { level: 5, title: "Walk an example", sub: "Step by step, still no code" },
];
const STARTERS = ["I don't know where to start.", "Is my approach fast enough?", "What am I missing?"];
type Loaded =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; problem: Problem; detail: ProblemDetail | null };

const MODES: { id: Mode; label: string; blurb: string }[] = [
  { id: "learn", label: "Learn", blurb: "Hint coach" },
  { id: "interview", label: "Interview", blurb: "Interviewer" },
  { id: "blitz", label: "Blitz", blurb: "Timed interview" },
  { id: "call", label: "Call", blurb: "Phone interviewer (typed here until a phone line is connected)" },
];
const DIFFICULTY_COLOR = { easy: "var(--seafoam)", medium: "var(--baltic)", hard: "var(--sky)" } as const;
const TRACK_IDS = ["blind_75", "neetcode_150"];

/** A problem with a stored statement comes from /problems; the rest are found in the tracks. */
async function loadProblem(problemId: string): Promise<{ problem: Problem; detail: ProblemDetail | null }> {
  try {
    const detail = await getProblem(problemId);
    return { problem: detail, detail };
  } catch (err) {
    if (!(err instanceof ApiError) || err.status !== 404) throw err;
  }
  for (const trackId of TRACK_IDS) {
    const found = (await getTrack(trackId)).problems.find((p) => p.id === problemId);
    if (found) return { problem: found, detail: null };
  }
  throw new Error(`Problem ${problemId} is not in the catalogue.`);
}

const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

export function Workspace() {
  const { page, go, mode, setMode, sessionId, problemId, openProblem } = useApp();
  const [loaded, setLoaded] = useState<Loaded>({ status: "loading" });
  const [code, setCode] = useState("");
  const [bubbles, setBubbles] = useState<Bubble[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [session, setSession] = useState<SessionState | null>(null);
  const [tests, setTests] = useState<TestResult[] | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [highlight, setHighlight] = useState<{ from: number; to: number; note: string } | null>(null);
  const nextId = useRef(0);
  const lastTraceId = useRef<string | null>(null);
  const chatEnd = useRef<HTMLDivElement>(null);

  const say = useCallback((kind: Bubble["kind"], text: string, meta?: string) => {
    setBubbles((list) => [...list, { id: nextId.current++, kind, text, meta }]);
  }, []);

  useEffect(() => {
    let current = true;
    setLoaded({ status: "loading" });
    setTests(null); setTestError(null); setHighlight(null);
    loadProblem(problemId).then(
      (found) => { if (current) { setLoaded({ status: "ready", ...found }); setCode(found.detail?.starter_code ?? ""); } },
      (err: Error) => current && setLoaded({ status: "error", message: err.message }),
    );
    return () => { current = false; };
  }, [problemId]);

  // A new session (mode change) starts a new conversation.
  useEffect(() => { setBubbles([]); setSession(null); }, [sessionId]);
  useEffect(() => { chatEnd.current?.scrollIntoView({ block: "nearest" }); }, [bubbles, busy]);

  const refresh = useCallback(async () => {
    if (sessionId) setSession(await getState(sessionId));
  }, [sessionId]);

  // Once a mentor has the session, show their replies in this chat as they arrive.
  const seenMentor = useRef(new Set<string>());
  useEffect(() => { seenMentor.current = new Set(); }, [sessionId]);
  useEffect(() => {
    if (!sessionId || !session?.escalated) return;
    const poll = () => getMentorMessages(sessionId).then((list) => {
      for (const m of list) {
        if (seenMentor.current.has(m.id)) continue;
        seenMentor.current.add(m.id);
        say("mentor", m.text, "Mentor · a person");
      }
    }, () => undefined);
    poll();
    const timer = setInterval(poll, 3000);
    return () => clearInterval(timer);
  }, [sessionId, session?.escalated, say]);

  // Blitz countdown: re-read the server's clock rather than keeping a second one here.
  useEffect(() => {
    if (mode !== "blitz" || !sessionId || !session?.problem_id) return;
    const timer = setInterval(() => { refresh().catch(() => undefined); }, 1000);
    return () => clearInterval(timer);
  }, [mode, sessionId, session?.problem_id, refresh]);

  const ask = useCallback(async (text: string) => {
    if (!sessionId) throw new Error("The session is not ready yet.");
    say("student", text, "You");
    setBusy("Reading your message…");
    let steps = 0;
    try {
      const final = await sendMessage(sessionId, { text, problem_id: problemId, code }, (event) => {
        steps += 1;
        setBusy(`${event.actor.replace(/_/g, " ")} · ${event.name.replace(/_/g, " ")} · step ${steps}`);
      });
      const who = final.mode === "learn" ? "Coach" : "Interviewer";
      say("coach", final.reply, final.mode === "learn" && final.hint_level > 0 ? `${who} · hint ${final.hint_level} of 5` : who);
      lastTraceId.current = final.trace_id;
      await refresh();
      return { reply: final.reply, hint_level: final.hint_level, escalated: final.escalated };
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      say("notice", `The coach could not answer: ${message}`);
      throw err;
    } finally {
      setBusy(null);
    }
  }, [sessionId, problemId, code, say, refresh]);

  const detail = loaded.status === "ready" ? loaded.detail : null;

  const run = useCallback(async () => {
    const entry = detail && entryPoint(detail.starter_code);
    if (!detail || !entry || !sessionId) throw new Error("This problem has no runnable tests yet.");
    setRunning(true); setTestError(null);
    try {
      const { results, runtimeMs } = await runTests(code, entry, detail.visible_tests);
      setTests(results);
      const failures = results.filter((r) => !r.passed).map((r) => ({ name: r.name, message: r.message }));
      const summary = { passed: results.length - failures.length, failed: failures.length, total: results.length };
      await postRun(sessionId, { problem_id: problemId, code, ...summary, failures, runtime_ms: runtimeMs });
      await refresh();
      return { ...summary, tests: results };
    } catch (err) {
      setTestError(err instanceof Error ? err.message : String(err));
      throw err;
    } finally {
      setRunning(false);
    }
  }, [detail, sessionId, code, problemId, refresh]);

  // Page tools: what an agent may do on this screen. See agent/tools.ts.
  useEffect(() => {
    const snapshot = (): PageSnapshot => ({
      page, mode,
      problem: loaded.status === "ready" ? loaded.problem : null,
      hintLevel: session?.hint_level ?? 0, failedRuns: session?.failed_runs ?? 0, escalated: session?.escalated ?? false,
      lastTestRun: tests ? { passed: tests.filter((t) => t.passed).length, failed: tests.filter((t) => !t.passed).length } : null,
    });
    const cleanups = [
      registerTool("get_page_state", snapshot),
      registerTool("navigate", ({ page: next }) => { go(next); return { page: next }; }),
      registerTool("set_mode", ({ mode: next }) => { setMode(next); return { mode: next }; }),
      registerTool("open_problem", ({ problem_id }) => { openProblem(problem_id); return { problem_id }; }),
      registerTool("ask_coach", ({ text }) => ask(text)),
      registerTool("run_tests", () => run()),
      registerTool("run_code", () => runCode(code)),
      registerTool("read_code", () => {
        const lines = code.split("\n");
        return { lines: lines.length, code: lines.map((line, i) => `${i + 1}: ${line}`).join("\n") };
      }),
      registerTool("read_problem", () => {
        if (loaded.status !== "ready") throw new Error("The problem has not loaded yet.");
        return { ...loaded.problem, statement: loaded.detail?.statement ?? null, visible_tests: loaded.detail?.visible_tests ?? [] };
      }),
      registerTool("read_conversation", () => ({
        messages: bubbles.slice(-8).map((b) => ({ from: b.kind === "notice" ? "system" : b.kind, text: b.text })),
      })),
      registerTool("explain_last_turn", async () => {
        if (!lastTraceId.current) throw new Error("The coach has not answered yet in this session.");
        const tree = await getTrace(lastTraceId.current);
        const flat: TraceNode[] = [];
        const walk = (node: TraceNode) => { flat.push(node); node.children.forEach(walk); };
        tree.roots.forEach(walk);
        const costs = flat.map((n) => n.event.cost_usd).filter((c): c is number => c !== null);
        return {
          total_ms: tree.roots[0]?.event.latency_ms ?? null,
          cost_usd: costs.length ? Number(costs.reduce((a, b) => a + b, 0).toFixed(6)) : null,
          steps: flat.slice(1).map(({ event: e }) => ({ actor: e.actor, step: e.name, decision: e.decision, reason: e.reason, model: e.model, ms: e.latency_ms })),
        };
      }),
      registerTool("search_problems", async ({ query }) => {
        const words = query.toLowerCase().split(/\s+/).filter(Boolean);
        const seen = new Map<string, Problem>();
        for (const trackId of TRACK_IDS) for (const p of (await getTrack(trackId)).problems) seen.set(p.id, p);
        const matches = [...seen.values()].filter((p) => words.every((w) => `${p.title} ${p.pattern}`.toLowerCase().includes(w)));
        return { matches: matches.slice(0, 8).map(({ id, title, difficulty, pattern }) => ({ id, title, difficulty, pattern })) };
      }),
      registerTool("highlight_lines", (range) => { setHighlight(range); return { from: range.from, to: range.to }; }),
      registerTool("clear_highlight", () => { setHighlight(null); return {}; }),
    ];
    return () => cleanups.forEach((off) => off());
  }, [page, mode, loaded, session, tests, code, bubbles, go, setMode, openProblem, ask, run]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    ask(text).catch(() => undefined);
  };

  const hintLevel = session?.hint_level ?? 0;
  const passed = tests?.filter((t) => t.passed).length ?? 0;
  const mastery = Object.entries(session?.mastery ?? {});

  return (
    <main className="page">
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "12px 20px" }}>
        <div role="group" aria-label="Mode" style={{ display: "flex", gap: 8 }}>
          {MODES.map((m) => (
            <button key={m.id} className={`filter ${mode === m.id ? "on" : ""}`} aria-pressed={mode === m.id}
              style={mode === m.id ? { borderColor: MODE_COLOR[m.id], color: MODE_COLOR[m.id] } : undefined}
              onClick={() => setMode(m.id)} title={m.blurb}>
              {m.label}
            </button>
          ))}
        </div>
        {mode === "blitz" && session?.countdown_seconds != null && (
          <span className="pill sky" aria-label="Time remaining">Blitz · {clock(session.countdown_seconds)} left</span>
        )}
        {session?.escalated && <span className="pill baltic">A mentor has this session</span>}
        <div aria-label="Pattern mastery" style={{ marginLeft: "auto", display: "flex", gap: 8, flexWrap: "wrap" }}>
          {mastery.length === 0
            ? <span className="dim" style={{ fontSize: 12 }}>Mastery appears after your first passing run</span>
            : mastery.map(([pattern, value]) => <span key={pattern} className="chip seafoam">{patternName(pattern)} {Math.round(value * 100)}%</span>)}
        </div>
      </div>

      <div className="row-wrap">
        <div style={{ flex: "2 1 560px", minWidth: 320, display: "flex", flexDirection: "column", gap: 18 }}>
          <section className="card" aria-label="Problem">
            {loaded.status === "loading" && <span className="muted">Loading the problem…</span>}
            {loaded.status === "error" && <div className="bubble notice" role="alert">Could not load the problem: {loaded.message}</div>}
            {loaded.status === "ready" && (
              <>
                <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10 }}>
                  <h1>{loaded.problem.title}</h1>
                  <span className="pill" style={{ color: DIFFICULTY_COLOR[loaded.problem.difficulty] }}>{loaded.problem.difficulty}</span>
                  <span className="chip" style={{ color: "var(--text-2)" }}>{patternName(loaded.problem.pattern)}</span>
                  <button className="btn-ghost" style={{ marginLeft: "auto", height: 36 }} onClick={() => go("tracks")}>Change problem</button>
                </div>
                <p className="statement">
                  {loaded.detail ? <RichText text={loaded.detail.statement} /> : "No statement is stored for this problem yet. The coach knows it by name: describe your approach and ask for help."}
                </p>
                {loaded.detail && loaded.detail.visible_tests.length > 0 && (
                  <div className="examples">
                    {loaded.detail.visible_tests.slice(0, 2).map((t) => (
                      <div key={t.name} className="example mono">
                        <span><span className="dim">input</span> {t.input}</span>
                        <span><span className="dim">output</span> {t.expected}</span>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </section>

          <section className="card" aria-label="Code editor" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <label className="label sr-only" htmlFor="code">Your code (Python)</label>
            <CodeEditor id="code" value={code} onChange={setCode} filename="solution.py"
              highlight={highlight} onDismissHighlight={() => setHighlight(null)} />
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12 }}>
              <button className="btn-primary" disabled={!detail || running || !sessionId} onClick={() => run().catch(() => undefined)}>
                {running ? "Running…" : "Run tests"}
              </button>
              {!detail && loaded.status === "ready" && <span className="dim" style={{ fontSize: 12 }}>No runnable tests for this problem yet</span>}
              {tests && (
                <span className={`pill ${passed === tests.length ? "seafoam" : "sky"}`}>
                  {passed === tests.length ? `Pass · ${passed} of ${tests.length}` : `Failing · ${passed} of ${tests.length} pass`}
                </span>
              )}
            </div>
            {testError && <div className="bubble notice" role="alert">The tests could not run: {testError}</div>}
            {tests && (
              <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
                {tests.map((t) => (
                  <li key={t.name} className="mono" style={{ fontSize: 12 }}>
                    <span className={t.passed ? "seafoam" : "sky"}>{t.passed ? "pass" : "fail"}</span> {t.name}
                    {!t.passed && <span className="muted"> — {t.message}</span>}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <section className="card" aria-label="Coach" style={{ flex: "1 1 380px", minWidth: 320, display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <h2>{mode === "learn" ? "Coach" : mode === "call" ? "Phone interviewer" : "Interviewer"}</h2>
            <span className="pill" style={{ color: MODE_COLOR[mode] }}>{MODES.find((m) => m.id === mode)!.label}</span>
            <button className="btn-ghost" style={{ marginLeft: "auto", height: 36 }} onClick={() => go("inspector")}>See why</button>
          </div>

          {mode === "learn" && (
            <ol className="ladder" aria-label={`Hint ladder: ${hintLevel === 0 ? "no hints used" : `hint ${hintLevel} of 5`}`}>
              {LADDER.map((rung) => {
                const state = rung.level < hintLevel ? "used" : rung.level === hintLevel ? "now" : rung.level === hintLevel + 1 ? "ready" : "locked";
                return (
                  <li key={rung.level} className={`ladder-rung ${state}`}>
                    <span className={`rung ${state}`}>{rung.level}</span>
                    <span className="ladder-text"><span className="ladder-title">{rung.title}</span><span className="ladder-sub">{rung.sub}</span></span>
                    <span className="ladder-tag">{state === "now" ? "Now" : state === "used" ? "Used" : state === "ready" ? "Next" : "Locked"}</span>
                  </li>
                );
              })}
              <li className={`ladder-rung mentor ${session?.escalated ? "now" : ""}`}>
                <span className="rung mentor">M</span>
                <span className="ladder-text"><span className="ladder-title">Mentor review</span><span className="ladder-sub">A person steps in if you are still stuck</span></span>
                <span className="ladder-tag">{session?.escalated ? "Joined" : "Standby"}</span>
              </li>
            </ol>
          )}

          <div aria-live="polite" style={{ display: "flex", flexDirection: "column", gap: 8, minHeight: 240, maxHeight: 460, overflowY: "auto" }}>
            {bubbles.length === 0 && (
              <div className="chat-empty">
                <p className="muted">
                  {mode === "learn" ? "Say what you have tried, or ask for a hint. Hints never include code." : "Explain your approach and its cost before you write code."}
                </p>
                <div className="starters">
                  {STARTERS.map((text) => (
                    <button key={text} type="button" className="starter" disabled={!sessionId || !!busy} onClick={() => ask(text).catch(() => undefined)}>{text}</button>
                  ))}
                </div>
              </div>
            )}
            {bubbles.map((b) => (
              <div key={b.id} className={`bubble ${b.kind}`} role={b.kind === "notice" ? "alert" : undefined}>
                {b.meta && <span className="bubble-meta">{b.meta}</span>}
                {b.text}
              </div>
            ))}
            {busy && <div className="bubble coach thinking" role="status"><span className="dots" aria-hidden="true"><i /><i /><i /></span><span className="mono">{busy}</span></div>}
            <div ref={chatEnd} />
          </div>

          <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <label className="label" htmlFor="message">Message</label>
            <textarea id="message" className="textarea" rows={2} value={draft} placeholder="I'm stuck on…"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) submit(e); }} />
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button type="submit" className="btn-primary" disabled={!sessionId || !!busy || !draft.trim()}>Send</button>
              {mode === "learn" && (
                <button type="button" className="btn-ghost" disabled={!sessionId || !!busy}
                  onClick={() => ask("I'm stuck. Can I have a hint?").catch(() => undefined)}>
                  Ask for a hint
                </button>
              )}
            </div>
          </form>
          <div className="session-bar mono" aria-label="Session">
            <span>failed runs <b>{session?.failed_runs ?? 0}</b></span>
            <span>hints <b>{hintLevel}/5</b></span>
            <span>mentor <b>{session?.escalated ? "on" : "off"}</b></span>
            <button className="linklike" onClick={() => go("inspector")}>Open the trace</button>
          </div>
        </section>
      </div>
    </main>
  );
}
