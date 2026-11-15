// A live feed of what the voice agent is doing on the page: each tool it calls, whether it
// worked, and how long it took. It shows the agent's actions, not its private reasoning.

import { useEffect, useState } from "react";
import { onToolCall, type ToolCall } from "./tools";

const MAX_ROWS = 6;

function summary(args: unknown): string {
  const text = JSON.stringify(args ?? {});
  return text === "{}" ? "" : text.length > 70 ? `${text.slice(0, 67)}…` : text;
}

export function AgentActivity() {
  const [calls, setCalls] = useState<ToolCall[]>([]);
  const [hidden, setHidden] = useState(false);
  useEffect(() => onToolCall((call) => { setHidden(false); setCalls((list) => [...list, call].slice(-MAX_ROWS)); }), []);

  if (calls.length === 0 || hidden) return null;
  return (
    <aside className="agent-activity" aria-label="What Senior is doing" aria-live="polite">
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span className="label">Senior is doing</span>
        <button className="btn-ghost" style={{ height: 28, marginLeft: "auto", padding: "0 10px" }} onClick={() => setHidden(true)}>Hide</button>
      </div>
      {calls.map((call) => (
        <div key={call.id} className="mono" style={{ fontSize: 12, lineHeight: "18px" }}>
          <span className={call.ok ? "seafoam" : "sky"}>{call.ok ? "done" : "failed"}</span>{" "}
          <span>{call.name}</span> <span className="dim">{call.ms} ms</span>
          {summary(call.args) && <div className="dim" style={{ wordBreak: "break-word" }}>{summary(call.args)}</div>}
          {call.error && <div className="sky">{call.error}</div>}
        </div>
      ))}
    </aside>
  );
}
