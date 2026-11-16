// Proctor: an optional camera check for interview modes, as in a proctored interview.
//
// Off by default. Turning it on asks for the camera (video only), shows a small mirrored
// preview, and checks about five times a second that a face is towards the screen and both
// hands are in view. When a rule in rules.ts fires, the reminder is shown as a banner, spoken
// in the coach's voice, and recorded as a trace event (rule and duration, nothing else).
//
// The video never leaves this browser: frames go from the <video> element straight into the
// detectors in detector.ts. Turning the proctor off, changing mode, leaving the Workspace or
// unmounting all run the same clean-up, which stops every camera track and closes the detectors.

import { useEffect, useId, useRef, useState } from "react";
import { useApp } from "../app-context";
import { loadDetector, type Detector } from "./detector";
import { reportReminder } from "./remote";
import { PROMPT_GAP_MS, TYPING_MS, start, step, type Reading, type Reminder } from "./rules";
import { createVoice } from "./voice";

/** One detector runs per tick, face and hands in turn, so each samples about 5 times a second
 *  and the page never waits on both at once. */
const SAMPLE_MS = 100;
/** This many frames in a row that cannot be analysed (2 s) means the detector has broken. */
const MAX_FAILED_FRAMES = 20;

type Phase = "asking" | "loading" | "running";
type Problem = "blocked" | "nocamera" | "failed";

const IDLE_COPY = "Optional. Turn it on to be reminded, as in a proctored interview, to keep your eyes on the screen and both hands in view. Your camera is checked in this browser: no video is sent or stored.";
const PHASE_COPY: Record<Phase, string> = {
  asking: "Asking for your camera. Choose Allow when the browser asks.",
  loading: "Loading the detector. The first time takes a few seconds.",
  running: "Checked in this browser only. No video is sent or stored. Reminders go in the activity log.",
};
const PROBLEM_COPY: Record<Problem, string> = {
  blocked: "The camera is blocked for this site, so Proctor is off. To use it, open the site settings from the address bar, set Camera to Allow, then turn Proctor on again. Your interview carries on without it.",
  nocamera: "No camera could be opened, so Proctor is off. Check that one is connected and not in use by another app, then turn Proctor on again. Your interview carries on without it.",
  failed: "The detector could not be loaded, so Proctor and the camera are off. Check your connection, then turn Proctor on again. Your interview carries on without it.",
};

function Check({ label, ok, value }: { label: string; ok: boolean | null; value: string }) {
  return (
    <span className="proctor-chip" data-ok={ok ?? undefined}>
      <i aria-hidden="true" />
      <span>{label}</span>
      <b>{value}</b>
    </span>
  );
}

