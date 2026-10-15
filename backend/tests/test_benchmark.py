from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

from app.benchmark import load_documents, load_questions
from app.ingestion import ingest_document
from app.models import Organization, User
from app.retrieval import RetrievalEngine

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from prepare_benchmark import prepare_benchmark  # noqa: E402
from prepare_enterprise_policy import validate_policy_annotations  # noqa: E402


def _question(question_id: str, document_ids: list[str]) -> dict:
    return {
        "question_id": question_id,
        "question_type": "basic",
        "source_types": ["confluence"],
        "question": f"Question for {question_id}?",
        "expected_doc_ids": document_ids,
        "gold_answer": "A supported answer.",
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def _write_zip(path: Path, documents: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in documents.items():
            archive.writestr(name, text)


def test_malformed_question_and_document_records_are_rejected(tmp_path: Path):
    questions_path = tmp_path / "questions.jsonl"
    questions_path.write_text('{"question_id":"qst_bad"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="question"):
        load_questions(questions_path)

    archive_path = tmp_path / "documents.zip"
    _write_zip(archive_path, {"confluence/not-a-dsid.txt": "A title\nBody"})
    with pytest.raises(ValueError, match="expected <source_type>/dsid_"):
        load_documents(archive_path)


def test_missing_gold_ids_and_seeded_subset_are_recorded(tmp_path: Path):
    question_path = tmp_path / "questions.jsonl"
    archive_path = tmp_path / "slice.zip"
    records = [
        _question("qst_0001", ["dsid_present"]),
        _question("qst_0002", ["dsid_missing"]),
        _question("qst_0003", ["dsid_present"]),
        _question("qst_0004", ["dsid_present"]),
    ]
    _write_jsonl(question_path, records)
    _write_zip(
        archive_path,
        {"confluence/dsid_present__known-title.txt": "Known title\nKnown body."},
    )

    manifests = []
    for folder in (tmp_path / "first", tmp_path / "second"):
        manifests.append(
            prepare_benchmark(
                questions_path=question_path,
                documents_zip=archive_path,
                output_dir=folder,
                seed=19,
                limit=2,
                dataset_version="test",
            )
        )

    assert manifests[0]["selected_question_ids"] == manifests[1]["selected_question_ids"]
    assert manifests[0]["missing_gold_ids"] == {"qst_0002": ["dsid_missing"]}
    prepared_docs = [
        json.loads(line)
        for line in (tmp_path / "first" / "documents.jsonl").read_text().splitlines()
    ]
    assert prepared_docs[0]["document_id"] == "dsid_present"
    assert prepared_docs[0]["source_type"] == "confluence"
    assert prepared_docs[0]["title"] == "Known title"


def test_policy_scenarios_match_accessible_gold_evidence():
    gold = ["dsid_a", "dsid_b"]
    questions = {
        "q1": {"expected_doc_ids": gold, "question_type": "basic"},
        "q2": {"expected_doc_ids": [], "question_type": "info_not_found"},
    }
    annotations = [
        {
            "question_id": "q1",
            "scenario_id": "authorized-1",
            "scenario_type": "authorized_supported",
            "organization_id": "tenant-a",
            "user_role": "viewer",
            "authorized_gold_document_ids": gold,
            "unauthorized_gold_document_ids": [],
            "expected_answerable": True,
            "policy_version": "v1",
            "policy_rule": "all gold documents accessible",
        },
        {
            "question_id": "q2",
            "scenario_id": "absent-1",
            "scenario_type": "absent",
            "organization_id": "tenant-b",
            "user_role": "viewer",
            "authorized_gold_document_ids": [],
            "unauthorized_gold_document_ids": [],
            "expected_answerable": False,
            "policy_version": "v1",
            "policy_rule": "official no-gold question",
        },
    ]
    validate_policy_annotations(annotations, questions)
    annotations[0]["authorized_gold_document_ids"] = ["dsid_a"]
    with pytest.raises(ValueError, match="does not partition|conflicts"):
        validate_policy_annotations(annotations, questions)


@pytest.mark.asyncio
async def test_original_dsid_survives_ingestion_and_retrieval(db):
    organization = Organization(name="Benchmark", slug="benchmark")
    db.add(organization)
    await db.flush()
    user = User(
        organization_id=organization.id,
        username="benchmark-viewer",
        email="benchmark-viewer@example.test",
        role="viewer",
        hashed_password="not-used",
    )
    db.add(user)
    await db.flush()

    engine = RetrievalEngine()
    await ingest_document(
        db,
        engine,
        organization_id=organization.id,
        title="Stable identifier document",
        content="Benchmark sentinel supports stable source identifier retrieval.",
        source_id="dsid_original-benchmark-id",
        allowed_roles=["viewer"],
    )
    results = await engine.search("benchmark sentinel stable identifier", user, db)

    assert results
    assert results[0].source_id == "dsid_original-benchmark-id"
