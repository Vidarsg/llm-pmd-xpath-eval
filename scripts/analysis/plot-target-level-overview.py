import argparse
import csv
from collections import defaultdict
from pathlib import Path

"""Plot target-level experiment results aggregated across models and repeated runs.

Usage example:
  python scripts/analysis/plot-target-level-overview.py \
    --syntax-summary out/analysis-summary/experiment/syntax_execution_summary.csv \
    --behavior-summary out/analysis-summary/experiment/behavioral_agreement_summary.csv \
    --out-figure out/analysis-summary/experiment/target_level_overview.png
"""


MATCH_COLUMNS = [
    "exactCount",
    "overlapCount",
    "fileLevelCount",
]

SIMILAR_COLUMNS = [
    "llmSupersetCount",
    "gtSupersetCount",
    "partialFileOverlapCount",
]


def read_csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def as_float(row: dict, name: str) -> float:
    try:
        return float(row.get(name) or 0.0)
    except ValueError:
        return 0.0


def as_int(row: dict, name: str) -> int:
    try:
        return int(float(row.get(name) or 0))
    except ValueError:
        return 0


def short_model_name(model: str) -> str:
    name = model.strip().replace("\\", "/")
    aliases = {
        "openai/openai/gpt-oss-120b": "gpt-oss-120b",
        "openai/gpt-oss-120b": "gpt-oss-120b",
        "openai/Qwen/Qwen3.5-122B-A10B-FP8": "Qwen3.5-122B",
        "Qwen/Qwen3.5-122B-A10B-FP8": "Qwen3.5-122B",
        "mistralai/Mistral-Large-3-675B-Instruct-2512-NVFP4": "Mistral-Large",
        "google/gemma-4-31B-it": "Gemma-4-31B",
    }
    if name in aliases:
        return aliases[name]
    parts = [part for part in name.split("/") if part]
    return parts[-1].replace("-Instruct-2512", "").replace("-NVFP4", "").replace("-FP8", "") if parts else model


def condition_key(row: dict) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("target", "")),
        str(row.get("model", "")),
        str(row.get("promptStyle", "")),
        str(row.get("temperature", "")),
        str(row.get("runCount", "")),
    )


def non_empty_denominator(row: dict) -> int:
    total = as_int(row, "totalRules")
    excluded = as_int(row, "bothEmptyCount") + as_int(row, "nonComparableCount")
    return total - excluded


def grouped_pct(row: dict, columns: list[str]) -> float:
    denominator = non_empty_denominator(row)
    if denominator <= 0:
        return 0.0
    count = sum(as_int(row, name) for name in columns)
    return 100.0 * count / denominator


