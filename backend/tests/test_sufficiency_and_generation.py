from __future__ import annotations

import pytest

from app.generation import LLMProvider, generate_answer
from app.schemas import EvidenceItem, SufficiencyDecision
from app.sufficiency import EvidenceSufficiencyController, HeuristicEstimator


class FabricatingProvider(LLMProvider):
    def provider_name(self) -> str:
        return "fabricating-test"

    async def generate(self, prompt: str, structured: bool = False) -> str:
        return "Unsupported claim [Evidence fabricated-id]"


@pytest.mark.asyncio
async def test_unsupported_evidence_causes_insufficiency_and_a_focused_retry_query():
    controller = EvidenceSufficiencyController(HeuristicEstimator())
    assessment = await controller.evaluate("What is the classified launch date?", [])

    assert assessment.decision is SufficiencyDecision.INSUFFICIENT
    assert controller.generate_retry_query("What is the classified launch date?", assessment)


@pytest.mark.asyncio
async def test_fabricated_citation_id_is_not_returned_to_a_client():
    evidence = [
        EvidenceItem(
            evidence_id="evidence-1",
            document_id="document-1",
            document_title="Allowed document",
            chunk_index=0,
            text="A supported fact.",
            score=1.0,
        )
    ]
    _, citations = await generate_answer("Question", evidence, FabricatingProvider())

    assert all(citation.document_id == "document-1" for citation in citations)
    assert "fabricated-id" not in str(citations)
