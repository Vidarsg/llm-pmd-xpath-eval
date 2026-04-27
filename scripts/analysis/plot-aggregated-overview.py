import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path

"""Create a compact visual overview of syntax and behavioral experiment results.

The input CSVs are produced by summarize-experiment-vs-ground-truth.py. The
figure is intended for quick comparison of experiment conditions rather than
for recomputing any metrics.
"""


def read_csv_rows(path: Path) -> list[dict]:
    """Read a CSV summary file as dictionaries."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def ensure_parent(path: Path) -> None:
    """Create the output directory before writing a figure."""
    path.parent.mkdir(parents=True, exist_ok=True)


def row_key(row: dict) -> tuple[str, str, str, str, str]:
    """Return the condition key shared by syntax and behavioral summaries."""
    return (
        str(row.get("target", "")),
        str(row.get("model", "")),
        str(row.get("promptStyle", "")),
        str(row.get("temperature", "")),
        str(row.get("runCount", "")),
    )


def row_label(row: dict, include_target: bool, include_model: bool) -> str:
    """Build a concise multi-line label for condition bars."""
    parts = []
    if include_model:
        parts.append(str(row["model"]))
    if include_target:
        parts.append(str(row["target"]))
    parts.append(str(row["promptStyle"]))
    parts.append(f"T={row['temperature']}")
    parts.append(f"run {row['runCount']}")
    return "\n".join(parts)


def category_order_key(value: str) -> tuple[int, str]:
    """Sort PMD categories in a stable, human-friendly order."""
    preferred = [
        "Best Practices",
        "Code Style",
        "Design",
        "Documentation",
        "Error Prone",
        "Multithreading",
        "Performance",
        "Security",
    ]
    if value in preferred:
        return (preferred.index(value), value)
    return (len(preferred), value)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plot an experiment overview from syntax and behavioral summary CSV files."
    )
    parser.add_argument("--syntax-summary", required=True, help="Path to syntax_execution_summary.csv")
    parser.add_argument("--behavior-summary", required=True, help="Path to behavioral_agreement_summary.csv")
    parser.add_argument(
        "--behavior-per-rule",
        required=True,
        help="Path to behavioral_agreement_per_rule.csv",
    )
    parser.add_argument("--out-figure", required=True, help="Output PNG path")
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
    behavior_per_rule_rows = read_csv_rows(Path(args.behavior_per_rule))
    if not syntax_rows:
        raise SystemExit(f"No rows found in {args.syntax_summary}")
    if not behavior_rows:
        raise SystemExit(f"No rows found in {args.behavior_summary}")
    if not behavior_per_rule_rows:
        raise SystemExit(f"No rows found in {args.behavior_per_rule}")

    behavior_by_key = {row_key(row): row for row in behavior_rows}
    merged_rows = []
    for syntax_row in syntax_rows:
        key = row_key(syntax_row)
        if key not in behavior_by_key:
            continue
        merged_rows.append({**syntax_row, **behavior_by_key[key]})

    # Plot only conditions that have both syntax/execution and behavioral data.
    if not merged_rows:
        raise SystemExit("No overlapping conditions found between syntax and behavioral summary CSV files")

    all_models = {row["model"] for row in merged_rows}
    all_targets = {row["target"] for row in merged_rows}
    include_model = len(all_models) > 1
    include_target = len(all_targets) > 1

    labels = [row_label(row, include_target=include_target, include_model=include_model) for row in merged_rows]
    x = np.arange(len(merged_rows))

    operational_pct = np.array([float(row["operationallyValidPct"]) for row in merged_rows], dtype=float)
    processing_pct = np.array([float(row["processingErrorPct"]) for row in merged_rows], dtype=float)
    config_pct = np.array([float(row["configErrorPct"]) for row in merged_rows], dtype=float)
    exact_pct = np.array([float(row["exactPct"]) for row in merged_rows], dtype=float)
    overlap_pct = np.array([float(row["overlapPct"]) for row in merged_rows], dtype=float)
    file_level_pct = np.array([float(row["fileLevelPct"]) for row in merged_rows], dtype=float)
    no_match_pct = np.array([float(row["noMatchPct"]) for row in merged_rows], dtype=float)
    non_comparable_pct = np.array([float(row["nonComparablePct"]) for row in merged_rows], dtype=float)

    category_groups = defaultdict(list)
    for row in behavior_per_rule_rows:
        category = str(row.get("category", "Unknown"))
        condition = (
            str(row.get("target", "")),
            str(row.get("model", "")),
            str(row.get("promptStyle", "")),
            str(row.get("temperature", "")),
            str(row.get("runCount", "")),
        )
        category_groups[(category, condition)].append(row)

    # The heatmap shows how often each rule category produced a useful
    # non-empty behavioral match for each experiment condition.
    ordered_conditions = [row_key(row) for row in merged_rows]
    categories = sorted({str(row.get("category", "Unknown")) for row in behavior_per_rule_rows}, key=category_order_key)
    heatmap = np.full((len(categories), len(ordered_conditions)), np.nan)
    for row_index, category in enumerate(categories):
        for col_index, condition in enumerate(ordered_conditions):
            rows = category_groups.get((category, condition), [])
            if not rows:
                continue
            positive_non_empty = sum(
                1
                for row in rows
                if str(row.get("matchType", "")) in {"exact", "overlap", "file-level"}
            )
            heatmap[row_index, col_index] = 100.0 * positive_non_empty / len(rows)

    fig_width = max(10.0, len(merged_rows) * 1.8)
    fig, axes = plt.subplots(2, 2, figsize=(fig_width, 9), constrained_layout=True)

    ax = axes[0, 0]
    ax.bar(x, operational_pct, label="Operationally valid", color="#3b7a57")
    ax.bar(x, processing_pct, bottom=operational_pct, label="Processing errors", color="#d98c3f")
    ax.bar(x, config_pct, bottom=operational_pct + processing_pct, label="Config errors", color="#b44444")
    ax.set_title("Execution Outcome Per Condition")
    ax.set_ylabel("Percent of rules")
    ax.set_ylim(0, 100)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.legend(frameon=False, fontsize=9)

    ax = axes[0, 1]
    ax.bar(x, no_match_pct, color="#e17c05", label="No match")
    ax.bar(x, non_comparable_pct, bottom=no_match_pct, color="#9c9c9c", label="Non-comparable")
    ax.set_title("Negative / Unusable Behavioral Outcomes")
    ax.set_ylabel("Percent of rules")
    ax.set_ylim(0, 100)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.legend(frameon=False, fontsize=9)

    ax = axes[1, 0]
    width = 0.18
    xpos = np.arange(len(merged_rows))
    ax.bar(xpos - 1.5 * width, exact_pct, width=width, label="Exact", color="#4c78a8")
    ax.bar(xpos - 0.5 * width, overlap_pct, width=width, label="Overlap", color="#72b7b2")
    ax.bar(xpos + 0.5 * width, file_level_pct, width=width, label="File-level", color="#f2cf5b")
    ax.set_title("Positive Non-Empty Agreement Categories")
    ax.set_ylabel("Percent of rules")
    ax.set_ylim(0, 100)
    ax.set_xticks(xpos)
    ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.legend(frameon=False, fontsize=9)

    ax = axes[1, 1]
    image = ax.imshow(heatmap, cmap="YlGn", vmin=0, vmax=100, aspect="auto")
    ax.set_title("Positive Non-Empty Agreement by Rule Category")
    ax.set_xticks(np.arange(len(labels)))
    ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.set_yticks(np.arange(len(categories)))
    ax.set_yticklabels(categories)
    for row_index in range(len(categories)):
        for col_index in range(len(labels)):
            value = heatmap[row_index, col_index]
            if math.isnan(value):
                continue
            ax.text(col_index, row_index, f"{value:.1f}", ha="center", va="center", color="black", fontsize=9)
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04, label="Positive non-empty agreement %")

    fig.suptitle("Experiment Overview From Summary Tables", fontsize=14)

    out_figure = Path(args.out_figure)
    ensure_parent(out_figure)
    fig.savefig(out_figure, dpi=220, bbox_inches="tight")
    print(f"Wrote figure to {out_figure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
