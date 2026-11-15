# Demo script (about 4 minutes)

Live: https://senior-coach-ai.web.app

## Before you go on stage

- Open the site once, about 2 minutes before, so the server is awake.
- Sign in with Google or choose "Try it as a guest". Guest works without any setup.
- In a second tab, open the site again on **Mentor**. That tab plays the human mentor.
- Have this ready to paste into the editor (it fails on purpose):

```python
def two_sum(nums, target):
    for i in range(len(nums)):
        for j in range(len(nums)):
            if nums[i] + nums[j] == target:
                return [i, j]
```

## 1. The problem (20 s), on the landing page

"Students preparing for coding interviews either get no help or get the whole answer.
Senior is a coach made of AI agents that never gives the answer away, and shows every
step it took." Click **Start a session**, then sign in.

## 2. Learn mode and the hint ladder (60 s), on the Workspace

1. Paste the code and click **Run tests**. The tests run in the browser: 1 of 3 pass.
2. Click **Ask for a hint**. The coach answers at rung 1 ("Clarify the goal") and points at
   the student's own code, without writing any.
3. Ask again. It climbs one rung. "Each request moves exactly one rung, and no rung contains code."

## 3. Why it said that (40 s), on the Agent inspector

Click **See why**. "One message, every step: the input guard classified it, the orchestrator
picked the agent and the hint level by rule, with the reason recorded, then the hint coach
answered and the leak check passed. Model, tokens, cost and latency on every step."

## 4. A human in the loop (50 s)

Back on the Workspace, type twice, as a frustrated student:
- "This is useless, I've been stuck for an hour and I want to give up."
- "I hate this. I'm so frustrated, nothing works, I give up."

Switch to the Mentor tab and click **Refresh**. The ticket is there, with the reason
("frustration flagged 2 times"), the transcript, the code and a suggested intervention.
Type a reply and send it: it lands in the student's chat.

## 5. Everything is on the record (20 s), on the Activity log

"Every action by every agent, across all sessions, kept permanently: which role, which
model or tool, the tokens and the spend." Click an agent to filter, then a row to see
its decision and reason.

## 6. Beyond the problem (40 s)

- **Profile**: start the interview, answer a few questions, then click **Find my roles now**.
  It searches the web live (Linkup) and returns roles with sources. It takes about 15 seconds,
  so talk over it.
- **CV studio** (optional): paste a job description and a CV to get it tailored, with nothing invented.
- **Call Senior** (optional, needs a microphone and a quiet room): the voice coach can drive the app.

## Close (10 s)

"Hints, not answers. Rules you can read. A human when it matters. And every step on the record."

## If something goes wrong

- Google sign-in fails: use "Try it as a guest".
- The coach is slow: the first message after an idle period can take a few seconds. Keep talking.
- The voice call fails: skip it; it is optional.
