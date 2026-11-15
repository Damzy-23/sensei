// The explainer: a short narrated walkthrough the agent plays for the student.
//
// The agent sends a title and a list of scenes through the play_explainer tool. Each scene
// has a caption, read aloud in the coach's own voice, and optionally a row of values with
// pointers. Scenes advance when the narration of each one ends, so words and picture stay
// together. It is an animation drawn in the page, not a rendered video file.
//
// Narration comes from the server (POST /voice/tts), which speaks in the voice of the coach
// the student chose. All scenes are requested when the explainer opens, so there is no gap
// between them. If a scene's audio cannot be fetched or played, that scene falls back to the
// browser's built-in speech rather than playing in silence.

import { useCallback, useEffect, useRef, useState } from "react";
import { API_URL, authHeaders } from "../api";
import { LOOKS_LIKE_CODE, parsePointers } from "./Glass";
import { registerTool } from "./tools";

interface Scene { caption: string; values: string[]; pointers: Map<number, string[]> }
interface Show { title: string; scenes: Scene[] }

const MIN_SCENES = 2;
const MAX_SCENES = 10;
const MAX_CELLS = 12;
const WORDS_PER_SECOND = 2.6; // an unhurried speaking pace
const MIN_SCENE_SECONDS = 3;
const GAP_MS = 500;

const PERSONAS = ["drill", "mentor", "peer"];

/** The coach the student picked for their call, so the explainer speaks in the same voice. */
function chosenPersona(): string {
  try {
    const saved = localStorage.getItem("senior.persona") ?? "";
    return PERSONAS.includes(saved) ? saved : "mentor";
  } catch {
    return "mentor";
  }
}

/** Fetch one caption as speech. Resolves to an object URL, or null when it could not be made. */
async function fetchNarration(caption: string, persona: string): Promise<string | null> {
  try {
    const response = await fetch(`${API_URL}/voice/tts`, {
      method: "POST", headers: { "content-type": "application/json", ...(await authHeaders()) },
      body: JSON.stringify({ text: caption, persona }),
    });
    if (!response.ok) return null;
    return URL.createObjectURL(await response.blob());
  } catch {
    return null;
  }
}

const sceneSeconds = (caption: string) => Math.max(MIN_SCENE_SECONDS, caption.trim().split(/\s+/).length / WORDS_PER_SECOND + 0.8);

