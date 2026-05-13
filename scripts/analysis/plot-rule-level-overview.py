import argparse
import csv
from collections import defaultdict
from pathlib import Path

"""Plot rule-level difficulty from behavioral agreement per-rule rows.

Usage example:
  python scripts/analysis/plot-rule-level-overview.py \
    --behavior-per-rule out/analysis-summary/experiment/behavioral_agreement_per_rule.csv \
    --out-figure out/analysis-summary/experiment/rule_level_overview.png
"""


MATCH_TYPES = {
    "exact",
    "overlap",
    "file-level",
}

SIMILAR_TYPES = {
    "llm-superset",
    "gt-superset",
    "partial-file-overlap",
}


def read_csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def short_rule_name(rule: str, max_len: int = 34) -> str:
    if len(rule) <= max_len:
        return rule
    return rule[: max_len - 1] + "…"


def as_int(row: dict, name: str) -> int:
    try:
        return int(float(row.get(name) or 0))
    except ValueError:
        return 0


def rule_key(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("ruleKey", "")),
        str(row.get("catalogId", "")),
        str(row.get("category", "")),
    )


def pct(part: int, whole: int) -> float:
    return 100.0 * part / whole if whole else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Plot easiest and hardest rules from behavioral per-rule results."
    )
    parser.add_argument("--behavior-per-rule", required=True)
    parser.add_argument("--out-figure", required=True)
    parser.add_argument("--top-n", type=int, default=10)
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

    rows = read_csv_rows(Path(args.behavior_per_rule))
    if not rows:
        raise SystemExit(f"No rows found in {args.behavior_per_rule}")

    groups = defaultdict(list)
    for row in rows:
        groups[rule_key(row)].append(row)

    rule_stats = []
    for (rule_number, catalog_id, category), group_rows in groups.items():
        total = len(group_rows)
        both_empty = sum(1 for row in group_rows if row.get(
            "matchType") == "both-empty")
        noncomparable = sum(1 for row in group_rows if row.get(
            "matchType") == "non-comparable")
        denominator = total - both_empty - noncomparable
        match = sum(1 for row in group_rows if row.get("matchType") in MATCH_TYPES)
        similar = sum(1 for row in group_rows if row.get("matchType") in SIMILAR_TYPES)
        positive = match + similar
        gt_only = sum(1 for row in group_rows if row.get(
            "matchType") == "gt-only")
        llm_only = sum(1 for row in group_rows if row.get(
            "matchType") == "llm-only")
        gt_nonempty = sum(1 for row in group_rows if as_int(
            row, "groundTruthFindingCount") > 0)
        llm_nonempty = sum(1 for row in group_rows if as_int(
            row, "llmFindingCount") > 0)
        rule_stats.append(
            {
                "ruleKey": rule_number,
                "catalogId": catalog_id,
                "category": category,
                "total": total,
                "denominator": denominator,
                "agreementPct": pct(positive, denominator),
                "matchPct": pct(match, denominator),
                "similarPct": pct(similar, denominator),
                "gtOnlyPct": pct(gt_only, total),
                "llmOnlyPct": pct(llm_only, total),
                "nonComparablePct": pct(noncomparable, total),
                "gtNonEmptyPct": pct(gt_nonempty, total),
                "llmNonEmptyPct": pct(llm_nonempty, total),
            }
        )

    comparable_stats = [stat for stat in rule_stats if stat["denominator"] > 0]
    if not comparable_stats:
        raise SystemExit("No rule-level non-empty comparable cases found.")

    top_n = max(1, args.top_n)
    easiest = sorted(
        comparable_stats,
        key=lambda stat: (stat["agreementPct"], -
                          stat["nonComparablePct"], stat["catalogId"]),
        reverse=True,
    )[:top_n]
    most_gt_only = sorted(
        rule_stats, key=lambda stat: stat["gtOnlyPct"], reverse=True)[:top_n]
    most_noncomparable = sorted(
        rule_stats, key=lambda stat: stat["nonComparablePct"], reverse=True)[:top_n]

    fig_height = max(10.5, top_n * 0.45 + 5.0)
    fig, axes = plt.subplots(2, 2, figsize=(
        14, fig_height), constrained_layout=True)

    def barh_rules(ax, stats: list[dict], value_name: str, title: str, color: str, xlabel: str) -> None:
        labels = [short_rule_name(
            stat["catalogId"] or stat["ruleKey"]) for stat in stats]
        values = [stat[value_name] for stat in stats]
        y = np.arange(len(stats))
        ax.barh(y, values, color=color)
        ax.set_title(title)
        ax.set_xlabel(xlabel)
        ax.set_xlim(0, 100)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=8)
        ax.invert_yaxis()
        for y_pos, value in zip(y, values):
            ax.text(value + 1, y_pos, f"{value:.1f}", va="center", fontsize=8)

    def stacked_agreement_rules(ax, stats: list[dict], title: str) -> None:
        labels = [short_rule_name(
            stat["catalogId"] or stat["ruleKey"]) for stat in stats]
        match_values = [stat["matchPct"] for stat in stats]
        similar_values = [stat["similarPct"] for stat in stats]
        totals = [stat["agreementPct"] for stat in stats]
        y = np.arange(len(stats))
        ax.barh(y, match_values, label="Match", color="#4c78a8")
        ax.barh(y, similar_values, left=match_values,
                label="Similar", color="#72b7b2")
        ax.set_title(title)
        ax.set_xlabel("match + similar % of non-empty comparable cases")
        ax.set_xlim(0, 100)
        ax.set_yticks(y)
        ax.set_yticklabels(labels, fontsize=8)
        ax.invert_yaxis()
        for y_pos, value in zip(y, totals):
            ax.text(value + 1, y_pos, f"{value:.1f}",
                    va="center", fontsize=8)
        ax.legend(frameon=False, fontsize=8)

    stacked_agreement_rules(
        axes[0, 0],
        easiest,
        "Easiest Rules: Highest Match + Similarity",
    )
    axes[0, 1].axis("off")
    barh_rules(
        axes[1, 0],
        most_gt_only,
        "gtOnlyPct",
        "Rules Most Often Missed by LLMs",
        "#e07a5f",
        "GT-only % of all evaluations",
    )
    barh_rules(
        axes[1, 1],
        most_noncomparable,
        "nonComparablePct",
        "Rules Most Often Non-Comparable",
        "#8c8c8c",
        "non-comparable % of all evaluations",
    )

    fig.suptitle("Rule-Level Experiment Overview", fontsize=14)
    out_figure = Path(args.out_figure)
    ensure_parent(out_figure)
    fig.savefig(out_figure, dpi=220, bbox_inches="tight")
    print(f"Wrote figure to {out_figure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
