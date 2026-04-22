import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path


def read_csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = (len(sorted_values) - 1) * p
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return sorted_values[lower]
    fraction = index - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plot a structural-similarity overview from summary CSV outputs."
    )
    parser.add_argument("--structural-summary", required=True,
                        help="Path to structural_similarity_summary.csv")
    parser.add_argument("--structural-per-rule", required=True,
                        help="Path to structural_similarity_per_rule.csv")
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

    summary_rows = read_csv_rows(Path(args.structural_summary))
    per_rule_rows = read_csv_rows(Path(args.structural_per_rule))
    if not summary_rows:
        raise SystemExit(f"No rows found in {args.structural_summary}")
    if not per_rule_rows:
        raise SystemExit(f"No rows found in {args.structural_per_rule}")

    label = summary_rows[0].get("label", "Structural Similarity")

    # If the summary only contains one overall row, derive the per-condition groups from the per-rule CSV.
    grouped = defaultdict(list)
    for row in per_rule_rows:
        if not str(row.get("structurallyComparable", "")).lower() == "true":
            continue
        prompt_style = str(row.get("promptStyle", "all"))
        temperature = str(row.get("temperature", "all"))
        run_count = str(row.get("runCount", "all"))
        grouped[(prompt_style, temperature, run_count)].append(row)

    if not grouped:
        # Fall back to one combined group when the per-rule CSV has no prompt/temperature columns.
        comparable_rows = [row for row in per_rule_rows if str(
            row.get("structurallyComparable", "")).lower() == "true"]
        grouped[("all", "all", "all")] = comparable_rows

    ordered_keys = sorted(grouped.keys(), key=lambda item: (item[0], item[1]))
    labels = [
        f"{key[0]}\nT={key[1]}\nrun {key[2]}"
        if key != ("all", "all", "all")
        else "all rules"
        for key in ordered_keys
    ]

    overall_box_data = []
    comparable_pct = []
    mean_node = []
    mean_edge = []
    mean_scalar = []
    median_scores = []

    for key in ordered_keys:
        rows = grouped[key]
        overall_scores = sorted(
            float(row.get("overallStructuralSimilarity", 0.0)) for row in rows)
        node_scores = [float(row.get("nodeLabelJaccard", 0.0)) for row in rows]
        edge_scores = [float(row.get("edgeLabelJaccard", 0.0)) for row in rows]
        scalar_scores = [
            float(row.get("scalarFeatureSimilarity", 0.0)) for row in rows]

        all_group_rows = [
            row
            for row in per_rule_rows
            if str(row.get("promptStyle", "all")) == key[0]
            and str(row.get("temperature", "all")) == str(key[1])
            and str(row.get("runCount", "all")) == str(key[2])
        ]
        group_total = len(all_group_rows)
        group_comparable = len(rows)
        group_comparable_pct = 100.0 * group_comparable / \
            group_total if group_total else 0.0

        overall_box_data.append(overall_scores if overall_scores else [0.0])
        comparable_pct.append(group_comparable_pct)
        mean_node.append(sum(node_scores) / len(node_scores)
                         if node_scores else 0.0)
        mean_edge.append(sum(edge_scores) / len(edge_scores)
                         if edge_scores else 0.0)
        mean_scalar.append(sum(scalar_scores) /
                           len(scalar_scores) if scalar_scores else 0.0)
        median_scores.append(percentile(overall_scores, 0.5)
                             if overall_scores else 0.0)

    prompt_style_runs = sorted({(key[0], key[2]) for key in ordered_keys})
    temperatures = sorted({str(key[1]) for key in ordered_keys})
    heatmap = np.full((len(prompt_style_runs), len(temperatures)), np.nan)
    for key, median in zip(ordered_keys, median_scores):
        heatmap[prompt_style_runs.index(
            (key[0], key[2])), temperatures.index(str(key[1]))] = median

    fig_width = max(10.0, len(labels) * 1.5)
    fig, axes = plt.subplots(2, 2, figsize=(
        fig_width, 9), constrained_layout=True)

    ax = axes[0, 0]
    bp = ax.boxplot(
        overall_box_data,
        patch_artist=True,
        widths=0.6,
        showfliers=False,
        whis=(0, 100),
    )
    for patch in bp["boxes"]:
        patch.set_facecolor("#8fb9d9")
        patch.set_alpha(0.9)
    ax.set_title("Overall Structural Similarity Distribution")
    ax.set_ylabel("Overall structural similarity")
    ax.set_ylim(0, 1)
    ax.set_xticks(range(1, len(labels) + 1))
    ax.set_xticklabels(labels, rotation=35, ha="right")

    ax = axes[0, 1]
    ax.bar(np.arange(len(labels)), comparable_pct, color="#4c9f70")
    ax.set_title("Pairs Were Both XPath ASTs Parsed")
    ax.set_ylabel("Percent")
    ax.set_ylim(0, 100)
    ax.set_xticks(np.arange(len(labels)))
    ax.set_xticklabels(labels, rotation=35, ha="right")

    ax = axes[1, 0]
    width = 0.24
    xpos = np.arange(len(labels))
    ax.bar(xpos - width, mean_node, width=width, label="Node", color="#4c78a8")
    ax.bar(xpos, mean_edge, width=width, label="Edge", color="#f58518")
    ax.bar(xpos + width, mean_scalar, width=width,
           label="Scalar", color="#54a24b")
    ax.set_title("Mean Structural Components")
    ax.set_ylabel("Similarity")
    ax.set_ylim(0, 1)
    ax.set_xticks(xpos)
    ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.legend(frameon=False, fontsize=9)

    ax = axes[1, 1]
    image = ax.imshow(heatmap, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    ax.set_title("Median Structural Similarity Heatmap")
    ax.set_xticks(np.arange(len(temperatures)))
    ax.set_xticklabels([f"T={value}" for value in temperatures])
    ax.set_yticks(np.arange(len(prompt_style_runs)))
    ax.set_yticklabels([f"{prompt}\nrun {run}" for prompt, run in prompt_style_runs])
    for row_index in range(len(prompt_style_runs)):
        for col_index in range(len(temperatures)):
            value = heatmap[row_index, col_index]
            if math.isnan(value):
                continue
            ax.text(col_index, row_index,
                    f"{value:.2f}", ha="center", va="center", color="black", fontsize=9)
    fig.colorbar(image, ax=ax, fraction=0.046,
                 pad=0.04, label="Median similarity")

    fig.suptitle(f"Structural Similarity Overview - {label}", fontsize=14)

    out_figure = Path(args.out_figure)
    ensure_parent(out_figure)
    fig.savefig(out_figure, dpi=220, bbox_inches="tight")
    print(f"Wrote figure to {out_figure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
