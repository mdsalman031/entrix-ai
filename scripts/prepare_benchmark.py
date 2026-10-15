"""Prepare a deterministic, slice-local EnterpriseRAG-Bench dataset."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.benchmark import load_documents, load_questions  # noqa: E402


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")


def prepare_benchmark(
    *,
    questions_path: Path,
    documents_zip: Path,
    output_dir: Path,
    seed: int,
    limit: int | None,
    dataset_version: str,
) -> dict[str, Any]:
    if limit is not None and limit < 1:
        raise ValueError("--limit must be greater than zero")
    questions_path = questions_path.resolve()
    documents_zip = documents_zip.resolve()
    output_dir = output_dir.resolve()
    output_paths = {
        "questions": output_dir / "questions.jsonl",
        "documents": output_dir / "documents.jsonl",
        "manifest": output_dir / "manifest.json",
    }
    input_paths = {questions_path, documents_zip}
    if any(path.resolve() in input_paths for path in output_paths.values()):
        raise ValueError("output files must not overwrite either benchmark raw input")

    questions = load_questions(questions_path)
    documents, skipped_documents = load_documents(documents_zip)
    document_ids = {document.document_id for document in documents}

    missing_by_question = {
        question.question_id: [
            document_id
            for document_id in question.gold_document_ids
            if document_id not in document_ids
        ]
        for question in questions
    }
    eligible = [
        question
        for question in questions
        if question.gold_document_ids and not missing_by_question[question.question_id]
    ]
    eligible_ids = {question.question_id for question in eligible}
    missing_gold_ids = {
        question_id: missing_ids
        for question_id, missing_ids in missing_by_question.items()
        if missing_ids
    }

    selected = eligible
    if limit is not None and len(eligible) > limit:
        selected_indices = set(random.Random(seed).sample(range(len(eligible)), limit))
        selected = [question for index, question in enumerate(eligible) if index in selected_indices]

    skipped_questions = [
        question.question_id
        for question in questions
        if question.question_id not in eligible_ids
    ]
    questions_without_gold = [
        question.question_id for question in questions if not question.gold_document_ids
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(
        output_paths["questions"],
        [question.to_dict() for question in selected],
    )
    _write_jsonl(
        output_paths["documents"],
        [document.to_dict() for document in documents],
    )

    manifest: dict[str, Any] = {
        "dataset": "EnterpriseRAG-Bench",
        "dataset_version": dataset_version,
        "source_slice": documents_zip.name,
        "seed": seed,
        "limit": limit,
        "counts": {
            "questions_official": len(questions),
            "questions_eligible": len(eligible),
            "questions_selected": len(selected),
            "questions_excluded": len(skipped_questions),
            "questions_skipped_missing_gold": len(missing_gold_ids),
            "questions_without_gold_documents": len(questions_without_gold),
            "questions_missing_gold_ids": len(missing_gold_ids),
            "documents_loaded": len(documents),
            "documents_skipped": len(skipped_documents),
        },
        "skipped_questions": skipped_questions,
        "questions_without_gold_documents": questions_without_gold,
        "skipped_documents": skipped_documents,
        "missing_gold_ids": missing_gold_ids,
        "selected_question_ids": [question.question_id for question in selected],
        "outputs": {
            "questions": output_paths["questions"].name,
            "documents": output_paths["documents"].name,
        },
    }
    output_paths["manifest"].write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--questions",
        type=Path,
        default=REPO_ROOT / "external" / "EnterpriseRAG-Bench" / "questions.jsonl",
    )
    parser.add_argument(
        "--documents-zip",
        type=Path,
        default=REPO_ROOT / "data" / "enterprise_rag_bench" / "raw" / "confluence_slice_1.zip",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT
        / "data"
        / "enterprise_rag_bench"
        / "processed"
        / "confluence_slice_1",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--dataset-version", default="v1.0.0")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    manifest = prepare_benchmark(
        questions_path=args.questions,
        documents_zip=args.documents_zip,
        output_dir=args.output_dir,
        seed=args.seed,
        limit=args.limit,
        dataset_version=args.dataset_version,
    )
    print(json.dumps(manifest["counts"], indent=2))
    print(f"Manifest: {args.output_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()