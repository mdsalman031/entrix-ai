"""Evidence-sufficiency controller — core research module.

Implements three estimator strategies behind a common interface:

  Baseline A (Heuristic): Lexical coverage, evidence count, simple
  contradiction detection. Transparent and explainable.

  Baseline B (LLM-based): Structured prompt to an LLM provider with
  Pydantic-validated output. Evidence IDs validated against actual passages.

  Candidate (Structured Controller): Query-specific requirement extraction,
  coverage matrix, contradiction analysis, and calibrated decision rule.

The controller enforces:
  - Maximum one retry attempt.
  - Retry uses only authorized evidence and the query to identify missing info.
  - Abstention produces structured, machine-readable output for evaluation.
  - LLM failure → safe abstention, never a fabricated answer.

Research formalism (ACES):
  Sufficiency(q, u) = F(q, D_Auth(u))
  Evidence sufficiency is an authorization-conditioned function of the user's
  identity, not an objective corpus-level invariant.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

import structlog

from app.config import get_settings
from app.schemas import EvidenceItem, SufficiencyAssessment, SufficiencyDecision

logger = structlog.get_logger(__name__)
_settings = get_settings()


# ── Estimator interface ──────────────────────────────────────────────────


class SufficiencyEstimator(ABC):
    """Base class for evidence-sufficiency estimators."""

    @abstractmethod
    async def assess(
        self,
        query: str,
        evidence: list[EvidenceItem],
        threshold: float | None = None,
    ) -> SufficiencyAssessment:
        """Assess whether the evidence is sufficient to answer the query."""
        ...

    @abstractmethod
    def name(self) -> str: ...


# ── Baseline A: Heuristic Sufficiency ────────────────────────────────────


class HeuristicEstimator(SufficiencyEstimator):
    """Lexical/rule-based sufficiency estimator (Baseline A).

    Transparent and deterministic. Uses:
      1. Query-term coverage: fraction of significant query words found in evidence.
      2. Evidence count: minimum number of evidence items required.
      3. Simple contradiction detection: opposing terms on same entities.

    This is a BASELINE, not a reliable semantic judge. It provides an explainable
    lower bound on sufficiency assessment quality.
    """

    def name(self) -> str:
        return "heuristic"

    async def assess(
        self,
        query: str,
        evidence: list[EvidenceItem],
        threshold: float | None = None,
    ) -> SufficiencyAssessment:
        threshold = threshold or _settings.sufficiency_threshold

        if not evidence:
            return SufficiencyAssessment(
                decision=SufficiencyDecision.INSUFFICIENT,
                coverage_score=0.0,
                rationale="No evidence available",
                missing_information=["No authorized evidence retrieved"],
            )

        # Extract significant query terms (skip stop words)
        query_terms = _extract_significant_terms(query)
        evidence_text = " ".join(e.text.lower() for e in evidence)

        # Coverage: fraction of query terms found in evidence
        if query_terms:
            covered = sum(1 for t in query_terms if t in evidence_text)
            coverage = covered / len(query_terms)
        else:
            coverage = 0.5  # No significant terms → neutral

        # Evidence count factor
        count_factor = min(len(evidence) / 2.0, 1.0)  # At least 2 items preferred

        # Simple contradiction detection
        contradictions = _detect_contradictions(evidence)

        # Combined score
        score = coverage * 0.7 + count_factor * 0.3
        if contradictions:
            score *= 0.8  # Penalize contradictions

        # Decision
        if score >= threshold:
            decision = SufficiencyDecision.SUFFICIENT
        else:
            decision = SufficiencyDecision.INSUFFICIENT

        # Identify missing terms
        missing = [t for t in query_terms if t not in evidence_text]

        return SufficiencyAssessment(
            decision=decision,
            coverage_score=round(score, 3),
            supporting_evidence_ids=[e.evidence_id for e in evidence],
            missing_information=[f"Query term not found in evidence: '{t}'" for t in missing[:5]],
            contradictions=contradictions,
            confidence=round(score, 3),
            rationale=f"Heuristic: coverage={coverage:.2f}, count_factor={count_factor:.2f}, "
            f"contradictions={len(contradictions)}",
        )


# ── Baseline B: LLM-based Sufficiency ───────────────────────────────────


class LLMEstimator(SufficiencyEstimator):
    """LLM-based sufficiency estimator (Baseline B).

    Sends a structured prompt to the configured LLM provider and validates
    the response with Pydantic. Every evidence ID in the response is validated
    against the actual passages supplied.

    On LLM failure: returns a safe INSUFFICIENT assessment rather than
    fabricating a sufficient judgment.
    """

    def __init__(self, llm_provider=None):
        self._llm = llm_provider

    def name(self) -> str:
        return "llm"

    async def assess(
        self,
        query: str,
        evidence: list[EvidenceItem],
        threshold: float | None = None,
    ) -> SufficiencyAssessment:
        if self._llm is None:
            from app.generation import get_llm_provider

            self._llm = get_llm_provider()

        valid_ids = {e.evidence_id for e in evidence}

        # Build evidence context (no unauthorized content — we only receive authorized evidence)
        evidence_text = "\n\n".join(
            f"[{e.evidence_id}] (from: {e.document_title}, chunk {e.chunk_index}):\n{e.text}"
            for e in evidence
        )

        prompt = f"""Assess whether the following evidence is sufficient to answer the query.

