import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path

"""Create a compact visual overview of syntax and behavioral experiment results.

The input CSVs are produced by summarize-experiment-vs-ground-truth.py. The
figure is intended for quick comparison of experiment conditions rather than
for recomputing any metrics.

Usage example:
  python scripts/analysis/plot-aggregated-overview.py \
    --syntax-summary out/analysis-summary/syntax_execution_summary.csv \
    --behavior-summary out/analysis-summary/behavioral_agreement_summary.csv \
    --behavior-per-rule out/analysis-summary/behavioral_agreement_per_rule.csv \
    --out-figure out/analysis-summary/aggregated_overview.png
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


def short_model_name(model: str) -> str:
    """Shorten provider-heavy model identifiers while keeping them recognizable."""
    name = model.strip().replace("\\", "/")
    aliases = {
        "openai/openai/gpt-oss-120b": "gpt-oss-120b",
        "openai/Qwen/Qwen3.5-122B-A10B-FP8": "Qwen3.5-122B",
        "openai/Qwen/Qwen3.6-27B-FP8": "Qwen3.6-27B",
        "moonshotai/Kimi-K2.6": "Kimi-K2.6",
        "mistralai/Mistral-Large-3-675B-Instruct-2512-NVFP4": "Mistral-Large",
        "mistralai/Devstral-Small-2-24B-Instruct-2512": "Devstral-Small",
        "google/gemma-4-31B-it": "Gemma-4-31B",
    }
    if name in aliases:
        return aliases[name]
    parts = [part for part in name.split("/") if part]
    if not parts:
        return model
    return parts[-1].replace("-Instruct-2512", "").replace("-NVFP4", "").replace("-FP8", "")


def row_label(row: dict, include_target: bool, include_model: bool) -> str:
    """Build a concise multi-line label for condition bars."""
    parts = []
    if include_model:
        parts.append(short_model_name(str(row["model"])))
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


def numeric_column(rows: list[dict], name: str) -> list[float]:
    """Read a numeric CSV column, treating missing older columns as zero."""
    values = []
    for row in rows:
        try:
            values.append(float(row.get(name) or 0.0))
        except ValueError:
            values.append(0.0)
    return values


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plot an experiment overview from syntax and behavioral summary CSV files."
    )
    parser.add_argument("--syntax-summary", required=True,
                        help="Path to syntax_execution_summary.csv")
    parser.add_argument("--behavior-summary", required=True,
                        help="Path to behavioral_agreement_summary.csv")
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
        from mpl_toolkits.axes_grid1 import make_axes_locatable
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
        raise SystemExit(
            "No overlapping conditions found between syntax and behavioral summary CSV files")

    all_models = {row["model"] for row in merged_rows}
    all_targets = {row["target"] for row in merged_rows}
    include_model = len(all_models) > 1
    include_target = len(all_targets) > 1

    labels = [row_label(row, include_target=include_target,
                        include_model=include_model) for row in merged_rows]
    x = np.arange(len(merged_rows))

    operational_pct = np.array(
        [float(row["operationallyValidPct"]) for row in merged_rows], dtype=float)
    processing_pct = np.array([float(row["processingErrorPct"])
                              for row in merged_rows], dtype=float)
    config_pct = np.array([float(row["configErrorPct"])
                          for row in merged_rows], dtype=float)
    exact_pct = np.array(numeric_column(merged_rows, "exactPct"), dtype=float)
    overlap_pct = np.array(numeric_column(
        merged_rows, "overlapPct"), dtype=float)
    file_level_pct = np.array(numeric_column(
        merged_rows, "fileLevelPct"), dtype=float)
    both_empty_pct = np.array(numeric_column(
        merged_rows, "bothEmptyPct"), dtype=float)
    no_match_pct = np.array(numeric_column(
        merged_rows, "noMatchPct"), dtype=float)
    gt_only_pct = np.array(numeric_column(
        merged_rows, "gtOnlyPct"), dtype=float)
    llm_only_pct = np.array(numeric_column(
        merged_rows, "llmOnlyPct"), dtype=float)
    different_files_pct = np.array(numeric_column(
        merged_rows, "differentFilesPct"), dtype=float)
    partial_file_overlap_pct = np.array(
        [
            float(row.get("llmSupersetPct") or 0.0)
            + float(row.get("gtSupersetPct") or 0.0)
            + float(row.get("partialFileOverlapPct") or 0.0)
            for row in merged_rows
        ],
        dtype=float,
    )
    detailed_no_match_pct = gt_only_pct + llm_only_pct + \
        different_files_pct + partial_file_overlap_pct
    non_comparable_pct = np.array(numeric_column(
        merged_rows, "nonComparablePct"), dtype=float)

    category_groups = defaultdict(list)
    per_rule_by_condition = defaultdict(list)
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
        per_rule_by_condition[condition].append(row)

    exact_non_empty_pct = []
    overlap_non_empty_pct = []
    file_level_non_empty_pct = []
    gt_only_non_empty_pct = []
    llm_only_non_empty_pct = []
    different_files_non_empty_pct = []
    partial_file_overlap_non_empty_pct = []
    unmatched_non_empty_pct = []
    for condition in [row_key(row) for row in merged_rows]:
        rows = per_rule_by_condition.get(condition, [])
        non_empty_total = sum(1 for row in rows if str(
            row.get("matchType", "")) != "both-empty")
        exact = 0
        overlap = 0
        file_level = 0
        gt_only = 0
        llm_only = 0
        different_files = 0
        partial_file_overlap = 0
        unmatched = 0
        for row in rows:
            match_type = str(row.get("matchType", ""))
            if match_type == "exact":
                exact += 1
            elif match_type == "overlap":
                overlap += 1
            elif match_type == "file-level":
                file_level += 1
            elif match_type == "gt-only":
                gt_only += 1
            elif match_type == "llm-only":
                llm_only += 1
            elif match_type == "different-files":
                different_files += 1
            elif match_type in {"llm-superset", "gt-superset", "partial-file-overlap"}:
                partial_file_overlap += 1
            elif match_type == "none":
                unmatched += 1
            try:
                llm_count = int(row.get("llmFindingCount") or 0)
                gt_count = int(row.get("groundTruthFindingCount") or 0)
            except ValueError:
                continue
            if match_type not in {"", "none"}:
                continue
            if llm_count == 0 and gt_count > 0:
                gt_only += 1
            elif llm_count > 0 and gt_count == 0:
                llm_only += 1
        exact_non_empty_pct.append(
            100.0 * exact / non_empty_total if non_empty_total else 0.0)
        overlap_non_empty_pct.append(
            100.0 * overlap / non_empty_total if non_empty_total else 0.0)
        file_level_non_empty_pct.append(
            100.0 * file_level / non_empty_total if non_empty_total else 0.0)
        gt_only_non_empty_pct.append(
            100.0 * gt_only / non_empty_total if non_empty_total else 0.0)
        llm_only_non_empty_pct.append(
            100.0 * llm_only / non_empty_total if non_empty_total else 0.0)
        different_files_non_empty_pct.append(
            100.0 * different_files / non_empty_total if non_empty_total else 0.0)
        partial_file_overlap_non_empty_pct.append(
            100.0 * partial_file_overlap / non_empty_total if non_empty_total else 0.0
        )
        unmatched_non_empty_pct.append(
            100.0 * unmatched / non_empty_total if non_empty_total else 0.0)
    exact_non_empty_pct = np.array(exact_non_empty_pct, dtype=float)
    overlap_non_empty_pct = np.array(overlap_non_empty_pct, dtype=float)
    file_level_non_empty_pct = np.array(file_level_non_empty_pct, dtype=float)
    gt_only_non_empty_pct = np.array(gt_only_non_empty_pct, dtype=float)
    llm_only_non_empty_pct = np.array(llm_only_non_empty_pct, dtype=float)
    different_files_non_empty_pct = np.array(
        different_files_non_empty_pct, dtype=float)
    partial_file_overlap_non_empty_pct = np.array(
        partial_file_overlap_non_empty_pct, dtype=float)
    unmatched_non_empty_pct = np.array(unmatched_non_empty_pct, dtype=float)

    # The heatmap keeps the category denominator as all rules in that category.
    # It answers how often each category produced a positive non-empty agreement overall.
    ordered_conditions = [row_key(row) for row in merged_rows]
    categories = sorted({str(row.get("category", "Unknown"))
                        for row in behavior_per_rule_rows}, key=category_order_key)
    has_category_data = any(
        str(row.get("category", "")).strip()
        and str(row.get("category", "")).strip().lower() != "unknown"
        for row in behavior_per_rule_rows
    )
    category_counts = {
        category: max(
            len(category_groups.get((category, condition), []))
            for condition in ordered_conditions
        )
        for category in categories
    }
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
            heatmap[row_index, col_index] = 100.0 * \
                positive_non_empty / len(rows)

    fig_width = max(12.0, len(merged_rows) * 2.0)
    if has_category_data:
        fig, axes = plt.subplots(2, 2, figsize=(
            fig_width, 9), constrained_layout=True)
    else:
        fig, axes = plt.subplots(2, 2, figsize=(
            fig_width, 9), constrained_layout=True)
        axes[1, 1].axis("off")

    ax = axes[0, 0]
    ax.bar(x, operational_pct, label="Operationally valid", color="#3b7a57")
    ax.bar(x, processing_pct, bottom=operational_pct,
           label="Processing errors", color="#d98c3f")
    ax.bar(x, config_pct, bottom=operational_pct +
           processing_pct, label="Config errors", color="#b44444")
    ax.set_title("Rule Execution Status")
    ax.set_ylabel("% of rules")
    ax.set_ylim(0, 100)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.legend(frameon=False, fontsize=8, loc="upper left",
              bbox_to_anchor=(1.01, 1.0))

    ax = axes[0, 1]
    bottom = np.zeros(len(merged_rows))
    for values, label, color in [
        (exact_pct, "Exact", "#4c78a8"),
        (overlap_pct, "Overlap", "#72b7b2"),
        (file_level_pct, "File-level", "#f2cf5b"),
        (both_empty_pct, "Both empty", "#6aaed6"),
        (gt_only_pct, "GT only", "#b279a2"),
        (llm_only_pct, "LLM only", "#ff9da6"),
        (partial_file_overlap_pct, "Partial files", "#59a14f"),
        (different_files_pct, "Different files", "#e17c05"),
        (non_comparable_pct, "Non-comparable", "#9c9c9c"),
    ]:
        ax.bar(x, values, bottom=bottom, label=label, color=color)
        bottom += values
    ax.set_title("Behavioral Comparison Outcomes")
    ax.set_ylabel("% of rules")
    ax.set_ylim(0, 100)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.legend(frameon=False, fontsize=8, loc="upper left",
              bbox_to_anchor=(1.01, 1.0))

    ax = axes[1, 0]
    width = 0.12
    xpos = np.arange(len(merged_rows))
    ax.bar(xpos - 3 * width, exact_non_empty_pct,
           width=width, label="Exact", color="#4c78a8")
    ax.bar(xpos - 2 * width, overlap_non_empty_pct,
           width=width, label="Overlap", color="#72b7b2")
    ax.bar(xpos - width, file_level_non_empty_pct,
           width=width, label="File-level", color="#f2cf5b")
    ax.bar(xpos, partial_file_overlap_non_empty_pct,
           width=width, label="Partial files", color="#59a14f")
    ax.bar(xpos + width, gt_only_non_empty_pct,
           width=width, label="GT only", color="#b279a2")
    ax.bar(xpos + 2 * width, llm_only_non_empty_pct,
           width=width, label="LLM only", color="#ff9da6")
    ax.bar(xpos + 3 * width, different_files_non_empty_pct + unmatched_non_empty_pct,
           width=width, label="Different/no match", color="#e17c05")
    ax.set_title("Behavioral Outcomes Excluding Both-Empty Rules")
    ax.set_ylabel("% of non-empty comparisons")
    ax.set_ylim(0, 100)
    ax.set_xticks(xpos)
    ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.legend(frameon=False, fontsize=8, loc="upper left",
              bbox_to_anchor=(1.01, 1.0))

    if has_category_data:
        ax = axes[1, 1]
        image = ax.imshow(heatmap, cmap="YlGn", vmin=0, vmax=100, aspect="auto")
        ax.set_title("Matched Rule Share by PMD Category")
        ax.set_xticks(np.arange(len(labels)))
        ax.set_xticklabels(labels, rotation=35, ha="right")
        ax.set_yticks(np.arange(len(categories)))
        ax.set_yticklabels([f"{category} (n={category_counts[category]})" for category in categories])
        for row_index in range(len(categories)):
            for col_index in range(len(labels)):
                value = heatmap[row_index, col_index]
                if math.isnan(value):
                    continue
                ax.text(col_index, row_index,
                        f"{value:.1f}", ha="center", va="center", color="black", fontsize=9)
        divider = make_axes_locatable(ax)
        colorbar_axis = divider.append_axes("right", size="3%", pad=0.08)
        fig.colorbar(image, cax=colorbar_axis,
                     label="Rules in category matched (%)")

    fig.suptitle("Execution and Behavioral Agreement Overview", fontsize=14)

    out_figure = Path(args.out_figure)
    ensure_parent(out_figure)
    fig.savefig(out_figure, dpi=220, bbox_inches="tight")
    print(f"Wrote figure to {out_figure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
