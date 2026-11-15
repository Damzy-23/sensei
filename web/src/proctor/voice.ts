// The proctor's voice. Reminders are spoken in the coach's own ElevenLabs voice and never
// in the browser's built-in speech. If the audio cannot be fetched or played, nothing is
// said: the banner on screen is the reminder.

import { chosenPersona, fetchSpeech } from "./remote";

export interface ProctorVoice {
  /** Speak one reminder, cutting off the previous one if it is still playing. */
  say(text: string): Promise<void>;
  /** Stop speaking and release every clip. */
  close(): void;
}

export function createVoice(): ProctorVoice {
  // A reminder is one of two fixed lines, so each is fetched once per voice and replayed.
  const clips = new Map<string, Promise<string | null>>();
  let playing: HTMLAudioElement | null = null;
  let unavailable = false;
  let closed = false;

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
      if (closed || unavailable) return;
      const url = await clip(text, chosenPersona());
      if (!url || closed) return;
      playing?.pause();
      const audio = new Audio(url);
      playing = audio;
      await audio.play().catch(() => undefined); // blocked or undecodable: stay silent
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
