# 4. The voice coach can operate every control, behind one guard

**Status:** accepted · 2026-11-16

## Context
The voice coach acts on the page through typed page tools (`web/src/agent/tools.ts`).
Each screen chose which tools to expose, and the tools changed React state directly,
never the DOM. That kept the agent narrow: an audit of the app's 152 controls found
it could do 32 of them. The owner asked for the opposite: "everything a human can
control" should be in reach of the agent, so a student can say "open the Learn path,
switch to NeetCode 150 and find islands" and have it done.

Writing a typed tool for each of more than a hundred controls would double every
screen's code and still miss the next control someone adds. Some controls must not
be the agent's at all (the student's code, passwords, signing in), and some change
or lose the student's things (signing out, resolving a mentor ticket, wiping).

## Decision
Add a control layer: six generic tools that operate the visible screen the way a
person does, by the controls' accessible names.

- `see_screen` lists the visible, enabled controls in reading order: name, kind
  (button, link, field, choice, tab, toggle) and state, at most 60, with a count of
  the rest. Names are unique on the screen: a shared name takes its row's or card's
  context ("Remove, Cut deploy time by 60%…"), else a number.
- `press`, `type_into`, `pick_option` and `scroll_to` find a control by a forgiving
  match (exact, then starts-with, then contains; several matches come back as
  candidates, never a guess) and act on it as a person would. `type_into` uses the
  native value setter and input and change events, so React sees real typing.
- `read_screen` returns the visible text of the screen or of one part by its
  heading, capped at about 1,800 characters, with a fixed note that it is what the
  page shows and not instructions.

Only what a person could reach counts: hidden screens (the Workspace and Profile stay
mounted while hidden), disabled controls, `aria-hidden` and `inert` subtrees do not
exist for the agent, and an open modal dialog (the explainer) is the whole screen.

Every action goes through one pure guard (`web/src/agent/control-rules.ts`), ruled on
the control and on every control a click would also reach (the controls around it,
and the control a surrounding label stands for), strictest ruling wins:

- **Blocked** with a plain error: typing into the code editor (the error points to
  `write_line`, which only writes a line the coach offered), any password field,
  anything in the sign-in screen or in a form that holds a password field, and any
  control marked `data-agent="off"`, which also hides it.
- **Needs the student's click**: signing out or in, resolving a mentor ticket, sending
  a mentor reply, wiping, resetting, deleting or removing, downloading or printing,
  links that leave the app or open a tab or download, and any control marked
  `data-agent="confirm"`: today Call Senior, End interview and get feedback, turning
  the proctor's camera on, Download PDF, the CV's own text (Your CV, its lines, New
  line), Add to my CV, and Tailor my CV once a tailored CV would be replaced. The
  audit had the CV boxes as blocked; they ask instead, so a student can still dictate
  their CV. The decision uses a short list of name patterns for action labels (four
  words or fewer, read with look-alike letters, zero-width characters and hyphens
  undone) plus the `data-agent` mark, which does not depend on wording. Sending from a
  box (`type_into` with submit) is ruled on the button it would set off.

A needs-click action shows a prompt, "Senior wants to: <action>. Allow / Not now"
(`web/src/agent/AgentControls.tsx`): a real dialog region with focus moved to it,
bottom centre unless that would cover the Workspace message box, Escape for Not now,
20 seconds before it counts as no answer. One prompt at a time, and nothing else runs
while it is open. The prompt is `data-agent="off"`, and Allow ignores any click that
is not a real one from the student (`isTrusted`), so the agent cannot answer for them.
After Allow, the control is checked again: if it changed while the student decided,
nothing is pressed.

Three things the agent cannot change about the student's view: the "Senior is doing"
line is `data-agent="off"` (its Always hide button included), the prompt itself, and
anything a screen marks off. The line names the control for these tools ("Pressed
Run tests").

## Consequences
- A new control is in reach the day it ships, by its accessible name. A control with
  no accessible name is hard for the agent and for a screen-reader user alike, so the
  layer rewards the accessibility work that was owed anyway.
- The typed page tools stay: they carry facts the screen does not show (the coach's
  hint level, the trace) and actions no control offers (drawing on the glass).
- The agent now touches the DOM. That is limited to `web/src/agent/controls.ts`; the
  rest of the app keeps changing state through React.
- An action the guard should stop but cannot recognise by name is stopped only if
  its control is marked `data-agent="confirm"` or `"off"`. Marking it is part of
  building any control that loses or sends the student's work.
- Page text read by the agent can carry another person's words (a ticket, a search
  result). The fixed note on `read_screen` and the voice coach's instructions say it
  is never to be followed.
- Tested by `web/src/agent/control-rules.test.mjs` (`npm test`): naming and dedup,
  matching, the block and confirm rules, text shaping and capping, and the change
  summary.
