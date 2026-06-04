import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

"""Summarize generated XPath experiments against reference PMD behavior.

The script combines validation outputs, PMD JSON reports, catalog metadata, and
optional structural-similarity rows into CSV/Markdown tables suitable for
analysis and thesis reporting.

Usage example:
  python scripts/analysis/summarize-experiment-vs-reference.py \
    --aggregated-results out/experiments/experiment/aggregated-results.jsonl \
    --experiment-root out/experiments/experiment \
    --reference-results out/catalog-runs/catalog-run/results.jsonl \
    --catalog-path config/pmd-catalog.json \
    --out-dir out/analysis-summary

For multi-target experiments, use --reference-root instead:
  python scripts/analysis/summarize-experiment-vs-reference.py \
    --aggregated-results out/experiments/experiment/aggregated-results.jsonl \
    --experiment-root out/experiments/experiment \
    --reference-root out/catalog-runs \
    --catalog-path config/pmd-catalog.json \
    --out-dir out/analysis-summary

The --reference-root option accepts both official PMD catalog runs
(catalog-run_<target>/results.jsonl) and custom ruleset runs
(custom-run_<target>/results.jsonl).
"""


def normalize_path(path: str) -> str:
    """Normalize paths so reports from different runs can be compared reliably."""
    return str(Path(path)).replace("/", "\\").lower()


def read_json_records(path: Path) -> list[dict]:
    """Read either compact JSONL or concatenated pretty-printed JSON objects."""
    text = path.read_text(encoding="utf-8-sig")
    if not text.strip():
        return []

    rows = []
    decoder = json.JSONDecoder()
    index = 0
    length = len(text)

    while index < length:
        while index < length and text[index].isspace():
            index += 1
        if index >= length:
            break
        obj, next_index = decoder.raw_decode(text, index)
        rows.append(obj)
        index = next_index

    return rows


def load_catalog_rule_order(catalog_path: Path) -> dict[int, str]:
    """Map numeric rule positions from the LLM input set to PMD catalog rule ids."""
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    mapping = {}
    for index, (rule_id, _) in enumerate((data.get("rules") or {}).items(), start=1):
        mapping[index] = rule_id
    return mapping


def load_catalog_rule_metadata(catalog_path: Path) -> dict[str, dict]:
    """Load PMD catalog metadata keyed by rule id."""
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    return dict(data.get("rules") or {})


def spec_key(obj: dict) -> tuple[str, str, str, str, str, str]:
    """Build a stable key that identifies one concrete experiment run."""
    return (
        str(obj["runName"]),
        normalize_path(str(obj["target"])),
        str(obj["model"]),
        str(obj["promptStyle"]),
        str(obj["temperature"]),
        str(obj["runCount"]),
    )


def load_run_report_dirs(experiment_root: Path) -> dict[tuple[str, str, str, str, str, str], Path]:
    """Index every experiment run to the directory containing its per-rule PMD reports."""
    report_dirs = {}
    for spec_path in experiment_root.rglob("run-spec.json"):
        spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
        report_dirs[spec_key(spec)] = spec_path.parent / \
            "evaluation" / "reports"
    return report_dirs


def load_reference_index(reference_results_path: Path) -> tuple[dict[str, dict], Path]:
    """Load reference rule metadata and resolve the sibling reports directory."""
    rows = read_json_records(reference_results_path)
    reports_dir = reference_results_path.parent / "reports"
    return {str(row["ruleKey"]): row for row in rows}, reports_dir


def normalize_target_key(target_name: str) -> str:
    """Normalize target names used in experiment paths and reference folders."""
    return target_name.strip().rstrip("_").lower()


def load_reference_by_target(reference_root: Path) -> dict[str, tuple[dict[str, dict], Path]]:
    """Load per-target reference results keyed by target directory name."""
    mapping = {}
    patterns = ("catalog-run_*/results.jsonl", "custom-run_*/results.jsonl")
    for pattern in patterns:
        for results_path in sorted(reference_root.glob(pattern)):
            target_name = results_path.parent.name
            for prefix in ("catalog-run_", "custom-run_"):
                target_name = target_name.removeprefix(prefix)
            reference = load_reference_index(results_path)
            mapping[normalize_target_key(target_name)] = reference
            mapping[target_name.lower()] = reference
    return mapping


