// Typed client for the Senior API. Shapes mirror docs/API.md.

export const API_URL: string = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type Mode = "learn" | "interview" | "blitz" | "call";
export type Difficulty = "easy" | "medium" | "hard";

export interface TraceEvent {
  event_id: string; trace_id: string; span_id: string; parent_span_id: string | null;
  session_id: string; seq: number; ts: string; actor: string; type: string; name: string;
  status: "ok" | "blocked" | "error" | "retried";
  latency_ms: number | null; model: string | null; tokens_in: number | null; tokens_out: number | null;
  cost_usd: number | null; input: string | null; output: string | null; decision: string | null; reason: string | null;
}
export interface FinalEvent { reply: string; mode: Mode; hint_level: number; escalated: boolean; trace_id: string }
export interface SessionState {
  session_id: string; problem_id: string | null; mode: Mode; hint_level: number; failed_runs: number;
  hints_used: number; time_on_problem: number; mastery: Record<string, number>; escalated: boolean;
  countdown_seconds: number | null;
}
export interface Problem { id: string; title: string; difficulty: Difficulty; pattern: string }
export interface TrackProblem extends Problem { runnable: boolean }
export interface TrackSummary { id: string; title: string; count: number }
export interface Track extends TrackSummary { problems: TrackProblem[] }
export interface VisibleTest { name: string; input: string; expected: string }
export interface ProblemDetail extends Problem { statement: string; starter_code: string; visible_tests: VisibleTest[] }
export interface RunIn {
  problem_id: string; code: string; passed: number; failed: number; total: number;
  failures: { name: string; message: string }[]; runtime_ms: number;
}
export interface RunOut { mode: Mode; hint_level_available: number; next_action: "keep_coding" | "ask_for_hint" | "review_complexity" | "escalate" }
export interface ChatMessage { id: string; session_id: string; actor: "student" | "coach" | "mentor"; text: string; ts: string; trace_id: string | null }
export interface Ticket { id: string; session_id: string; problem_id: string; status: "open" | "resolved"; stuck_reason: string; created_at: string }
export interface TicketDetail extends Ticket { transcript: ChatMessage[]; latest_code: string; suggested_intervention: string }
export interface TraceNode { event: TraceEvent; children: TraceNode[] }
export interface TraceTree { trace_id: string; session_id: string; roots: TraceNode[] }

export class ApiError extends Error {
  constructor(message: string, readonly status?: number, readonly traceId?: string) { super(message); }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { ...init, headers: { "content-type": "application/json", ...init?.headers } });
  if (!response.ok) {
    const detail = await response.json().then((b) => b.detail, () => response.statusText);
    throw new ApiError(typeof detail === "string" ? detail : JSON.stringify(detail), response.status);
  }
  return response.json() as Promise<T>;
}
const post = <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const createSession = (mode: Mode) => post<{ session_id: string }>("/sessions", { mode }).then((r) => r.session_id);
export const getState = (sessionId: string) => request<SessionState>(`/sessions/${sessionId}/state`);
export const postRun = (sessionId: string, run: RunIn) => post<RunOut>(`/sessions/${sessionId}/runs`, run);
export const listTracks = () => request<TrackSummary[]>("/tracks");
export const getTrack = (trackId: string) => request<Track>(`/tracks/${trackId}`);
export const getProblem = (problemId: string) => request<ProblemDetail>(`/problems/${problemId}`);
export const getTrace = (traceId: string) => request<TraceTree>(`/traces/${traceId}`);
export const listTickets = () => request<Ticket[]>("/mentor/tickets");
export const getTicket = (ticketId: string) => request<TicketDetail>(`/mentor/tickets/${ticketId}`);
export const replyTicket = (ticketId: string, text: string) => post<ChatMessage>(`/mentor/tickets/${ticketId}/reply`, { text });
export const startVoiceSession = () => post<{ signed_url: string; agent_id: string }>("/voice/session");
export const resolveTicket = (ticketId: string) => post<Ticket>(`/mentor/tickets/${ticketId}/resolve`);

/** Send a student message. Trace events arrive through `onTrace` as the agents work;
 *  the promise resolves with the final reply, or rejects with the named error. */
export async function sendMessage(
  sessionId: string,
  body: { text: string; problem_id: string; code: string },
  onTrace: (event: TraceEvent) => void,
): Promise<FinalEvent> {
  const response = await fetch(`${API_URL}/sessions/${sessionId}/message`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    const detail = await response.json().then((b) => b.detail, () => response.statusText);
    throw new ApiError(String(detail), response.status);
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let final: FinalEvent | null = null;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let split: number;
    while ((split = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      const name = /^event: (.+)$/m.exec(frame)?.[1];
      const data = /^data: (.+)$/m.exec(frame)?.[1];
      if (!name || !data) continue;
      const payload = JSON.parse(data);
      if (name === "trace") onTrace(payload as TraceEvent);
      else if (name === "final") final = payload as FinalEvent;
      else if (name === "error") throw new ApiError(payload.message, undefined, payload.trace_id);
    }
  }
  if (!final) throw new ApiError("The reply stream ended before a final event.");
  return final;
}

/** Live trace stream for a session: stored events first, then new ones. Returns a function that closes it. */
export function subscribeTraces(sessionId: string, onTrace: (event: TraceEvent) => void, onStatus?: (live: boolean) => void): () => void {
  const source = new EventSource(`${API_URL}/sessions/${sessionId}/events`);
  source.addEventListener("trace", (e) => onTrace(JSON.parse((e as MessageEvent).data) as TraceEvent));
  source.onopen = () => onStatus?.(true);
  source.onerror = () => onStatus?.(false);
  return () => source.close();
}
