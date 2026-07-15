"""Routing eval — how well does the agent decide *which* actions need a human?

    PYTHONPATH=src python -m evals.run_eval

Prints precision / recall / F1 / false-escalation on the gold set. The headline
number: of actions that truly need approval, how many the router flags (recall);
and how often it needlessly escalates (false-escalation rate).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root -> import evals.*

from evals.harness import Metrics, score  # noqa: E402
from evals.router import predict  # noqa: E402

DATASET = Path(__file__).resolve().parent / "datasets" / "routing_cases.jsonl"


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


async def evaluate(path: Path = DATASET) -> tuple[Metrics, list[tuple]]:
    cases = load(path)
    pairs: list[tuple[bool, bool]] = []
    rows: list[tuple] = []
    for case in cases:
        predicted, reason = await predict(case)
        pairs.append((bool(case["expected"]), bool(predicted)))
        rows.append((case, bool(predicted), reason))
    return score(pairs), rows


def _report(metrics: Metrics, rows: list[tuple]) -> None:
    print("\n=== Routing eval — should this action need approval? ===\n")
    misses = [(c, p) for c, p, _ in rows if bool(c["expected"]) != p]
    for case, predicted, _reason in rows:
        ok = "PASS" if bool(case["expected"]) == predicted else "FAIL"
        print(f"  [{ok}] {case['id']:<4} {case['tool']:<15} "
              f"amount={str(case.get('amount')):<7} "
              f"expected={str(case['expected']):<5} predicted={predicted}")
    pct = lambda x: f"{x * 100:.1f}%"  # noqa: E731
    print("\n  ------------------------------------------------------------")
    print(f"  cases={metrics.total}  correct={metrics.tp + metrics.tn}  "
          f"missed(FN)={metrics.fn}  false-escalations(FP)={metrics.fp}")
    print(f"  accuracy           {pct(metrics.accuracy)}")
    print(f"  precision          {pct(metrics.precision)}")
    print(f"  recall             {pct(metrics.recall)}   "
          f"<- flags {pct(metrics.recall)} of actions needing approval")
    print(f"  F1                 {pct(metrics.f1)}")
    print(f"  false-escalation   {pct(metrics.false_escalation_rate)}")
    if misses:
        print(f"\n  {len(misses)} misroute(s): {[c['id'] for c, _ in misses]}")
    print()


if __name__ == "__main__":
    m, r = asyncio.run(evaluate())
    _report(m, r)
