import { useState, type FormEvent } from "react";
import { API_URL, authHeaders } from "../api";

// Mirrors POST /cv/tailor (app/api/cv.py).
interface Role { role: string; company: string; dates: string; bullets: string[] }
interface TailoredCv {
  name: string; headline: string; summary: string; skills: string[];
  experience: Role[]; education: string[]; gaps: string[]; trace_id: string;
}
type Result =
  | { status: "empty" }
  | { status: "busy" }
  | { status: "error"; message: string }
  | { status: "ready"; cv: TailoredCv };

const MIN_JOB = 20;
const MIN_CV = 50;
const INK = "#16242d";
const ACCENT = "#33658A";
const textLength = (value: string) => value.replace(/\s/g, "").length;

const PRINT_CSS = `
.cv-paper { background: #fff; color: ${INK}; max-width: 794px; width: 100%; padding: 48px; border-radius: 6px;
  box-shadow: 0 40px 80px -30px rgba(0, 0, 0, 0.8); font: 400 14px/1.5 Inter, system-ui, sans-serif; }
.cv-paper h3 { font: 700 11px Inter, sans-serif; letter-spacing: 1.2px; text-transform: uppercase; color: ${ACCENT}; margin: 18px 0 6px; }
.cv-paper ul { margin: 4px 0 0; padding-left: 18px; }
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
    return `${inner.detail ?? "The CV writer failed."}${inner.trace_id ? ` (trace ${inner.trace_id})` : ""}`;
  }
  return `The server answered ${response.status}.`;
}

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

export function CvStudio() {
  const [job, setJob] = useState("");
  const [cvText, setCvText] = useState("");
  const [result, setResult] = useState<Result>({ status: "empty" });

  const busy = result.status === "busy";
  const tooShort = textLength(job) < MIN_JOB || textLength(cvText) < MIN_CV;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || tooShort) return;
    setResult({ status: "busy" });
    try {
      const response = await fetch(`${API_URL}/cv/tailor`, {
        method: "POST", headers: { "content-type": "application/json", ...(await authHeaders()) },
        body: JSON.stringify({ job_description: job, cv_text: cvText }),
      });
      if (!response.ok) { setResult({ status: "error", message: await readError(response) }); return; }
      setResult({ status: "ready", cv: (await response.json()) as TailoredCv });
    } catch (err) {
      setResult({ status: "error", message: `Could not reach the Senior API: ${err instanceof Error ? err.message : String(err)}` });
    }
  };

  return (
    <main className="page">
      <style>{PRINT_CSS}</style>
      <div>
        <div className="label">CV studio</div>
        <h1 style={{ marginTop: 4 }}>Job description to tailored CV</h1>
        <p className="muted" style={{ margin: "6px 0 0" }}>Senior reorders and rewords what your CV already says. It never invents experience, so gaps stay gaps.</p>
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
          {result.status === "empty" && <div className="card muted">Paste a job description and your CV to begin</div>}
          {result.status === "busy" && <div className="card muted">Reading the job and your CV. This takes a few seconds…</div>}
          {result.status === "error" && <div className="bubble notice" role="alert">The CV could not be tailored: {result.message}</div>}
          {result.status === "ready" && (
            <>
              <Paper cv={result.cv} />
              <div className="bubble notice" style={{ maxWidth: 794 }}>
                <strong>Gaps</strong>
                {result.cv.gaps.length === 0
                  ? <div>None reported: your CV shows everything the job asks for.</div>
                  : (
                    <>
                      <div>The job asks for these and your CV does not show them. Senior did not add them.</div>
                      <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{result.cv.gaps.map((gap, i) => <li key={i}>{gap}</li>)}</ul>
                    </>
                  )}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                <button className="btn-primary" onClick={() => window.print()}>Download PDF</button>
                <span className="dim" style={{ fontSize: 12 }}>Opens the print dialog: choose “Save as PDF”. Trace {result.cv.trace_id}</span>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
