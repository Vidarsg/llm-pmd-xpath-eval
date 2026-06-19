import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path

"""Create an overview figure for XPath structural-similarity results.

The script visualizes the CSV tables emitted by summarize-experiment-vs-ground-
truth.py and focuses on comparable pairs where both XPath expressions parsed.

Usage example:
  python scripts/analysis/plot-structural-similarity-overview.py \
    --structural-summary out/analysis-summary/structural_similarity_summary.csv \
    --structural-per-rule out/analysis-summary/structural_similarity_per_rule.csv \
    --out-figure out/analysis-summary/structural_similarity_overview.png
"""

MODEL_COLORS = {
    "Gemma-4-31B": "#59a14f",
    "Mistral-Large": "#f28e2b",
    "Qwen3.5-122B": "#e15759",
    "gpt-oss-120b": "#4e79a7",
}

MODEL_ORDER = [
    "Gemma-4-31B",
    "Mistral-Large",
    "Qwen3.5-122B",
    "gpt-oss-120b",
]


def read_csv_rows(path: Path) -> list[dict]:
    """Read a CSV summary file as dictionaries."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def ensure_parent(path: Path) -> None:
    """Create the output directory before saving the plot."""
    path.parent.mkdir(parents=True, exist_ok=True)


def save_panel(fig, ax, path: Path) -> None:
    ensure_parent(path)
    axes_visibility = [(figure_ax, figure_ax.get_visible())
                       for figure_ax in fig.axes]
    for figure_ax, _visible in axes_visibility:
        figure_ax.set_visible(figure_ax is ax)

    suptitle = getattr(fig, "_suptitle", None)
    suptitle_visible = suptitle.get_visible() if suptitle is not None else None
    if suptitle is not None:
        suptitle.set_visible(False)

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    bbox = ax.get_tightbbox(renderer).expanded(1.03, 1.06)
    bbox_inches = bbox.transformed(fig.dpi_scale_trans.inverted())
    fig.savefig(path, dpi=220, bbox_inches=bbox_inches)

    for figure_ax, visible in axes_visibility:
        figure_ax.set_visible(visible)
    if suptitle is not None and suptitle_visible is not None:
        suptitle.set_visible(suptitle_visible)


def percentile(sorted_values: list[float], p: float) -> float:
    """Compute a percentile from an already sorted list using linear interpolation."""
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


def short_model_name(model: str) -> str:
    """Shorten provider-heavy model identifiers while keeping them recognizable."""
    name = model.strip().replace("\\", "/")
    aliases = {
        "openai/openai/gpt-oss-120b": "gpt-oss-120b",
        "openai/gpt-oss-120b": "gpt-oss-120b",
        "openai/Qwen/Qwen3.5-122B-A10B-FP8": "Qwen3.5-122B",
        "Qwen/Qwen3.5-122B-A10B-FP8": "Qwen3.5-122B",
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


def model_color(model: str) -> str:
    return MODEL_COLORS.get(short_model_name(model), "#4c9f70")


def model_sort_key(model: str) -> tuple[int, str]:
    short_name = short_model_name(model)
    try:
        return (MODEL_ORDER.index(short_name), short_name)
    except ValueError:
        return (len(MODEL_ORDER), short_name)


def condition_label(
    key: tuple[str, str, str, str],
    varying_fields: set[str],
    *,
    multiline: bool = True,
) -> str:
    """Build compact condition labels by only showing fields that vary."""
    model, prompt_style, temperature, run_count = key
    parts = []
    if "model" in varying_fields or not varying_fields:
        parts.append(short_model_name(model))
    if "promptStyle" in varying_fields:
        parts.append(prompt_style)
    if "runCount" in varying_fields:
        parts.append(f"run {run_count}")
    separator = "\n" if multiline else " / "
    return separator.join(parts) if parts else short_model_name(model)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plot a structural-similarity overview from summary CSV outputs."
    )
    parser.add_argument("--structural-summary", required=True,
                        help="Path to structural_similarity_summary.csv")
    parser.add_argument("--structural-per-rule", required=True,
                        help="Path to structural_similarity_per_rule.csv")
    parser.add_argument("--out-figure", required=True, help="Output PNG path")
    parser.add_argument("--panel-parseable")
    parser.add_argument("--panel-score-distribution")
    parser.add_argument("--panel-components")
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

    # Derive per-condition groups from the per-rule CSV. Repeated runs are
    # pooled so each model/prompt/temperature condition appears once.
    all_grouped = defaultdict(list)
    grouped = defaultdict(list)
    for row in per_rule_rows:
        model = str(row.get("model", "all"))
        prompt_style = str(row.get("promptStyle", "all"))
        temperature = str(row.get("temperature", "all"))
        key = (model, prompt_style, temperature)
        all_grouped[key].append(row)
        if not str(row.get("structurallyComparable", "")).lower() == "true":
            continue
        grouped[key].append(row)

    if not all_grouped:
        # Fall back to one combined group when the per-rule CSV has no prompt/temperature columns.
        comparable_rows = [row for row in per_rule_rows if str(
            row.get("structurallyComparable", "")).lower() == "true"]
        all_grouped[("all", "all", "all")] = per_rule_rows
        grouped[("all", "all", "all")] = comparable_rows

    ordered_keys = sorted(all_grouped.keys(), key=lambda item: (
        model_sort_key(item[0]), item[1], item[2]))
    unique_models = {key[0] for key in ordered_keys}
    unique_prompts = {key[1] for key in ordered_keys}
    unique_temperatures = {str(key[2]) for key in ordered_keys}
    varying_fields = set()
    if len(unique_models) > 1:
        varying_fields.add("model")
    if len(unique_prompts) > 1:
        varying_fields.add("promptStyle")
    # Temperature is intentionally omitted from labels; current experiments keep
    # it fixed, and showing it makes the figures harder to read.

    labels = [
        condition_label((key[0], key[1], key[2], ""), varying_fields)
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

    # Each condition gets a boxplot distribution plus mean component scores, so
    # spread and metric composition are visible in the same figure.
    for key in ordered_keys:
        rows = grouped.get(key, [])
        overall_scores = sorted(
            float(row.get("overallStructuralSimilarity", 0.0)) for row in rows)
        node_scores = [float(row.get("nodeLabelJaccard", 0.0)) for row in rows]
        edge_scores = [float(row.get("edgeLabelJaccard", 0.0)) for row in rows]
        scalar_scores = [
            float(row.get("scalarFeatureSimilarity", 0.0)) for row in rows]

        all_group_rows = all_grouped.get(key, [])
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

    temperatures = sorted({str(key[2]) for key in ordered_keys})
    model_prompt_rows = sorted(
        {(key[0], key[1]) for key in ordered_keys},
        key=lambda item: (model_sort_key(item[0]), item[1]),
    )
    heatmap = np.full((len(model_prompt_rows), len(temperatures)), np.nan)
    for key, median in zip(ordered_keys, median_scores):
        heatmap[model_prompt_rows.index(
            (key[0], key[1])), temperatures.index(str(key[2]))] = median

    fig_width = max(11.0, len(labels) * 1.45)
    fig_height = max(8.5, len(model_prompt_rows) * 0.55 + 5.5)
    fig, axes = plt.subplots(2, 2, figsize=(
        fig_width, fig_height), constrained_layout=True)

    ax = axes[0, 0]
    ax.bar(
        np.arange(len(labels)),
        comparable_pct,
        color=[model_color(key[0]) for key in ordered_keys],
    )
    ax.set_title("Generated XPath Rules That Could Be Parsed")
    ax.set_ylabel("Percent")
    ax.set_ylim(0, 100)
    ax.set_xticks(np.arange(len(labels)))
    ax.set_xticklabels(labels, rotation=30, ha="right")

    ax = axes[0, 1]
    bp = ax.boxplot(
        overall_box_data,
        patch_artist=True,
        widths=0.45,
        showfliers=False,
        whis=(0, 100),
    )
    for patch in bp["boxes"]:
        patch.set_facecolor("#8fb9d9")
        patch.set_alpha(0.9)
    ax.set_title("Distribution of Parsed AST Similarity Scores")
    ax.set_ylabel("Overall structural similarity")
    ax.set_ylim(0, 1)
    ax.set_xticks(range(1, len(labels) + 1))
    ax.set_xticklabels(labels, rotation=30, ha="right")

    ax = axes[1, 0]
    width = 0.18
    xpos = np.arange(len(labels))
    ax.bar(xpos - width, mean_node, width=width, label="Node", color="#4c78a8")
    ax.bar(xpos, mean_edge, width=width, label="Edge", color="#f58518")
    ax.bar(xpos + width, mean_scalar, width=width,
           label="Scalar", color="#54a24b")
    ax.set_title("Average Parsed AST Similarity Components")
    ax.set_ylabel("Similarity")
    ax.set_ylim(0, 1)
    ax.set_xticks(xpos)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.legend(frameon=False, fontsize=8, loc="upper left",
              bbox_to_anchor=(1.01, 1.0))

    ax = axes[1, 1]
    image = ax.imshow(heatmap, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    ax.set_title("Median Parsed AST Similarity by Model")
    ax.set_xticks(np.arange(len(temperatures)))
    ax.set_xticklabels(["" for _value in temperatures])
    ax.set_yticks(np.arange(len(model_prompt_rows)))
    heatmap_fields = set()
    if len({model for model, _ in model_prompt_rows}) > 1:
        heatmap_fields.add("model")
    if len({prompt for _, prompt in model_prompt_rows}) > 1:
        heatmap_fields.add("promptStyle")
    ax.set_yticklabels([
        condition_label((model, prompt, "", ""), heatmap_fields)
        for model, prompt in model_prompt_rows
    ])
    for row_index in range(len(model_prompt_rows)):
        for col_index in range(len(temperatures)):
            value = heatmap[row_index, col_index]
            if math.isnan(value):
                continue
            ax.text(col_index, row_index,
                    f"{value:.2f}", ha="center", va="center", color="black", fontsize=9)
    fig.colorbar(image, ax=ax, fraction=0.046,
                 pad=0.04, label="Median AST similarity")

    fig.suptitle(f"XPath AST Similarity Overview - {label}", fontsize=14)

    out_figure = Path(args.out_figure)
    ensure_parent(out_figure)
    fig.savefig(out_figure, dpi=220, bbox_inches="tight")
    if args.panel_parseable:
        save_panel(fig, axes[0, 0], Path(args.panel_parseable))
    if args.panel_score_distribution:
        save_panel(fig, axes[0, 1], Path(args.panel_score_distribution))
    if args.panel_components:
        save_panel(fig, axes[1, 0], Path(args.panel_components))
    print(f"Wrote figure to {out_figure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