def get_reference_for_target(
    target_name: str,
    single_reference: tuple[dict[str, dict], Path] | None,
    reference_by_target: dict[str, tuple[dict[str, dict], Path]],
) -> tuple[dict[str, dict], Path] | None:
    """Return the correct reference index/report directory for one target."""
    if single_reference is not None:
        return single_reference
    return reference_by_target.get(normalize_target_key(target_name))


def resolve_reference_report_path(
    reference_row: dict,
    reference_reports_dir: Path,
    mapped_rule_id: str,
    generated_rule_key: str,
) -> Path:
    """Resolve reference PMD report paths for official and custom rulesets."""
    candidates = [
        reference_reports_dir / f"{mapped_rule_id}.json",
        reference_reports_dir / f"{reference_row.get('ruleKey')}.json",
        reference_reports_dir / f"{generated_rule_key}.json",
    ]
    report_path = reference_row.get("reportPath")
    if report_path:
        candidates.append(Path(str(report_path)))

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def parse_report_violations(report_path: Path, cache: dict[Path, dict]) -> dict:
    """Read one PMD JSON report and extract violations plus script-detected error flags."""
    if report_path in cache:
        return cache[report_path]

    # Missing reports mean the rule could not be compared behaviorally. Marking
    # both error types keeps that case out of positive agreement categories.
    if not report_path.exists():
        result = {
            "files": {},
            "hadConfigErrors": True,
            "hadProcessingErrors": True,
            "exists": False,
            "parseError": "report file does not exist",
        }
        cache[report_path] = result
        return result

    try:
        data = json.loads(report_path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError as exc:
        result = {
            "files": {},
            "hadConfigErrors": False,
            "hadProcessingErrors": True,
            "exists": True,
            "parseError": f"report is not valid UTF-8: {exc}",
        }
        cache[report_path] = result
        return result
    except json.JSONDecodeError as exc:
        result = {
            "files": {},
            "hadConfigErrors": False,
            "hadProcessingErrors": True,
            "exists": True,
            "parseError": f"invalid JSON report: {exc}",
        }
        cache[report_path] = result
        return result

    files = {}
    for file_entry in data.get("files", []):
        filename = normalize_path(file_entry["filename"])
        spans = []
        for violation in file_entry.get("violations", []):
            spans.append(
                (
                    int(violation["beginline"]),
                    int(violation["begincolumn"]),
                    int(violation["endline"]),
                    int(violation["endcolumn"]),
                )
            )
        files[filename] = sorted(spans)

    # The validation wrapper adds scriptDetected* fields so syntax/configuration
    # failures can be separated from ordinary "rule matched no files" outcomes.
    result = {
        "files": files,
        "hadConfigErrors": bool((data.get("scriptDetectedConfigurationErrors") or {}).get("hadConfigErrors", False)),
        "hadProcessingErrors": bool((data.get("scriptDetectedProcessingErrors") or {}).get("hadProcessingErrors", False)),
        "exists": True,
        "parseError": "",
    }
    cache[report_path] = result
    return result


def span_overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    """Check whether two PMD source spans overlap at all."""
    a_start = (a[0], a[1])
    a_end = (a[2], a[3])
    b_start = (b[0], b[1])
    b_end = (b[2], b[3])
    return not (a_end < b_start or b_end < a_start)


def all_spans_overlap(left: list[tuple[int, int, int, int]], right: list[tuple[int, int, int, int]]) -> bool:
    """Require every span on each side to overlap at least one span on the other side."""
    if not left and not right:
        return True
    if not left or not right:
        return False
    return all(any(span_overlaps(a, b) for b in right) for a in left) and all(
        any(span_overlaps(b, a) for a in left) for b in right
    )


def classify_behavior(llm_report: dict, reference_report: dict) -> str:
    """Classify behavioral correspondence between one LLM rule report and one reference report."""
    # Behavioral comparison only makes sense when both PMD runs completed well
    # enough to produce trustworthy violation spans.
    if (
        llm_report["hadConfigErrors"]
        or llm_report["hadProcessingErrors"]
        or reference_report["hadConfigErrors"]
        or reference_report["hadProcessingErrors"]
        or not llm_report["exists"]
        or not reference_report["exists"]
    ):
        return "non-comparable"

    llm_files = llm_report["files"]
    reference_files = reference_report["files"]

    if not llm_files and not reference_files:
        return "both-empty"
    if not llm_files:
        return "reference-only"
    if not reference_files:
        return "llm-only"

    # Exact is strict span equality; overlap and file-level progressively relax
    # the comparison while still requiring the same affected files.
    if llm_files == reference_files:
        return "exact"

    if set(llm_files.keys()) == set(reference_files.keys()):
        if all(all_spans_overlap(llm_files[name], reference_files[name]) for name in llm_files):
            return "overlap"
        return "file-level"

    llm_file_set = set(llm_files.keys())
    reference_file_set = set(reference_files.keys())
    common_files = llm_file_set & reference_file_set
    if not common_files:
        return "different-files"
    if reference_file_set < llm_file_set:
        return "llm-superset"
    if llm_file_set < reference_file_set:
        return "reference-superset"
    return "partial-file-overlap"


def report_finding_count(report: dict) -> int:
    """Count violation spans across all files in a parsed PMD JSON report."""
    return sum(len(spans) for spans in report.get("files", {}).values())


def row_group_key(row: dict) -> tuple[str, str, str, str, str]:
    """Group rows into one summary bucket for the thesis tables."""
    return (
        Path(str(row["target"])).name,
        str(row["model"]),
        str(row["promptStyle"]),
        str(row["temperature"]),
        str(row["runCount"]),
    )


def percent(count: int, total: int) -> str:
    """Format a percentage for summary-table output."""
    if total == 0:
        return "0.0"
    return f"{(100.0 * count / total):.1f}"


def mean_or_zero(values: list[float]) -> str:
    """Format the mean of a metric list, defaulting to zero when empty."""
    if not values:
        return "0.0000"
    return f"{statistics.fmean(values):.4f}"


def median_or_zero(values: list[float]) -> str:
    """Format the median of a metric list, defaulting to zero when empty."""
    if not values:
        return "0.0000"
    return f"{statistics.median(values):.4f}"


def min_or_zero(values: list[float]) -> str:
    """Format the minimum of a metric list, defaulting to zero when empty."""
    if not values:
        return "0.0000"
    return f"{min(values):.4f}"


def max_or_zero(values: list[float]) -> str:
    """Format the maximum of a metric list, defaulting to zero when empty."""
    if not values:
        return "0.0000"
    return f"{max(values):.4f}"


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    """Write a list of dictionaries as a CSV table."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown_table(path: Path, title: str, rows: list[dict], fieldnames: list[str]) -> None:
    """Write a simple markdown table version of the same summary data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(f"{title}\n\n")
        f.write("| " + " | ".join(fieldnames) + " |\n")
        f.write("| " + " | ".join("---" for _ in fieldnames) + " |\n")
        for row in rows:
            f.write("| " + " | ".join(str(row.get(name, ""))
                    for name in fieldnames) + " |\n")


def normalize_resolved_path(path: str | Path) -> str:
    """Resolve a path for robust comparisons between run-specs and artifacts."""
    return str(Path(path).resolve()).lower()


def structural_generated_jsonl_path(structural_results_path: Path) -> Path | None:
    """Infer the generated.jsonl that produced one structural result file."""
    structural_dir = structural_results_path.parent
    if structural_dir.name != "structural":
        return None

    run_count_dir = structural_dir.parent
    candidates = sorted(run_count_dir.glob("*/generated.jsonl"))
    if not candidates:
        # Compatibility with structural outputs created before shared
        # generation artifacts were placed under runCount_<N>/structural.
        candidates = sorted(run_count_dir.rglob("generated.jsonl"))
    if len(candidates) == 1:
        return candidates[0]
    return None


def load_run_specs_by_generated_jsonl(experiment_root: Path) -> dict[str, dict]:
    """Index run-spec metadata by the generatedJsonl path recorded in each run."""
    specs = {}
    for spec_path in experiment_root.rglob("run-spec.json"):
        spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
        generated_jsonl = str(spec.get("generatedJsonl", "")).strip()
        if generated_jsonl:
            specs[normalize_resolved_path(generated_jsonl)] = spec
    return specs


def find_associated_run_spec(structural_results_path: Path, experiment_root: Path) -> dict | None:
    """Best-effort lookup of the run-spec matching one structural-similarity result file."""
    current = structural_results_path.parent
    experiment_root = experiment_root.resolve()

    while True:
        direct_candidate = current / "run-spec.json"
        if direct_candidate.exists():
            return json.loads(direct_candidate.read_text(encoding="utf-8-sig"))

        descendant_candidates = list(current.glob("runCount_*/run-spec.json"))
        if len(descendant_candidates) == 1:
            return json.loads(descendant_candidates[0].read_text(encoding="utf-8-sig"))
        if len(descendant_candidates) > 1:
            raise ValueError(
                f"Multiple run-spec.json files found under {current}; cannot uniquely associate {structural_results_path}"
            )

        if current == experiment_root or current.parent == current:
            break
        current = current.parent

    return None


def infer_shared_generation_spec(structural_results_path: Path, experiment_root: Path) -> dict | None:
    """Infer run metadata for target-independent _generation structural outputs."""
    parts = structural_results_path.resolve().parts
    if "_generation" not in parts:
        return None

    generation_index = parts.index("_generation")
    if len(parts) <= generation_index + 4:
        return None

    model = parts[generation_index + 2]
    temperature_dir = parts[generation_index + 3]
    run_count_dir = parts[generation_index + 4]
    if not temperature_dir.startswith("temp_") or not run_count_dir.startswith("runCount_"):
        return None

    prompt_style = ""
    generated_jsonl = structural_generated_jsonl_path(structural_results_path)
    if generated_jsonl is not None:
        prompt_style = generated_jsonl.parent.name

    run_name = ""
    try:
        relative_parts = structural_results_path.resolve().relative_to(
            experiment_root.resolve()).parts
        if relative_parts:
            run_name = relative_parts[0]
    except ValueError:
        pass

    return {
        "target": "",
        "model": model.replace("_", "/"),
        "promptStyle": prompt_style,
        "temperature": temperature_dir.removeprefix("temp_"),
        "runCount": run_count_dir.removeprefix("runCount_"),
        "runName": run_name,
    }


def load_structural_rows(
    structural_results_path: Path | None,
    experiment_root: Path,
) -> tuple[list[dict], str]:
    """Load structural results either from one file or by scanning the experiment tree."""
    if structural_results_path is not None:
        rows = read_json_records(structural_results_path)
        return rows, structural_results_path.stem

    structural_files = sorted(
        experiment_root.rglob("structural-similarity.jsonl"))
    specs_by_generated_jsonl = load_run_specs_by_generated_jsonl(experiment_root)
    rows = []
    for structural_file in structural_files:
        spec = find_associated_run_spec(structural_file, experiment_root)
        if spec is None:
            generated_jsonl = structural_generated_jsonl_path(structural_file)
            if generated_jsonl is not None:
                spec = specs_by_generated_jsonl.get(normalize_resolved_path(generated_jsonl))
        if spec is None:
            spec = infer_shared_generation_spec(structural_file, experiment_root)
        for row in read_json_records(structural_file):
            enriched = dict(row)
            # Structural result rows produced in batch mode do not always carry
            # run metadata, so recover it from the nearest run-spec.json.
            if spec is not None:
                enriched["target"] = Path(str(spec.get("target", ""))).name
                enriched["model"] = str(spec.get("model", ""))
                enriched["promptStyle"] = str(spec.get("promptStyle", ""))
                enriched["temperature"] = str(spec.get("temperature", ""))
                enriched["runCount"] = str(spec.get("runCount", ""))
                enriched["runName"] = str(spec.get("runName", ""))
            rows.append(enriched)
    return rows, experiment_root.name


def write_structural_similarity_summaries(
    structural_results_path: Path | None,
    experiment_root: Path,
    out_dir: Path,
    label: str,
) -> None:
    """Summarize structural-similarity rows into overall, per-condition, and per-rule thesis tables."""
    rows, inferred_label = load_structural_rows(
        structural_results_path, experiment_root)
    if not label:
        label = inferred_label

    comparable_rows = [row for row in rows if row.get(
        "structurallyComparable")]

    # Overall rows capture the entire dataset; condition rows below split the
    # same metrics by target/model/prompt/temperature/run.
    overall_scores = [float(row["overallStructuralSimilarity"])
                      for row in comparable_rows]
    node_scores = [float(row["nodeLabelJaccard"]) for row in comparable_rows]
    edge_scores = [float(row["edgeLabelJaccard"]) for row in comparable_rows]
    scalar_scores = [float(row["scalarFeatureSimilarity"])
                     for row in comparable_rows]

    overall_summary_rows = [
        {
            "scope": "overall",
            "label": label,
            "totalPairs": len(rows),
            "structurallyComparableCount": len(comparable_rows),
            "structurallyComparablePct": percent(len(comparable_rows), len(rows)),
            "llmParsedCount": sum(1 for row in rows if row.get("parseSuccessLlm")),
            "referenceParsedCount": sum(1 for row in rows if row.get("parseSuccessReference")),
            "meanOverallStructuralSimilarity": mean_or_zero(overall_scores),
            "medianOverallStructuralSimilarity": median_or_zero(overall_scores),
            "minOverallStructuralSimilarity": min_or_zero(overall_scores),
            "maxOverallStructuralSimilarity": max_or_zero(overall_scores),
            "meanNodeLabelJaccard": mean_or_zero(node_scores),
            "meanEdgeLabelJaccard": mean_or_zero(edge_scores),
            "meanScalarFeatureSimilarity": mean_or_zero(scalar_scores),
        }
    ]

    grouped_rows = defaultdict(list)
    for row in rows:
        key = (
            str(row.get("target", "")),
            str(row.get("model", "")),
            str(row.get("promptStyle", "")),
            str(row.get("temperature", "")),
            str(row.get("runCount", "")),
        )
        grouped_rows[key].append(row)

    # Append one summary row per experimental condition so plotting scripts can
    # compare runs without re-reading the JSONL source.
    for key, condition_rows in sorted(grouped_rows.items()):
        condition_comparable = [
            row for row in condition_rows if row.get("structurallyComparable")]
        condition_overall = [float(row["overallStructuralSimilarity"])
                             for row in condition_comparable]
        condition_node = [float(row["nodeLabelJaccard"])
                          for row in condition_comparable]
        condition_edge = [float(row["edgeLabelJaccard"])
                          for row in condition_comparable]
        condition_scalar = [float(row["scalarFeatureSimilarity"])
                            for row in condition_comparable]
        overall_summary_rows.append(
            {
                "scope": "condition",
                "label": label,
                "target": key[0],
                "model": key[1],
                "promptStyle": key[2],
                "temperature": key[3],
                "runCount": key[4],
                "totalPairs": len(condition_rows),
                "structurallyComparableCount": len(condition_comparable),
                "structurallyComparablePct": percent(len(condition_comparable), len(condition_rows)),
                "llmParsedCount": sum(1 for row in condition_rows if row.get("parseSuccessLlm")),
                "referenceParsedCount": sum(1 for row in condition_rows if row.get("parseSuccessReference")),
                "meanOverallStructuralSimilarity": mean_or_zero(condition_overall),
                "medianOverallStructuralSimilarity": median_or_zero(condition_overall),
                "minOverallStructuralSimilarity": min_or_zero(condition_overall),
                "maxOverallStructuralSimilarity": max_or_zero(condition_overall),
                "meanNodeLabelJaccard": mean_or_zero(condition_node),
                "meanEdgeLabelJaccard": mean_or_zero(condition_edge),
                "meanScalarFeatureSimilarity": mean_or_zero(condition_scalar),
            }
        )

    per_rule_rows = []
    for row in sorted(rows, key=lambda item: str(item.get("ruleKey"))):
        # The per-rule table keeps raw parse/comparison status so failures can
        # be inspected without opening the large structural JSONL files.
        per_rule_rows.append(
            {
                "target": row.get("target", ""),
                "model": row.get("model", ""),
                "promptStyle": row.get("promptStyle", ""),
                "temperature": row.get("temperature", ""),
                "runCount": row.get("runCount", ""),
                "ruleKey": row.get("ruleKey"),
                "referenceRuleKey": row.get("referenceRuleKey"),
                "parseSuccessLlm": row.get("parseSuccessLlm"),
                "parseSuccessReference": row.get("parseSuccessReference"),
                "structurallyComparable": row.get("structurallyComparable"),
                "overallStructuralSimilarity": row.get("overallStructuralSimilarity", ""),
                "nodeLabelJaccard": row.get("nodeLabelJaccard", ""),
                "edgeLabelJaccard": row.get("edgeLabelJaccard", ""),
                "scalarFeatureSimilarity": row.get("scalarFeatureSimilarity", ""),
                "comparisonError": row.get("comparisonError", ""),
            }
        )

    overall_fields = [
        "scope",
        "label",
        "target",
        "model",
        "promptStyle",
        "temperature",
        "runCount",
        "totalPairs",
        "structurallyComparableCount",
        "structurallyComparablePct",
        "llmParsedCount",
        "referenceParsedCount",
        "meanOverallStructuralSimilarity",
        "medianOverallStructuralSimilarity",
        "minOverallStructuralSimilarity",
        "maxOverallStructuralSimilarity",
        "meanNodeLabelJaccard",
        "meanEdgeLabelJaccard",
        "meanScalarFeatureSimilarity",
    ]
    per_rule_fields = [
        "target",
        "model",
        "promptStyle",
        "temperature",
        "runCount",
        "ruleKey",
        "referenceRuleKey",
        "parseSuccessLlm",
        "parseSuccessReference",
        "structurallyComparable",
        "overallStructuralSimilarity",
        "nodeLabelJaccard",
        "edgeLabelJaccard",
        "scalarFeatureSimilarity",
        "comparisonError",
    ]

    write_csv(out_dir / "structural_similarity_summary.csv",
              overall_summary_rows, overall_fields)
    write_markdown_table(
        out_dir / "structural_similarity_summary.md",
        "# Structural Similarity Summary",
        overall_summary_rows,
        overall_fields,
    )
    write_csv(out_dir / "structural_similarity_per_rule.csv",
              per_rule_rows, per_rule_fields)
    write_markdown_table(
        out_dir / "structural_similarity_per_rule.md",
        "# Structural Similarity Per Rule",
        per_rule_rows,
        per_rule_fields,
    )


def main() -> int:
    """Load experiment outputs, compare them to reference, and emit thesis-ready summary tables."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--aggregated-results", required=True,
                    help="Path to aggregated-results.jsonl")
    ap.add_argument("--experiment-root", required=True,
                    help="Experiment root containing run-spec.json files")
    ap.add_argument("--reference-results",
                    help="Reference results.jsonl path")
    ap.add_argument("--reference-root",
                    help="Directory containing catalog-run_<target>/results.jsonl reference runs")
    ap.add_argument("--catalog-path", default="config/pmd-catalog.json",
                    help="PMD catalog JSON for numeric ruleKey to PMD id mapping")
    ap.add_argument("--structural-results",
                    help="Optional structural-similarity.jsonl path")
    ap.add_argument("--structural-label", default="",
                    help="Optional label shown in the structural similarity summary")
    ap.add_argument("--out-dir", required=True,
                    help="Directory for summary tables")
    args = ap.parse_args()
    if bool(args.reference_results) == bool(args.reference_root):
        raise SystemExit(
            "Specify exactly one of --reference-results or --reference-root"
        )

    aggregated_rows = read_json_records(Path(args.aggregated_results))
    run_report_dirs = load_run_report_dirs(Path(args.experiment_root))
    single_reference = (
        load_reference_index(Path(args.reference_results))
        if args.reference_results
        else None
    )
    reference_by_target = (
        load_reference_by_target(Path(args.reference_root))
        if args.reference_root
        else {}
    )
    if args.reference_root and not reference_by_target:
        raise SystemExit(
            f"No catalog-run_<target>/results.jsonl or custom-run_<target>/results.jsonl files found under {args.reference_root}"
        )
    catalog_path = Path(args.catalog_path)
    catalog_index = load_catalog_rule_order(catalog_path)
    catalog_metadata = load_catalog_rule_metadata(catalog_path)
    report_cache: dict[Path, dict] = {}

    syntax_counters = defaultdict(Counter)
    behavior_counters = defaultdict(Counter)
    behavior_per_rule_rows = []

    # First pass: count syntactic/execution outcomes from validation rows and
    # compare each generated rule's PMD report to its reference report.
    for row in aggregated_rows:
        group = row_group_key(row)
        syntax_counters[group]["totalRules"] += 1
        syntax_counters[group]["syntacticValid"] += int(
            bool(row.get("syntacticValid")))
        syntax_counters[group]["hadConfigErrors"] += int(
            bool(row.get("hadConfigErrors")))
        syntax_counters[group]["hadProcessingErrors"] += int(
            bool(row.get("hadProcessingErrors")))
        syntax_counters[group]["operationallyValid"] += int(
            bool(row.get("syntacticValid")) and not bool(
                row.get("hadConfigErrors")) and not bool(row.get("hadProcessingErrors"))
        )

        mapped_rule_id = catalog_index.get(int(row["ruleKey"])) if str(
            row["ruleKey"]).isdigit() else str(row["ruleKey"])
        rule_metadata = catalog_metadata.get(str(mapped_rule_id), {})
        rule_category = str(rule_metadata.get("category", "Unknown"))
        reference = get_reference_for_target(
            group[0], single_reference, reference_by_target)
        if reference is None:
            # Multi-target mode requires a matching catalog run per target.
            # Keep the row visible as non-comparable instead of silently using
            # the wrong repository's reference.
            behavior_counters[group]["totalRules"] += 1
            behavior_counters[group]["non-comparable"] += 1
            behavior_per_rule_rows.append(
                {
                    "target": group[0],
                    "model": group[1],
                    "promptStyle": group[2],
                    "temperature": group[3],
                    "runCount": group[4],
                    "ruleKey": row.get("ruleKey"),
                    "catalogId": mapped_rule_id,
                    "category": rule_category,
                    "llmFindingCount": "",
                    "referenceFindingCount": "",
                    "matchType": "non-comparable",
                }
            )
            continue
        reference_index, reference_reports_dir = reference
        reference_row = reference_index.get(str(mapped_rule_id)) or reference_index.get(str(row["ruleKey"]))
        if reference_row is None:
            # Without a reference record there is no meaningful behavioral
            # comparison, but the row still counts toward the condition total.
            behavior_counters[group]["totalRules"] += 1
            behavior_counters[group]["non-comparable"] += 1
            behavior_per_rule_rows.append(
                {
                    "target": group[0],
                    "model": group[1],
                    "promptStyle": group[2],
                    "temperature": group[3],
                    "runCount": group[4],
                    "ruleKey": row.get("ruleKey"),
                    "catalogId": mapped_rule_id,
                    "category": rule_category,
                    "llmFindingCount": "",
                    "referenceFindingCount": "",
                    "matchType": "non-comparable",
                }
            )
            continue

        run_key = spec_key(row)
        llm_report_dir = run_report_dirs.get(run_key)
        if llm_report_dir is None:
            # If the run directory cannot be resolved, keep the rule visible as
            # non-comparable instead of dropping it from the denominator.
            behavior_counters[group]["totalRules"] += 1
            behavior_counters[group]["non-comparable"] += 1
            behavior_per_rule_rows.append(
                {
                    "target": group[0],
                    "model": group[1],
                    "promptStyle": group[2],
                    "temperature": group[3],
                    "runCount": group[4],
                    "ruleKey": row.get("ruleKey"),
                    "catalogId": mapped_rule_id,
                    "category": rule_category,
                    "llmFindingCount": "",
                    "referenceFindingCount": "",
                    "matchType": "non-comparable",
                }
            )
            continue

        llm_report = parse_report_violations(
            llm_report_dir / f"{row['ruleKey']}.json", report_cache)
        reference_report_path = resolve_reference_report_path(
            reference_row,
            reference_reports_dir,
            str(mapped_rule_id),
            str(row["ruleKey"]),
        )
        reference_report = parse_report_violations(reference_report_path, report_cache)
        match_type = classify_behavior(llm_report, reference_report)
        llm_finding_count = report_finding_count(llm_report)
        reference_finding_count = report_finding_count(reference_report)
        behavior_counters[group]["totalRules"] += 1
        behavior_counters[group][match_type] += 1
        behavior_per_rule_rows.append(
            {
                "target": group[0],
                "model": group[1],
                "promptStyle": group[2],
                "temperature": group[3],
                "runCount": group[4],
                "ruleKey": row.get("ruleKey"),
                "catalogId": mapped_rule_id,
                "category": rule_category,
                "llmFindingCount": llm_finding_count,
                "referenceFindingCount": reference_finding_count,
                "matchType": match_type,
            }
        )

    syntax_rows = []
    # Convert counters into stable CSV rows with both counts and percentages.
    for group, counts in sorted(syntax_counters.items()):
        total = counts["totalRules"]
        syntax_rows.append(
            {
                "target": group[0],
                "model": group[1],
                "promptStyle": group[2],
                "temperature": group[3],
                "runCount": group[4],
                "totalRules": total,
                "syntacticValidCount": counts["syntacticValid"],
                "syntacticValidPct": percent(counts["syntacticValid"], total),
                "configErrorCount": counts["hadConfigErrors"],
                "configErrorPct": percent(counts["hadConfigErrors"], total),
                "processingErrorCount": counts["hadProcessingErrors"],
                "processingErrorPct": percent(counts["hadProcessingErrors"], total),
                "operationallyValidCount": counts["operationallyValid"],
                "operationallyValidPct": percent(counts["operationallyValid"], total),
            }
        )

    behavior_rows = []
    # Behavioral categories are mutually exclusive, so each count contributes to
    # one percentage column in the summary table.
    no_match_types = [
        "none",
        "reference-only",
        "llm-only",
        "different-files",
        "llm-superset",
        "reference-superset",
        "partial-file-overlap",
    ]
    for group, counts in sorted(behavior_counters.items()):
        total = counts["totalRules"]
        no_match_count = sum(counts[match_type] for match_type in no_match_types)
        behavior_rows.append(
            {
                "target": group[0],
                "model": group[1],
                "promptStyle": group[2],
                "temperature": group[3],
                "runCount": group[4],
                "totalRules": total,
                "exactCount": counts["exact"],
                "exactPct": percent(counts["exact"], total),
                "overlapCount": counts["overlap"],
                "overlapPct": percent(counts["overlap"], total),
                "fileLevelCount": counts["file-level"],
                "fileLevelPct": percent(counts["file-level"], total),
                "bothEmptyCount": counts["both-empty"],
                "bothEmptyPct": percent(counts["both-empty"], total),
                "referenceOnlyCount": counts["reference-only"],
                "referenceOnlyPct": percent(counts["reference-only"], total),
                "llmOnlyCount": counts["llm-only"],
                "llmOnlyPct": percent(counts["llm-only"], total),
                "differentFilesCount": counts["different-files"],
                "differentFilesPct": percent(counts["different-files"], total),
                "llmSupersetCount": counts["llm-superset"],
                "llmSupersetPct": percent(counts["llm-superset"], total),
                "referenceSupersetCount": counts["reference-superset"],
                "referenceSupersetPct": percent(counts["reference-superset"], total),
                "partialFileOverlapCount": counts["partial-file-overlap"],
                "partialFileOverlapPct": percent(counts["partial-file-overlap"], total),
                "noMatchCount": no_match_count,
                "noMatchPct": percent(no_match_count, total),
                "nonComparableCount": counts["non-comparable"],
                "nonComparablePct": percent(counts["non-comparable"], total),
            }
        )

    out_dir = Path(args.out_dir)
    syntax_fields = [
        "target", "model", "promptStyle", "temperature", "runCount", "totalRules",
        "syntacticValidCount", "syntacticValidPct",
        "configErrorCount", "configErrorPct",
        "processingErrorCount", "processingErrorPct",
        "operationallyValidCount", "operationallyValidPct",
    ]
    behavior_fields = [
        "target", "model", "promptStyle", "temperature", "runCount", "totalRules",
        "exactCount", "exactPct",
        "overlapCount", "overlapPct",
        "fileLevelCount", "fileLevelPct",
        "bothEmptyCount", "bothEmptyPct",
        "referenceOnlyCount", "referenceOnlyPct",
        "llmOnlyCount", "llmOnlyPct",
        "differentFilesCount", "differentFilesPct",
        "llmSupersetCount", "llmSupersetPct",
        "referenceSupersetCount", "referenceSupersetPct",
        "partialFileOverlapCount", "partialFileOverlapPct",
        "noMatchCount", "noMatchPct",
        "nonComparableCount", "nonComparablePct",
    ]
    behavior_per_rule_fields = [
        "target",
        "model",
        "promptStyle",
        "temperature",
        "runCount",
        "ruleKey",
        "catalogId",
        "category",
        "llmFindingCount",
        "referenceFindingCount",
        "matchType",
    ]

    write_csv(out_dir / "syntax_execution_summary.csv",
              syntax_rows, syntax_fields)
    write_csv(out_dir / "behavioral_agreement_summary.csv",
              behavior_rows, behavior_fields)
    write_csv(out_dir / "behavioral_agreement_per_rule.csv",
              behavior_per_rule_rows, behavior_per_rule_fields)
    write_markdown_table(out_dir / "syntax_execution_summary.md",
                         "# Syntax / Execution Summary", syntax_rows, syntax_fields)
    write_markdown_table(out_dir / "behavioral_agreement_summary.md",
                         "# Behavioral Agreement Summary", behavior_rows, behavior_fields)

    structural_results_path = Path(
        args.structural_results) if args.structural_results else None
    # Structural summaries are optional because older experiment runs may only
    # have syntax and behavioral validation artifacts.
    if structural_results_path is not None or any(Path(args.experiment_root).rglob("structural-similarity.jsonl")):
        write_structural_similarity_summaries(
            structural_results_path,
            Path(args.experiment_root),
            out_dir,
            args.structural_label,
        )

    print(
        f"Wrote syntax summary to {out_dir / 'syntax_execution_summary.csv'}")
    print(
        f"Wrote behavior summary to {out_dir / 'behavioral_agreement_summary.csv'}")
    if structural_results_path is not None or any(Path(args.experiment_root).rglob("structural-similarity.jsonl")):
        print(
            f"Wrote structural summary to {out_dir / 'structural_similarity_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
