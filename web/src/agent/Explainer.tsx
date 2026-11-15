// The explainer: a short narrated walkthrough the agent plays for the student.
//
// The agent sends a title and a list of scenes through the play_explainer tool. Each scene
// has a caption, read aloud by the browser's own speech, and optionally a row of values with
// pointers. Scenes advance when the narration of each one ends, so words and picture stay
// together. It is an animation drawn in the page, not a rendered video file.

import { useCallback, useEffect, useRef, useState } from "react";
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

const sceneSeconds = (caption: string) => Math.max(MIN_SCENE_SECONDS, caption.trim().split(/\s+/).length / WORDS_PER_SECOND + 0.8);

export function Explainer() {
  const [show, setShow] = useState<Show | null>(null);
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [finished, setFinished] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  const stopAudio = () => { window.clearTimeout(timer.current); window.speechSynthesis?.cancel(); };
  const close = useCallback(() => { stopAudio(); setShow(null); }, []);

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
    setShow({ title: String(title ?? "").trim() || "Explainer", scenes: parsed });
    setIndex(0); setPaused(false); setFinished(false);
    return { playing: true as const, scenes: parsed.length, seconds: Math.round(parsed.reduce((sum, s) => sum + sceneSeconds(s.caption), 0)) };
  }), []);

  // Play the current scene: speak its caption, then move on when the speech ends.
  // Without speech in this browser, or if it never reports an end, a timer advances instead.
  useEffect(() => {
    if (!show || paused || finished) return;
    const scene = show.scenes[index];
    let moved = false;
    const next = () => {
      if (moved) return;
      moved = true;
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => {
        if (index + 1 < show.scenes.length) setIndex(index + 1); else setFinished(true);
      }, GAP_MS);
    };
    const fallbackMs = sceneSeconds(scene.caption) * 1000;
    const canSpeak = typeof window.speechSynthesis !== "undefined" && typeof SpeechSynthesisUtterance !== "undefined";
    if (canSpeak) {
      const speech = new SpeechSynthesisUtterance(scene.caption);
      speech.rate = 1;
      speech.onend = next;
      speech.onerror = () => { timer.current = window.setTimeout(next, fallbackMs); };
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(speech);
      // Some browsers never fire onend: do not let a scene hang.
      timer.current = window.setTimeout(next, fallbackMs * 1.8 + 2000);
    } else {
      timer.current = window.setTimeout(next, fallbackMs);
    }
    return stopAudio;
  }, [show, index, paused, finished]);

  useEffect(() => stopAudio, []);

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
