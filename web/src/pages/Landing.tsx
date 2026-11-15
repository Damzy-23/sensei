import { useState, type CSSProperties } from "react";

// Landing page, rebuilt from the "Landing page" design board.
// Every claim here describes what is built today. Things that are planned
// but not built sit in the separate "Coming next" section.

interface ModeDemo {
  id: "learn" | "interview" | "blitz" | "call";
  label: string;
  color: string;
  tint: string;
  kicker: string;
  title: string;
  body: string;
  coach: string;
  student: string;
  rule: string;
}

const MODES: ModeDemo[] = [
  {
    id: "learn", label: "Learn", color: "var(--seafoam)", tint: "rgba(127, 209, 193, 0.14)",
    kicker: "Learn mode", title: "Hints on, pace yours",
    body: "A Socratic hint coach and no clock. Each request for help moves you one rung up the ladder, and no rung contains code.",
    coach: "What does the shorter wall do to the water level?",
    student: "It limits it, right?",
    rule: "rule mode.learn: session is in learn mode",
  },
  {
    id: "interview", label: "Interview", color: "var(--baltic)", tint: "rgba(107, 159, 224, 0.14)",
    kicker: "Interview mode", title: "No hints, real questions",
    body: "An interviewer asks for your approach and its cost, then probes one edge case at a time, the way an interviewer asks. It does not teach.",
    coach: "Walk me through your approach before you code. What is the time complexity?",
    student: "Two pointers, so O(n).",
    rule: "rule mode.interview: session is in interview mode",
  },
  {
    id: "blitz", label: "Blitz", color: "var(--sky)", tint: "rgba(134, 187, 216, 0.16)",
    kicker: "Blitz mode", title: "The same interview, on a clock",
    body: "A ten-minute countdown on the interview, plus the Blitz lab: name the pattern for a problem before the timer runs out.",
    coach: "Sorted array, find a pair with a target sum. Which pattern?",
    student: "Two pointers.",
    rule: "rule mode.blitz: session is in blitz mode, timed",
  },
  {
    id: "call", label: "Call", color: "var(--baltic)", tint: "rgba(107, 159, 224, 0.14)",
    kicker: "Call mode", title: "An interviewer who talks like one",
    body: "A phone-style interviewer: short spoken sentences, one question at a time. You type to it here; a phone line is not connected yet.",
    coach: "Before any code, tell me in your own words what the problem is asking.",
    student: "Find two positions whose values add up to the target.",
    rule: "rule mode.call: session is a live phone interview",
  },
];

const TICKER = ["HINT LADDER", "INPUT GUARD", "LEAK CHECK", "RULE-BASED ROUTING", "TRACE EVERYTHING", "HUMAN MENTOR", "BLIND 75", "NEETCODE 150"];

const FEATURES: { n: string; color: string; title: string; body: string }[] = [
  {
    n: "01", color: "var(--sky)", title: "Hints are earned",
    body: "Five rungs, from clarifying the problem to a worked example in words. Each request for help moves one rung up. No rung contains code.",
  },
  {
    n: "02", color: "var(--seafoam)", title: "Decisions with reasons",
    body: "Plain rules, not a model, pick the agent and the hint level. The rule that fired is recorded and shown in the agent inspector.",
  },
  {
    n: "03", color: "var(--sky)", title: "Guards that show up",
    body: "Injection and off-topic messages are stopped before an agent sees them. Every reply is checked for leaked code before you see it.",
  },
  {
    n: "04", color: "var(--baltic)", title: "A human on call",
    body: "Still stuck after the last rung? A mentor gets your transcript, your code and a summary of where you are, and replies in your chat.",
  },
];

const BUILT: string[] = [
  "Agent inspector: model, tokens, cost, latency and the reason for every step",
  "Blind 75 and NeetCode 150, grouped by pattern",
  "Python tests that run in your browser",
];

const COMING: string[] = [
  "Interviews by phone call",
  "Diagrams drawn while the coach explains",
  "Generated concept videos",
  "A fine-tuned hint model",
  "Accounts with history across sessions",
];

const sectionWrap: CSSProperties = { width: "100%", maxWidth: 1240, margin: "0 auto", padding: "0 clamp(16px, 4vw, 56px)" };
const well: CSSProperties = { flex: "1 1 280px", minWidth: 0, padding: 22, borderRadius: 20, background: "var(--well)", border: "1px solid var(--line)" };

export function Logo() {
  return (
    <span className="brand-mark" style={{ width: 42, height: 42 }}>
      <svg width="25" height="29" viewBox="380 230 520 720" aria-hidden="true">
        <defs>
          <linearGradient id="senior-mark-landing" gradientUnits="userSpaceOnUse" x1="440" y1="260" x2="860" y2="900">
            <stop offset="0" stopColor="#86BBD8" />
            <stop offset="1" stopColor="#5F9CC4" />
          </linearGradient>
        </defs>
        <path d="M780 313 L560 382 C480 410 445 450 445 475 C445 510 480 535 545 555 L740 622 C790 640 822 675 822 710 C822 750 790 785 735 805 L483 871" fill="none" stroke="url(#senior-mark-landing)" strokeWidth="100" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  );
}

