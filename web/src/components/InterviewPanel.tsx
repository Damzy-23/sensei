// The interview panel: a lead interviewer who talks and an observer who takes notes.
// Both work on every turn, side by side, so the second interviewer adds no wait.
// The scorecard fills in as the observer notes things; the feedback report is written
// from those notes when the candidate ends the interview.

import { useEffect, useState } from "react";
import { ApiError, getPanel, postDebrief, type Debrief, type Dimension, type DimensionScore, type PanelView } from "../api";
import { Proctor } from "../proctor/Proctor";

const DIMENSIONS: { id: Dimension; label: string }[] = [
  { id: "communication", label: "Communication" },
  { id: "approach", label: "Approach" },
  { id: "correctness", label: "Correctness" },
  { id: "complexity", label: "Complexity" },
];
const RATING = { 1: { word: "Strength", cls: "seafoam" }, 0: { word: "Mixed", cls: "muted" }, [-1]: { word: "To work on", cls: "sky" } } as const;
const SHOWN_NOTES = 3;

/** A 502 from the debrief carries {message, trace_id}; everything else is plain text. */
function explain(err: unknown): string {
  if (err instanceof ApiError) {
    try { return (JSON.parse(err.message) as { message?: string }).message ?? err.message; } catch { return err.message; }
  }
  return err instanceof Error ? err.message : String(err);
}

function Scorecard({ scores }: { scores: Record<Dimension, DimensionScore> }) {
  return (
    <div className="scorecard" aria-label="Scorecard">
      {DIMENSIONS.map(({ id, label }) => {
        const { score, signals } = scores[id];
        return (
          <div key={id} style={{ display: "contents" }}>
            <span>{label}</span>
            <div className="score-track" role="img"
              aria-label={score === null ? `${label}: not observed yet` : `${label}: ${score} out of 4`}>
              {score !== null && <div className="score-fill" style={{ width: `${(score / 4) * 100}%` }} />}
            </div>
            <span className="mono dim" title={score === null ? "No notes on this yet" : `From ${signals} note${signals === 1 ? "" : "s"}`}>
              {score === null ? "not observed" : `${score.toFixed(1)} / 4`}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function InterviewPanel({ sessionId, turns, busy }: { sessionId: string | null; turns: number; busy: boolean }) {
  const [view, setView] = useState<PanelView | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [debrief, setDebrief] = useState<Debrief | null>(null);
  const [debriefError, setDebriefError] = useState<string | null>(null);
  const [writing, setWriting] = useState(false);

  // A new session is a new interview.
  useEffect(() => { setView(null); setDebrief(null); setDebriefError(null); }, [sessionId]);

  // Re-read the panel when a turn finishes (the observer's notes land with the lead's reply).
  useEffect(() => {
    if (!sessionId || busy) return;
    let current = true;
    getPanel(sessionId).then(
      (next) => { if (current) { setView(next); setLoadError(null); } },
      (err) => { if (current) setLoadError(explain(err)); },
    );
    return () => { current = false; };
  }, [sessionId, turns, busy]);

  const finish = async () => {
    if (!sessionId) return;
    setWriting(true); setDebriefError(null);
    try { setDebrief(await postDebrief(sessionId)); } catch (err) { setDebriefError(explain(err)); } finally { setWriting(false); }
  };

  const notes = view?.notes ?? [];
  return (
    <div className="panel" aria-label="Interview panel">
      <div className="panelists">
        <div className="panelist" data-active={busy || undefined}>
          <span className="panelist-face" aria-hidden="true">L</span>
          <div>
            <div className="panelist-name">Lead interviewer</div>
            <div className="panelist-state">{busy ? "Thinking about your answer…" : "Asks the questions"}</div>
          </div>
        </div>
        <div className="panelist" data-active={busy || undefined}>
          <span className="panelist-face observer" aria-hidden="true">O</span>
          <div>
            <div className="panelist-name">Observer</div>
            <div className="panelist-state">{busy ? "Taking notes…" : notes.length ? `${notes.length} note${notes.length === 1 ? "" : "s"} so far` : "Listens and scores"}</div>
          </div>
        </div>
      </div>

      <Proctor sessionId={sessionId} />

      {loadError && <div className="bubble notice" role="alert">The panel's notes could not be loaded: {loadError}</div>}
      {view && <Scorecard scores={(debrief ?? view).scores} />}

      {!debrief && notes.length > 0 && (
        <div aria-live="polite" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span className="label">Observer's latest notes</span>
          {notes.slice(-SHOWN_NOTES).reverse().map((n, i) => (
            <div key={`${notes.length - i}-${n.dimension}`} className="panel-note">
              <span className={RATING[n.rating].cls} style={{ fontWeight: 600 }}>{RATING[n.rating].word}</span>
              <span className="dim"> · {n.dimension}</span>
              <div>{n.note}</div>
            </div>
          ))}
        </div>
      )}

      {debrief ? (
        <div className="debrief" aria-label="Interview feedback">
          <span className="label">Feedback from the panel · from {debrief.notes_used} note{debrief.notes_used === 1 ? "" : "s"}</span>
          <div style={{ fontSize: 14, lineHeight: "22px" }}>{debrief.summary}</div>
          {debrief.strengths.length > 0 && <div><h3>What you did well</h3><ul>{debrief.strengths.map((t) => <li key={t}>{t}</li>)}</ul></div>}
          <div><h3>What to work on</h3><ul>{debrief.work_on.map((t) => <li key={t}>{t}</li>)}</ul></div>
          <div><h3>What interviewers look for</h3><ul>{debrief.interviewers_look_for.map((t) => <li key={t}>{t}</li>)}</ul></div>
        </div>
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <button type="button" className="btn-ghost" style={{ height: 36 }} disabled={!sessionId || busy || writing || notes.length === 0} onClick={() => void finish()}>
            {writing ? "Writing your feedback…" : "End interview and get feedback"}
          </button>
          {notes.length === 0 && <span className="dim" style={{ fontSize: 12 }}>Answer a question first: the observer has nothing to score yet.</span>}
        </div>
      )}
      {debriefError && <div className="bubble notice" role="alert">The feedback could not be written: {debriefError}</div>}
    </div>
  );
}
