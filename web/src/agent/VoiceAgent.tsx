// The voice agent's control in the header. It connects the ElevenLabs agent to the page
// tools: every tool the agent calls goes through `invoke`, so it can only do what a screen
// has registered. The provider key never reaches the browser; the server issues a signed URL.

import { ConversationProvider, useConversationControls, useConversationMode, useConversationStatus } from "@elevenlabs/react";
import { useMemo, useState } from "react";
import { ApiError, startVoiceSession } from "../api";
import { TOOL_NAMES, invoke, type ToolName, type ToolSignatures } from "./tools";

/** Each page tool, in the shape the voice SDK calls: arguments in, a JSON string back. */
function clientTools(): Record<string, (args: unknown) => Promise<string>> {
  const entries = TOOL_NAMES.map((name) => [
    name,
    async (args: unknown) => JSON.stringify(await invoke(name, (args ?? {}) as ToolSignatures[ToolName][0])),
  ]);
  return Object.fromEntries(entries);
}

function Control() {
  const { startSession, endSession } = useConversationControls();
  const { status } = useConversationStatus();
  const { isSpeaking } = useConversationMode();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tools = useMemo(clientTools, []);

  const start = async () => {
    setStarting(true); setError(null);
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true });
      const { signed_url } = await startVoiceSession();
      await startSession({
        signedUrl: signed_url, connectionType: "websocket", clientTools: tools,
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
  const label = live ? "End voice" : starting || status === "connecting" ? "Connecting…" : "Talk to Senior";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      {live && (
        <span className="pill baltic" aria-live="polite">
          <span className="live-dot" style={{ background: "var(--baltic)" }} />
          {isSpeaking ? "Senior is speaking" : "Listening"}
        </span>
      )}
      {error && <span className="pill sky" role="alert" title={error}>Voice problem: {error.slice(0, 60)}</span>}
      <button className={live ? "btn-ghost" : "btn-primary"} style={{ height: 36 }} disabled={starting || status === "connecting"}
        onClick={() => (live ? void endSession() : void start())}>
        {label}
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
