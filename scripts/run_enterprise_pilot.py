"""Run a small, controlled EnterpriseRAG-Bench authorization pilot."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "enterprise_rag_bench" / "processed" / "confluence_slice_1"
DEFAULT_POLICY = ROOT / "experiments" / "configs" / "enterprise_policy_v1.json"
DEFAULT_OUTPUT = ROOT / "experiments" / "results" / "enterprise_pilot"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as source:
        return [json.loads(line) for line in source if line.strip()]


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")


def _policy_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _compute_metrics(rows: list[dict[str, Any]], baseline: str) -> dict[str, Any]:
    answered = [row for row in rows if row["answered"]]
    abstained = [row for row in rows if row["abstained"]]
    unanswerable = [row for row in rows if not row["expected_answerable"]]
    correct_abstentions = [row for row in abstained if not row["expected_answerable"]]
    recall_rows = [row["authorized_recall"] for row in rows if row["authorized_recall"] is not None]
    citation_rows = [row["citation_valid"] for row in answered if row["citation_valid"] is not None]
    scenario_counts = Counter(row["scenario_type"] for row in rows)
    return {
        "baseline": baseline,
        "total_questions": len(rows),
        "answered_count": len(answered),
        "abstained_count": len(abstained),
        "abstention_precision": (
            len(correct_abstentions) / len(abstained) if abstained else None
        ),
        "abstention_recall": (
            len(correct_abstentions) / len(unanswerable) if unanswerable else None
        ),
        "answer_coverage": len(answered) / len(rows) if rows else None,
        "authorized_recall": sum(recall_rows) / len(recall_rows) if recall_rows else None,
        "citation_validity": sum(citation_rows) / len(citation_rows) if citation_rows else None,
        "citation_validity_denominator": len(citation_rows),
        "leakage_count": sum(row["leakage_count"] for row in rows),
        "retry_count": sum(row["retry_attempted"] for row in rows),
        "mean_latency_ms": (
            sum(row["latency_ms"] for row in rows) / len(rows) if rows else 0.0
        ),
        "scenario_counts": dict(scenario_counts),
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    policy_path = args.policy.resolve()
    input_dir = args.input_dir.resolve()
    output_dir = args.output_dir.resolve()
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    questions = _read_jsonl(input_dir / "questions.jsonl")
    documents = _read_jsonl(input_dir / "documents.jsonl")
    official_questions = {
        item["question_id"]: item
        for item in _read_jsonl(ROOT / "external" / "EnterpriseRAG-Bench" / "questions.jsonl")
    }
    question_by_id = {item["question_id"]: item for item in questions}
    question_by_id.update(
        {
            item["question_id"]: {
                "question_id": item["question_id"],
                "question": item["question"],
                "category": item["question_type"],
                "gold_document_ids": item["expected_doc_ids"],
                "gold_answer": item["gold_answer"],
            }
            for item in official_questions.values()
            if item["question_id"] not in question_by_id
        }
    )
    annotations = policy["annotations"]
    if len(annotations) != args.expected_questions:
        raise ValueError(
            f"Expected {args.expected_questions} policy annotations, got {len(annotations)}"
        )
    scenario_counts = Counter(item["scenario_type"] for item in annotations)
    if len(scenario_counts) != 4 or len(set(scenario_counts.values())) != 1:
        raise ValueError(f"Pilot policy must be balanced over four scenarios: {scenario_counts}")

    document_by_id = {item["document_id"]: item for item in documents}
    corpus_ids = sorted(
        {
            document_id
            for item in annotations
            for document_id in (
                item["authorized_gold_document_ids"]
                + item["unauthorized_gold_document_ids"]
            )
        }
    )
    missing_document_ids = [document_id for document_id in corpus_ids if document_id not in document_by_id]
    if missing_document_ids:
        raise ValueError(f"Pilot policy gold documents absent from prepared slice: {missing_document_ids}")
    common_documents = [document_by_id[document_id] for document_id in corpus_ids]

    # Isolate the benchmark run from the developer's interactive demo database.
    with tempfile.TemporaryDirectory(prefix="entrix-enterprise-pilot-") as temporary_directory:
        db_path = Path(temporary_directory) / "pilot.sqlite"
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        os.environ["EMBEDDING_BACKEND"] = "hash"
        os.environ["QDRANT_IN_MEMORY"] = "true"
        os.environ["AUTO_CREATE_SCHEMA"] = "true"

        import sys

        sys.path.insert(0, str(ROOT / "backend"))
        from app.config import get_settings

        get_settings.cache_clear()
        from app.database import Base
        from app.database import engine as database_engine
        from app.generation import generate_answer, get_llm_provider
        from app.ingestion import ingest_document
        from app.models import Organization, User
        from app.retrieval import RetrievalEngine
        from app.schemas import SufficiencyDecision
        from app.sufficiency import (
            EvidenceSufficiencyController,
            HeuristicEstimator,
            LLMEstimator,
            StructuredEstimator,
        )

        settings = get_settings()
        await database_engine.dispose()
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        isolated_engine = create_async_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},
        )
        session_factory = async_sessionmaker(
            isolated_engine, expire_on_commit=False
        )
        async with isolated_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        retrieval = RetrievalEngine()
        provider = get_llm_provider()
        async with session_factory() as db:
            users: dict[str, User] = {}
            for annotation in annotations:
                organization = Organization(
                    name=annotation["organization_id"],
                    slug=annotation["organization_id"],
                )
                db.add(organization)
                await db.flush()
                user = User(
                    organization_id=organization.id,
                    username=annotation["scenario_id"],
                    email=f"{annotation['scenario_id']}@benchmark.invalid",
                    role=annotation["user_role"],
                    hashed_password="not-used-in-offline-evaluation",
                )
                db.add(user)
                await db.flush()
                users[annotation["question_id"]] = user

                restricted_ids = set(annotation["unauthorized_gold_document_ids"])
                for document in common_documents:
                    allowed_roles = (
                        ["admin"]
                        if document["document_id"] in restricted_ids
                        else ["viewer", "editor", "admin"]
                    )
                    await ingest_document(
                        db,
                        retrieval,
                        organization_id=organization.id,
                        title=document["title"],
                        content=document["text"],
                        source_id=document["document_id"],
                        allowed_roles=allowed_roles,
                    )
            await db.commit()

            estimators = {
                "B2": HeuristicEstimator(),
                "B3": LLMEstimator(provider),
                "B4": StructuredEstimator(),
            }
            result_rows: dict[str, list[dict[str, Any]]] = {name: [] for name in ("B1", "B2", "B3", "B4")}
            for baseline in result_rows:
                for annotation in annotations:
                    question = question_by_id[annotation["question_id"]]
                    query = question["question"]
                    user = users[annotation["question_id"]]
                    started = time.perf_counter()
                    evidence = await retrieval.search(query, user, db, top_k=args.top_k)
                    controller = (
                        EvidenceSufficiencyController(estimators[baseline])
                        if baseline != "B1"
                        else None
                    )
                    answered = baseline == "B1"
                    retry_attempted = False
                    score = None
                    if controller is not None:
                        assessment = await controller.evaluate(query, evidence)
                        score = assessment.coverage_score
                        answered = assessment.decision is SufficiencyDecision.SUFFICIENT
                        if (
                            baseline == "B4"
                            and not answered
                            and evidence
                        ):
                            retry_query = controller.generate_retry_query(query, assessment)
                            if retry_query:
                                retry_attempted = True
                                retry_evidence = await retrieval.search(
                                    retry_query, user, db, top_k=args.top_k
                                )
                                existing_ids = {item.evidence_id for item in evidence}
                                evidence.extend(
                                    item
                                    for item in retry_evidence
                                    if item.evidence_id not in existing_ids
                                )
                                assessment = await controller.evaluate(query, evidence)
                                score = assessment.coverage_score
                                answered = assessment.decision is SufficiencyDecision.SUFFICIENT

                    answer = None
                    citations = []
                    if answered:
                        answer, citations = await generate_answer(query, evidence, provider)
                    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

                    retrieved_ids = sorted({item.source_id for item in evidence if item.source_id})
                    auth_gold = set(annotation["authorized_gold_document_ids"])
                    unauthorized_gold = set(annotation["unauthorized_gold_document_ids"])
                    recall = (
                        len(auth_gold & set(retrieved_ids)) / len(auth_gold) if auth_gold else None
                    )
                    valid_citation_ids = [citation.source_id for citation in citations]
                    citation_valid = (
                        all(source_id in retrieved_ids for source_id in valid_citation_ids)
                        if valid_citation_ids
                        else None
                    )
                    inaccessible_doc_ids = [
                        item.source_id
                        for item in evidence
                        if item.source_id in unauthorized_gold
                    ]
                    row = {
                        "question_id": annotation["question_id"],
                        "answer": answer,
                        "document_ids": retrieved_ids,
                        "scenario_type": annotation["scenario_type"],
                        "expected_answerable": annotation["expected_answerable"],
                        "answered": answered,
                        "abstained": not answered,
                        "retrieved_document_ids": retrieved_ids,
                        "authorized_recall": recall,
                        "citation_valid": citation_valid,
                        "citation_document_ids": valid_citation_ids,
                        "leakage_count": len(inaccessible_doc_ids),
                        "leaked_document_ids": inaccessible_doc_ids,
                        "retry_attempted": retry_attempted,
                        "sufficiency_score": score,
                        "latency_ms": elapsed_ms,
                    }
                    result_rows[baseline].append(row)

            await db.close()

        await isolated_engine.dispose()
        await database_engine.dispose()

    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_by_baseline: dict[str, dict[str, Any]] = {}
    official_dir = output_dir / "official_answers"
    official_dir.mkdir(exist_ok=True)
    for baseline, rows in result_rows.items():
        _write_jsonl(output_dir / f"{baseline}_results.jsonl", rows)
        official_answers = [
            {
                "question_id": row["question_id"],
                "answer": row["answer"] or "",
                "document_ids": row["document_ids"],
            }
            for row in rows
        ]
        _write_jsonl(official_dir / f"{baseline}_answers.jsonl", official_answers)
        metrics = _compute_metrics(rows, baseline)
        metrics["sufficiency_provider"] = provider.provider_name()
        metrics["real_llm_provider"] = provider.provider_name() != "mock"
        metrics_by_baseline[baseline] = metrics
        (output_dir / f"{baseline}_metrics.json").write_text(
            json.dumps(metrics, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    metadata = {
        "dataset": "EnterpriseRAG-Bench pilot",
        "purpose": "Validate data mapping, authorization labels, and evaluation plumbing; not research evidence.",
        "dataset_version": "v1.0.0",
        "source_slice": "confluence_slice_1.zip",
        "seed": policy["seed"],
        "policy_version": policy["policy_version"],
        "policy_sha256": _policy_hash(policy_path),
        "question_count": len(annotations),
        "scenario_counts": dict(scenario_counts),
        "document_count": len(common_documents),
        "document_ids": corpus_ids,
        "document_subset_description": "Union of gold dsids for the selected 20 questions; the identical subset is replicated into each synthetic case tenant.",
        "organization_assignment": "Deterministic case-isolated tenants; no random document-to-organization split.",
        "top_k": args.top_k,
        "embedding_backend": "hash",
        "embedding_model": settings.embedding_model,
        "answer_generation_provider": provider.provider_name(),
        "real_llm_provider_configured": provider.provider_name() != "mock",
        "baselines": {
            "B1": "authorized retrieval, always answer",
            "B2": "heuristic sufficiency",
            "B3": "configured provider/LLM sufficiency",
            "B4": "structured sufficiency plus one authorized retry",
        },
        "metrics": metrics_by_baseline,
        "research_improvement_claim": False,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _write_jsonl(output_dir / "policy_annotations.jsonl", annotations)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--expected-questions", type=int, default=20)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    metadata = asyncio.run(_run(args))
    print(json.dumps(metadata["scenario_counts"], indent=2))
    print(f"Pilot artifacts: {args.output_dir.resolve()}")
    print(f"Sufficiency provider: {metadata['answer_generation_provider']}")


if __name__ == "__main__":
    main()
