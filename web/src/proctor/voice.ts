// The proctor's voice. Reminders are spoken in the coach's own ElevenLabs voice and never
// in the browser's built-in speech. If the audio cannot be fetched or played, nothing is
// said: the banner on screen is the reminder.

import { voiceCall } from "../agent/callState";
import { chosenPersona, fetchSpeech } from "./remote";

export interface ProctorVoice {
  /** Speak one reminder, cutting off the previous one if it is still playing. */
  say(text: string): Promise<void>;
  /** Fetch the fixed reminders ahead of time. */
  warm(): void;
  /** Stop speaking and release every clip. */
  close(): void;
}

/** A reminder's clip is not played if it takes longer than this to arrive (its banner shows for 6 s). */
const STALE_MS = 3000;
const WARM_LINES = ["Eyes on the screen, please.", "Let me see both hands, please."];

export function createVoice(): ProctorVoice {
  // A reminder is one of two fixed lines, so each is fetched once per voice and replayed.
  const clips = new Map<string, Promise<string | null>>();
  let playing: HTMLAudioElement | null = null;
  let unavailable = false;
  let closed = false;
  let said = 0; // which say() is the newest

  const clip = (text: string, persona: string): Promise<string | null> => {
    const key = `${persona}\n${text}`;
    const known = clips.get(key);
    if (known) return known;
    const pending = fetchSpeech(text, persona).then((speech) => {
      if (speech.ok) {
        if (closed) URL.revokeObjectURL(speech.url); // arrived after the proctor was turned off
        return closed ? null : speech.url;
      }
      unavailable ||= speech.unavailable;
      clips.delete(key); // a failure is not remembered: the next reminder asks again
      return null;
    });
    clips.set(key, pending);
    return pending;
  };

  return {
    async say(text) {
      // In a live call the coach is the one talking: the banner is the reminder, not a second voice.
      if (closed || unavailable || voiceCall.live) return;
      const mine = ++said;
      const asked = performance.now();
      const url = await clip(text, chosenPersona());
      // A clip that arrives after a newer reminder, or too late to match its banner, is not played.
      if (!url || closed || mine !== said || performance.now() - asked > STALE_MS || voiceCall.live) return;
      playing?.pause();
      const audio = new Audio(url);
      playing = audio;
      await audio.play().catch(() => undefined); // blocked or undecodable: stay silent
    },
    warm() {
      // Fetch both fixed lines as soon as the proctor runs, so the first reminder is not late.
      if (!closed && !unavailable) for (const line of WARM_LINES) void clip(line, chosenPersona());
    },
    close() {
      closed = true;
      playing?.pause();
      playing = null;
      clips.forEach((pending) => void pending.then((url) => { if (url) URL.revokeObjectURL(url); }));
      clips.clear();
    },
  };
}
