"""Evaluation. Cross-cutting: not one of the six building blocks.

Measures, on real model output, whether the coach keeps to its own rules: no more code than the
code rule allows, no naming of the approach before the hint level allows it, and replies that stay
within their hint level. Fixed conversations (scenarios.py) are run through the real turn loop
(runner.py); each reply gets rule checks and a model judge (checks.py); report.py writes
app/eval/report.json, served by GET /eval/report. Run it with scripts/run_eval.py; read
docs/EVALUATION.md for what it can and cannot show.

GET /eval/results (tuned versus base hint model) is still a placeholder.
"""
