// Typed client for the Senior API. Shapes mirror docs/API.md.
import { auth } from "./firebase";

/** The signed-in user's ID token, or null for a guest. */
const idToken = async (): Promise<string | null> => (auth.currentUser ? auth.currentUser.getIdToken() : null);

// Same origin in a production build (FastAPI serves the app); the local API in dev.
export const API_URL: string = import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? "http://localhost:8000" : "");

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

// The sessions this browser has started, newest first. The API shows a visitor only the
// data of sessions they hold, and a session id is the proof: it is unguessable, and it is
// sent with every request. Kept in localStorage so every tab of this browser shares the list.
const SESSIONS_KEY = "senior.sessions";
const MAX_SESSIONS = 30;
const SESSION_ID = /^ses_[0-9a-z_]{1,40}$/;
let sessionsThisTab: string[] = []; // newest first; also the whole list when storage is unavailable

/** Newest first, 30 at most. This tab's current session leads, so it is always sent; the list
 *  every tab shares follows, and it is in the order the sessions were started. If the shared
 *  list has lost one of this tab's sessions (site data was cleared, or other tabs started
 *  thirty newer ones), it is written back here, so the other tabs see the session again. */
function heldSessions(): string[] {
  let stored: string[] = [];
  try { stored = (localStorage.getItem(SESSIONS_KEY) ?? "").split(","); } catch { /* storage is blocked */ }
  const all = [...sessionsThisTab.slice(0, 1), ...stored, ...sessionsThisTab].filter((id) => SESSION_ID.test(id));
  const held = [...new Set(all)].slice(0, MAX_SESSIONS);
  if (held.some((id) => !stored.includes(id))) {
    try { localStorage.setItem(SESSIONS_KEY, held.join(",")); } catch { /* private window: this tab still remembers */ }
  }
  return held;
}

function rememberSession(sessionId: string): string {
  sessionsThisTab = [sessionId, ...sessionsThisTab].slice(0, MAX_SESSIONS);
  heldSessions(); // reads the shared list afresh, as another tab may have added to it, and writes the new id in
  return sessionId;
}

/** How an id is shown on screen. A session id is the key to its session, and a trace id leads
 *  to one, so neither is ever printed whole: a shared screen or a photo of the page must not
 *  hand a session to whoever is watching. The last four characters tell two rows apart. */
export const idTag = (id: string): string => (id.length > 8 ? `…${id.slice(-4)}` : id);
/** A trace event as it may be printed: every field, with the session and trace ids as tags. */
export const printable = (event: TraceEvent): TraceEvent => ({ ...event, session_id: idTag(event.session_id), trace_id: idTag(event.trace_id) });

/** Who is calling: the sign-in token, if any, and the sessions this browser holds. */
export async function authHeaders(): Promise<Record<string, string>> {
  const token = await idToken();
  const sessions = heldSessions();
  return {
    ...(token ? { authorization: `Bearer ${token}` } : {}),
    ...(sessions.length ? { "x-senior-sessions": sessions.join(",") } : {}),
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { ...init, headers: { "content-type": "application/json", ...(await authHeaders()), ...init?.headers } });
  if (!response.ok) {
    const detail = await response.json().then((b) => b.detail, () => response.statusText);
    throw new ApiError(typeof detail === "string" ? detail : JSON.stringify(detail), response.status);
  }
  return response.json() as Promise<T>;
}
const post = <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const createSession = (mode: Mode) => post<{ session_id: string }>("/sessions", { mode }).then((r) => rememberSession(r.session_id));
export const getState = (sessionId: string) => request<SessionState>(`/sessions/${sessionId}/state`);
export const postRun = (sessionId: string, run: RunIn) => post<RunOut>(`/sessions/${sessionId}/runs`, run);
export const listTracks = () => request<TrackSummary[]>("/tracks");
export const getTrack = (trackId: string) => request<Track>(`/tracks/${trackId}`);
export const getProblem = (problemId: string) => request<ProblemDetail>(`/problems/${problemId}`);
export const getTrace = (traceId: string) => request<TraceTree>(`/traces/${traceId}`);
export const listTickets = () => request<Ticket[]>("/mentor/tickets");
/** Whether the queue holds every ticket (a mentor) or only those of the viewer's own sessions. */
export const getQueueScope = () => request<{ scope: "all" | "own" }>("/mentor/scope").then((r) => r.scope);
export const getMentorMessages = (sessionId: string) => request<ChatMessage[]>(`/sessions/${sessionId}/mentor-messages`);
export const getTicket = (ticketId: string) => request<TicketDetail>(`/mentor/tickets/${ticketId}`);
export const replyTicket = (ticketId: string, text: string) => post<ChatMessage>(`/mentor/tickets/${ticketId}/reply`, { text });
export type Dimension = "communication" | "approach" | "correctness" | "complexity";
export interface PanelNote { dimension: Dimension; rating: -1 | 0 | 1; note: string }
/** `score` is null when the dimension has not been observed: unknown, not zero. */
export interface DimensionScore { score: number | null; signals: number }
export interface PanelView { active: boolean; notes: PanelNote[]; scores: Record<Dimension, DimensionScore> }
export interface Debrief {
  summary: string; strengths: string[]; work_on: string[]; interviewers_look_for: string[];
  scores: Record<Dimension, DimensionScore>; notes_used: number; trace_id: string;
}
export const getPanel = (sessionId: string) => request<PanelView>(`/sessions/${sessionId}/panel`);
export const postDebrief = (sessionId: string) => post<Debrief>(`/sessions/${sessionId}/debrief`);
export const startVoiceSession = () => post<{ signed_url: string; agent_id: string }>("/voice/session");
export interface ActorSummary { actor: string; events: number; model_calls: number; tool_calls: number; blocked: number; errors: number; tokens_in: number; tokens_out: number; cost_usd: number }
/** Counts over every session. Numbers only, so any visitor may see them. */
export interface LogTotals { events: number; model_calls: number; tool_calls: number; cost_usd: number }
/** `scope` says whose sessions `events` and `summary` cover: every session for a mentor, the
 *  viewer's own otherwise. `totals_all` always covers every session; null if it could not be read. */