export function Landing({ onStart }: { onStart: () => void }) {
  const [selected, setSelected] = useState(0);
  const mode = MODES[selected];

  return (
    <main style={{ position: "relative", minHeight: "100vh", overflow: "hidden", paddingBottom: 72, display: "flex", flexDirection: "column" }}>
      <div aria-hidden="true" style={{
        position: "absolute", top: -260, left: "50%", width: "min(840px, 120vw)", height: 620, transform: "translateX(-50%)",
        borderRadius: 999, filter: "blur(100px)", pointerEvents: "none",
        background: "radial-gradient(circle, rgba(134, 187, 216, 0.42), rgba(134, 187, 216, 0) 70%)",
      }} />

      <header style={{ ...sectionWrap, position: "relative", zIndex: 2, display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap", paddingTop: 22, paddingBottom: 22 }}>
        <div className="brand" style={{ fontSize: 24 }}><Logo />Senior</div>
        <button className="btn-ghost" style={{ marginLeft: "auto" }} onClick={onStart}>Open the demo</button>
      </header>

      <section aria-label="Introduction" style={{ ...sectionWrap, position: "relative", zIndex: 2, textAlign: "center", paddingTop: "clamp(40px, 8vw, 84px)", paddingBottom: 36, display: "flex", flexDirection: "column", alignItems: "center", gap: 26 }}>
        <span className="pill sky" style={{ padding: "8px 16px", fontWeight: 500, fontSize: 13, background: "rgba(134, 187, 216, 0.08)", whiteSpace: "normal" }}>
          AI coding-interview coach · built to teach, not to answer
        </span>
        <h1 style={{ fontSize: "clamp(40px, 8vw, 104px)", lineHeight: 0.98, letterSpacing: "clamp(-5px, -0.4vw, -1.5px)", maxWidth: 1100 }}>
          Practice with a coach that{" "}
          <span style={{ background: "var(--sky-grad)", WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent" }}>never gives it away</span>
        </h1>
        <p className="muted" style={{ margin: 0, maxWidth: 640, fontSize: "clamp(16px, 2vw, 20px)", lineHeight: 1.5 }}>
          Choose Learn, Interview, Blitz or Call. Senior hands out hints one rung at a time, checks every reply for leaked code, and brings in a human mentor when you are truly stuck.
        </p>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", justifyContent: "center" }}>
          <button className="btn-primary" style={{ height: 54, padding: "0 24px", fontSize: 16, borderRadius: 14 }} onClick={onStart}>Start a session</button>
          <button className="btn-ghost" style={{ height: 54, padding: "0 24px", fontSize: 16, borderRadius: 14 }} onClick={onStart}>See every agent step</button>
        </div>
      </section>

      <section aria-label="The four modes" style={{ ...sectionWrap, maxWidth: 1040, position: "relative", zIndex: 2, marginTop: 30 }}>
        <div style={{ padding: "clamp(12px, 2vw, 20px)", borderRadius: 28, background: "linear-gradient(180deg, rgba(21, 35, 45, 0.9), rgba(16, 28, 36, 0.9))", border: "1px solid rgba(255, 255, 255, 0.09)", boxShadow: "0 40px 100px -30px rgba(134, 187, 216, 0.35)" }}>
          <div role="tablist" aria-label="Mode" style={{ display: "flex", flexWrap: "wrap", gap: 4, padding: 4, borderRadius: 24, background: "var(--well)", border: "1px solid rgba(255, 255, 255, 0.08)", maxWidth: 560, margin: "0 auto 20px" }}>
            {MODES.map((m, i) => {
              const on = i === selected;
              return (
                <button key={m.id} role="tab" id={`landing-tab-${m.id}`} aria-selected={on} aria-controls="landing-mode-panel" onClick={() => setSelected(i)}
                  style={{
                    flex: "1 1 96px", height: 44, borderRadius: 999, font: "600 14px var(--body)", transition: "all 0.3s var(--ease)",
                    border: `1px solid ${on ? m.color : "transparent"}`, background: on ? m.tint : "transparent", color: on ? m.color : "var(--text-2)",
                  }}>
                  {m.label}
                </button>
              );
            })}
          </div>
          <div key={mode.id} id="landing-mode-panel" role="tabpanel" aria-labelledby={`landing-tab-${mode.id}`} style={{ display: "flex", flexWrap: "wrap", gap: 20, alignItems: "stretch", animation: "fade 0.5s var(--ease) both" }}>
            <div style={well}>
              <div className="label" style={{ color: mode.color }}>{mode.kicker}</div>
              <h2 style={{ marginTop: 8, fontSize: 28, lineHeight: "32px", letterSpacing: "-0.6px" }}>{mode.title}</h2>
              <p className="muted" style={{ margin: "10px 0 0", fontSize: 15, lineHeight: "23px" }}>{mode.body}</p>
            </div>
            <div style={{ ...well, display: "flex", flexDirection: "column", gap: 10, justifyContent: "center" }}>
              <div className="label">Example exchange</div>
              <div className="bubble coach" style={{ fontSize: 14, lineHeight: "21px", maxWidth: "92%", animation: "none" }}>{mode.coach}</div>
              <div className="bubble student" style={{ fontSize: 14, lineHeight: "21px", maxWidth: "92%", animation: "none" }}>{mode.student}</div>
              <div className="mono muted" style={{ padding: "8px 12px", borderRadius: 12, border: "1px dashed var(--border)", fontSize: 12, overflowWrap: "anywhere" }}>{mode.rule}</div>
            </div>
          </div>
        </div>
      </section>

      <section aria-label="What is inside" style={{ position: "relative", zIndex: 2, marginTop: 70, borderTop: "1px solid rgba(255, 255, 255, 0.06)", borderBottom: "1px solid rgba(255, 255, 255, 0.06)", padding: "22px clamp(16px, 4vw, 56px)", background: "rgba(16, 28, 36, 0.6)" }}>
        <ul className="mono dim" style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexWrap: "wrap", justifyContent: "center", gap: "10px 40px", fontSize: 15, fontWeight: 500 }}>
          {TICKER.map((item) => <li key={item}>{item}</li>)}
        </ul>
      </section>

      <section aria-label="Why it can be trusted" style={{ ...sectionWrap, position: "relative", zIndex: 2, paddingTop: "clamp(48px, 8vw, 90px)" }}>
        <h2 style={{ margin: "0 0 34px", fontSize: "clamp(30px, 5vw, 52px)", lineHeight: 1.05, letterSpacing: "-2px", maxWidth: 760 }}>Four things that make it trustworthy</h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(260px, 100%), 1fr))", gap: 18 }}>
          {FEATURES.map((f) => (
            <div key={f.n} className="card" style={{ padding: 26, borderRadius: 24 }}>
              <div className="mono" style={{ fontSize: 12, fontWeight: 500, color: f.color }}>{f.n}</div>
              <h3 style={{ marginTop: 12, fontSize: 22 }}>{f.title}</h3>
              <p className="muted" style={{ margin: "8px 0 0", lineHeight: "22px" }}>{f.body}</p>
            </div>
          ))}
        </div>
        <ul style={{ listStyle: "none", margin: "22px 0 0", padding: 0, display: "flex", flexWrap: "wrap", gap: 10 }}>
          {BUILT.map((item) => <li key={item} className="chip seafoam" style={{ whiteSpace: "normal", padding: "6px 12px" }}>{item}</li>)}
        </ul>
      </section>

      <section aria-label="Coming next" style={{ ...sectionWrap, position: "relative", zIndex: 2, paddingTop: "clamp(40px, 6vw, 70px)" }}>
        <div style={{ padding: "clamp(18px, 3vw, 28px)", borderRadius: 24, border: "1px dashed var(--border)", background: "rgba(16, 28, 36, 0.5)" }}>
          <div className="label">Coming next · not built yet</div>
          <p className="muted" style={{ margin: "8px 0 14px", maxWidth: 640 }}>These are planned. None of them is in the demo today.</p>
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexWrap: "wrap", gap: 10 }}>
            {COMING.map((item) => <li key={item} className="chip" style={{ color: "var(--text-2)", whiteSpace: "normal", padding: "6px 12px" }}>{item}</li>)}
          </ul>
        </div>
      </section>

      <section aria-label="Get started" style={{ ...sectionWrap, maxWidth: 1040, position: "relative", zIndex: 2, marginTop: "clamp(56px, 9vw, 110px)", textAlign: "center" }}>
        <div style={{ padding: "clamp(32px, 6vw, 60px) clamp(18px, 4vw, 40px)", borderRadius: 32, background: "rgba(134, 187, 216, 0.14)", border: "1px solid rgba(134, 187, 216, 0.4)" }}>
          <h2 style={{ fontSize: "clamp(30px, 5.5vw, 56px)", lineHeight: 1.05, letterSpacing: "-2px" }}>Get unstuck without getting the answer</h2>
          <div style={{ marginTop: 28 }}>
            <button className="btn-primary" style={{ height: 54, padding: "0 24px", fontSize: 16, borderRadius: 14 }} onClick={onStart}>Try the demo</button>
          </div>
        </div>
      </section>

      <footer className="site-footer" style={{ ...sectionWrap, maxWidth: 1040 }}>
        <span>Senior, built at the Imperial AI Hack, November 2026.</span>
        <a href="/privacy">Privacy</a>
        <a href="/tos">Terms</a>
      </footer>
    </main>
  );
}
