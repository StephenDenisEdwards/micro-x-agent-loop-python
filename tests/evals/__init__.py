"""Behavioural eval suite.

Runs the real Agent (same construction path as ``--run``) against canonical
prompts and asserts on tool-call sequence + final answer + cost ceiling.
See documentation/docs/planning/PLAN-behavioural-eval-suite.md and
documentation/docs/issues/ISSUE-007-prose-contract-drift-across-policy-layers.md.

These tests cost money and need network/credentials. They are skipped unless
the env var MICRO_X_RUN_EVALS=1 is set (see tests/evals/conftest.py).
"""
