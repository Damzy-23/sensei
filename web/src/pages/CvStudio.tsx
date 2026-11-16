import { useEffect, useRef, useState, type FormEvent } from "react";
import { API_URL, authHeaders, idTag } from "../api";

// Mirrors app/api/cv.py. Scores are computed by rule on the server; this page only shows them.
interface Check { id: string; label: string; points: number; max: number; detail: string }
interface BulletScore { text: string; score: number; max: number; checks: Check[] }
interface Role { role: string; company: string; dates: string; bullets: string[]; bullet_scores: BulletScore[] }
interface Requirement { term: string; importance: string }
/** `score` is null when the job could not be read: unknown, not zero. */
interface Fit { score: number | null; matched: Requirement[]; missing: Requirement[]; note: string }
interface SuggestedLine { gap: string; draft: string; question: string }
interface TailoredCv {
  name: string; headline: string; summary: string; skills: string[];
  experience: Role[]; education: string[]; gaps: string[];
  suggested_lines: SuggestedLine[]; fit: Fit; job_terms: string[]; role_title: string; company: string; trace_id: string;
}
interface Source { title: string; url: string; excerpt: string }
interface Search { available: boolean; reason: string; answer: string; sources: Source[] }
interface Research { linkup: Search; exa: Search; trace_id: string }

type Result =
  | { status: "empty" }
  | { status: "busy" }
  | { status: "error"; message: string }
  | { status: "ready" };
type ResearchState =
  | { status: "idle" }
  | { status: "busy" }
  | { status: "error"; message: string }
  | { status: "ready"; data: Research };

const MIN_JOB = 20;
const MIN_CV = 50;
const INK = "#16242d";
const ACCENT = "#33658A";
const RESCORE_DELAY_MS = 400;
const textLength = (value: string) => value.replace(/\s/g, "").length;
/** A draft still has a [blank] only the candidate can fill. It cannot go on the CV like that. */
const hasBlank = (text: string) => /\[[^\]]+\]/.test(text);

const PRINT_CSS = `
.cv-paper { background: #fff; color: ${INK}; max-width: 794px; width: 100%; padding: 48px; border-radius: 6px;
  box-shadow: 0 40px 80px -30px rgba(0, 0, 0, 0.8); font: 400 14px/1.5 Inter, system-ui, sans-serif; }
.cv-paper h3 { font: 700 11px Inter, sans-serif; letter-spacing: 1.2px; text-transform: uppercase; color: ${ACCENT}; margin: 18px 0 6px; }
.cv-paper ul { margin: 4px 0 0; padding-left: 18px; }
.cv-tools { max-width: 794px; display: flex; flex-direction: column; gap: 14px; }
.fit-number { font: 700 44px/1 var(--display); letter-spacing: -1.5px; }
.bullet-row { display: grid; grid-template-columns: 1fr auto; gap: 8px 10px; align-items: start; padding: 10px 0; border-top: 1px solid var(--line); }
.bullet-score { font: 600 12px var(--mono); padding: 4px 8px; border-radius: 999px; border: 1px solid currentColor; white-space: nowrap; }
.check-list { grid-column: 1 / -1; margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: var(--text-2); }
@media print {
  body * { visibility: hidden }
  .cv-paper, .cv-paper * { visibility: visible }
  .cv-paper { position: absolute; left: 0; top: 0; width: 100%; box-shadow: none }
}`;

/** The server's `detail` is text for most errors and `{detail, trace_id}` when the model failed. */
async function readError(response: Response): Promise<string> {
  const body: unknown = await response.json().catch(() => null);
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d: { msg?: string }) => d.msg ?? "").filter(Boolean).join(" ");
  if (detail && typeof detail === "object") {
    const inner = detail as { detail?: string; trace_id?: string };
    return `${inner.detail ?? "The CV writer failed."}${inner.trace_id ? ` (trace ${idTag(inner.trace_id)})` : ""}`;
  }
  return `The server answered ${response.status}.`;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST", headers: { "content-type": "application/json", ...(await authHeaders()) }, body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as T;
}

const scoreBullets = (bullets: string[], jobTerms: string[]) =>
  postJson<{ scores: BulletScore[] }>("/cv/score", { bullets, job_terms: jobTerms }).then((r) => r.scores);

/** Colour is a second signal only: the number is always printed. */
const scoreClass = (s: BulletScore) => (s.score / s.max >= 0.8 ? "seafoam" : s.score / s.max >= 0.5 ? "baltic" : "sky");

