// What the voice coach just did on the page: the most recent action only, whether it worked,
// and how long it took. It shows the agent's actions, not its private reasoning.
// It appears when the agent acts and leaves by itself a second later; hovering keeps it open.

import { useEffect, useRef, useState } from "react";
import { onToolCall, type ToolCall, type ToolName } from "./tools";


/** What each tool call means to the student. One coach is acting, so none of these names a second party. */
const PLAIN: Record<ToolName, string> = {
  get_page_state: "Looked at your screen",
  read_problem: "Read the problem",
  read_code: "Read your code",
  read_conversation: "Read our conversation",
  run_code: "Ran your code",
  run_tests: "Ran the tests",
  ask_coach: "Thought about your question",
  explain_last_turn: "Looked up why I said that",
  search_problems: "Searched the problems",
  open_problem: "Opened a problem",
  set_mode: "Switched mode",
  navigate: "Switched screen",
  highlight_lines: "Pointed at your code",
  clear_highlight: "Stopped pointing",
  glass_array: "Drew an array",
  glass_steps: "Wrote out the steps",
  glass_note: "Pinned a note",
  glass_3d: "Drew a 3D picture",
  glass_clear: "Cleared the glass",
  play_explainer: "Played an explainer",
  propose_calendar_event: "Offered a practice slot",
  write_line: "Wrote a line into your code",
};

const SHOW_MS = 1000; // how long the panel stays after the last action
const SHOW_FAILURE_MS = 4000; // a failure stays longer: it is the one thing worth reading
const OFF_KEY = "senior.activity.off";

function savedOff(): boolean {
  try { return localStorage.getItem(OFF_KEY) === "1"; } catch { return false; }
}

export function AgentActivity() {
  const [latest, setLatest] = useState<ToolCall | null>(null); // one line: the most recent action only
  const [visible, setVisible] = useState(false);
  const [off, setOff] = useState(savedOff);
  const timer = useRef<number | undefined>(undefined);
  const hovering = useRef(false);

  const hideLater = (ms: number) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => { if (!hovering.current) setVisible(false); }, ms);
  };

  useEffect(() => {
    const stop = onToolCall((call) => {
      setLatest(call);
      setVisible(true);
      hideLater(call.ok ? SHOW_MS : SHOW_FAILURE_MS);
    });
    return () => { stop(); window.clearTimeout(timer.current); };
  }, []);

  const turnOff = (next: boolean) => {
    setOff(next);
    try { localStorage.setItem(OFF_KEY, next ? "1" : "0"); } catch { /* private window: lasts for this visit only */ }
    if (!next && latest) { setVisible(true); hideLater(SHOW_FAILURE_MS); }
  };

  if (off) {
    // Turned off for good: one small, quiet control to bring it back, and nothing else.
    return (
      <button type="button" className="agent-activity-toggle" aria-pressed="true" title="Show what Senior is doing"
        onClick={() => turnOff(false)}>
        <span aria-hidden="true">···</span><span className="sr-only">Show what Senior is doing</span>
      </button>
    );
  }
  if (!latest || !visible) return null;
  return (
    <aside className="agent-activity" aria-label="What Senior is doing" aria-live="polite"
      onMouseEnter={() => { hovering.current = true; window.clearTimeout(timer.current); }}
      onMouseLeave={() => { hovering.current = false; hideLater(SHOW_MS); }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span className="label">Senior is doing</span>
        <button className="btn-ghost" style={{ height: 28, marginLeft: "auto", padding: "0 10px" }} onClick={() => turnOff(true)}>Always hide</button>
      </div>
      <div className="mono" style={{ fontSize: 12, lineHeight: "18px" }}>
        <span className={latest.ok ? "seafoam" : "sky"}>{latest.ok ? "done" : "failed"}</span>{" "}
        <span title={`tool: ${latest.name}`}>{PLAIN[latest.name] ?? latest.name}</span> <span className="dim">{latest.ms} ms</span>
        {latest.error && <div className="sky">{latest.error}</div>}
      </div>
    </aside>
  );
}
