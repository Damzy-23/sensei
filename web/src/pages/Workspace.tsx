import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  ApiError, getProblem, getState, getTrack, postRun, sendMessage,
  type Mode, type Problem, type ProblemDetail, type SessionState,
} from "../api";
import { registerTool, type PageSnapshot } from "../agent/tools";
import { MODE_COLOR, useApp } from "../app-context";
import { entryPoint, runTests, type TestResult } from "../runner";

type Bubble = { id: number; kind: "student" | "coach" | "notice"; text: string };
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
  const chatEnd = useRef<HTMLDivElement>(null);

  const say = useCallback((kind: Bubble["kind"], text: string) => {
    setBubbles((list) => [...list, { id: nextId.current++, kind, text }]);
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

  // Blitz countdown: re-read the server's clock rather than keeping a second one here.
  useEffect(() => {
    if (mode !== "blitz" || !sessionId || !session?.problem_id) return;
    const timer = setInterval(() => { refresh().catch(() => undefined); }, 1000);
    return () => clearInterval(timer);
  }, [mode, sessionId, session?.problem_id, refresh]);

  const ask = useCallback(async (text: string) => {
    if (!sessionId) throw new Error("The session is not ready yet.");
    say("student", text);
    setBusy("Reading your message…");
    let steps = 0;
    try {
      const final = await sendMessage(sessionId, { text, problem_id: problemId, code }, (event) => {
        steps += 1;
        setBusy(`${event.actor}: ${event.name} (${steps} steps so far)`);
      });
      say("coach", final.reply);
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
      return summary;
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
      registerTool("highlight_lines", (range) => { setHighlight(range); return { from: range.from, to: range.to }; }),
      registerTool("clear_highlight", () => { setHighlight(null); return {}; }),
    ];
    return () => cleanups.forEach((off) => off());
  }, [page, mode, loaded, session, tests, go, setMode, openProblem, ask, run]);

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
            : mastery.map(([pattern, value]) => <span key={pattern} className="chip seafoam">{pattern} {Math.round(value * 100)}%</span>)}
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
                  <span className="chip" style={{ color: "var(--text-2)" }}>{loaded.problem.pattern}</span>
                  <button className="btn-ghost" style={{ marginLeft: "auto", height: 36 }} onClick={() => go("tracks")}>Change problem</button>
                </div>
                <p className="muted" style={{ margin: "12px 0 0" }}>
                  {loaded.detail?.statement ?? "No statement is stored for this problem yet. The coach knows it by name: describe your approach and ask for help."}
                </p>
              </>
            )}
          </section>

          <section className="card" aria-label="Code editor" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <label className="label" htmlFor="code">Your code (Python)</label>
            <textarea id="code" className="textarea code" spellCheck={false} value={code} onChange={(e) => setCode(e.target.value)} />
            {highlight && (
              <div className="bubble notice" style={{ display: "flex", gap: 12, alignItems: "center" }}>
                <span>Lines {highlight.from}–{highlight.to}: {highlight.note}</span>
                <button className="btn-ghost" style={{ height: 32, marginLeft: "auto" }} onClick={() => setHighlight(null)}>Dismiss</button>
              </div>
            )}
            <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12 }}>
              <button className="btn-ghost" disabled={!detail || running || !sessionId} onClick={() => run().catch(() => undefined)}>
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
            <div aria-label="Hint ladder" style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
              {[1, 2, 3, 4, 5].map((level) => (
                <div key={level} title={`Hint level ${level}`}
                  className={`rung ${level < hintLevel ? "used" : level === hintLevel ? "now" : level === hintLevel + 1 ? "ready" : ""}`}>
                  {level}
                </div>
              ))}
              <div className="rung mentor" title="Mentor: a person steps in when you are still stuck after level 5">M</div>
              <span className="dim" style={{ fontSize: 12 }}>{hintLevel === 0 ? "No hints used" : `Hint ${hintLevel} of 5`}</span>
            </div>
          )}

          <div aria-live="polite" style={{ display: "flex", flexDirection: "column", gap: 8, minHeight: 240, maxHeight: 460, overflowY: "auto" }}>
            {bubbles.length === 0 && (
              <span className="muted" style={{ fontSize: 13 }}>
                {mode === "learn" ? "Say what you have tried, or ask for a hint. Hints never include code." : "Explain your approach and its cost before you write code."}
              </span>
            )}
            {bubbles.map((b) => <div key={b.id} className={`bubble ${b.kind}`} role={b.kind === "notice" ? "alert" : undefined}>{b.text}</div>)}
            {busy && <div className="bubble coach dim mono" style={{ fontSize: 12 }}>{busy}</div>}
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
        </section>
      </div>
    </main>
  );
}
