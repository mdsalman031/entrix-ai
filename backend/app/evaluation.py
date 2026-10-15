"""Offline evaluation pipeline for the research experiments.

Implements baseline configurations B1-B4, metric computation, and
per-query result export. Runs against either the synthetic test suite
or a loaded benchmark subset.

Baselines:
  B1: Permission-filtered RAG (no sufficiency control, always answers)
  B2: Heuristic sufficiency (lexical/rule-based controller)
  B3: LLM sufficiency (LLM-based assessment, no retry)
  B4: Proposed controller (structured assessment + 1 retry + abstention)

Metrics:
  - Abstention precision/recall
  - Answer coverage
  - Authorized recall@K
  - Citation validity rate
  - Latency measurements
"""

from __future__ import annotations

import time
from pathlib import Path

import structlog

from app.schemas import (
    EvalAggregateMetrics,
    EvalQueryResult,
    EvidenceItem,
    SufficiencyDecision,
)
from app.sufficiency import (
    EvidenceSufficiencyController,
    HeuristicEstimator,
    LLMEstimator,
    StructuredEstimator,
)

logger = structlog.get_logger(__name__)


# ── Synthetic test dataset ───────────────────────────────────────────────


def create_synthetic_dataset() -> list[dict]:
    """Create a small, deterministic synthetic dataset for evaluation.

    Categories:
      1. Answerable with authorized evidence.
      2. Unanswerable — evidence absent from corpus entirely.
      3. Unanswerable — evidence exists but is not authorized.
      4. Ambiguous/contradictory authorized evidence.
    """
    return [
        {
            "query_id": "SYN-001",
            "query": "What is the company's password policy?",
            "category": "answerable_authorized",
            "expected_answerable": True,
            "org_id": "org-acme",
            "user_role": "viewer",
            "relevant_doc_ids": ["doc-security-policy"],
        },
        {
            "query_id": "SYN-002",
            "query": "What are the quarterly revenue projections?",
            "category": "unanswerable_restricted",
            "expected_answerable": False,
            "org_id": "org-acme",
            "user_role": "viewer",
            "relevant_doc_ids": ["doc-financial-report"],
            "note": "Financial report exists but viewer role cannot access it",
        },
        {
            "query_id": "SYN-003",
            "query": "What is the procedure for handling a data breach?",
            "category": "answerable_authorized",
            "expected_answerable": True,
            "org_id": "org-acme",
            "user_role": "editor",
            "relevant_doc_ids": ["doc-incident-response"],
        },
        {
            "query_id": "SYN-004",
            "query": "What programming language is used for the quantum computing project?",
            "category": "unanswerable_absent",
            "expected_answerable": False,
            "org_id": "org-acme",
            "user_role": "admin",
            "relevant_doc_ids": [],
            "note": "No document in corpus discusses quantum computing",
        },
        {
            "query_id": "SYN-005",
            "query": "What is the remote work policy for the engineering team?",
            "category": "answerable_authorized",
            "expected_answerable": True,
            "org_id": "org-acme",
            "user_role": "editor",
            "relevant_doc_ids": ["doc-hr-policy"],
        },
        {
            "query_id": "SYN-006",
            "query": "What are the employee salary ranges by department?",
            "category": "unanswerable_restricted",
            "expected_answerable": False,
            "org_id": "org-acme",
            "user_role": "viewer",
            "relevant_doc_ids": ["doc-compensation"],
            "note": "Compensation data requires admin role",
        },
        {
            "query_id": "SYN-007",
            "query": "How many vacation days do employees get per year?",
            "category": "answerable_authorized",
            "expected_answerable": True,
            "org_id": "org-acme",
            "user_role": "viewer",
            "relevant_doc_ids": ["doc-hr-policy"],
        },
        {
            "query_id": "SYN-008",
            "query": "What is the VPN configuration? The server also uses port 443 for HTTPS.",
            "category": "ambiguous_contradictory",
            "expected_answerable": True,
            "org_id": "org-acme",
            "user_role": "editor",
            "relevant_doc_ids": ["doc-network-guide", "doc-security-policy"],
            "note": "Two documents may have conflicting VPN port information",
        },
        {
            "query_id": "SYN-009",
            "query": "What are Globex's onboarding procedures?",
            "category": "answerable_authorized",
            "expected_answerable": True,
            "org_id": "org-globex",
            "user_role": "editor",
            "relevant_doc_ids": ["doc-globex-onboarding"],
        },
        {
            "query_id": "SYN-010",
            "query": "What is the Acme Corp incident response plan?",
            "category": "unanswerable_cross_tenant",
            "expected_answerable": False,
            "org_id": "org-globex",
            "user_role": "admin",
            "relevant_doc_ids": [],
            "note": "Acme docs are not visible to Globex users at all",
        },
    ]


# ── Evaluation runner ────────────────────────────────────────────────────


