import { useEffect, useMemo, useState } from "react";
import { printable, subscribeTraces, type TraceEvent } from "../api";
import { useApp } from "../app-context";

type Filter = "all" | "guards" | "tools" | "llm";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "guards", label: "Guards" },
  { id: "tools", label: "Tools" },
  { id: "llm", label: "Model calls" },
];

const TOOL_TYPES = new Set(["tool.call", "tool.result", "escalation.created"]);

const ACTOR_COLOR: Record<string, string> = {
  client: "#A9BCC9",
  guard: "var(--sky)",
  orchestrator: "var(--baltic)",
  hint_coach: "var(--sky)",
  illustrator: "var(--seafoam)",
  interviewer: "var(--baltic)",
  evaluator: "var(--seafoam)",
  planner: "var(--seafoam)",
  mentor: "var(--baltic)",
  escalation: "var(--baltic)",
  career_agent: "var(--seafoam)",
};
const actorColor = (actor: string): string => ACTOR_COLOR[actor] ?? "var(--text-2)";

function matches(filter: Filter, event: TraceEvent): boolean {
  if (filter === "guards") return event.type.startsWith("guard.");
  if (filter === "tools") return TOOL_TYPES.has(event.type);
  if (filter === "llm") return event.type === "llm.call";
  return true;
}

/** Sum the values that are present. Null when none are: an unknown total is not zero. */
function sumKnown(values: (number | null)[]): number | null {
  const known = values.filter((v): v is number => v !== null);
  return known.length ? known.reduce((a, b) => a + b, 0) : null;
}

const formatCost = (cost: number | null): string =>
  cost === null ? "n/a" : `$${cost.toFixed(cost > 0 && cost < 0.0001 ? 6 : 4)}`;
const formatMs = (ms: number | null): string => (ms === null ? "—" : `${Math.round(ms)} ms`);
const formatCount = (n: number | null): string => (n === null ? "n/a" : n.toLocaleString());

interface Row {
  event: TraceEvent;
  depth: number;
  left: number;
  width: number;
}

interface TraceView {
  traceId: string;
  label: string;
  lastSeen: number;
  events: TraceEvent[];
}

function buildTraces(events: TraceEvent[]): TraceView[] {
  const byTrace = new Map<string, TraceEvent[]>();
  for (const event of events) {
    const list = byTrace.get(event.trace_id);
    if (list) list.push(event);
    else byTrace.set(event.trace_id, [event]);
  }
  const views: TraceView[] = [];
  for (const [traceId, list] of byTrace) {
    list.sort((a, b) => a.seq - b.seq);
    const turn = list.find((e) => e.type === "turn.end") ?? list.find((e) => e.type === "turn.start");
    const message = list.find((e) => e.type === "guard.input" && e.input)?.input;
    const name = turn?.name ?? "turn";
    views.push({
      traceId,
      label: message ? `${name} · “${message.length > 60 ? `${message.slice(0, 60)}…` : message}”` : name,
      lastSeen: Math.max(...list.map((e) => Date.parse(e.ts))),
      events: list,
    });
  }
  return views.sort((a, b) => b.lastSeen - a.lastSeen);
}

function buildRows(events: TraceEvent[]): Row[] {
  const shown = events.filter((e) => e.type !== "turn.start");
  const parentOf = new Map<string, string | null>();
  for (const e of events) parentOf.set(e.span_id, e.parent_span_id);
  const depthOf = (spanId: string): number => {
    let depth = 0;
    let parent = parentOf.get(spanId) ?? null;
    const seen = new Set<string>([spanId]);
    while (parent !== null && parentOf.has(parent) && !seen.has(parent)) {
      seen.add(parent);
      depth += 1;
      parent = parentOf.get(parent) ?? null;
    }
    return depth;
  };

  const timed = shown.map((event) => {
    const end = Date.parse(event.ts);
    return { event, end, start: end - (event.latency_ms ?? 0) };
  });
  const earliest = Math.min(...timed.map((t) => t.start));
  const latest = Math.max(...timed.map((t) => t.end));
  const span = Math.max(latest - earliest, 1);

  return timed.map(({ event, start, end }) => {
    const left = Math.min(((start - earliest) / span) * 100, 98.8);
    const width = Math.min(Math.max(((end - start) / span) * 100, 1.2), 100 - left);
    return { event, depth: depthOf(event.span_id), left, width };
  });
}

