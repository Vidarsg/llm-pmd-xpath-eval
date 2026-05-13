import argparse
import csv
from collections import defaultdict
from pathlib import Path

"""Plot model-level experiment results aggregated across targets and repeated runs.

Usage example:
  python scripts/analysis/plot-model-level-overview.py \
    --syntax-summary out/analysis-summary/experiment/syntax_execution_summary.csv \
    --behavior-summary out/analysis-summary/experiment/behavioral_agreement_summary.csv \
    --out-figure out/analysis-summary/experiment/model_level_overview.png
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


def ground_truth_only_label(*paths: str) -> str:
    text = " ".join(str(path).lower() for path in paths)
    if "jpinpoint" in text:
        return "jPinpoint only"
    return "PMD only"


def condition_key(row: dict) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("target", "")),
        str(row.get("model", "")),
        str(row.get("promptStyle", "")),
        str(row.get("temperature", "")),
        str(row.get("runCount", "")),
    )


def model_group_key(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("model", "")),
        str(row.get("promptStyle", "")),
        str(row.get("temperature", "")),
    )


def non_empty_denominator(row: dict) -> int:
    total = as_int(row, "totalRules")
    excluded = as_int(row, "bothEmptyCount") + \
        as_int(row, "nonComparableCount")
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


def minmax_errors(values: list[float], center: float) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    return center - min(values), max(values) - center


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plot model-level performance averaged across targets and repeated runs."
    )
    parser.add_argument("--syntax-summary", required=True)
    parser.add_argument("--behavior-summary", required=True)
    parser.add_argument("--out-figure", required=True)
    args = parser.parse_args()
    gt_only_label = ground_truth_only_label(
        args.syntax_summary, args.behavior_summary, args.out_figure)

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

    groups = defaultdict(list)
    for syntax_row in syntax_rows:
        behavior_row = behavior_by_condition.get(condition_key(syntax_row))
        if behavior_row is None:
            continue
        merged = {**behavior_row, **syntax_row}
        groups[model_group_key(merged)].append(merged)

    if not groups:
        raise SystemExit(
            "No overlapping model conditions found in summary CSVs.")

    ordered_keys = sorted(groups, key=lambda key: (
        short_model_name(key[0]), key[1], key[2]))
    labels = [
        f"{short_model_name(model)}\n{prompt}"
        for model, prompt, _temperature in ordered_keys
    ]
    x = np.arange(len(labels))

    operational_values = [[as_float(row, "operationallyValidPct")
                           for row in groups[key]] for key in ordered_keys]
    positive_values = [[positive_non_empty_pct(
        row) for row in groups[key]] for key in ordered_keys]
    match_values = [[grouped_pct(row, MATCH_COLUMNS)
                     for row in groups[key]] for key in ordered_keys]
    similar_values = [[grouped_pct(row, SIMILAR_COLUMNS)
                       for row in groups[key]] for key in ordered_keys]
    noncomparable_values = [
        [as_float(row, "nonComparablePct") for row in groups[key]] for key in ordered_keys]
    gt_only_values = [[as_float(row, "gtOnlyPct")
                       for row in groups[key]] for key in ordered_keys]
    llm_only_values = [[as_float(row, "llmOnlyPct")
                        for row in groups[key]] for key in ordered_keys]

    operational_mean = [mean(values) for values in operational_values]
    positive_mean = [mean(values) for values in positive_values]
    match_mean = [mean(values) for values in match_values]
    similar_mean = [mean(values) for values in similar_values]
    noncomparable_mean = [mean(values) for values in noncomparable_values]
    gt_only_mean = [mean(values) for values in gt_only_values]
    llm_only_mean = [mean(values) for values in llm_only_values]

    operational_err = np.array(
        [minmax_errors(v, c) for v, c in zip(operational_values, operational_mean)]).T
    positive_err = np.array([minmax_errors(v, c)
                            for v, c in zip(positive_values, positive_mean)]).T

    fig_width = max(10.5, len(labels) * 1.35)
    fig, axes = plt.subplots(2, 2, figsize=(
        fig_width, 8.5), constrained_layout=True)

    ax = axes[0, 0]
    ax.bar(x, operational_mean, yerr=operational_err,
           capsize=3, color="#4c9f70")
    ax.set_title("Executable Generated Rules by Model")
    ax.set_ylabel("Mean % across all targets/runs")
    ax.set_ylim(0, 100)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right")

    ax = axes[0, 1]
    ax.bar(x, match_mean, label="Match", color="#4c78a8")
    ax.bar(x, similar_mean, bottom=match_mean, label="Similar", color="#72b7b2")
    ax.errorbar(x, positive_mean, yerr=positive_err,
                fmt="none", ecolor="#333333", capsize=3, linewidth=1)
    ax.set_title("Behavioral Match and Similarity on Non-Empty Cases")
    ax.set_ylabel("Mean % across all targets/runs")
    ax.set_ylim(0, 100)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right")
    ax.legend(frameon=False, fontsize=8)

    ax = axes[1, 0]
    width = 0.24
    ax.bar(x - width, gt_only_mean, width=width,
           label=gt_only_label, color="#d95f02")
    ax.bar(x, llm_only_mean, width=width, label="LLM only", color="#7570b3")
    ax.bar(x + width, noncomparable_mean, width=width,
           label="Non-comparable", color="#8c8c8c")
    ax.set_title("Main Failure Modes by Model")
    ax.set_ylabel("Mean % of all rules")
    ax.set_ylim(0, 100)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right")
    ax.legend(frameon=False, fontsize=8)

    axes[1, 1].axis("off")

    fig.suptitle("Model-Level Experiment Overview", fontsize=14)
    out_figure = Path(args.out_figure)
    ensure_parent(out_figure)
    fig.savefig(out_figure, dpi=220, bbox_inches="tight")
    print(f"Wrote figure to {out_figure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
