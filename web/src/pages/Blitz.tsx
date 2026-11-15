import { useCallback, useEffect, useState } from "react";
import { getTrack, type TrackProblem } from "../api";

const SECONDS = 20;
const ROUND = 5;
const LETTERS = ["A", "B", "C", "D"];
const RING = 226.2; // circumference of the r=36 timer ring
const TIME_UP = -1;

interface Question { title: string; pattern: string; options: string[]; answer: number }

function shuffle<T>(items: T[]): T[] {
  const out = [...items];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/** Five questions from the real catalogue: name the pattern of a problem. */
function buildRound(problems: TrackProblem[]): Question[] {
  const patterns = [...new Set(problems.map((p) => p.pattern))];
  return shuffle(problems).slice(0, ROUND).map((problem) => {
    const distractors = shuffle(patterns.filter((p) => p !== problem.pattern)).slice(0, 3);
    const options = shuffle([problem.pattern, ...distractors]);
    return { title: problem.title, pattern: problem.pattern, options, answer: options.indexOf(problem.pattern) };
  });
}

interface Round { questions: Question[]; q: number; t: number; picked: number | null; score: number; streak: number; right: number; answered: number; done: boolean }

const newRound = (problems: TrackProblem[]): Round => ({
  questions: buildRound(problems), q: 0, t: SECONDS, picked: null, score: 0, streak: 0, right: 0, answered: 0, done: false,
});

export function Blitz() {
  const [problems, setProblems] = useState<TrackProblem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [round, setRound] = useState<Round | null>(null);

  useEffect(() => {
    let current = true;
    getTrack("neetcode_150").then(
      (track) => {
        if (!current) return;
        if (new Set(track.problems.map((p) => p.pattern)).size < 4) {
          setError("The catalogue has too few patterns to build a round.");
          return;
        }
        setProblems(track.problems);
        setRound(newRound(track.problems));
      },
      (err: Error) => current && setError(`Could not load the catalogue: ${err.message}`),
    );
    return () => { current = false; };
  }, []);

  const ticking = round !== null && !round.done && round.picked === null;
  useEffect(() => {
    if (!ticking) return;
    const timer = setInterval(() => {
      setRound((r) => {
        if (!r || r.done || r.picked !== null) return r;
        if (r.t <= 1) return { ...r, t: 0, picked: TIME_UP, streak: 0, answered: r.answered + 1 };
        return { ...r, t: r.t - 1 };
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [ticking]);

  const choose = useCallback((i: number) => {
    setRound((r) => {
      if (!r || r.done || r.picked !== null) return r;
      const ok = i === r.questions[r.q].answer;
      return {
        ...r, picked: i, answered: r.answered + 1, right: r.right + (ok ? 1 : 0),
        streak: ok ? r.streak + 1 : 0, score: r.score + (ok ? 100 + r.t * 5 + r.streak * 25 : 0),
      };
    });
  }, []);

  const advance = useCallback(() => {
    setRound((r) => {
      if (!r || !problems) return r;
      if (r.done || r.picked === null) return newRound(problems);
      if (r.q >= r.questions.length - 1) return { ...r, done: true };
      return { ...r, q: r.q + 1, t: SECONDS, picked: null };
    });
  }, [problems]);

  if (error) return <main className="page"><div className="bubble notice" role="alert">{error}</div></main>;
  if (!round) return <main className="page"><div className="muted">Loading the Blitz lab…</div></main>;

  const question = round.questions[round.q];
  const answered = round.picked !== null;
  const correct = round.picked === question.answer;
  const fraction = round.t / SECONDS;
  const explain = `${question.title} is a ${question.pattern} problem.`;
  let feedback = "Pick one before the clock runs out.";
  let feedbackColor = "var(--text-2)";
  if (round.done) feedback = `Round over. ${round.right} of ${round.questions.length} right. Press Play again to beat it.`;
  else if (round.picked === TIME_UP) { feedback = `Time up. ${explain}`; feedbackColor = "var(--sky)"; }
  else if (answered && correct) { feedback = `Correct. ${explain}`; feedbackColor = "var(--seafoam)"; }
  else if (answered) { feedback = `Not quite. ${explain}`; feedbackColor = "var(--sky)"; }
  const accuracy = round.answered ? Math.round((round.right / round.answered) * 100) : 0;
  const buttonLabel = round.done ? "Play again" : answered ? (round.q >= round.questions.length - 1 ? "Finish round" : "Next question") : "Restart round";

  return (
    <main className="page">
      <div className="row-wrap" style={{ gap: 22, justifyContent: "center" }}>
        <section aria-label="Question" style={{ flex: "2 1 560px", maxWidth: 760, minWidth: 320, display: "flex", flexDirection: "column", gap: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
            <div style={{ position: "relative", width: 84, height: 84, flex: "none" }} role="timer" aria-label={`${round.t} seconds left`}>
              <svg width="84" height="84" viewBox="0 0 84 84" aria-hidden="true">
                <circle cx="42" cy="42" r="36" fill="none" stroke="var(--line)" strokeWidth="7" />
                <circle
                  cx="42" cy="42" r="36" fill="none" stroke={fraction > 0.5 ? "var(--seafoam)" : "var(--sky)"} strokeWidth="7" strokeLinecap="round"
                  strokeDasharray={RING} strokeDashoffset={(RING * (1 - fraction)).toFixed(1)} transform="rotate(-90 42 42)"
                  style={{ transition: "stroke-dashoffset .9s linear, stroke .4s" }}
                />
              </svg>
              <div className="mono" style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 24, fontWeight: 500 }}>{round.t}</div>
            </div>
            <div>
              <div className="label">Question {round.q + 1} of {round.questions.length}</div>
              <h1 style={{ marginTop: 2, fontSize: 32, lineHeight: "36px", letterSpacing: -0.8 }}>Which pattern fits?</h1>
            </div>
            <div style={{ marginLeft: "auto", textAlign: "right" }}>
              <div className="label">Score</div>
              <div className="mono sky" style={{ fontSize: 32, fontWeight: 500, letterSpacing: -1 }}>{round.score}</div>
            </div>
          </div>

          <div style={{ display: "flex", gap: 6 }} role="img" aria-label={`Combo: ${Math.min(round.streak, 5)} of 5`}>
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} style={{ flex: 1, height: 8, borderRadius: 999, background: i < round.streak ? "linear-gradient(90deg,#86BBD8,#5F9CC4)" : "var(--line)", transition: "background .3s" }} />
            ))}
          </div>

          <div key={`${round.questions[0].title}-${round.q}`} style={{ display: "flex", flexDirection: "column", gap: 14, animation: "fade .45s var(--ease) both" }}>
            <div className="card" style={{ padding: 22, fontSize: 17, lineHeight: "27px", boxShadow: "0 24px 60px -24px rgba(0,0,0,.7)" }}>
              Which pattern fits &ldquo;{question.title}&rdquo;?
            </div>
            {question.options.map((option, i) => {
              const state = !answered ? "" : i === question.answer ? "right" : i === round.picked ? "wrong" : "";
              return (
                <button key={option} className={`opt ${state}`} disabled={answered || round.done} onClick={() => choose(i)}>
                  <span className="k">{LETTERS[i]}</span>
                  <span style={{ textTransform: "capitalize", flex: 1 }}>{option}</span>
                  {state === "right" && <span className="pill seafoam">Correct answer</span>}
                  {state === "wrong" && <span className="pill sky">Your pick</span>}
                </button>
              );
            })}
            <div style={{ minHeight: 44, fontSize: 14, lineHeight: "21px", color: feedbackColor }} aria-live="polite">{feedback}</div>
          </div>
        </section>

        <aside aria-label="Round stats" style={{ flex: "1 1 280px", maxWidth: 340, minWidth: 260, display: "flex", flexDirection: "column", gap: 14 }}>
          <div className="card" style={{ padding: 20 }}>
            <div className="label">Streak</div>
            <div className="mono sky" style={{ marginTop: 6, fontSize: 44, fontWeight: 500, letterSpacing: -2 }}>
              {round.streak}<span className="dim" style={{ fontSize: 16, letterSpacing: 0 }}> in a row</span>
            </div>
          </div>
          <div className="card" style={{ padding: 20 }}>
            <div className="label">Accuracy</div>
            <div className="mono" style={{ marginTop: 6, fontSize: 44, fontWeight: 500, letterSpacing: -2 }}>
              {round.answered ? accuracy : "–"}<span className="dim" style={{ fontSize: 16, letterSpacing: 0 }}>{round.answered ? "%" : " no answers yet"}</span>
            </div>
            <div style={{ marginTop: 10, height: 8, borderRadius: 999, background: "var(--line)", overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${accuracy}%`, borderRadius: 999, background: "linear-gradient(90deg,#86BBD8,#5F9CC4)", transition: "width .6s var(--ease)" }} />
            </div>
          </div>
          <div className="card" style={{ padding: 20, display: "flex", flexDirection: "column", gap: 10 }}>
            <div className="label">Why Blitz</div>
            <div className="muted" style={{ fontSize: 13, lineHeight: "20px" }}>
              No code, only the call. Naming the pattern in under 30 seconds is the skill interviewers look for first.
            </div>
          </div>
          <button className="btn-primary" style={{ height: 48, fontSize: 15 }} onClick={advance}>{buttonLabel}</button>
        </aside>
      </div>
    </main>
  );
}