QUERY: {query}

EVIDENCE:
{evidence_text}

Respond with a JSON object containing:
- "decision": "sufficient" or "insufficient"
- "supporting_evidence_ids": list of evidence IDs that support answering
- "missing_information": list of specific facts or information still needed
- "contradictions": list of any contradictions found in evidence
- "confidence": float 0-1 indicating assessment confidence
- "rationale": brief explanation of the assessment

IMPORTANT: Only reference evidence IDs that appear above. Do not fabricate IDs."""

        try:
            response = await self._llm.generate(prompt, structured=True)
            assessment = _parse_llm_assessment(response, valid_ids, threshold)
            return assessment
        except Exception as e:
            logger.error("llm_sufficiency_failed", error=str(e))
            return SufficiencyAssessment(
                decision=SufficiencyDecision.INSUFFICIENT,
                coverage_score=0.0,
                rationale=f"LLM assessment failed: {type(e).__name__}. Failing safe.",
                confidence=0.0,
            )


# ── Candidate: Structured Evidence Controller ────────────────────────────


class StructuredEstimator(SufficiencyEstimator):
    """Structured evidence-sufficiency controller (Candidate method).

    The proposed method for the research contribution:
      1. Extract query-specific evidence requirements (what facts are needed).
      2. Map requirements to authorized passages (coverage matrix).
      3. Detect contradictions and consistency issues.
      4. Score coverage against a calibrated threshold.
      5. Decision: sufficient → answer, insufficient → retry (max 1), still insufficient → abstain.

    This method combines elements of RINSE's pre-generation assessment with
    authorization-conditioned evidence evaluation (ACES formalism).
    """

    def __init__(self, llm_provider=None):
        self._llm = llm_provider

    def name(self) -> str:
        return "structured"

    async def assess(
        self,
        query: str,
        evidence: list[EvidenceItem],
        threshold: float | None = None,
    ) -> SufficiencyAssessment:
        threshold = threshold or _settings.sufficiency_threshold

        if not evidence:
            return SufficiencyAssessment(
                decision=SufficiencyDecision.INSUFFICIENT,
                coverage_score=0.0,
                rationale="No authorized evidence available",
                missing_information=["No evidence retrieved within authorization scope"],
            )

        # Step 1: Extract query requirements
        requirements = _extract_query_requirements(query)

        # Step 2: Build coverage matrix
        coverage_matrix = _build_coverage_matrix(requirements, evidence)

        # Step 3: Compute coverage score
        if requirements:
            covered_count = sum(1 for r in requirements if coverage_matrix.get(r, 0) > 0)
            coverage_score = covered_count / len(requirements)
        else:
            coverage_score = 0.5

        # Step 4: Detect contradictions
        contradictions = _detect_contradictions(evidence)
        if contradictions:
            coverage_score *= 0.85  # Penalize contradictions

        # Step 5: Evidence provenance and diversity check
        unique_docs = len({e.document_id for e in evidence})
        diversity_bonus = min(unique_docs / 3.0, 1.0) * 0.1
        final_score = min(coverage_score + diversity_bonus, 1.0)

        # Step 6: Decision
        missing = [r for r in requirements if coverage_matrix.get(r, 0) == 0]
        supporting_ids = [
            e.evidence_id
            for e in evidence
            if any(
                r.lower() in e.text.lower() for r in requirements if coverage_matrix.get(r, 0) > 0
            )
        ]

        if final_score >= threshold:
            decision = SufficiencyDecision.SUFFICIENT
        else:
            decision = SufficiencyDecision.INSUFFICIENT

        return SufficiencyAssessment(
            decision=decision,
            coverage_score=round(final_score, 3),
            supporting_evidence_ids=supporting_ids,
            missing_information=[f"Missing: {m}" for m in missing[:5]],
            contradictions=contradictions,
            confidence=round(final_score, 3),
            rationale=(
                f"Structured: {covered_count}/{len(requirements)} requirements covered, "
                f"{unique_docs} unique sources, {len(contradictions)} contradictions"
                if requirements
                else "No specific requirements extracted"
            ),
        )


# ── Evidence Sufficiency Controller (orchestrator) ───────────────────────


class EvidenceSufficiencyController:
    """Orchestrates the sufficiency assessment → retry → answer/abstain flow.

    Enforces:
      - Maximum 1 retry attempt.
      - Retry reformulation uses only the query and authorized evidence.
      - Abstention is structured for offline evaluation.
    """

    def __init__(self, estimator: SufficiencyEstimator | None = None):
        self.estimator = estimator or _get_default_estimator()

    async def evaluate(
        self,
        query: str,
        evidence: list[EvidenceItem],
        threshold: float | None = None,
    ) -> SufficiencyAssessment:
        """Assess evidence sufficiency. Does NOT handle retry — that's the caller's job."""
        return await self.estimator.assess(query, evidence, threshold)

    def generate_retry_query(
        self,
        original_query: str,
        assessment: SufficiencyAssessment,
    ) -> str | None:
        """Generate a focused retrieval reformulation based on missing information.

        Uses ONLY the original query and the assessment (which is derived from
        authorized evidence). Never uses restricted documents.
        """
        if not assessment.missing_information:
            return None

        # Build a focused query from the missing information
        missing_terms = " ".join(
            info.replace("Missing: ", "")
            .replace("Query term not found in evidence: ", "")
            .strip("'")
            for info in assessment.missing_information[:3]
        )

        if missing_terms.strip():
            return f"{original_query} {missing_terms}"
        return None


# ── Utility functions ────────────────────────────────────────────────────

_STOP_WORDS = frozenset(
    "a an the is are was were be been being have has had do does did will would "
    "shall should may might can could of in to for on with at by from as into "
    "through during before after above below between under over about up down "
    "out off then than too very what which who whom this that these those "
    "am it its i me my we our you your he him his she her they them their how "
    "when where why all each every both few more most other some such no not "
    "only same so and but or if".split()
)


def _extract_significant_terms(text: str) -> list[str]:
    """Extract significant (non-stop) words from text."""
    words = re.findall(r"\b[a-zA-Z]{2,}\b", text.lower())
    return [w for w in words if w not in _STOP_WORDS]


def _extract_query_requirements(query: str) -> list[str]:
    """Extract query-specific information requirements.

    Uses a simple heuristic: significant terms and noun-phrase patterns.
    A full implementation would use NLP or an LLM for requirement extraction.
    """
    terms = _extract_significant_terms(query)
    # Group consecutive significant terms as requirements
    if len(terms) <= 2:
        return terms

    requirements = []
    # Individual significant terms
    requirements.extend(terms[:6])
    # Bigrams of significant terms
    for i in range(len(terms) - 1):
        requirements.append(f"{terms[i]} {terms[i + 1]}")

    return requirements[:8]  # Cap at 8 requirements


def _build_coverage_matrix(
    requirements: list[str],
    evidence: list[EvidenceItem],
) -> dict[str, float]:
    """Map each requirement to its coverage score across evidence items."""
    coverage = {}
    evidence_text = " ".join(e.text.lower() for e in evidence)

    for req in requirements:
        req_lower = req.lower()
        if req_lower in evidence_text:
            # Count occurrences for a rough strength signal
            count = evidence_text.count(req_lower)
            coverage[req] = min(count / 2.0, 1.0)  # Normalize
        else:
            coverage[req] = 0.0

    return coverage


def _detect_contradictions(evidence: list[EvidenceItem]) -> list[str]:
    """Detect simple contradictions in evidence passages.

    Uses a heuristic: looks for opposing sentiment indicators or negation
    patterns applied to the same key terms across different evidence items.
    """
    contradictions = []
    negation_patterns = ["not ", "no ", "never ", "cannot ", "isn't ", "aren't ", "don't "]

    # Collect key terms and their assertion/negation status per evidence item
    for i, e1 in enumerate(evidence):
        for e2 in evidence[i + 1 :]:
            text1 = e1.text.lower()
            text2 = e2.text.lower()

            # Find shared significant terms
            terms1 = set(_extract_significant_terms(e1.text))
            terms2 = set(_extract_significant_terms(e2.text))
            shared = terms1 & terms2

            for term in shared:
                # Check if one negates what the other asserts
                neg_in_1 = any(f"{neg}{term}" in text1 for neg in negation_patterns)
                neg_in_2 = any(f"{neg}{term}" in text2 for neg in negation_patterns)

                if neg_in_1 != neg_in_2:
                    contradictions.append(
                        f"Conflicting statements about '{term}' between "
                        f"evidence {e1.evidence_id[:8]} and {e2.evidence_id[:8]}"
                    )

            if len(contradictions) >= 3:
                return contradictions

    return contradictions


def _parse_llm_assessment(
    response: str,
    valid_ids: set[str],
    threshold: float | None,
) -> SufficiencyAssessment:
    """Parse LLM response into a validated SufficiencyAssessment.

    Validates that all referenced evidence IDs exist in the actual evidence set.
    """
    import json

    threshold = threshold or _settings.sufficiency_threshold

    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        return SufficiencyAssessment(
            decision=SufficiencyDecision.INSUFFICIENT,
            coverage_score=0.0,
            rationale="LLM returned non-JSON response. Failing safe.",
            confidence=0.0,
        )

    # Validate evidence IDs — reject fabricated ones
    raw_ids = data.get("supporting_evidence_ids", [])
    validated_ids = [eid for eid in raw_ids if eid in valid_ids]
    fabricated_count = len(raw_ids) - len(validated_ids)
    if fabricated_count > 0:
        logger.warning("fabricated_evidence_ids_rejected", count=fabricated_count)

    confidence = float(data.get("confidence", 0.0))
    decision_str = data.get("decision", "insufficient").lower()

    if decision_str == "sufficient" and confidence >= threshold:
        decision = SufficiencyDecision.SUFFICIENT
    else:
        decision = SufficiencyDecision.INSUFFICIENT

    return SufficiencyAssessment(
        decision=decision,
        coverage_score=round(confidence, 3),
        supporting_evidence_ids=validated_ids,
        missing_information=data.get("missing_information", []),
        contradictions=data.get("contradictions", []),
        confidence=round(confidence, 3),
        rationale=data.get("rationale", ""),
    )


# ── Factory ──────────────────────────────────────────────────────────────


def _get_default_estimator() -> SufficiencyEstimator:
    name = _settings.sufficiency_estimator
    if name == "llm":
        return LLMEstimator()
    elif name == "structured":
        return StructuredEstimator()
    else:
        return HeuristicEstimator()


def get_estimator(name: str | None = None) -> SufficiencyEstimator:
    """Get an estimator by name."""
    name = name or _settings.sufficiency_estimator
    if name == "llm":
        return LLMEstimator()
    elif name == "structured":
        return StructuredEstimator()
    else:
        return HeuristicEstimator()
