import argparse
import json
from collections import Counter
from pathlib import Path

"""Compare normalized XPath ASTs using lightweight structural features.

The Java parser emits a deliberately small AST schema. This script turns those
trees into comparable feature sets and writes one similarity row per generated
rule, paired against its reference rule.

Usage example:
  python scripts/analysis/compute-xpath-structural-similarity.py \
    --llm-asts out/experiments/experiment/run/structural/llm-xpath-asts.jsonl \
    --reference-asts config/pmd-official-rule-asts.jsonl \
    --catalog-path config/pmd-catalog.json \
    --out out/experiments/experiment/run/structural/structural-similarity.jsonl
"""


def read_json_records(path: Path) -> list[dict]:
    """Read either compact JSONL or concatenated JSON objects."""
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
    """Map numeric PMD input rule positions to stable PMD rule ids."""
    data = json.loads(catalog_path.read_text(encoding="utf-8"))
    return {
        index: rule_id
        for index, (rule_id, _) in enumerate((data.get("rules") or {}).items(), start=1)
    }


def node_label(node: dict) -> str:
    """Create a normalized label for multiset comparison."""
    return "|".join(
        [
            str(node.get("kind") or ""),
            str(node.get("name") or ""),
            str(node.get("operator") or ""),
        ]
    )


def walk_ast(node: dict, parent_label: str | None, depth: int, features: dict) -> None:
    """Traverse the AST and accumulate multiset and scalar structural features."""
    label = node_label(node)
    children = node.get("children") or []

    features["nodeLabels"][label] += 1
    features["scalar"]["node_count"] += 1
    features["scalar"]["max_depth"] = max(
        features["scalar"]["max_depth"], depth)

    kind = str(node.get("kind") or "")
    operator = str(node.get("operator") or "")
    if kind == "Predicate":
        features["scalar"]["predicate_count"] += 1
    if kind == "FunctionCall":
        features["scalar"]["function_count"] += 1
    if kind == "AxisStep":
        features["scalar"]["axis_step_count"] += 1
    if kind == "Literal":
        features["scalar"]["literal_count"] += 1
    if operator == "|":
        features["scalar"]["union_count"] += 1

    if parent_label is not None:
        features["edgeLabels"][f"{parent_label}->{label}"] += 1

    for child in children:
        walk_ast(child, label, depth + 1, features)


def extract_features(ast: dict) -> dict:
    """Extract all structural features from one normalized XPath AST."""
    # The three feature families mirror config/xpath-ast-schema.md: node labels,
    # parent-child edge labels, and scalar counts such as number of predicates.
    features = {
        "nodeLabels": Counter(),
        "edgeLabels": Counter(),
        "scalar": {
            "node_count": 0,
            "max_depth": 0,
            "predicate_count": 0,
            "union_count": 0,
            "function_count": 0,
            "axis_step_count": 0,
            "literal_count": 0,
        },
    }
    walk_ast(ast, None, 0, features)
    return features


def weighted_jaccard(left: Counter, right: Counter) -> float:
    """Compute weighted Jaccard similarity for multiset-like counters."""
    keys = set(left) | set(right)
    if not keys:
        return 1.0

    intersection = sum(min(left.get(key, 0), right.get(key, 0))
                       for key in keys)
    union = sum(max(left.get(key, 0), right.get(key, 0)) for key in keys)
    if union == 0:
        return 1.0
    return intersection / union


def scalar_similarity(left: dict, right: dict) -> float:
    """Compare scalar feature counts with normalized per-feature similarity."""
    scores = []
    for key in sorted(set(left) | set(right)):
        lval = float(left.get(key, 0))
        rval = float(right.get(key, 0))
        denom = max(lval, rval, 1.0)
        scores.append(1.0 - (abs(lval - rval) / denom))

    if not scores:
        return 1.0
    return sum(scores) / len(scores)