export function Inspector() {
  const { sessionId } = useApp();
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [live, setLive] = useState(false);
  const [pickedTrace, setPickedTrace] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [selectedEvent, setSelectedEvent] = useState<string | null>(null);

  useEffect(() => {
    setEvents([]);
    setLive(false);
    setPickedTrace(null);
    setSelectedEvent(null);
    if (!sessionId) return;
    const seen = new Set<string>();
    return subscribeTraces(
      sessionId,
      (event) => {
        if (seen.has(event.event_id)) return;
        seen.add(event.event_id);
        setEvents((prev) => [...prev, event]);
      },
      setLive,
    );
  }, [sessionId]);

  const traces = useMemo(() => buildTraces(events), [events]);
  const trace = traces.find((t) => t.traceId === pickedTrace) ?? traces[0] ?? null;
  const rows = useMemo(() => (trace ? buildRows(trace.events) : []), [trace]);
  const visibleRows = rows.filter((row) => matches(filter, row.event));
  const selected =
    rows.find((row) => row.event.event_id === selectedEvent)?.event ??
    // Open on the most telling step: the last one that records a decision and its reason.
    [...visibleRows].reverse().find((row) => row.event.decision && row.event.reason)?.event ??
    visibleRows[visibleRows.length - 1]?.event ??
    null;

  const stats = useMemo(() => {
    const list = trace?.events ?? [];
    const calls = list.filter((e) => e.type === "llm.call");
    const guards = list.filter((e) => e.type === "guard.input" || e.type === "guard.output");
    return {
      latency: list.find((e) => e.type === "turn.end")?.latency_ms ?? null,
      cost: sumKnown(list.map((e) => e.cost_usd)),
      tokensIn: sumKnown(calls.map((e) => e.tokens_in)),
      tokensOut: sumKnown(calls.map((e) => e.tokens_out)),
      guards: guards.length,
      blocked: guards.filter((e) => e.status === "blocked").length,
    };
  }, [trace]);

  if (!sessionId) {
    return (
      <main className="page">
        <p className="muted">Starting a session…</p>
      </main>
    );
  }

  const selectedOk = selected?.status === "ok";
  const decisionColor = selectedOk ? "var(--seafoam)" : "var(--sky)";

  return (
    <main className="page">
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "flex-end", gap: "12px 24px" }}>
        <div>
          <div className="label">One student message, every step</div>
          <h1 style={{ marginTop: 4, fontSize: 34, lineHeight: "38px", letterSpacing: -1 }}>Agent inspector</h1>
        </div>
        {traces.length > 0 && (
          <label style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 260, flex: "1 1 260px", maxWidth: 520 }}>
            <span className="label">Turn</span>
            <select
              className="select mono"
              value={trace?.traceId ?? ""}
              onChange={(e) => {
                // Choosing the newest turn means "keep following new ones".
                setPickedTrace(e.target.value === traces[0]?.traceId ? null : e.target.value);
                setSelectedEvent(null);
              }}
            >
              {traces.map((t) => (
                <option key={t.traceId} value={t.traceId}>{t.label}</option>
              ))}
            </select>
          </label>
        )}
        <div className="muted" role="status" style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8, font: "500 12px var(--body)" }}>
          {live ? <span className="live-dot" aria-hidden="true" /> : null}
          {live ? "Live: streaming over SSE" : "Not connected: reconnecting to the trace stream"}
        </div>
      </div>

      {!trace ? (
        <div className="card muted">No turns yet. Send the coach a message in the Workspace.</div>
      ) : (
        <>
          <section className="grid-stats" aria-label="Turn totals">
            <div className="card">
              <div className="label">Total latency</div>
              <div className="stat">
                {stats.latency === null ? "n/a" : Math.round(stats.latency).toLocaleString()}
                {stats.latency !== null && <small> ms</small>}
              </div>
            </div>
            <div className="card">
              <div className="label">Cost</div>
              <div className="stat">{formatCost(stats.cost)}</div>
            </div>
            <div className="card">
              <div className="label">Tokens in / out</div>
              <div className="stat">
                {formatCount(stats.tokensIn)}
                <small> / {formatCount(stats.tokensOut)}</small>
              </div>
            </div>
            <div className="card">
              <div className="label">Guard decisions</div>
              <div className="stat" style={{ color: stats.blocked > 0 ? "var(--sky)" : "var(--seafoam)" }}>
                {stats.guards === 0 ? "none" : stats.blocked > 0 ? `${stats.blocked} blocked` : `${stats.guards} pass`}
                {stats.guards > 0 && <small> of {stats.guards}</small>}
              </div>
            </div>
          </section>

          <div className="row-wrap">
            <section className="card" aria-label="Event timeline" style={{ flex: "2 1 620px", minWidth: 320, padding: 0, overflow: "hidden" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", padding: "14px 16px", borderBottom: "1px solid var(--line)" }}>
                {FILTERS.map((f) => (
                  <button key={f.id} className={`filter ${filter === f.id ? "on" : ""}`} aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
                    {f.label}
                  </button>
                ))}
                <span className="mono dim" style={{ marginLeft: "auto", fontSize: 12 }}>{visibleRows.length} events</span>
              </div>
              <div role="region" aria-label="Timeline rows, scroll sideways for more" style={{ overflowX: "auto" }}>
                <div style={{ minWidth: 560 }}>
                  <div className="label" style={{ display: "grid", gridTemplateColumns: "128px minmax(150px, 1.1fr) minmax(160px, 2fr) 72px", gap: 12, padding: "10px 16px 6px 19px", fontSize: 10 }}>
                    <span>Actor</span>
                    <span>Step</span>
                    <span>Waterfall</span>
                    <span style={{ textAlign: "right" }}>Time</span>
                  </div>
                  <div style={{ paddingBottom: 10 }}>
                    {visibleRows.length === 0 && <div className="muted" style={{ padding: "12px 19px" }}>No events of this kind in this turn.</div>}
                    {visibleRows.map(({ event, depth, left, width }) => (
                      <button
                        key={event.event_id}
                        className={`trace-row ${selected?.event_id === event.event_id ? "sel" : ""}`}
                        aria-pressed={selected?.event_id === event.event_id}
                        onClick={() => setSelectedEvent(event.event_id)}
                      >
                        <span style={{ paddingLeft: depth * 14 }}>
                          <span className="chip" style={{ color: actorColor(event.actor) }}>{event.actor}</span>
                        </span>
                        <span style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
                          <span className="mono" style={{ fontWeight: 500, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis" }}>{event.name}</span>
                          <span className="dim" style={{ fontSize: 11 }}>
                            {event.type}
                            {event.status !== "ok" ? ` · ${event.status}` : ""}
                          </span>
                        </span>
                        <span className="bar-track" aria-hidden="true">
                          <span className="bar" style={{ left: `${left}%`, width: `${width}%`, background: event.type === "llm.call" ? "var(--sky-grad)" : actorColor(event.actor) }} />
                        </span>
                        <span className="mono muted" style={{ textAlign: "right", fontWeight: 500, fontSize: 12 }}>{formatMs(event.latency_ms)}</span>
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </section>

            <section className="card" aria-label="Event detail" style={{ flex: "1 1 340px", minWidth: 300, display: "flex", flexDirection: "column", gap: 14 }}>
              {!selected ? (
                <div className="muted">Select a step to see its decision and reason.</div>
              ) : (
                <>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                    <span className="chip" style={{ color: actorColor(selected.actor) }}>{selected.actor}</span>
                    <span className="mono" style={{ fontWeight: 500, fontSize: 16 }}>{selected.name}</span>
                  </div>
                  <div style={{ padding: 14, borderRadius: 14, border: `1px solid ${decisionColor}`, background: "rgba(255,255,255,.03)" }}>
                    <div className="label" style={{ fontSize: 10 }}>Decision · status {selected.status}</div>
                    <div style={{ marginTop: 4, font: "600 15px var(--body)", color: decisionColor }}>
                      {selected.decision ?? "No decision recorded for this step"}
                    </div>
                    <div className="muted" style={{ marginTop: 6, fontSize: 13, lineHeight: "19px" }}>
                      {selected.reason ?? "No reason recorded for this step."}
                    </div>
                  </div>
                  {selected.model && (
                    <div className="mono muted" style={{ fontSize: 12, lineHeight: "19px" }}>
                      {selected.model} · {formatCount(selected.tokens_in)} in / {formatCount(selected.tokens_out)} out · {formatCost(selected.cost_usd)}
                    </div>
                  )}
                  <pre className="json">{JSON.stringify(printable(selected), null, 2)}</pre>
                </>
              )}
            </section>
          </div>
        </>
      )}
    </main>
  );
}
