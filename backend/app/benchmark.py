"""Read-only adapters for the official EnterpriseRAG-Bench exports."""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_DOCUMENT_FILENAME = re.compile(r"^(dsid_[A-Za-z0-9-]+)__.+\.txt$")


@dataclass(frozen=True)
class BenchmarkQuestion:
    question_id: str
    question: str
    category: str
    source_types: list[str]
    gold_document_ids: list[str]
    gold_answer: str
    answer_facts: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BenchmarkDocument:
    document_id: str
    source_type: str
    title: str
    text: str
    filename: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _required_string(record: dict[str, Any], key: str, context: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context}: '{key}' must be a non-empty string")
    return value.strip()


def load_questions(path: Path) -> list[BenchmarkQuestion]:
    """Load and validate official JSONL questions without changing the source."""
    questions: list[BenchmarkQuestion] = []
    seen_ids: set[str] = set()

    with path.open("r", encoding="utf-8-sig") as source:
        for line_number, line in enumerate(source, start=1):
            context = f"{path}:{line_number}"
            if not line.strip():
                raise ValueError(f"{context}: blank lines are not valid question records")
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{context}: malformed JSON: {error.msg}") from error
            if not isinstance(record, dict):
                raise ValueError(f"{context}: question record must be a JSON object")

            question_id = _required_string(record, "question_id", context)
            if question_id in seen_ids:
                raise ValueError(f"{context}: duplicate question_id '{question_id}'")
            seen_ids.add(question_id)

            source_types = record.get("source_types")
            if not isinstance(source_types, list) or any(
                not isinstance(item, str) or not item.strip() for item in source_types
            ):
                raise ValueError(f"{context}: 'source_types' must be a list of non-empty strings")

            gold_ids = record.get("expected_doc_ids")
            if not isinstance(gold_ids, list) or any(
                not isinstance(item, str) or not item.startswith("dsid_") for item in gold_ids
            ):
                raise ValueError(f"{context}: 'expected_doc_ids' must be a list of dsid strings")

            answer_facts = record.get("answer_facts", [])
            if not isinstance(answer_facts, list) or any(
                not isinstance(item, str) for item in answer_facts
            ):
                raise ValueError(f"{context}: 'answer_facts' must be a list of strings")

            questions.append(
                BenchmarkQuestion(
                    question_id=question_id,
                    question=_required_string(record, "question", context),
                    category=_required_string(record, "question_type", context),
                    source_types=[item.strip() for item in source_types],
                    gold_document_ids=gold_ids.copy(),
                    gold_answer=_required_string(record, "gold_answer", context),
                    answer_facts=answer_facts.copy(),
                )
            )

    if not questions:
        raise ValueError(f"{path}: no question records found")
    return questions


def load_documents(zip_path: Path) -> tuple[list[BenchmarkDocument], list[dict[str, str]]]:
    """Read text documents from a source ZIP and preserve their official dsid."""
    documents: list[BenchmarkDocument] = []
    skipped: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    with zipfile.ZipFile(zip_path) as archive:
        for entry in sorted(archive.infolist(), key=lambda item: item.filename):
            if entry.is_dir():
                continue
            if not entry.filename.lower().endswith(".txt"):
                skipped.append({"filename": entry.filename, "reason": "not a text document"})
                continue

            path = Path(entry.filename)
            match = _DOCUMENT_FILENAME.fullmatch(path.name)
            source_type = path.parts[0] if len(path.parts) > 1 else ""
            context = f"{zip_path}:{entry.filename}"
            if match is None or not source_type:
                raise ValueError(
                    f"{context}: expected <source_type>/dsid_<id>__<title>.txt"
                )

            document_id = match.group(1)
            if document_id in seen_ids:
                raise ValueError(f"{context}: duplicate document ID '{document_id}'")
            seen_ids.add(document_id)

            try:
                text = archive.read(entry).decode("utf-8-sig").strip()
            except UnicodeDecodeError as error:
                raise ValueError(f"{context}: document is not valid UTF-8") from error
            if not text:
                raise ValueError(f"{context}: document text is empty")
            title = next((line.strip() for line in text.splitlines() if line.strip()), "")
            if not title:
                raise ValueError(f"{context}: document has no title")

            documents.append(
                BenchmarkDocument(
                    document_id=document_id,
                    source_type=source_type,
                    title=title,
                    text=text,
                    filename=entry.filename,
                )
            )

    if not documents:
        raise ValueError(f"{zip_path}: no text documents found")
    return documents, skipped