async def run_baseline(
    baseline_name: str,
    evidence_sets: dict[str, list[EvidenceItem]],
    dataset: list[dict],
) -> list[EvalQueryResult]:
    """Run a single baseline over the test dataset.

    evidence_sets maps query_id -> list of retrieved authorized evidence items.
    """
    results: list[EvalQueryResult] = []

    # Select estimator
    if baseline_name == "B1":
        controller = None  # No sufficiency control
    elif baseline_name == "B2":
        controller = EvidenceSufficiencyController(HeuristicEstimator())
    elif baseline_name == "B3":
        controller = EvidenceSufficiencyController(LLMEstimator())
    elif baseline_name == "B4":
        controller = EvidenceSufficiencyController(StructuredEstimator())
    else:
        raise ValueError(f"Unknown baseline: {baseline_name}")

    for query_item in dataset:
        qid = query_item["query_id"]
        query_text = query_item["query"]
        expected = query_item.get("expected_answerable")
        evidence = evidence_sets.get(qid, [])

        start = time.monotonic()

        try:
            if controller is None:
                # B1: Always answer if evidence exists
                answered = len(evidence) > 0
                abstained = not answered
                score = 1.0 if evidence else 0.0
                retry = False
            else:
                assessment = await controller.evaluate(query_text, evidence)
                answered = assessment.decision == SufficiencyDecision.SUFFICIENT
                abstained = not answered
                score = assessment.coverage_score
                retry = False

                # For B4, attempt retry if insufficient
                if baseline_name == "B4" and not answered and evidence:
                    retry_query = controller.generate_retry_query(query_text, assessment)
                    if retry_query:
                        retry = True
                        # In a full evaluation, we'd re-retrieve here
                        # For now, reassess with existing evidence
                        assessment2 = await controller.evaluate(retry_query, evidence)
                        answered = assessment2.decision == SufficiencyDecision.SUFFICIENT
                        abstained = not answered
                        score = assessment2.coverage_score

            latency = (time.monotonic() - start) * 1000

            results.append(
                EvalQueryResult(
                    query_id=qid,
                    query_text=query_text,
                    baseline=baseline_name,
                    expected_answerable=expected,
                    answered=answered,
                    abstained=abstained,
                    sufficiency_score=score,
                    evidence_count=len(evidence),
                    retry_attempted=retry,
                    latency_ms=round(latency, 2),
                )
            )

        except Exception as e:
            latency = (time.monotonic() - start) * 1000
            results.append(
                EvalQueryResult(
                    query_id=qid,
                    query_text=query_text,
                    baseline=baseline_name,
                    expected_answerable=expected,
                    answered=False,
                    abstained=True,
                    error=str(e),
                    latency_ms=round(latency, 2),
                )
            )

    return results


# ── Metrics computation ─────────────────────────────────────────────────


def compute_aggregate_metrics(
    results: list[EvalQueryResult],
    baseline: str,
) -> EvalAggregateMetrics:
    """Compute aggregate metrics from per-query results."""
    total = len(results)
    if total == 0:
        return EvalAggregateMetrics(
            baseline=baseline,
            total_queries=0,
            answered_count=0,
            abstained_count=0,
            error_count=0,
            mean_latency_ms=0.0,
        )

    answered = sum(1 for r in results if r.answered)
    abstained = sum(1 for r in results if r.abstained)
    errors = sum(1 for r in results if r.error is not None)
    latencies = [r.latency_ms for r in results]

    # Abstention precision: of those that abstained, how many should have?
    # (expected_answerable=False → abstention is correct)
    abstention_correct = sum(1 for r in results if r.abstained and r.expected_answerable is False)
    abstention_precision = abstention_correct / abstained if abstained > 0 else None

    # Abstention recall: of truly unanswerable, how many did we abstain on?
    truly_unanswerable = sum(1 for r in results if r.expected_answerable is False)
    abstention_recall = abstention_correct / truly_unanswerable if truly_unanswerable > 0 else None

    # Answer coverage: fraction of questions we answered
    answer_coverage = answered / total if total > 0 else None

    # Mean sufficiency score
    scores = [r.sufficiency_score for r in results if r.sufficiency_score is not None]
    mean_suff = sum(scores) / len(scores) if scores else None

    return EvalAggregateMetrics(
        baseline=baseline,
        total_queries=total,
        answered_count=answered,
        abstained_count=abstained,
        error_count=errors,
        mean_latency_ms=round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        abstention_precision=round(abstention_precision, 3)
        if abstention_precision is not None
        else None,
        abstention_recall=round(abstention_recall, 3) if abstention_recall is not None else None,
        answer_coverage=round(answer_coverage, 3) if answer_coverage is not None else None,
        mean_sufficiency_score=round(mean_suff, 3) if mean_suff is not None else None,
    )


# ── Results export ───────────────────────────────────────────────────────


def export_results(
    results: list[EvalQueryResult],
    metrics: EvalAggregateMetrics,
    output_dir: Path,
    baseline: str,
) -> None:
    """Export evaluation results to JSONL (per-query) and JSON (aggregate)."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Per-query results as JSONL
    results_file = output_dir / f"{baseline}_results.jsonl"
    with open(results_file, "w") as f:
        for r in results:
            f.write(r.model_dump_json() + "\n")

    # Aggregate metrics as JSON
    metrics_file = output_dir / f"{baseline}_metrics.json"
    with open(metrics_file, "w") as f:
        f.write(metrics.model_dump_json(indent=2))

    logger.info("results_exported", baseline=baseline, dir=str(output_dir))
