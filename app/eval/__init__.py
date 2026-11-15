"""Evaluation. Cross-cutting: not one of the six building blocks.

Compares the tuned hint model with the base model on held-out problems, judged
pairwise: win rate per criterion, and leak rate as a hard fail. Its output is
served by GET /eval/results and is the evidence for the Adaption prize.
"""