export interface ActivityLog { events: TraceEvent[]; summary: ActorSummary[]; durable: boolean; scope: "all" | "own"; totals_all: LogTotals | null }
export const getLogs = (filter: { actor?: string; type?: string }) =>
  request<ActivityLog>(`/logs?${new URLSearchParams(Object.entries(filter).filter(([, v]) => v) as [string, string][])}`);
export const resolveTicket = (ticketId: string) => post<Ticket>(`/mentor/tickets/${ticketId}/resolve`);

// Profile: the career agent's interview and its Linkup-backed role recommendations.
export interface ProfileTurn { profile_id: string; step: number; total: number; question: string | null; done: boolean; trace_id: string | null }
export interface Source { title: string; url: string }
export interface RoleRecommendation { title: string; fit: string; skills_to_strengthen: string[]; sources: Source[] }
export interface PracticePlan { track_id: string; track_title: string; patterns: string[]; why: string }
export interface ProfileResult { profile_id: string; summary: string; roles: RoleRecommendation[]; practice: PracticePlan; sources: Source[]; trace_id: string | null }
const sessionQuery = (sessionId: string | null) => (sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "");
export const startProfile = (sessionId: string | null) => post<ProfileTurn>("/profile", { session_id: sessionId });
export const answerProfile = (profileId: string, text: string, sessionId: string | null) =>
  post<ProfileTurn>(`/profile/${profileId}/answer${sessionQuery(sessionId)}`, { text });
export const recommendRoles = (profileId: string, sessionId: string | null) =>
  post<ProfileResult>(`/profile/${profileId}/recommend${sessionQuery(sessionId)}`);

/** Send a student message. Trace events arrive through `onTrace` as the agents work;
 *  the promise resolves with the final reply, or rejects with the named error. */
export async function sendMessage(
  sessionId: string,
  body: { text: string; problem_id: string; code: string },
  onTrace: (event: TraceEvent) => void,
): Promise<FinalEvent> {
  const response = await fetch(`${API_URL}/sessions/${sessionId}/message`, {
    method: "POST", headers: { "content-type": "application/json", ...(await authHeaders()) }, body: JSON.stringify(body),
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
  // EventSource cannot send headers, so the sign-in token goes in the query string.
  let source: EventSource | null = null;
  let closed = false;
  idToken().then((token) => {
    if (closed) return;
    const query = token ? `?token=${encodeURIComponent(token)}` : "";
    source = new EventSource(`${API_URL}/sessions/${sessionId}/events${query}`);
    source.addEventListener("trace", (e) => onTrace(JSON.parse((e as MessageEvent).data) as TraceEvent));
    source.onopen = () => onStatus?.(true);
    source.onerror = () => onStatus?.(false);
  });
  return () => { closed = true; source?.close(); };
}