def positive_non_empty_pct(row: dict) -> float:
    return grouped_pct(row, MATCH_COLUMNS + SIMILAR_COLUMNS)


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plot target-level performance averaged across models and repeated runs."
    )
    parser.add_argument("--syntax-summary", required=True)
    parser.add_argument("--behavior-summary", required=True)
    parser.add_argument("--out-figure", required=True)
    args = parser.parse_args()

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError as exc:
        raise SystemExit(
            "This script requires matplotlib and numpy. Install them with: python -m pip install matplotlib numpy"
        ) from exc

    syntax_rows = read_csv_rows(Path(args.syntax_summary))
    behavior_rows = read_csv_rows(Path(args.behavior_summary))
    behavior_by_condition = {condition_key(row): row for row in behavior_rows}

    merged_rows = []
    for syntax_row in syntax_rows:
        behavior_row = behavior_by_condition.get(condition_key(syntax_row))
        if behavior_row is not None:
            merged_rows.append({**behavior_row, **syntax_row})
    if not merged_rows:
        raise SystemExit("No overlapping target conditions found in summary CSVs.")

    target_groups = defaultdict(list)
    target_model_groups = defaultdict(list)
    for row in merged_rows:
        target_groups[str(row.get("target", ""))].append(row)
        target_model_groups[(str(row.get("target", "")), str(row.get("model", "")))].append(row)

    targets = sorted(target_groups)
    models = sorted({str(row.get("model", "")) for row in merged_rows}, key=short_model_name)
    target_labels = targets
    x = np.arange(len(targets))

    operational = [mean([as_float(row, "operationallyValidPct") for row in target_groups[target]]) for target in targets]
    match = [mean([grouped_pct(row, MATCH_COLUMNS) for row in target_groups[target]]) for target in targets]
    similar = [mean([grouped_pct(row, SIMILAR_COLUMNS) for row in target_groups[target]]) for target in targets]
    positive = [mean([positive_non_empty_pct(row) for row in target_groups[target]]) for target in targets]
    gt_only = [mean([as_float(row, "gtOnlyPct") for row in target_groups[target]]) for target in targets]
    noncomparable = [mean([as_float(row, "nonComparablePct") for row in target_groups[target]]) for target in targets]

    heatmap = np.zeros((len(targets), len(models)))
    for row_index, target in enumerate(targets):
        for col_index, model in enumerate(models):
            rows = target_model_groups.get((target, model), [])
            heatmap[row_index, col_index] = mean([positive_non_empty_pct(row) for row in rows])

    fig_height = max(8.0, len(targets) * 0.55 + 4.0)
    fig_width = max(11.0, len(models) * 1.1 + 7.0)
    fig, axes = plt.subplots(2, 2, figsize=(fig_width, fig_height), constrained_layout=True)

    ax = axes[0, 0]
    ax.barh(x, operational, color="#4c9f70")
    ax.set_title("Executable Generated Rules by Target")
    ax.set_xlabel("Mean % across models/runs")
    ax.set_xlim(0, 100)
    ax.set_yticks(x)
    ax.set_yticklabels(target_labels)
    ax.invert_yaxis()

    ax = axes[0, 1]
    image = ax.imshow(heatmap, cmap="Blues", vmin=0, vmax=100, aspect="auto")
    ax.set_title("Behavioral Agreement by Target and Model")
    ax.set_xticks(np.arange(len(models)))
    ax.set_xticklabels([short_model_name(model) for model in models], rotation=25, ha="right")
    ax.set_yticks(np.arange(len(targets)))
    ax.set_yticklabels(target_labels)
    for row_index in range(len(targets)):
        for col_index in range(len(models)):
            value = heatmap[row_index, col_index]
            ax.text(col_index, row_index, f"{value:.0f}", ha="center", va="center", fontsize=8)
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04, label="Positive non-empty agreement %")

    ax = axes[1, 0]
    ax.barh(x, match, label="Match", color="#4c78a8")
    ax.barh(x, similar, left=match, label="Similar", color="#72b7b2")
    ax.set_title("Behavioral Match and Similarity by Target")
    ax.set_xlabel("Mean % on non-empty comparable cases")
    ax.set_xlim(0, 100)
    ax.set_yticks(x)
    ax.set_yticklabels(target_labels)
    ax.invert_yaxis()
    ax.legend(frameon=False, fontsize=8)

    ax = axes[1, 1]
    width = 0.38
    ax.barh(x - width / 2, gt_only, height=width, label="GT only", color="#d95f02")
    ax.barh(x + width / 2, noncomparable, height=width, label="Non-comparable", color="#8c8c8c")
    ax.set_title("Target-Level Failure Pressure")
    ax.set_xlabel("Mean % of all rules")
    ax.set_xlim(0, 100)
    ax.set_yticks(x)
    ax.set_yticklabels(target_labels)
    ax.invert_yaxis()
    ax.legend(frameon=False, fontsize=8)

    fig.suptitle("Target-Level Experiment Overview", fontsize=14)
    out_figure = Path(args.out_figure)
    ensure_parent(out_figure)
    fig.savefig(out_figure, dpi=220, bbox_inches="tight")
    print(f"Wrote figure to {out_figure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
