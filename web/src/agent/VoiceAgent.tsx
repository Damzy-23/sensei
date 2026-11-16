// The voice agent's control in the header. It connects the ElevenLabs agent to the page
// tools: every tool the agent calls goes through `invoke`, so it can only do what a screen
// has registered. The provider key never reaches the browser; the server issues a signed URL.

import { ConversationProvider, useConversationControls, useConversationMode, useConversationStatus } from "@elevenlabs/react";
import { useMemo, useState } from "react";
import { ApiError, startVoiceSession } from "../api";
import { useAuth } from "../auth";
import personas from "./personas.json";
import { TOOL_NAMES, invoke, type ToolName, type ToolSignatures } from "./tools";
import { voiceCall } from "./callState";

type PersonaId = keyof typeof personas;
const PERSONA_IDS = Object.keys(personas) as PersonaId[];
const remembered = (key: string) => { try { return localStorage.getItem(key) ?? ""; } catch { return ""; } };
const remember = (key: string, value: string) => { try { localStorage.setItem(key, value); } catch { /* private window */ } };

/** Each page tool, in the shape the voice SDK calls: arguments in, a JSON string back. */
function clientTools(): Record<string, (args: unknown) => Promise<string>> {
  const entries = TOOL_NAMES.map((name) => [
    name,
    async (args: unknown) => JSON.stringify(await invoke(name, (args ?? {}) as ToolSignatures[ToolName][0])),
  ]);
  return Object.fromEntries(entries);
}

const PHONE = "M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z";

/** Call and hang-up icons: the same handset, turned face down to hang up. */
function PhoneIcon({ hangUp = false }: { hangUp?: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" style={{ transform: hangUp ? "rotate(135deg)" : undefined, flex: "none" }}>
      <path d={PHONE} />
    </svg>
  );
}

function Control() {
  const { startSession, endSession, sendUserMessage } = useConversationControls();
  const [typed, setTyped] = useState("");
  const { status } = useConversationStatus();
  const { isSpeaking } = useConversationMode();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tools = useMemo(clientTools, []);
  const { user } = useAuth();
  const [name, setName] = useState(() => remembered("senior.name") || user?.displayName?.split(" ")[0] || "");
  const [personaId, setPersonaId] = useState<PersonaId>(() => {
    const saved = remembered("senior.persona") as PersonaId;
    return PERSONA_IDS.includes(saved) ? saved : "mentor";
  });

  const start = async () => {
    setStarting(true); setError(null);
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true });
      const { signed_url } = await startVoiceSession();
      const persona = personas[personaId];
      const who = name.trim();
      remember("senior.name", who); remember("senior.persona", personaId);
      await startSession({
        signedUrl: signed_url, connectionType: "websocket", clientTools: tools,
        overrides: { tts: { voiceId: persona.voice_id } },
        dynamicVariables: {
          user_name: who || "unknown",
          persona_style: persona.style,
          first_line: who ? persona.greeting_known.split("NAME").join(who) : persona.greeting_unknown,
        },
        onError: (message: string) => setError(message),
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === "NotAllowedError") setError("Microphone access was blocked. Allow it in the browser to talk to Senior.");
      else if (err instanceof ApiError && err.status === 503) setError("Voice is not set up on this server.");
      else setError(err instanceof Error ? err.message : String(err));
    } finally {
      setStarting(false);
    }
  };

  const live = status === "connected";
  voiceCall.live = live;
  const label = live ? "Hang up" : starting || status === "connecting" ? "Connecting…" : "Call Senior";
  return (
    <div className="voice-bar">
      {live && (
        <span className="pill baltic" aria-live="polite">
          <span className="live-dot" style={{ background: "var(--baltic)" }} />
          {isSpeaking ? "Senior is speaking" : "Listening"}
        </span>
      )}
      {live && (
        <form className="voice-type" onSubmit={(e) => { e.preventDefault(); if (typed.trim()) { sendUserMessage(typed.trim()); setTyped(""); } }}>
          <label className="dim" style={{ fontSize: 12, alignSelf: "center" }} htmlFor="voice-text">Or type</label>
          <input id="voice-text" className="input voice-text" value={typed}
            placeholder="Open two sum…" onChange={(e) => setTyped(e.target.value)} />
        </form>
      )}
      {error && <span className="pill sky" role="alert" title={error}>Voice problem: {error.slice(0, 60)}</span>}
      {!live && (
        <>
          <label className="dim voice-label" htmlFor="voice-name">Your name</label>
          <input id="voice-name" className="input voice-name" value={name}
            placeholder="Your name" onChange={(e) => setName(e.target.value)} />
          <label className="dim voice-label" htmlFor="voice-persona">Coach's style</label>
          <select id="voice-persona" className="select voice-persona" value={personaId}
            title={personas[personaId].blurb} onChange={(e) => setPersonaId(e.target.value as PersonaId)}>
            {PERSONA_IDS.map((id) => <option key={id} value={id}>{personas[id].label}</option>)}
          </select>
        </>
      )}
      <button className={live ? "btn-ghost" : "btn-primary"} style={{ height: 36 }} disabled={starting || status === "connecting"}
        data-agent={live ? undefined : "confirm"}
        onClick={() => (live ? void endSession() : void start())}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}><PhoneIcon hangUp={live} />{label}</span>
      </button>
    </div>
  );
}

export function VoiceAgent() {
  return (
    <ConversationProvider>
      <Control />
    </ConversationProvider>
  );
}
