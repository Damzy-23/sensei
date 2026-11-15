import { useCallback, useEffect, useMemo, useState } from "react";
import { getLogs, idTag, type ActivityLog, type TraceEvent } from "../api";

const TYPES = [
  { id: "", label: "All" },
  { id: "llm", label: "Model calls" },
  { id: "tool", label: "Tool calls" },
  { id: "guard", label: "Guards" },
  { id: "mode", label: "Routing" },
];
const STATUS_CLASS: Record<TraceEvent["status"], string> = { ok: "seafoam", blocked: "sky", error: "sky", retried: "baltic" };
const money = (n: number) => (n === 0 ? "$0" : n < 0.01 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`);
const human = (s: string) => s.replace(/_/g, " ");
const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

const ALL_SESSIONS = { fontSize: 12, marginTop: 6 } as const;

/** The agents' actions: who did what, with which model or tool, and what it cost. A mentor is
 *  shown every session. Anyone else is shown their own, with the whole system's totals beneath. */
export function Logs() {
  const [actor, setActor] = useState("");
  const [type, setType] = useState("");
  const [log, setLog] = useState<ActivityLog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    getLogs({ actor: actor || undefined, type: type || undefined }).then(setLog, (err: Error) => setError(err.message));
  }, [actor, type]);
  useEffect(load, [load]);

  // What the list and the agent tiles cover: the events the server read for this view.
  const shown = useMemo(() => (log?.summary ?? []).reduce(
    (t, s) => ({ events: t.events + s.events, calls: t.calls + s.model_calls + s.tool_calls, cost: t.cost + s.cost_usd }),
    { events: 0, calls: 0, cost: 0 }), [log]);
  // The three tiles say how much has been done. For a visitor that is their own sessions, with
  // the whole system's totals beneath. For a mentor it is every session, so the tiles take the
  // stored totals: the summary only counts the newest actions the server read. (Totals that
  // lag a moment behind the list are passed over, so a tile is never smaller than the list.)
  const whole = log?.totals_all ?? null;
  const own = log?.scope === "own";
  const everything = !own && whole && whole.events >= shown.events ? whole : null;
  const tiles = everything ? { events: everything.events, calls: everything.model_calls + everything.tool_calls, cost: everything.cost_usd } : shown;
  const everyone = own ? whole : null;
  const newest = everything && everything.events > shown.events ? shown.events : null; // the agent tiles cover fewer actions than the tiles above

  return (
    <main className="page">
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", gap: "12px 24px" }}>
        <div>
          <div className="label">Every agent, every action</div>
          <h1 style={{ marginTop: 4, fontSize: 34, lineHeight: "38px", letterSpacing: -1 }}>Activity log</h1>
        </div>
        <span className="dim" style={{ fontSize: 12, marginLeft: "auto" }}>
          {log ? (log.durable ? "Stored permanently" : "Stored on this server only") : ""}
        </span>
        <button className="btn-ghost btn-small" onClick={load}>Refresh</button>
      </div>

      {error && <div className="bubble notice" role="alert">Could not load the log: {error}</div>}

      {log && (
        <>
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>
            {own ? "Showing your own sessions. Mentors on the team see every session." : "Showing every session."}
            {!own && !whole && " The totals could not be read, so the tiles count the newest actions only."}
          </p>

          <div className="log-stats">
            <div className="card">
              <div className="label">Actions</div>
              <div className="stat">{tiles.events.toLocaleString()}</div>
              {everyone && <div className="mono dim" style={ALL_SESSIONS}>{everyone.events.toLocaleString()} across all sessions</div>}
            </div>
            <div className="card">
              <div className="label">Model and tool calls</div>
              <div className="stat">{tiles.calls.toLocaleString()}</div>
              {everyone && <div className="mono dim" style={ALL_SESSIONS}>{(everyone.model_calls + everyone.tool_calls).toLocaleString()} across all sessions</div>}
            </div>
            <div className="card">
              <div className="label">Spend</div>
              <div className="stat">{money(tiles.cost)}</div>
              {everyone && <div className="mono dim" style={ALL_SESSIONS}>{money(everyone.cost_usd)} across all sessions</div>}
            </div>
          </div>

          <section className="card" aria-label="Agents">
            <div className="label" style={{ marginBottom: 10 }}>
              Agents, by role{newest !== null && ` · the newest ${newest.toLocaleString()} actions`}
            </div>
            <div className="agent-grid">
              <button className={`agent-tile ${actor === "" ? "on" : ""}`} aria-pressed={actor === ""} onClick={() => setActor("")}>
                <span className="agent-name">All agents</span>
                <span className="agent-meta mono">{shown.events} actions</span>
              </button>
              {log.summary.map((s) => (
                <button key={s.actor} className={`agent-tile ${actor === s.actor ? "on" : ""}`} aria-pressed={actor === s.actor} onClick={() => setActor(s.actor)}>
                  <span className="agent-name">{human(s.actor)}</span>
                  <span className="agent-meta mono">
                    {s.events} actions · {s.model_calls} model · {s.tool_calls} tool
                    {s.blocked > 0 && ` · ${s.blocked} blocked`}{s.errors > 0 && ` · ${s.errors} errors`}
                  </span>
                  <span className="agent-meta mono">{(s.tokens_in + s.tokens_out).toLocaleString()} tokens · {money(s.cost_usd)}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="card" aria-label="Actions" style={{ padding: 0, overflow: "hidden" }}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, padding: 16, borderBottom: "1px solid var(--line)" }} role="group" aria-label="Action type">
              {TYPES.map((t) => (
                <button key={t.id} className={`filter ${type === t.id ? "on" : ""}`} aria-pressed={type === t.id} onClick={() => setType(t.id)}>{t.label}</button>
              ))}
              <span className="mono dim" style={{ marginLeft: "auto", alignSelf: "center", fontSize: 12 }}>{log.events.length} shown</span>
            </div>
            {log.events.length === 0 && <p className="muted" style={{ padding: 16, margin: 0 }}>No actions yet. Talk to the coach in the Workspace and they appear here.</p>}
            <ul className="log-list">
              {log.events.map((e) => (
                <li key={e.event_id}>
                  <button className="log-row" aria-expanded={open === e.event_id} onClick={() => setOpen(open === e.event_id ? null : e.event_id)}>
                    <span className="mono dim log-time">{time(e.ts)}</span>
                    <span className="chip" style={{ color: "var(--baltic)" }}>{human(e.actor)}</span>
                    <span className="log-what"><span className="mono">{e.name}</span><span className="dim"> {e.type}</span></span>
                    <span className="log-model mono dim">{e.model ?? ""}</span>
                    <span className="mono log-num">{e.latency_ms != null ? `${Math.round(e.latency_ms)} ms` : ""}</span>
                    <span className="mono log-num">{e.cost_usd ? money(e.cost_usd) : ""}</span>
                    <span className={`pill ${STATUS_CLASS[e.status]}`}>{e.status}</span>
                  </button>
                  {open === e.event_id && (
                    <div className="log-detail">
                      {e.decision && <p><span className="label">Decision</span> {e.decision}</p>}
                      {e.reason && <p><span className="label">Why</span> {e.reason}</p>}
                      {e.input && <p><span className="label">Input</span> <span className="mono">{e.input}</span></p>}
                      {e.output && <p><span className="label">Output</span> <span className="mono">{e.output}</span></p>}
                      <p className="mono dim" style={{ fontSize: 11 }}>
                        session {idTag(e.session_id)} · trace {idTag(e.trace_id)}{e.tokens_in != null && ` · ${e.tokens_in} in / ${e.tokens_out ?? 0} out tokens`}
                      </p>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
      {!log && !error && <span className="muted">Loading the log…</span>}
    </main>
  );
}
