// The proctor's rules as a pure function: detector readings and a clock go in, at most one
// reminder comes out. There is no DOM and no timer in this file, so every rule can be tested
// with made-up readings and times (rules.test.mjs).
//
// A reminder is due when a condition has held for longer than its limit:
//   no face towards the screen for more than 3 s   -> "Eyes on the screen, please."
//   fewer than two hands in view for more than 5 s -> "Let me see both hands, please."
// It is held back during the first 3 s after the proctor starts, for 20 s after the same
// reminder, and while another reminder is still on screen, so two never arrive together.

export type Rule = "eyes_off_screen" | "hands_not_visible";

/** The reminders, word for word. app/api/proctor.py records the same words. */
export const PROMPTS: Record<Rule, string> = {
  eyes_off_screen: "Eyes on the screen, please.",
  hands_not_visible: "Let me see both hands, please.",
};

/** How long a condition must hold before its reminder. */
export const LIMIT_MS: Record<Rule, number> = { eyes_off_screen: 3000, hands_not_visible: 5000 };
/** No reminder this soon after the proctor is turned on. */
export const GRACE_MS = 3000;
/** The same reminder is not repeated within this time. */
export const COOLDOWN_MS = 20_000;
/** Hands are reminded less often: on a laptop the keyboard is often just below the camera. */
export const HANDS_COOLDOWN_MS = 60_000;
/** Typing in the last this many ms means the hands are on the keyboard: no hands reminder. */
export const TYPING_MS = 4000;
/** How long one reminder owns the banner and the voice. No other reminder starts inside it. */
export const PROMPT_GAP_MS = 6000;
/** A condition has cleared once it has been fine for this long. One good frame in the middle
 *  of looking away is detector noise, not the candidate looking back. */
export const CLEAR_MS = 600;
/** No reading for this long means sampling was paused (a hidden tab, a sleeping laptop).
 *  The time in between was not observed, so it must not count: the timers start again.
 *  Reminders already given are still remembered, so a pause never shortens a cooldown. */
export const STALL_MS = 2000;

/** Eyes first: when both are due at once, the more important reminder goes out. */
const ORDER: Rule[] = ["eyes_off_screen", "hands_not_visible"];

/** One look at the camera. */
export interface Reading {
  /** A face is in view and roughly towards the screen. */
  facing: boolean;
  /** How many hands are in view: 0, 1 or 2. */
  hands: number;
  /** The candidate typed within the last TYPING_MS. Their hands are on the keyboard, out of view. */
  typing?: boolean;
}

interface Watch {
  /** When the condition started to hold, or null while it does not. */
  since: number | null;
  /** When it last looked fine again, while `since` is still set. */
  fineSince: number | null;
  /** When this reminder was last given. Survives the condition clearing: it is the cooldown. */
  remindedAt: number | null;
}

export interface ProctorState {
  startedAt: number;
  lastAt: number | null;
  lastReminderAt: number | null;
  watch: Record<Rule, Watch>;
}

export interface Reminder {
  rule: Rule;
  text: string;
  /** How long the condition had held when the reminder was given. */
  seconds: number;
}

const idle = (): Watch => ({ since: null, fineSince: null, remindedAt: null });

/** The state at the moment the proctor is turned on. All times are milliseconds on one clock. */
export function start(now: number): ProctorState {
  return { startedAt: now, lastAt: null, lastReminderAt: null, watch: { eyes_off_screen: idle(), hands_not_visible: idle() } };
}

/** The state after a pause in sampling: as if just turned on, except for the cooldowns. */
function resume(paused: ProctorState, now: number): ProctorState {
  const fresh = start(now);
  for (const rule of ORDER) fresh.watch[rule].remindedAt = paused.watch[rule].remindedAt;
  fresh.lastReminderAt = paused.lastReminderAt;
  return fresh;
}

function observe(watch: Watch, holds: boolean, now: number): Watch {
  if (holds) return { ...watch, since: watch.since ?? now, fineSince: null };
  if (watch.since === null) return watch;
  const fineSince = watch.fineSince ?? now;
  return now - fineSince >= CLEAR_MS ? { ...watch, since: null, fineSince: null } : { ...watch, fineSince };
}

/** Take one reading. Returns the next state and the reminder to give now, if any. */
export function step(previous: ProctorState, reading: Reading, now: number): { state: ProctorState; reminder: Reminder | null } {
  const state = previous.lastAt !== null && now - previous.lastAt > STALL_MS ? resume(previous, now) : previous;
  const holds: Record<Rule, boolean> = { eyes_off_screen: !reading.facing, hands_not_visible: reading.hands < 2 && !reading.typing };
  const watch: Record<Rule, Watch> = {
    eyes_off_screen: observe(state.watch.eyes_off_screen, holds.eyes_off_screen, now),
    hands_not_visible: observe(state.watch.hands_not_visible, holds.hands_not_visible, now),
  };
  const next: ProctorState = { ...state, lastAt: now, watch };

  const settling = now - state.startedAt < GRACE_MS;
  const speaking = state.lastReminderAt !== null && now - state.lastReminderAt < PROMPT_GAP_MS;
  if (settling || speaking) return { state: next, reminder: null };

  for (const rule of ORDER) {
    const { since, remindedAt } = watch[rule];
    if (!holds[rule]) continue; // it looks fine right now: never remind someone who has just looked back
    if (since === null || now - since <= LIMIT_MS[rule]) continue;
    if (remindedAt !== null && now - remindedAt < (rule === "hands_not_visible" ? HANDS_COOLDOWN_MS : COOLDOWN_MS)) continue;
    return {
      state: { ...next, lastReminderAt: now, watch: { ...watch, [rule]: { ...watch[rule], remindedAt: now } } },
      reminder: { rule, text: PROMPTS[rule], seconds: Math.round((now - since) / 100) / 10 },
    };
  }
  return { state: next, reminder: null };
}
