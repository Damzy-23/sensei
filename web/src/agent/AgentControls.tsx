// Registers the control tools (see_screen, press, type_into, pick_option, read_screen,
// scroll_to) once for the whole app, and shows the prompt that asks the student before an
// action that is theirs to take: "Senior wants to: Sign out. Allow / Not now".
//
// The prompt is not part of what Senior can see or press (data-agent="off"), and Allow only
// counts a real click or key press from the student: a click made by script is ignored.

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { pickOption, press, readScreen, scrollTo, seeScreen, setAsker, typeInto, type Answer } from "./controls";
import { registerTool } from "./tools";

const ASK_MS = 20_000;
const GAP = 24;

interface Question { id: number; what: string; answer: (answer: Answer) => void }
type Box = { top: number; bottom: number; left: number; right: number };

/** How much of `a` lies over `b`, with a small margin so the two never touch. */
function overlap(a: Box, b: DOMRect): number {
  const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
  const h = Math.min(a.bottom + 8, b.bottom) - Math.max(a.top - 8, b.top);
  return w > 0 && h > 0 ? w * h : 0;
}

export function AgentControls() {
  const [question, setQuestion] = useState<Question | null>(null);
  const [top, setTop] = useState<number | null>(null); // null: bottom centre
  const box = useRef<HTMLDivElement>(null);
  const notNow = useRef<HTMLButtonElement>(null);
  const returnTo = useRef<HTMLElement | null>(null);
  const open = useRef<Question | null>(null);

  useEffect(() => {
    let count = 0;
    setAsker((what) => new Promise<Answer>((resolve) => {
      returnTo.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      let done = false;
      const finish = (answer: Answer) => {
        if (done) return;
        done = true;
        window.clearTimeout(timer);
        open.current = null;
        setQuestion(null);
        resolve(answer);
      };
      const timer = window.setTimeout(() => finish("timeout"), ASK_MS);
      open.current = { id: count++, what, answer: finish };
      setQuestion(open.current);
    }));
    const offs = [
      registerTool("see_screen", () => seeScreen()),
      registerTool("press", (args) => press(args)),
      registerTool("type_into", (args) => typeInto(args)),
      registerTool("pick_option", (args) => pickOption(args)),
      registerTool("read_screen", (args) => readScreen(args)),
      registerTool("scroll_to", (args) => scrollTo(args)),
    ];
    return () => {
      open.current?.answer("timeout");
      setAsker(null);
      offs.forEach((off) => off());
    };
  }, []);

  // Focus goes to the prompt (to Not now, so a stray Enter declines), and back where it was after.
  useEffect(() => {
    if (question) { notNow.current?.focus(); return; }
    const back = returnTo.current;
    returnTo.current = null;
    if (back?.isConnected && document.activeElement === document.body) back.focus({ preventScroll: true });
  }, [question]);

  // Escape is Not now. Only a real key press counts, and it goes no further (the glass would lower too).
  useEffect(() => {
    if (!question) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || !event.isTrusted) return;
      event.preventDefault();
      event.stopPropagation();
      question.answer("deny");
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [question]);

  // Bottom centre, unless that would cover the Workspace message box: then just under the top bar.
  useLayoutEffect(() => {
    if (!question) return;
    let frame = 0;
    const place = () => {
      const el = box.current;
      if (!el) return;
      const w = el.offsetWidth, h = el.offsetHeight, vw = window.innerWidth, vh = window.innerHeight;
      const left = (vw - w) / 2;
      const bar = document.querySelector(".topbar")?.getBoundingClientRect();
      const high = Math.max(16, (bar && bar.bottom > 0 ? bar.bottom : 0) + 12);
      const message = document.getElementById("message")?.getBoundingClientRect();
      if (!message || message.width === 0) { setTop(null); return; }
      const low = overlap({ top: vh - GAP - h, bottom: vh - GAP, left, right: left + w }, message);
      const up = overlap({ top: high, bottom: high + h, left, right: left + w }, message);
      setTop(low > 0 && up < low ? high : null);
    };
    const later = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(place); };
    place();
    window.addEventListener("scroll", later, true);
    window.addEventListener("resize", later);
    return () => { cancelAnimationFrame(frame); window.removeEventListener("scroll", later, true); window.removeEventListener("resize", later); };
  }, [question]);

  if (!question) return null;
  return (
    <div ref={box} className={`agent-ask${top !== null ? " top" : ""}`} style={top !== null ? { top } : undefined}
      role="alertdialog" aria-modal="false" aria-labelledby="agent-ask-title" aria-describedby="agent-ask-what"
      data-agent="off" tabIndex={-1}>
      <span id="agent-ask-title" className="label">Senior is asking you</span>
      <div id="agent-ask-what" className="agent-ask-what" aria-live="assertive">
        Senior wants to: <b>{question.what}</b>
      </div>
      <div className="agent-ask-row">
        <button type="button" className="btn-primary"
          onClick={(event) => { if (event.nativeEvent.isTrusted) question.answer("allow"); }}>
          Allow
        </button>
        <button ref={notNow} type="button" className="btn-ghost" onClick={() => question.answer("deny")}>Not now</button>
      </div>
      <div className="agent-ask-clock" aria-hidden="true"><span key={question.id} /></div>
      <span className="dim agent-ask-note">No answer in 20 seconds counts as not now.</span>
    </div>
  );
}
