# Two-minute demo

Live: https://senior-coach-ai.web.app

## Set up before you go on (5 minutes before)

Open both tabs in the same browser: they share the list of your sessions, which is what lets
Tab 2 see Tab 1's ticket. A mentor on another device must be signed in with a team mentor email.

1. **Tab 1, the student.** Start a session (guest is fine). Open **Container With Most Water**
   from the Learn path. Paste the buggy solution below and click **Run tests** once: 1 of 2 pass.
   Then send these two messages, so a mentor ticket already exists:
   - "This is useless, I've been stuck for an hour and I want to give up."
   - "I hate this. I'm so frustrated, nothing works, I give up."
2. **Tab 2, the mentor.** Same site, open **Mentor**, click **Refresh**, and select the ticket.
   Type the reply below, but do not send it.
3. Go back to Tab 1 and scroll the chat so the hint ladder shows.

Buggy solution (it only ever uses the left wall, and always moves the left pointer):

```python
def max_area(height):
    l, r = 0, len(height) - 1
    best = 0
    while l < r:
        best = max(best, (r - l) * height[l])
        l += 1
    return best
```

Mentor reply: "Look at line 5: which of the two walls actually limits how much water they hold?"

## On stage

**0:00 to 0:15, the problem.** "Interview prep gives you nothing or everything. Ask an AI and it hands you the answer, so you learn nothing. Senior is a team of AI agents that coach you to the answer and never give it away."

**0:15 to 0:45, the hint ladder (Tab 1).** Click **Ask for a hint**. While it answers: "Hints come on a ladder, one rung per request: clarify the goal, name the area, the key insight, the approach in words, walk an example. No rung ever contains code." Point at the reply: it talks about the student's own code, without writing any.

**0:45 to 1:10, why it said that.** Click **See why**. "Every message is a trace. A guard model checked the input. The orchestrator chose the agent and the hint level by a written rule, and recorded why. The coach answered, and a leak check made sure there was no code. Model, tokens, cost and time on every step: this hint cost a fraction of a cent."

**1:10 to 1:40, a human when it matters (Tab 2).** "Earlier this student got frustrated twice, so Senior handed them to a person with the transcript, the code and a suggested intervention." Click **Send reply**, switch to Tab 1, and wait for the mentor's message to appear (about 3 seconds). "The mentor's reply lands right in the student's chat."

**1:40 to 1:55, the record.** Click **Activity log** under Behind the scenes. "Every action by every agent in my sessions, kept permanently: which role, which model or tool, and what it cost. I see my own sessions; the team's mentors see them all."

**1:55 to 2:00, close.** "Hints, not answers. Rules you can read. A human when it matters. Every step on the record. That's Senior."

## If something goes wrong

- Sign-in fails: use "Try it as a guest".
- A hint is slow: keep talking through the ladder line; it arrives within a few seconds.
- The mentor reply does not appear within a few seconds: read it out from Tab 2 and move on.

---

# Longer demo (about 4 minutes)

Live: https://senior-coach-ai.web.app

## Before you go on stage

- Open the site once, about 2 minutes before, so the server is awake.
- Sign in with Google or choose "Try it as a guest". Guest works without any setup.
- In a second tab, open the site again on **Mentor**. That tab plays the human mentor.
  Both tabs must be in the same browser (they share the list of your sessions); a mentor on
  another device must be signed in with a team mentor email.
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

"Every action by every agent in my sessions, kept permanently: which role, which model or
tool, the tokens and the spend. A visitor sees their own sessions, the team's mentors see
them all, and the small numbers are the whole system's totals." Click an agent to filter,
then a row to see its decision and reason.

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