export function Explainer() {
  const [show, setShow] = useState<Show | null>(null);
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [finished, setFinished] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const playing = useRef<HTMLAudioElement | null>(null);
  const narration = useRef<Promise<string | null>[]>([]);

  const stopAudio = () => {
    window.clearTimeout(timer.current);
    window.speechSynthesis?.cancel();
    playing.current?.pause();
    playing.current = null;
  };
  /** Release the audio of the explainer that is ending. */
  const dropNarration = () => {
    narration.current.forEach((pending) => void pending.then((url) => { if (url) URL.revokeObjectURL(url); }));
    narration.current = [];
  };
  const close = useCallback(() => { stopAudio(); dropNarration(); setShow(null); }, []);

  useEffect(() => registerTool("play_explainer", ({ title, scenes }) => {
    if (!Array.isArray(scenes) || scenes.length < MIN_SCENES) throw new Error(`Send at least ${MIN_SCENES} scenes.`);
    if (scenes.length > MAX_SCENES) throw new Error(`Send at most ${MAX_SCENES} scenes.`);
    const parsed = scenes.map((scene, i) => {
      const caption = String(scene.caption ?? "").trim();
      if (!caption) throw new Error(`Scene ${i + 1} has no caption.`);
      if (LOOKS_LIKE_CODE.test(caption)) throw new Error("Explainers do not show code. Describe it in words.");
      const values = String(scene.values ?? "").split(",").map((v) => v.trim()).filter(Boolean);
      if (values.length > MAX_CELLS) throw new Error(`Scene ${i + 1} has more than ${MAX_CELLS} cells.`);
      return { caption, values, pointers: parsePointers(String(scene.pointers ?? ""), values.length) };
    });
    stopAudio();
    dropNarration();
    const persona = chosenPersona();
    narration.current = parsed.map((scene) => fetchNarration(scene.caption, persona));
    setShow({ title: String(title ?? "").trim() || "Explainer", scenes: parsed });
    setIndex(0); setPaused(false); setFinished(false);
    return { playing: true as const, scenes: parsed.length, seconds: Math.round(parsed.reduce((sum, s) => sum + sceneSeconds(s.caption), 0)) };
  }), []);

  // Play the current scene: speak its caption, then move on when the speech ends.
  // The coach's voice is used when its audio arrived; otherwise the browser speaks the scene.
  // A timer backs both up, so a scene can never hang if an "ended" event does not fire.
  useEffect(() => {
    if (!show || paused || finished) return;
    const scene = show.scenes[index];
    let moved = false;
    let cancelled = false;
    const next = () => {
      if (moved || cancelled) return;
      moved = true;
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => {
        if (index + 1 < show.scenes.length) setIndex(index + 1); else setFinished(true);
      }, GAP_MS);
    };
    const fallbackMs = sceneSeconds(scene.caption) * 1000;

    const speakWithBrowser = () => {
      if (cancelled || moved) return;
      const canSpeak = typeof window.speechSynthesis !== "undefined" && typeof SpeechSynthesisUtterance !== "undefined";
      window.clearTimeout(timer.current);
      if (!canSpeak) { timer.current = window.setTimeout(next, fallbackMs); return; }
      const speech = new SpeechSynthesisUtterance(scene.caption);
      speech.onend = next;
      speech.onerror = () => { timer.current = window.setTimeout(next, fallbackMs); };
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(speech);
      timer.current = window.setTimeout(next, fallbackMs * 1.8 + 2000);
    };

    void (narration.current[index] ?? Promise.resolve(null)).then((url) => {
      if (cancelled) return;
      if (!url) { speakWithBrowser(); return; }
      const audio = new Audio(url);
      playing.current = audio;
      audio.onended = next;
      audio.onerror = speakWithBrowser;
      timer.current = window.setTimeout(next, fallbackMs * 1.8 + 4000);
      audio.play().catch(speakWithBrowser);
    });

    return () => { cancelled = true; stopAudio(); };
  }, [show, index, paused, finished]);

  useEffect(() => () => { stopAudio(); dropNarration(); }, []);

  if (!show) return null;
  const scene = show.scenes[index];
  return (
    <div className="explainer-backdrop" role="dialog" aria-modal="true" aria-label={`Explainer: ${show.title}`}>
      <div className="explainer">
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <div>
            <div className="label">Explainer · scene {index + 1} of {show.scenes.length}</div>
            <h2 style={{ marginTop: 2 }}>{show.title}</h2>
          </div>
          <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
            {finished
              ? <button className="btn-primary" style={{ height: 36 }} onClick={() => { setIndex(0); setFinished(false); setPaused(false); }}>Play again</button>
              : <button className="btn-ghost" style={{ height: 36 }} onClick={() => { if (!paused) stopAudio(); setPaused(!paused); }}>{paused ? "Resume" : "Pause"}</button>}
            <button className="btn-ghost" style={{ height: 36 }} onClick={close}>Close</button>
          </div>
        </div>

        <div className="explainer-stage" aria-live="polite">
          {scene.values.length > 0 && (
            <div className="explainer-cells">
              {scene.values.map((value, i) => (
                <div key={i} className="explainer-cell" data-pointed={scene.pointers.has(i) || undefined}>
                  <span className="dim mono" style={{ fontSize: 11 }}>{i}</span>
                  <span className="box">{value}</span>
                  <span className="mono sky" style={{ fontSize: 13, minHeight: 18 }}>{scene.pointers.get(i)?.join(" ") ?? ""}</span>
                </div>
              ))}
            </div>
          )}
          <div key={index} className="explainer-caption">{scene.caption}</div>
        </div>

        <div className="explainer-progress" aria-hidden="true">
          {show.scenes.map((_, i) => <span key={i} data-done={i < index || finished || undefined} data-now={(i === index && !finished) || undefined} />)}
        </div>
      </div>
    </div>
  );
}
