// Everything the proctor sends to the Senior server, in one place so it is easy to audit:
// a reminder's words to be spoken, and the fact that a reminder was given. Neither request
// has anywhere to put a camera frame.

import { API_URL, authHeaders } from "../api";
import type { Rule } from "./rules";

const PERSONAS = ["drill", "mentor", "peer"];
const MAX_SECONDS = 3600; // the server refuses longer; an hour away is the same reminder anyway

/** The coach the student picked for their voice call, so the proctor speaks in the same voice. */
export function chosenPersona(): string {
  try {
    const saved = localStorage.getItem("senior.persona") ?? "";
    return PERSONAS.includes(saved) ? saved : "mentor";
  } catch {
    return "mentor";
  }
}

export type Speech = { ok: true; url: string } | { ok: false; unavailable: boolean };

/** Fetch `text` as speech in a coach's voice (ElevenLabs, through POST /voice/tts).
 *  `unavailable` means the server has no voice service, so there is no point asking again. */
export async function fetchSpeech(text: string, persona: string): Promise<Speech> {
  try {
    const response = await fetch(`${API_URL}/voice/tts`, {
      method: "POST", headers: { "content-type": "application/json", ...(await authHeaders()) },
      body: JSON.stringify({ text, persona }),
    });
    if (!response.ok) return { ok: false, unavailable: response.status === 503 };
    return { ok: true, url: URL.createObjectURL(await response.blob()) };
  } catch {
    return { ok: false, unavailable: false };
  }
}

/** Record a reminder in the session's trace: the rule and how long it had held. Best effort:
 *  the candidate has already been reminded, so a failure here only loses the log entry. */
export async function reportReminder(sessionId: string, rule: Rule, seconds: number): Promise<void> {
  try {
    await fetch(`${API_URL}/sessions/${encodeURIComponent(sessionId)}/proctor-events`, {
      method: "POST", headers: { "content-type": "application/json", ...(await authHeaders()) },
      body: JSON.stringify({ rule, seconds: Math.min(seconds, MAX_SECONDS) }),
    });
  } catch {
    /* offline or the server is down: nothing to do */
  }
}
