# Literature review and research gap

Search log: ACL Anthology and arXiv searches performed 2026-10-15 for permission-aware enterprise RAG, selective prediction/abstention, and citation attribution. The matrix intentionally distinguishes verified peer-reviewed work from preprints.

| Work | Type | Question / method | Evaluation and limitation |
|---|---|---|---|
| Sorodoc et al., *GaRAGe: A Benchmark with Grounding Annotations for RAG Evaluation* (Findings ACL 2025), DOI 10.18653/v1/2025.findings-acl.875 | Peer reviewed | Evaluates whether RAG models find relevant groundings and deflect when support is absent. | 2,366 questions with grounding annotations; it measures grounding/deflection, but does not model document authorization as a condition of answerability. |
| Li et al., *AttributionBench* (Findings ACL 2024), DOI 10.18653/v1/2024.findings-acl.886 | Peer reviewed | Tests automatic evaluation of whether citations support each claim. | Demonstrates that attribution assessment remains hard; it is not a retrieval-time access-control study. |
| Qi et al., *MIRAGE* (EMNLP 2024), DOI 10.18653/v1/2024.emnlp-main.347 | Peer reviewed | Uses model internals for answer attribution in RAG. | Attribution-focused; permissions and action authorization are out of scope. |
| Bhatt et al., *Enterprise AI Must Enforce Participant-Aware Access Control* (arXiv:2509.14608) | Preprint | Demonstrates enterprise AI exfiltration risks and proposes participant-aware access control. | Security-focused; its relation to evidence sufficiency and controlled abstention needs independent study. |
| Sun et al., *Permit* (arXiv:2605.09480) | Preprint | Applies permission-aware hidden-state intervention during controlled generation. | Not a substitute for retrieval-layer enforcement; it should not be cited as evidence that Entrix's retrieval controls are novel. |

## Supported research gap

Prior work establishes the value of citation grounding, deflection/abstention, and permission-aware control. This implementation does **not** establish a novel combination. The measurable, still-unverified research question is narrower: when the available corpus is filtered by a current authorization policy, how well do transparent sufficiency estimates distinguish answerable cases from cases that are unanswerable only because supporting evidence is unauthorized?

The proposed policy-version binding of a task action is an engineering safety mechanism, not a claimed research novelty. It should be evaluated as a security/control-flow property (stale policy rejection and zero observed leakage in scoped tests), not as a claim of universal protection.

## References

- [GaRAGe, ACL Anthology](https://aclanthology.org/2025.findings-acl.875/)
- [AttributionBench, ACL Anthology](https://aclanthology.org/2024.findings-acl.886/)
- [MIRAGE, ACL Anthology](https://aclanthology.org/2024.emnlp-main.347/)
- [Enterprise AI participant-aware access control, arXiv](https://arxiv.org/abs/2509.14608)
- [Permit, arXiv](https://arxiv.org/abs/2605.09480)