export function Proctor(props: { sessionId: string | null }) {
  const sessionId = props.sessionId;
  const { page } = useApp();
  const [on, setOn] = useState(false);
  const [phase, setPhase] = useState<Phase>("asking");
  const [problem, setProblem] = useState<Problem | null>(null);
  const [reading, setReading] = useState<Reading | null>(null);
  const [reminder, setReminder] = useState<Reminder | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const session = useRef(sessionId);
  session.current = sessionId;
  const titleId = useId();

  // A new session is a new interview, and the preview lives on the Workspace: either one
  // turns the camera off rather than leaving it running where it cannot be seen.
  useEffect(() => { setOn(false); setProblem(null); }, [sessionId]);
  useEffect(() => { if (page !== "workspace") setOn(false); }, [page]);

  useEffect(() => {
    if (!on) return;
    const el = video.current;
    let stopped = false;
    let stream: MediaStream | null = null;
    let detector: Detector | null = null;
    let sampler: number | undefined;
    let bannerTimer: number | undefined;
    const voice = createVoice();

    /** Turn the proctor off and say why. Flipping `on` runs the clean-up below. */
    const giveUp = (why: Problem) => { if (!stopped) { setProblem(why); setOn(false); } };

    const remind = (next: Reminder) => {
      setReminder(next);
      window.clearTimeout(bannerTimer);
      bannerTimer = window.setTimeout(() => setReminder(null), PROMPT_GAP_MS);
      void voice.say(next.text);
      if (session.current) void reportReminder(session.current, next.rule, next.seconds);
    };

    let state = start(performance.now());
    let typedAt = -Infinity;
    const onKey = () => { typedAt = performance.now(); };
    window.addEventListener("keydown", onKey, true);
    let facing: boolean | null = null;
    let hands: number | null = null;
    let ticks = 0;
    let failures = 0;
    const tick = () => {
      if (!detector || !el || el.readyState < HTMLMediaElement.HAVE_CURRENT_DATA || el.videoWidth === 0) return;
      const now = performance.now();
      try {
        if (ticks++ % 2 === 0) facing = detector.facing(el, now);
        else hands = detector.hands(el, now);
        failures = 0;
      } catch {
        if (++failures >= MAX_FAILED_FRAMES) giveUp("failed");
        return;
      }
      if (facing === null || hands === null) return;
      const seen: Reading = { facing, hands, typing: now - typedAt < TYPING_MS };
      setReading((old) => (old && old.facing === seen.facing && old.hands === seen.hands ? old : seen));
      const next = step(state, seen, now);
      state = next.state;
      if (next.reminder) remind(next.reminder);
    };

    // Sampling stops while the tab is hidden. The rules notice the gap and start their timers
    // again, so time the proctor did not watch is never counted against the candidate.
    const pause = () => { window.clearInterval(sampler); sampler = undefined; };
    const sample = () => { if (sampler === undefined && !document.hidden) sampler = window.setInterval(tick, SAMPLE_MS); };
    const onVisibility = () => (document.hidden ? pause() : sample());

    void (async () => {
      if (!navigator.mediaDevices?.getUserMedia) return giveUp("nocamera");
      let camera: MediaStream;
      try {
        camera = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } } });
      } catch (err) {
        const refused = err instanceof DOMException && (err.name === "NotAllowedError" || err.name === "SecurityError");
        return giveUp(refused ? "blocked" : "nocamera");
      }
      if (stopped) return camera.getTracks().forEach((track) => track.stop()); // turned off while the browser was asking
      stream = camera;
      camera.getVideoTracks()[0]?.addEventListener("ended", () => giveUp("nocamera")); // unplugged, or permission withdrawn
      if (el) { el.srcObject = camera; void el.play().catch(() => undefined); }
      setPhase("loading");

      let loaded: Detector;
      try {
        loaded = await loadDetector();
      } catch {
        return giveUp("failed");
      }
      if (stopped) return loaded.close(); // turned off while the models were downloading
      detector = loaded;
      state = start(performance.now());
      setPhase("running");
      voice.warm();
      document.addEventListener("visibilitychange", onVisibility);
      sample();
    })();

    return () => {
      stopped = true;
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("keydown", onKey, true);
      pause();
      window.clearTimeout(bannerTimer);
      voice.close();
      stream?.getTracks().forEach((track) => track.stop());
      if (el) el.srcObject = null;
      try { detector?.close(); } catch { /* already released */ }
      detector = null;
    };
  }, [on]);

  const toggle = () => {
    setProblem(null); setReading(null); setReminder(null); setPhase("asking");
    setOn((was) => !was);
  };

  const cameraOn = on && phase !== "asking";
  return (
    <section className="proctor" data-on={on || undefined} aria-labelledby={titleId}>
      <div className="proctor-head">
        <span id={titleId} className="proctor-title">Proctor</span>
        {cameraOn && (
          <span className="pill baltic">
            <span className="live-dot" style={{ background: "var(--baltic)" }} aria-hidden="true" />Camera on
          </span>
        )}
        <button type="button" role="switch" aria-checked={on} aria-labelledby={titleId} className="proctor-switch"
          disabled={!sessionId} onClick={toggle}>
          <span className="proctor-track" aria-hidden="true"><i /></span>
          <span>{on ? "On" : "Off"}</span>
        </button>
      </div>

      {/* Always mounted, so the stream has somewhere to go the moment the camera opens. */}
      <div className="proctor-live" hidden={!cameraOn}>
        <div className="proctor-video">
          <video ref={video} muted playsInline aria-label="Your camera, mirrored" />
        </div>
        <div className="proctor-checks">
          <Check label="Eyes on screen" ok={reading ? reading.facing : null} value={reading ? (reading.facing ? "yes" : "no") : "checking"} />
          <Check label="Both hands visible" ok={reading ? reading.hands >= 2 : null} value={reading ? `${reading.hands} of 2` : "checking"} />
        </div>
      </div>

      <div aria-live="polite">
        {on && reminder && (
          <div key={`${reminder.rule}-${reminder.seconds}`} className="proctor-banner">
            <span className="bubble-meta">Proctor</span>
            {reminder.text}
          </div>
        )}
      </div>

      <p className={problem ? "proctor-copy problem" : "proctor-copy"} role="status">
        {problem ? PROBLEM_COPY[problem] : on ? PHASE_COPY[phase] : IDLE_COPY}
      </p>
    </section>
  );
}