def compute_similarity(left_ast: dict, right_ast: dict) -> dict:
    """Compute the structural similarity metrics for one AST pair."""
    left_features = extract_features(left_ast)
    right_features = extract_features(right_ast)

    # Each component captures a different aspect of structure: vocabulary,
    # topology, and coarse size/shape. The final score weighs them equally.
    node_sim = weighted_jaccard(
        left_features["nodeLabels"], right_features["nodeLabels"])
    edge_sim = weighted_jaccard(
        left_features["edgeLabels"], right_features["edgeLabels"])
    scalar_sim = scalar_similarity(
        left_features["scalar"], right_features["scalar"])
    overall = (node_sim + edge_sim + scalar_sim) / 3.0

    return {
        "nodeLabelJaccard": round(node_sim, 6),
        "edgeLabelJaccard": round(edge_sim, 6),
        "scalarFeatureSimilarity": round(scalar_sim, 6),
        "overallStructuralSimilarity": round(overall, 6),
        "leftFeatures": {
            "nodeLabels": dict(left_features["nodeLabels"]),
            "edgeLabels": dict(left_features["edgeLabels"]),
            "scalar": left_features["scalar"],
        },
        "rightFeatures": {
            "nodeLabels": dict(right_features["nodeLabels"]),
            "edgeLabels": dict(right_features["edgeLabels"]),
            "scalar": right_features["scalar"],
        },
    }


def pair_reference_rule_key(llm_row: dict, reference_rows: dict[str, dict], catalog_index: dict[int, str]) -> str | None:
    """Resolve the matching reference key, preferring direct id matches over catalog remapping."""
    # Generated rows may carry a PMD id directly, or they may carry the numeric
    # position from the original input file. Try direct identifiers first.
    direct_candidates = []
    for key_name in ("ruleKey", "catalogId", "ruleId", "id"):
        value = llm_row.get(key_name)
        if value is not None:
            direct_candidates.append(str(value))

    for candidate in direct_candidates:
        if candidate in reference_rows:
            return candidate

    llm_rule_key = llm_row.get("ruleKey")
    text = str(llm_rule_key)
    if text.isdigit():
        mapped = str(catalog_index[int(text)])
        if mapped in reference_rows:
            return mapped
        return mapped
    return text if text in reference_rows else text


def write_jsonl(path: Path, rows: list[dict]) -> None:
    """Write result rows as compact JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    """Load two AST JSONL files, pair their rows, and write similarity results."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm-asts", required=True,
                    help="JSONL file with normalized ASTs for LLM-generated XPath rules")
    ap.add_argument("--reference-asts", required=True,
                    help="JSONL file with normalized ASTs for reference XPath rules")
    ap.add_argument("--catalog-path", default="config/pmd-catalog.json",
                    help="PMD catalog used to map numeric LLM rule keys to PMD ids")
    ap.add_argument("--out", required=True,
                    help="Output JSONL file for structural similarity rows")
    args = ap.parse_args()

    catalog_index = load_catalog_rule_order(Path(args.catalog_path))
    llm_rows = read_json_records(Path(args.llm_asts))
    reference_rows = {str(row["ruleKey"]): row for row in read_json_records(
        Path(args.reference_asts))}

    output_rows = []
    for llm_row in llm_rows:
        reference_rule_key = pair_reference_rule_key(
            llm_row, reference_rows, catalog_index)
        reference_row = reference_rows.get(reference_rule_key)

        # Keep a row even when comparison is impossible so parse failures and
        # missing reference mappings remain visible in downstream summaries.
        out_row = {
            "ruleKey": llm_row["ruleKey"],
            "referenceRuleKey": reference_rule_key,
            "xpath": llm_row.get("xpath"),
            "parseSuccessLlm": bool(llm_row.get("parseSuccess")),
            "parseSuccessReference": bool(reference_row and reference_row.get("parseSuccess")),
            "structurallyComparable": False,
        }

        if not reference_row:
            out_row["comparisonError"] = "Reference AST record not found"
            output_rows.append(out_row)
            continue

        if not llm_row.get("parseSuccess") or not reference_row.get("parseSuccess"):
            out_row["comparisonError"] = "One or both XPath expressions did not parse successfully"
            output_rows.append(out_row)
            continue

        similarity = compute_similarity(llm_row["ast"], reference_row["ast"])
        out_row["structurallyComparable"] = True
        out_row.update(similarity)
        output_rows.append(out_row)

    write_jsonl(Path(args.out), output_rows)
    print(f"Wrote structural similarity rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