function Paper({ cv }: { cv: TailoredCv }) {
  return (
    <article className="cv-paper" aria-label="Tailored CV">
      <div style={{ fontSize: 30, fontWeight: 700, letterSpacing: "-0.5px" }}>{cv.name || "Name not found in your CV"}</div>
      {cv.headline && <div style={{ marginTop: 2, fontSize: 15, fontWeight: 600, color: ACCENT }}>{cv.headline}</div>}
      <div style={{ height: 2, background: ACCENT, margin: "16px 0 4px" }} />
      {cv.summary && (<><h3>Summary</h3><div>{cv.summary}</div></>)}
      {cv.skills.length > 0 && (<><h3>Skills</h3><div>{cv.skills.join(" · ")}</div></>)}
      {cv.experience.length > 0 && (
        <>
          <h3>Experience</h3>
          {cv.experience.map((job, index) => (
            <div key={index} style={{ marginBottom: 12 }}>
              <div style={{ fontWeight: 700 }}>{[job.role, job.company].filter(Boolean).join(", ")}</div>
              {job.dates && <div style={{ fontSize: 12, color: "#5a6070" }}>{job.dates}</div>}
              {job.bullets.length > 0 && <ul>{job.bullets.map((bullet, i) => <li key={i}>{bullet}</li>)}</ul>}
            </div>
          ))}
        </>
      )}
      {cv.education.length > 0 && (<><h3>Education</h3><ul>{cv.education.map((entry, i) => <li key={i}>{entry}</li>)}</ul></>)}
    </article>
  );
}

function FitCard({ fit }: { fit: Fit }) {
  return (
    <section className="card" aria-label="Job fit">
      <div className="label">Job fit</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap", marginTop: 6 }}>
        <span className="fit-number">{fit.score === null ? "No score" : `${fit.score}%`}</span>
        <span className="muted" style={{ fontSize: 13, flex: "1 1 260px" }}>{fit.note}</span>
      </div>
      {fit.matched.length + fit.missing.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}>
          {fit.matched.map((r) => <span key={r.term} className="chip seafoam">On your CV: {r.term}</span>)}
          {fit.missing.map((r) => (
            <span key={r.term} className="chip sky">Missing: {r.term}{r.importance === "nice" ? " (nice to have)" : ""}</span>
          ))}
        </div>
      )}
    </section>
  );
}

