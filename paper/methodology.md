# Methodology

**Research question.** Under document-level role permissions, can a controller distinguish authorized evidence that is sufficient from authorized evidence that is relevant but insufficient, then perform at most one further authorized retrieval or abstain?

**Hypotheses (unverified).** H1: a structured coverage controller improves abstention precision over always-answer retrieval on a policy-labelled corpus. H2: authorization revalidation rejects policy-stale actions. H3: server-side filtering yields zero observed restricted-text exposures in the defined adversarial suite. These are hypotheses, not results.

**Method.** The modular monolith provides independent dense and lexical candidate retrieval, reciprocal-rank fusion, and a document authorization check before chunk text is read. It compares B1 always-answer, B2 heuristic sufficiency, B3 provider-backed sufficiency, and B4 structured coverage plus one retry. Outputs record sufficient/insufficient decisions, retries, citations, and latency.

**Dataset plan.** Start with synthetic access-controlled documents for software validation; annotate each query with answerability for a given user/policy, gold document IDs, and expected abstention. A defensible study must add a licensed corpus, pre-register a split, and keep policy annotations separate from threshold tuning.

**Metrics.** Authorized recall@K, abstention precision/recall, answer coverage, citation validity, observed exposure count, retrieval/total latency, retry count, and model calls. Report per-query JSONL, bootstrap confidence intervals, paired comparisons, effect sizes, configuration, seeds, hardware, and failures.

**Threats.** Synthetic policy labels, small data, heuristic requirement extraction, model/provider dependence, threshold leakage, limited action adapter realism, and finite test coverage all limit generalization.
