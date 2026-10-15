# Paper outline and contribution-to-evidence matrix

1. Introduction — authorization-conditioned answerability, without novelty claims before evaluation.
2. Related work — permission-aware control, RAG grounding, abstention, and attribution.
3. System — trusted identity, hybrid retrieval, pre-text authorization, controller, and bounded actions.
4. Experimental protocol — policy-labelled queries, comparable retrieval, fixed retry budget, metrics.
5. Results — populated only from exported run artifacts.
6. Discussion — false abstentions, unsupported answers, retrieval failures, and policy failures.
7. Limitations, ethics, reproducibility, and threats to validity.

| Intended claim | Implemented mechanism | Required evidence | Current status |
|---|---|---|---|
| Restricted text is not sent downstream | Document authorization before chunk-text load | Adversarial tests and audit review | Software-tested; finite coverage only |
| Controller can answer, retry once, or abstain | Explicit sufficiency controller and one retry branch | Policy-labelled benchmark comparison | Synthetic validation only |
| Task execution is bounded and policy revalidated | Allowlist, Pydantic schemas, trusted user reload, policy version | Action adversarial tests | Software-tested; mock adapter |
| Structured controller improves outcomes | B1–B4 runner | Pre-registered external evaluation | Unverified |
