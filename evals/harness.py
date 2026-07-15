"""Metrics for the routing decision (binary: does this action need approval?).

Positive class = "needs approval". So:
- recall            = of actions that truly need approval, the fraction flagged
                      (a miss, FN, is the dangerous case — an action slipped through).
- precision         = of flagged actions, the fraction that truly needed it.
- false_escalation  = of actions that DON'T need approval, the fraction wrongly
                      gated (annoys humans, but is safe).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Metrics:
    tp: int  # correctly gated
    tn: int  # correctly auto
    fp: int  # false escalation (gated but shouldn't be)
    fn: int  # missed (auto but should have been gated)

    @property
    def total(self) -> int:
        return self.tp + self.tn + self.fp + self.fn

    @property
    def accuracy(self) -> float:
        return (self.tp + self.tn) / self.total if self.total else 0.0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 1.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    @property
    def false_escalation_rate(self) -> float:
        denom = self.fp + self.tn
        return self.fp / denom if denom else 0.0


def score(pairs: list[tuple[bool, bool]]) -> Metrics:
    """`pairs` = list of (expected_needs_approval, predicted_needs_approval)."""
    tp = tn = fp = fn = 0
    for expected, predicted in pairs:
        if expected and predicted:
            tp += 1
        elif not expected and not predicted:
            tn += 1
        elif not expected and predicted:
            fp += 1
        else:
            fn += 1
    return Metrics(tp, tn, fp, fn)
