# Hint-coach eval and Adaption task

## Status

| Part | Status |
|---|---|
| Training and held-out data pipeline (`scripts/make_hint_data.py`) | Built and tested with fake functions. Not yet run: needs `ANTHROPIC_API_KEY`. |
| Win-rate eval (`scripts/run_eval.py`, `app/eval/winrate.py`) | Built and tested with fake functions. Not yet run against real models. |
| `/eval/results` | Serves the stub until a real run writes `data/eval/results.json`. |
| Adaption upload and leaderboard submission | **Not started.** `docs/adaption.md` is missing, so the upload steps are unknown. See below. |

## Held-out problems

`container-most-water` (two pointers), `number-of-islands` (BFS/DFS) and `coin-change`
(dynamic programming). They are defined in `app/eval/hint_data.py` as `HOLDOUT_PROBLEMS`. They
never appear in `data/adaption/train.jsonl`, and a test checks this.

## Data

`scripts/make_hint_data.py` writes:

- `data/adaption/train.jsonl`: one row per kept hint, in chat format
  (`system`, `user`, `assistant`), with `problem_id` and `level`.
- `data/adaption/test.jsonl`: one row per held-out scenario (problem, level, student code and
  last failure). The reference solution is not written to either file.

Each training hint must pass the server's `leak_check`, be at most 60 words, and pass a rubric
judge (right level, Socratic, helpful). Nine training problems × 5 attempts × 5 levels × 2
variants gives at most **450** rows, so the 400+ target depends on how many hints pass the
filters. The run prints the count.

## Win-rate eval

```bash
python scripts/run_eval.py              # all held-out scenarios
python scripts/run_eval.py --limit 10   # quick check
```

For each scenario it generates a hint from `hint_base` and from `hint_tuned`, checks both with
`leak_check`, and asks a judge to compare them on the rubric (correct level, Socratic, helpful,
brevity). The A/B order is random, seeded by `--seed`. Leakage is a hard fail: a leaked hint
loses without being judged. Each judged pair is logged as an `eval.pair` span.

Outputs:

- `data/eval/results.json`: the `EvalResults` payload served at `GET /eval/results`.
- `data/eval/results.md`: win rate, leak rate, per-criterion scores, and three side-by-side
  examples. It says plainly when the tuned model loses.

`HINT_MODEL=tuned` selects the tuned model for live coaching. The eval always runs both models,
so it needs `HINT_TUNED_BASE_URL`, `HINT_TUNED_API_KEY` and `HINT_TUNED_MODEL` set. It fails
loudly if they are missing, and does not quietly substitute base for tuned.

## Adaption: what is needed before the upload can be built

The spec says to read `docs/adaption.md` before writing any upload code, and to stop and ask if
it is missing. It is missing, so these are still open:

1. The upload format Adaption expects (file type, schema, size limits).
2. How the model is submitted to the leaderboard, and what counts as the win rate for ranking.
3. Whether the tuned model must be hosted by Adaption or can stay on our OpenAI-compatible endpoint.

Once `docs/adaption.md` exists, the upload step and the record of how the model reaches the
leaderboard go into that file.
