import { useCallback, useEffect, useState } from "react";
import { getQueueScope, getTicket, listTickets, replyTicket, resolveTicket, type Ticket, type TicketDetail } from "../api";

const REFRESH_MS = 5000;

const errorText = (err: unknown): string => (err instanceof Error ? err.message : String(err));
const formatTime = (iso: string): string => {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
};

function StatusPill({ status }: { status: Ticket["status"] }) {
  return status === "open" ? <span className="pill sky">Open</span> : <span className="pill seafoam">Resolved</span>;
}

export function Mentor() {
  // null = not loaded yet, so "could not load" and "empty" never look the same.
  const [tickets, setTickets] = useState<Ticket[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<TicketDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  // "own" when the API shows this viewer only the tickets of their own sessions. Unknown stays silent.
  const [scope, setScope] = useState<"all" | "own" | null>(null);

  const loadList = useCallback(async () => {
    try {
      const next = await listTickets();
      setTickets(next);
      setListError(null);
      setSelectedId((current) => current ?? next.find((t) => t.status === "open")?.id ?? next[0]?.id ?? null);
    } catch (err) {
      setListError(`Could not load the queue: ${errorText(err)}`);
    }
  }, []);

  const loadDetail = useCallback(async (ticketId: string) => {
    try {
      const next = await getTicket(ticketId);
      setDetail(next);
      setDetailError(null);
    } catch (err) {
      setDetailError(`Could not load this session: ${errorText(err)}`);
    }
  }, []);

  useEffect(() => {
    void loadList();
    const timer = window.setInterval(() => void loadList(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [loadList]);

  useEffect(() => {
    let current = true;
    getQueueScope().then((next) => current && setScope(next), () => undefined);
    return () => { current = false; };
  }, []);

  useEffect(() => {
    setDetail(null);
    setDetailError(null);
    setActionError(null);
    setReply("");
    if (selectedId) void loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  const refresh = async () => {
    setRefreshing(true);
    await loadList();
    if (selectedId) await loadDetail(selectedId);
    setRefreshing(false);
  };

  const sendReply = async () => {
    if (!selectedId || !reply.trim()) return;
    setBusy(true);
    setActionError(null);
    try {
      await replyTicket(selectedId, reply.trim());
      setReply("");
      await loadDetail(selectedId);
    } catch (err) {
      setActionError(`The reply was not sent: ${errorText(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const resolve = async () => {
    if (!selectedId) return;
    setBusy(true);
    setActionError(null);
    try {
      await resolveTicket(selectedId);
      await Promise.all([loadList(), loadDetail(selectedId)]);
    } catch (err) {
      setActionError(`The ticket was not resolved: ${errorText(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const openCount = tickets?.filter((t) => t.status === "open").length ?? null;

  return (
    <main className="page">
      <div>
        <div className="label">Human in the loop</div>
        <h1 style={{ marginTop: 4, fontSize: 34, lineHeight: "38px", letterSpacing: -1 }}>Mentor</h1>
        {scope === "own" && (
          <p className="muted" style={{ margin: "8px 0 0", fontSize: 13 }}>Tickets from your own sessions. Team mentors see the whole queue.</p>
        )}
      </div>

      <div className="row-wrap">
        <section className="card" aria-label="Escalation queue" style={{ flex: "1 1 340px", minWidth: 300, maxWidth: 480, display: "flex", flexDirection: "column", gap: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <h2>Queue</h2>
            {openCount !== null && <span className="muted" style={{ fontSize: 12 }}>{openCount} open</span>}
            <button className="btn-ghost" style={{ marginLeft: "auto", height: 36 }} onClick={() => void refresh()} disabled={refreshing}>
              {refreshing ? "Refreshing…" : "Refresh"}
            </button>
          </div>

          {listError && <div className="bubble notice" role="alert">{listError}</div>}
          {tickets === null && !listError && <div className="muted">Loading the queue…</div>}
          {tickets !== null && tickets.length === 0 && (
            <div className="muted">
              No escalations. A ticket appears when a student is still stuck after the last hint, is blocked three times, or shows frustration twice.
            </div>
          )}

          {tickets?.map((ticket) => {
            const on = ticket.id === selectedId;
            return (
              <button
                key={ticket.id}
                onClick={() => setSelectedId(ticket.id)}
                aria-pressed={on}
                style={{
                  display: "flex", flexDirection: "column", gap: 6, width: "100%", textAlign: "left", padding: 14,
                  borderRadius: 14, color: "var(--text)",
                  background: on ? "rgba(134, 187, 216, 0.09)" : "var(--well)",
                  border: `1px solid ${on ? "var(--sky)" : "var(--line)"}`,
                }}
              >
                <span style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                  <span className="mono" style={{ fontWeight: 500, fontSize: 13 }}>{ticket.problem_id || "no problem recorded"}</span>
                  <span style={{ marginLeft: "auto" }}><StatusPill status={ticket.status} /></span>
                </span>
                <span className="muted" style={{ fontSize: 13, lineHeight: "19px" }}>{ticket.stuck_reason}</span>
                <span className="dim" style={{ fontSize: 11 }}>{formatTime(ticket.created_at)}</span>
              </button>
            );
          })}
        </section>

        <section className="card" aria-label="Session" style={{ flex: "2 1 560px", minWidth: 320, display: "flex", flexDirection: "column", gap: 16 }}>
          <h2>Session</h2>
          {detailError && <div className="bubble notice" role="alert">{detailError}</div>}
          {!selectedId && <div className="muted">Select a ticket from the queue to see the student's session.</div>}
          {selectedId && !detail && !detailError && <div className="muted">Loading the session…</div>}

          {detail && (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <span className="mono" style={{ fontWeight: 500 }}>{detail.problem_id || "no problem recorded"}</span>
                <StatusPill status={detail.status} />
                <span className="dim mono" style={{ fontSize: 11 }}>{detail.session_id}</span>
              </div>

              <div>
                <div className="label">Why it was escalated</div>
                <div style={{ marginTop: 4 }}>{detail.stuck_reason}</div>
              </div>

              <div style={{ padding: 14, borderRadius: 14, border: "1px solid var(--baltic)", background: "rgba(107, 159, 224, 0.08)" }}>
                <div className="label">Suggested intervention</div>
                <div style={{ marginTop: 4, fontSize: 13, lineHeight: "20px" }}>{detail.suggested_intervention}</div>
              </div>

              <div>
                <div className="label" style={{ marginBottom: 6 }}>Student code</div>
                <pre className="json">{detail.latest_code.trim() ? detail.latest_code : "(the student has not written any code)"}</pre>
              </div>

              <div>
                <div className="label" style={{ marginBottom: 6 }}>Transcript</div>
                {detail.transcript.length === 0 ? (
                  <div className="muted">No messages in this session.</div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 360, overflowY: "auto", padding: 2 }}>
                    {detail.transcript.map((message) => (
                      <div key={message.id} className={`bubble ${message.actor}`}>
                        <div className="label" style={{ fontSize: 10, marginBottom: 2 }}>{message.actor}</div>
                        {message.text}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <label className="label" htmlFor="mentor-reply">Reply to the student</label>
                <textarea
                  id="mentor-reply"
                  className="textarea"
                  rows={3}
                  maxLength={2000}
                  value={reply}
                  onChange={(e) => setReply(e.target.value)}
                  placeholder="Your message appears in the student's chat."
                />
                {actionError && <div className="bubble notice" role="alert">{actionError}</div>}
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                  <button className="btn-primary" onClick={() => void sendReply()} disabled={busy || !reply.trim()}>
                    {busy ? "Working…" : "Send reply"}
                  </button>
                  <button className="btn-ghost" onClick={() => void resolve()} disabled={busy || detail.status === "resolved"}>
                    {detail.status === "resolved" ? "Resolved" : "Resolve"}
                  </button>
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
