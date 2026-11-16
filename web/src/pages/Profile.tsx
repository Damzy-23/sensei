import { useEffect, useRef, useState, type FormEvent } from "react";
import { answerProfile, recommendRoles, startProfile, type ProfileResult, type Source } from "../api";
import { useApp } from "../app-context";

interface Line { id: string; kind: "coach" | "student"; text: string }

const STEPS = ["Turning your answers into a search", "Searching the web with Linkup", "Ranking roles against what you said"];
const MIN_ANSWERS = 3;

function hostOf(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return url; }
}

function SourceLinks({ sources }: { sources: Source[] }) {
  if (!sources.length) return null;
  return (
    <ul className="source-list">
      {sources.map((s) => (
        <li key={s.url}>
          <a href={s.url} target="_blank" rel="noreferrer noopener">
            <span className="source-title">{s.title}</span>
            <span className="dim mono source-host">{hostOf(s.url)}</span>
          </a>
        </li>
      ))}
    </ul>
  );
}

export function Profile() {
  const { sessionId, go } = useApp();
  const [profileId, setProfileId] = useState<string | null>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [step, setStep] = useState(0);
  const [total, setTotal] = useState(6);
  const [question, setQuestion] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState<"start" | "answer" | "search" | null>(null);
  const [searchStep, setSearchStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ProfileResult | null>(null);
  const chatEnd = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { chatEnd.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [lines, busy]);
  useEffect(() => {
    if (busy !== "search") return;
    setSearchStep(0);
    const timer = window.setInterval(() => setSearchStep((s) => Math.min(s + 1, STEPS.length - 1)), 2600);
    return () => window.clearInterval(timer);
  }, [busy]);

  const say = (kind: Line["kind"], text: string) => setLines((l) => [...l, { id: `${kind}-${l.length}`, kind, text }]);

  const start = async () => {
    setBusy("start"); setError(null); setResult(null); setLines([]);
    try {
      const turn = await startProfile(sessionId);
      setProfileId(turn.profile_id); setStep(turn.step); setTotal(turn.total); setQuestion(turn.question);
      if (turn.question) say("coach", turn.question);
      window.setTimeout(() => input.current?.focus(), 50);
    } catch (err) {
      setError(`The career agent could not start: ${(err as Error).message}`);
    } finally { setBusy(null); }
  };

  const findRoles = async (id: string) => {
    setBusy("search"); setError(null);
    try {
      setResult(await recommendRoles(id, sessionId));
    } catch (err) {
      setError(`The search did not finish: ${(err as Error).message}. Try again.`);
    } finally { setBusy(null); }
  };

  const send = async (e: FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    if (!profileId || !text || busy) return;
    say("student", text); setDraft(""); setBusy("answer"); setError(null);
    try {
      const turn = await answerProfile(profileId, text, sessionId);
      setStep(turn.step); setQuestion(turn.question);
      if (turn.question) say("coach", turn.question);
      setBusy(null);
      if (turn.done) {
        say("coach", "Thanks. I'm searching the web for the roles that fit you best.");
        await findRoles(profileId);
      } else {
        input.current?.focus();
      }
    } catch (err) {
      setError(`Your answer did not send: ${(err as Error).message}`);
      setBusy(null);
    }
  };

  const done = step >= total;
  const canFinishEarly = !!profileId && step >= MIN_ANSWERS && !done && !busy && !result;

  return (
    <main className="page profile">
      <header className="profile-head">
        <div>
          <span className="label">Career agent · Linkup search</span>
          <h1>Find the roles that fit you</h1>
          <p className="muted">Six short questions. Then the agent searches the web and recommends roles, with sources, and what to practise here.</p>
        </div>
        {profileId && (
          <button className="btn-ghost" onClick={() => go("inspector")}>See the agent's steps</button>
        )}
      </header>

      <div className="profile-grid">
        <section className="card profile-chat" aria-label="Interview">
          {!profileId ? (
            <div className="profile-intro">
              <ol className="profile-topics">
                {["Experience", "Languages", "Interests", "What you enjoy", "Level", "Location"].map((t, i) => (
                  <li key={t}><span className="rung">{i + 1}</span>{t}</li>
                ))}
              </ol>
              <button className="btn-primary" onClick={start} disabled={busy === "start"}>
                {busy === "start" ? "Starting…" : "Start the interview"}
              </button>
            </div>
          ) : (
            <>
              <div className="profile-progress">
                <span className="label">{done ? "Interview complete" : `Question ${Math.min(step + 1, total)} of ${total}`}</span>
                <div className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={step} aria-label="Interview progress">
                  <span style={{ width: `${(step / total) * 100}%` }} />
                </div>
              </div>
              <div className="chat-log" role="log" aria-label="Interview transcript" aria-live="polite">
                {lines.map((l) => <div key={l.id} className={`bubble ${l.kind}`}>{l.text}</div>)}
                {busy === "answer" && <div className="bubble coach dim mono" style={{ fontSize: 12 }}>career_agent is thinking…</div>}
                <div ref={chatEnd} />
              </div>
              {!done && question && (
                <form onSubmit={send} className="chat-form">
                  <label className="label" htmlFor="profile-answer">Your answer</label>
                  <textarea
                    id="profile-answer" ref={input} className="textarea" rows={2} value={draft} maxLength={2000}
                    placeholder="A sentence or two is plenty"
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(e); } }}
                  />
                  <div className="row-wrap" style={{ gap: 10 }}>
                    <button type="submit" className="btn-primary" disabled={!draft.trim() || !!busy}>Send</button>
                    {canFinishEarly && (
                      <button type="button" className="btn-ghost" onClick={() => findRoles(profileId)}>Find my roles now</button>
                    )}
                  </div>
                </form>
              )}
              {done && !busy && (
                <div className="row-wrap" style={{ gap: 10 }}>
                  {!result && <button className="btn-primary" onClick={() => findRoles(profileId)}>Find my roles</button>}
                  <button className="btn-ghost" data-agent="confirm" onClick={start}>Start again</button>
                </div>
              )}
            </>
          )}
          {error && <div className="bubble notice" role="alert">{error}</div>}
        </section>

        <section className="profile-results" aria-label="Recommended roles" aria-busy={busy === "search"}>
          {busy === "search" && (
            <div className="card" role="status">
              <span className="label">Working</span>
              <ol className="search-steps">
                {STEPS.map((s, i) => (
                  <li key={s} className={i < searchStep ? "done" : i === searchStep ? "now" : ""}>
                    <span className="step-dot" aria-hidden="true" />{s}
                  </li>
                ))}
              </ol>
              <div className="skeleton" /><div className="skeleton short" /><div className="skeleton" />
            </div>
          )}

          {!busy && !result && (
            <div className="card profile-empty">
              <span className="label">Your roles</span>
              <p className="muted">Recommendations appear here: each role with why it fits you, the skills to strengthen, and the pages the agent read.</p>
            </div>
          )}

          {result && busy !== "search" && (
            <>
              <div className="card">
                <span className="label">About you</span>
                <p className="profile-summary">{result.summary}</p>
              </div>
              <ol className="role-list">
                {result.roles.map((role, i) => (
                  <li key={role.title} className="card role-card" style={{ animationDelay: `${i * 80}ms` }}>
                    <div className="role-head">
                      <span className="rank mono">{i + 1}</span>
                      <h2>{role.title}</h2>
                    </div>
                    <p>{role.fit}</p>
                    {role.skills_to_strengthen.length > 0 && (
                      <div>
                        <span className="label">Strengthen</span>
                        <div className="chips">
                          {role.skills_to_strengthen.map((s) => <span key={s} className="chip baltic">{s}</span>)}
                        </div>
                      </div>
                    )}
                    <SourceLinks sources={role.sources} />
                  </li>
                ))}
              </ol>
              <div className="card practice-card">
                <span className="label">Practise in Senior · {result.practice.track_title}</span>
                {result.practice.why && <p className="muted">{result.practice.why}</p>}
                <div className="chips">
                  {result.practice.patterns.map((p) => <span key={p} className="chip seafoam">{p}</span>)}
                </div>
                <button className="btn-primary" onClick={() => go("tracks")}>Open the learn path</button>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
