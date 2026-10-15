"""Build controlled policy annotations separate from official benchmark labels."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    REPO_ROOT / "data" / "enterprise_rag_bench" / "processed" / "confluence_slice_1"
)
DEFAULT_OFFICIAL = REPO_ROOT / "external" / "EnterpriseRAG-Bench" / "questions.jsonl"
DEFAULT_OUTPUT = REPO_ROOT / "experiments" / "configs" / "enterprise_policy_v1.json"
POLICY_VERSION = "enterprise_policy_v1"
SCENARIO_TYPES = (
    "authorized_supported",
    "unauthorized_supported",
    "absent",
    "incomplete_or_conflicting",
)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8-sig") as source:
        for line_number, line in enumerate(source, start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: malformed JSON") from error
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number}: expected a JSON object")
            records.append(record)
    return records


def _gold_ids(question: dict[str, Any]) -> list[str]:
    return list(question.get("gold_document_ids", question.get("expected_doc_ids", [])))


def validate_policy_annotations(
    annotations: list[dict[str, Any]],
    questions_by_id: dict[str, dict[str, Any]],
) -> None:
    """Reject annotations whose labels disagree with accessible official gold IDs."""
    seen_ids: set[str] = set()
    for annotation in annotations:
        question_id = annotation.get("question_id")
        if question_id not in questions_by_id:
            raise ValueError(f"Policy references unknown question: {question_id}")
        if question_id in seen_ids:
            raise ValueError(f"Duplicate policy annotation: {question_id}")
        seen_ids.add(question_id)

        scenario_type = annotation.get("scenario_type")
        gold = set(_gold_ids(questions_by_id[question_id]))
        accessible = set(annotation.get("authorized_gold_document_ids", []))
        inaccessible = set(annotation.get("unauthorized_gold_document_ids", []))
        if accessible & inaccessible or accessible | inaccessible != gold:
            raise ValueError(f"Policy evidence does not partition gold IDs for {question_id}")

        if scenario_type == "authorized_supported":
            valid = bool(gold) and accessible == gold and not inaccessible
            valid = valid and annotation.get("expected_answerable") is True
        elif scenario_type == "unauthorized_supported":
            valid = bool(gold) and not accessible and inaccessible == gold
            valid = valid and annotation.get("expected_answerable") is False
        elif scenario_type == "absent":
            source = questions_by_id[question_id]
            category = source.get("category", source.get("question_type"))
            valid = not gold and category == "info_not_found"
            valid = valid and annotation.get("expected_answerable") is False
        elif scenario_type == "incomplete_or_conflicting":
            valid = bool(accessible) and bool(inaccessible) and accessible | inaccessible == gold
            valid = valid and annotation.get("expected_answerable") is False
        else:
            raise ValueError(f"Unknown policy scenario type: {scenario_type}")

        required_fields = (
            "scenario_id",
            "organization_id",
            "user_role",
            "policy_version",
            "policy_rule",
        )
        if not valid or any(not annotation.get(field) for field in required_fields):
            raise ValueError(f"Policy label conflicts with accessible gold evidence: {question_id}")


def build_policy(
    prepared_questions: list[dict[str, Any]],
    official_questions: list[dict[str, Any]],
    *,
    seed: int,
    per_scenario: int,
) -> dict[str, Any]:
    if per_scenario < 1:
        raise ValueError("per_scenario must be greater than zero")

    prepared_by_id = {question["question_id"]: question for question in prepared_questions}
    official_by_id = {question["question_id"]: question for question in official_questions}
    missing_official = set(prepared_by_id) - set(official_by_id)
    if missing_official:
        raise ValueError(f"Prepared questions absent from official set: {sorted(missing_official)}")

    rng = random.Random(seed)
    incomplete_pool = sorted(
        question_id
        for question_id, question in prepared_by_id.items()
        if len(_gold_ids(question)) >= 2
    )
    if len(incomplete_pool) < per_scenario:
        raise ValueError("Not enough multi-gold questions for incomplete scenarios")
    incomplete_ids = rng.sample(incomplete_pool, per_scenario)

    remaining_supported = sorted(
        question_id
        for question_id, question in prepared_by_id.items()
        if _gold_ids(question) and question_id not in incomplete_ids
    )
    if len(remaining_supported) < 2 * per_scenario:
        raise ValueError("Not enough remaining evidence-backed questions for supported scenarios")
    supported_ids = rng.sample(remaining_supported, 2 * per_scenario)

    absent_pool = sorted(
        question["question_id"]
        for question in official_questions
        if question.get("question_type") == "info_not_found"
        and not question.get("expected_doc_ids")
    )
    if len(absent_pool) < per_scenario:
        raise ValueError("Not enough official Info Not Found questions")
    absent_ids = rng.sample(absent_pool, per_scenario)

    selections = {
        "authorized_supported": supported_ids[:per_scenario],
        "unauthorized_supported": supported_ids[per_scenario:],
        "absent": absent_ids,
        "incomplete_or_conflicting": incomplete_ids,
    }
    annotations: list[dict[str, Any]] = []
    for scenario_type in SCENARIO_TYPES:
        for index, question_id in enumerate(selections[scenario_type], start=1):
            question = official_by_id[question_id]
            gold_ids = _gold_ids(prepared_by_id.get(question_id, question))
            if scenario_type == "authorized_supported":
                authorized, unauthorized, answerable = gold_ids, [], True
                rule = "viewer can access every gold document for this case"
            elif scenario_type == "unauthorized_supported":
                authorized, unauthorized, answerable = [], gold_ids, False
                rule = "gold documents require admin; this case uses a viewer"
            elif scenario_type == "absent":
                authorized, unauthorized, answerable = [], [], False
                rule = "official Info Not Found question has no gold documents"
            else:
                authorized = gold_ids[:-1]
                unauthorized = gold_ids[-1:]
                answerable = False
                rule = "viewer can access only part of the required gold evidence"

            annotations.append(
                {
                    "question_id": question_id,
                    "scenario_id": f"{scenario_type}_{index:02d}",
                    "scenario_type": scenario_type,
                    "organization_id": f"pilot-{scenario_type}-{index:02d}",
                    "user_role": "viewer",
                    "authorized_gold_document_ids": authorized,
                    "unauthorized_gold_document_ids": unauthorized,
                    "expected_answerable": answerable,
                    "policy_version": POLICY_VERSION,
                    "policy_rule": rule,
                }
            )

    questions_for_validation = dict(official_by_id)
    validate_policy_annotations(annotations, questions_for_validation)
    return {
        "policy_version": POLICY_VERSION,
        "seed": seed,
        "per_scenario": per_scenario,
        "synthetic_controlled_policy_intervention": True,
        "scenario_counts": {scenario: len(selections[scenario]) for scenario in SCENARIO_TYPES},
        "annotations": annotations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--official-questions", type=Path, default=DEFAULT_OFFICIAL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--per-scenario", type=int, default=5)
    args = parser.parse_args()

    policy = build_policy(
        _load_jsonl(args.input_dir / "questions.jsonl"),
        _load_jsonl(args.official_questions),
        seed=args.seed,
        per_scenario=args.per_scenario,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(policy, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(policy["scenario_counts"], indent=2))
    print(f"Policy annotations: {args.output}")


if __name__ == "__main__":
    main()