function BulletRow({ score, onChange, onRemove }: { score: BulletScore; onChange: (text: string) => void; onRemove: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="bullet-row">
      <textarea className="textarea" rows={2} aria-label="Bullet text" value={score.text} onChange={(e) => onChange(e.target.value)} />
      <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" }}>
        <span className={`bullet-score ${scoreClass(score)}`} aria-label={`Score ${score.score} out of ${score.max}`}>{score.score} / {score.max}</span>
        <button type="button" className="btn-ghost" style={{ height: 28, padding: "0 10px", fontSize: 12 }} aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Hide why" : "Why"}
        </button>
        <button type="button" className="btn-ghost" style={{ height: 28, padding: "0 10px", fontSize: 12 }} onClick={onRemove}>Remove</button>
      </div>
      {open && (
        <ul className="check-list">
          {score.checks.map((c) => (
            <li key={c.id}><span className="mono">{c.points}/{c.max}</span> <strong>{c.label}.</strong> {c.detail}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ResearchCard({ roleTitle, company }: { roleTitle: string; company: string }) {
  const [role, setRole] = useState(roleTitle);
  // Blank by default: a short or little-known company name can pull the search onto an unrelated site.
  const [employer, setEmployer] = useState("");
  const [state, setState] = useState<ResearchState>({ status: "idle" });

  const run = async (event: FormEvent) => {
    event.preventDefault();
    setState({ status: "busy" });
    try {
      setState({ status: "ready", data: await postJson<Research>("/cv/research", { role_title: role, company: employer }) });
    } catch (err) {
      setState({ status: "error", message: err instanceof Error ? err.message : String(err) });
    }
  };

  const sources = (list: Source[]) => (
    <ul style={{ margin: "6px 0 0", paddingLeft: 18, fontSize: 13 }}>
      {list.map((s) => (
        <li key={s.url}>
          <a href={s.url} target="_blank" rel="noreferrer" style={{ color: "var(--baltic)" }}>{s.title}</a>
          {s.excerpt && <div className="dim" style={{ fontSize: 12 }}>{s.excerpt}</div>}
        </li>
      ))}
    </ul>
  );

  return (
    <section className="card" aria-label="Role research">
      <div className="label">Research this role</div>
      <form onSubmit={run} style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end", marginTop: 8 }}>
        <div style={{ flex: "1 1 200px" }}>
          <label className="dim" style={{ fontSize: 12 }} htmlFor="research-role">Role</label>
          <input id="research-role" className="input" value={role} onChange={(e) => setRole(e.target.value)} />
        </div>
        <div style={{ flex: "1 1 160px" }}>
          <label className="dim" style={{ fontSize: 12 }} htmlFor="research-company">Company (optional)</label>
          <input id="research-company" className="input" value={employer} placeholder={company ? `e.g. ${company}` : ""} onChange={(e) => setEmployer(e.target.value)} />
        </div>
        <button type="submit" className="btn-ghost" disabled={state.status === "busy" || role.trim().length < 2}>
          {state.status === "busy" ? "Searching…" : "Search the web"}
        </button>
      </form>
      {state.status === "error" && <div className="bubble notice" role="alert" style={{ marginTop: 10 }}>The search could not run: {state.message}</div>}
      {state.status === "ready" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 12 }}>
          <div>
            <strong style={{ fontSize: 13 }}>What they look for · Linkup</strong>
            {state.data.linkup.available
              ? (<><div style={{ fontSize: 13, lineHeight: "20px", marginTop: 4, whiteSpace: "pre-wrap" }}>{state.data.linkup.answer || "The search ran and returned no answer."}</div>{sources(state.data.linkup.sources)}</>)
              : <div className="dim" style={{ fontSize: 13, marginTop: 4 }}>Did not run: {state.data.linkup.reason}</div>}
          </div>
          <div>
            <strong style={{ fontSize: 13 }}>Comparable postings · Exa</strong>
            {state.data.exa.available
              ? (state.data.exa.sources.length ? sources(state.data.exa.sources) : <div className="dim" style={{ fontSize: 13, marginTop: 4 }}>The search ran and found no postings.</div>)
              : <div className="dim" style={{ fontSize: 13, marginTop: 4 }}>Did not run: {state.data.exa.reason}</div>}
          </div>
        </div>
      )}
    </section>
  );
}

export function CvStudio() {
  const [job, setJob] = useState("");
  const [cvText, setCvText] = useState("");
  const [result, setResult] = useState<Result>({ status: "empty" });
  const [cv, setCv] = useState<TailoredCv | null>(null);
  const [newLine, setNewLine] = useState<{ role: number; text: string; score: BulletScore | null }>({ role: 0, text: "", score: null });
  const [scoreError, setScoreError] = useState<string | null>(null);
  const rescoreTimer = useRef<number | undefined>(undefined);

  const busy = result.status === "busy";
  const tooShort = textLength(job) < MIN_JOB || textLength(cvText) < MIN_CV;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || tooShort) return;
    setResult({ status: "busy" });
    try {
      const tailored = await postJson<TailoredCv>("/cv/tailor", { job_description: job, cv_text: cvText });
      setCv(tailored);
      setNewLine({ role: 0, text: "", score: null });
      setResult({ status: "ready" });
    } catch (err) {
      setResult({ status: "error", message: err instanceof Error ? err.message : String(err) });
    }
  };

  /** Edit one bullet: the text changes at once, and its score follows shortly after the typing stops. */
  const editBullet = (roleIndex: number, bulletIndex: number, text: string) => {
    if (!cv) return;
    const experience = cv.experience.map((role, r) => r !== roleIndex ? role : {
      ...role,
      bullets: role.bullets.map((b, i) => (i === bulletIndex ? text : b)),
      bullet_scores: role.bullet_scores.map((s, i) => (i === bulletIndex ? { ...s, text } : s)),
    });
    setCv({ ...cv, experience });
    window.clearTimeout(rescoreTimer.current);
    rescoreTimer.current = window.setTimeout(() => {
      scoreBullets([text], cv.job_terms).then(
        ([fresh]) => {
          setScoreError(null);
          setCv((current) => current && {
            ...current,
            experience: current.experience.map((role, r) => r !== roleIndex ? role : {
              ...role, bullet_scores: role.bullet_scores.map((s, i) => (i === bulletIndex && s.text === fresh.text ? fresh : s)),
            }),
          });
        },
        (err: Error) => setScoreError(err.message),
      );
    }, RESCORE_DELAY_MS);
  };

  const removeBullet = (roleIndex: number, bulletIndex: number) => {
    if (!cv) return;
    setCv({
      ...cv,
      experience: cv.experience.map((role, r) => r !== roleIndex ? role : {
        ...role, bullets: role.bullets.filter((_, i) => i !== bulletIndex), bullet_scores: role.bullet_scores.filter((_, i) => i !== bulletIndex),
      }),
    });
  };

  // Score the line being written as the candidate types.
  const jobTerms = cv?.job_terms;
  useEffect(() => {
    const text = newLine.text.trim();
    if (!jobTerms || !text) return;
    const timer = window.setTimeout(() => {
      scoreBullets([text], jobTerms).then(
        ([fresh]) => { setScoreError(null); setNewLine((line) => (line.text.trim() === fresh.text ? { ...line, score: fresh } : line)); },
        (err: Error) => setScoreError(err.message),
      );
    }, RESCORE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [newLine.text, jobTerms]);

  const addLine = () => {
    const text = newLine.text.trim();
    if (!cv || !text || hasBlank(text) || !newLine.score) return;
    const score = newLine.score;
    setCv({
      ...cv,
      experience: cv.experience.map((role, r) => r !== newLine.role ? role : {
        ...role, bullets: [...role.bullets, text], bullet_scores: [...role.bullet_scores, { ...score, text }],
      }),
    });
    setNewLine({ role: newLine.role, text: "", score: null });
  };

  const draftText = newLine.text.trim();
  const blankLeft = hasBlank(draftText);

  return (
    <main className="page">
      <style>{PRINT_CSS}</style>
      <div>
        <div className="label">CV studio</div>
        <h1 style={{ marginTop: 4 }}>Job description to tailored CV</h1>
        <p className="muted" style={{ margin: "6px 0 0" }}>Senior reorders and rewords what your CV already says, scores every line, and shows how well you fit the job. It never invents experience, so gaps stay gaps.</p>
      </div>

      <div className="row-wrap">
        <form className="card" aria-label="Inputs" onSubmit={submit}
          style={{ flex: "1 1 360px", maxWidth: 480, minWidth: 290, display: "flex", flexDirection: "column", gap: 10 }}>
          <label className="label" htmlFor="cv-job">Job description</label>
          <textarea id="cv-job" className="textarea" rows={9} value={job} onChange={(e) => setJob(e.target.value)} placeholder="Paste the job description" />
          <span className="dim" style={{ fontSize: 12 }}>At least {MIN_JOB} characters.</span>
          <label className="label" htmlFor="cv-text" style={{ marginTop: 8 }}>Your CV</label>
          <textarea id="cv-text" className="textarea" rows={12} value={cvText} onChange={(e) => setCvText(e.target.value)} placeholder="Paste your CV as text" />
          <span className="dim" style={{ fontSize: 12 }}>At least {MIN_CV} characters. Only what is written here is used.</span>
          <button type="submit" className="btn-primary" disabled={busy || tooShort} style={{ marginTop: 8 }}>
            {busy ? "Tailoring…" : "Tailor my CV"}
          </button>
        </form>

        <section aria-label="CV preview" aria-live="polite" style={{ flex: "2 1 520px", minWidth: 320, display: "flex", flexDirection: "column", gap: 14 }}>
          {result.status === "empty" && (
            <div className="card empty-steps">
              <div className="label">How it works</div>
              <ol>
                <li><span className="step-no">1</span><span><b>Paste the job.</b> The agent pulls out what the role asks for, in its own words.</span></li>
                <li><span className="step-no">2</span><span><b>Paste your CV.</b> Only what you wrote is used. Nothing is invented, so a gap stays a gap.</span></li>
                <li><span className="step-no">3</span><span><b>Get a tailored CV with scores.</b> A job-fit score, a score and reasons for every line, and lines you can add yourself.</span></li>
              </ol>
            </div>
          )}
          {result.status === "busy" && (
            <div className="card thinking-card" role="status"><span className="dots" aria-hidden="true"><i /><i /><i /></span>Reading the job and your CV. This takes a few seconds…</div>
          )}
          {result.status === "error" && <div className="bubble notice" role="alert">The CV could not be tailored: {result.message}</div>}
          {result.status === "ready" && cv && (
            <>
              <div className="cv-tools"><FitCard fit={cv.fit} /></div>
              <Paper cv={cv} />
              <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                <button className="btn-primary" onClick={() => window.print()}>Download PDF</button>
                <span className="dim" style={{ fontSize: 12 }}>Opens the print dialog: choose “Save as PDF”. Trace {idTag(cv.trace_id)}</span>
              </div>

              <div className="cv-tools">
                <section className="card" aria-label="Line scores">
                  <div className="label">Every line, scored</div>
                  <p className="muted" style={{ margin: "6px 0 4px", fontSize: 13 }}>
                    Each line is scored by fixed rules: an action verb, a measurable result, the job's own terms, length, and no filler. Edit a line and its score updates. Press “Why” to see what earned each point.
                  </p>
                  {scoreError && <div className="bubble notice" role="alert">A line could not be re-scored: {scoreError}</div>}
                  {cv.experience.length === 0 && <div className="dim" style={{ fontSize: 13 }}>No experience entries were found in your CV, so there are no lines to score.</div>}
                  {cv.experience.map((role, r) => (
                    <div key={r} style={{ marginTop: 10 }}>
                      <strong style={{ fontSize: 13 }}>{[role.role, role.company].filter(Boolean).join(", ") || `Role ${r + 1}`}</strong>
                      {role.bullet_scores.map((score, i) => (
                        <BulletRow key={i} score={score} onChange={(text) => editBullet(r, i, text)} onRemove={() => removeBullet(r, i)} />
                      ))}
                    </div>
                  ))}
                </section>

                {cv.experience.length > 0 && (
                  <section className="card" aria-label="Add a line">
                    <div className="label">Add a line</div>
                    <p className="muted" style={{ margin: "6px 0 8px", fontSize: 13 }}>Write something you really did. It is scored as you type, and only you can add it.</p>
                    {cv.suggested_lines.length > 0 && (
                      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 12 }}>
                        <span className="dim" style={{ fontSize: 12 }}>Starting points for your gaps. Each has [blanks] only you can fill:</span>
                        {cv.suggested_lines.map((line, i) => (
                          <div key={i} className="panel-note">
                            <div><span className="sky" style={{ fontWeight: 600 }}>{line.gap}</span>{line.question && <span className="dim"> · {line.question}</span>}</div>
                            <div className="mono" style={{ fontSize: 12, margin: "4px 0 6px" }}>{line.draft}</div>
                            <button type="button" className="btn-ghost" style={{ height: 28, padding: "0 10px", fontSize: 12 }}
                              onClick={() => setNewLine({ role: newLine.role, text: line.draft, score: null })}>Start from this</button>
                          </div>
                        ))}
                      </div>
                    )}
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "flex-end" }}>
                      <div style={{ flex: "0 1 220px" }}>
                        <label className="dim" style={{ fontSize: 12 }} htmlFor="new-line-role">Under</label>
                        <select id="new-line-role" className="select" value={newLine.role} onChange={(e) => setNewLine({ ...newLine, role: Number(e.target.value) })}>
                          {cv.experience.map((role, r) => <option key={r} value={r}>{[role.role, role.company].filter(Boolean).join(", ") || `Role ${r + 1}`}</option>)}
                        </select>
                      </div>
                      <div style={{ flex: "1 1 320px" }}>
                        <label className="dim" style={{ fontSize: 12 }} htmlFor="new-line">New line</label>
                        <textarea id="new-line" className="textarea" rows={2} value={newLine.text} placeholder="Cut deploy time by 60% by…"
                          onChange={(e) => setNewLine({ ...newLine, text: e.target.value, score: null })} />
                      </div>
                    </div>
                    <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginTop: 10 }}>
                      <button type="button" className="btn-primary" style={{ height: 36 }} disabled={!draftText || blankLeft || !newLine.score} onClick={addLine}>Add to my CV</button>
                      {draftText && newLine.score && <span className={`bullet-score ${scoreClass(newLine.score)}`}>{newLine.score.score} / {newLine.score.max}</span>}
                      {blankLeft && <span className="sky" style={{ fontSize: 12 }}>Fill in the [blanks] with what you actually did before adding it.</span>}
                    </div>
                    {draftText && newLine.score && (
                      <ul className="check-list" style={{ marginTop: 8 }}>
                        {newLine.score.checks.map((c) => <li key={c.id}><span className="mono">{c.points}/{c.max}</span> <strong>{c.label}.</strong> {c.detail}</li>)}
                      </ul>
                    )}
                  </section>
                )}

                <div className="bubble notice" style={{ maxWidth: "100%" }}>
                  <strong>Gaps</strong>
                  {cv.gaps.length === 0
                    ? <div>None reported: your CV shows everything the job asks for.</div>
                    : (
                      <>
                        <div>The job asks for these and your CV does not show them. Senior did not add them.</div>
                        <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{cv.gaps.map((gap, i) => <li key={i}>{gap}</li>)}</ul>
                      </>
                    )}
                </div>

                <ResearchCard key={cv.trace_id} roleTitle={cv.role_title} company={cv.company} />
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
