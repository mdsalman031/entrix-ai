"""Run deterministic software-validation baselines and export actual results."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.evaluation import (
    compute_aggregate_metrics,
    create_synthetic_dataset,
    export_results,
    run_baseline,
)
from app.schemas import EvidenceItem


def evidence_for(dataset: list[dict]) -> dict[str, list[EvidenceItem]]:
    """Create deliberately synthetic evidence; this is not a benchmark result."""
    output: dict[str, list[EvidenceItem]] = {}
    for item in dataset:
        if item["expected_answerable"]:
            output[item["query_id"]] = [
                EvidenceItem(
                    evidence_id=f"evidence-{item['query_id']}",
                    document_id=item["relevant_doc_ids"][0],
                    document_title="Synthetic validation passage",
                    chunk_index=0,
                    score=1.0,
                    text=f"Synthetic validation evidence for: {item['query']}",
                )
            ]
        else:
            output[item["query_id"]] = []
    return output


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", default="../experiments/results/software_validation"
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--baselines", nargs="+", default=["B1", "B2", "B3", "B4"])
    args = parser.parse_args()
    dataset = create_synthetic_dataset()
    evidence_sets = evidence_for(dataset)
    output_dir = Path(args.output_dir)
    for baseline in args.baselines:
        results = await run_baseline(baseline, evidence_sets, dataset)
        export_results(
            results, compute_aggregate_metrics(results, baseline), output_dir, baseline
        )
    (output_dir / "run_metadata.json").write_text(
        '{"dataset":"synthetic software-validation only","seed":'
        + str(args.seed)
        + "}",
        encoding="utf-8",
    )


if __name__ == "__main__":
    asyncio.run(main())
