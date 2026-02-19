#!/usr/bin/env python3
"""
Extract PMD 7.20.0 Java *XPath-based* rule metadata from category XML files into a single JSON catalogue.

Filters out all non-XPath rules (i.e., rules implemented by Java classes) and retains only rules
whose implementation is XPath-based.

Note:
- "xpath" are also kept in "properties" (as in the source), but promoted to
  top-level fields for convenience.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import xml.etree.ElementTree as ET


def _strip_ns(tag: str) -> str:
    """Remove XML namespace if present."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _find_child(parent: ET.Element, name: str) -> Optional[ET.Element]:
    for ch in list(parent):
        if _strip_ns(ch.tag) == name:
            return ch
    return None


def _find_children(parent: ET.Element, name: str) -> list[ET.Element]:
    return [ch for ch in list(parent) if _strip_ns(ch.tag) == name]


def _text_of(elem: Optional[ET.Element]) -> str:
    """Return all text inside an element (including nested text) trimmed."""
    if elem is None:
        return ""
    return "".join(elem.itertext()).strip()


def _coerce_default(value: str, pmd_type: str) -> Any:
    """Coerce PMD property value text into a typed Python value when safe."""
    v = value.strip()

    if v == "":
        return ""

    t = pmd_type.strip()

    if t == "Boolean":
        if v.lower() in ("true", "false"):
            return v.lower() == "true"
        return v
    if t in ("Integer", "Long"):
        try:
            return int(v)
        except ValueError:
            return v
    if t in ("Float", "Double"):
        try:
            return float(v)
        except ValueError:
            return v
    if t in ("String", "Character", "Regex"):
        return v

    if t in ("List[String]", "List[Integer]", "List[Long]"):
        raw = re.sub(r"\s+", " ", v)
        parts = [p.strip() for p in raw.split(",")]
        parts = [p for p in parts if p]
        if t in ("List[Integer]", "List[Long]"):
            out: list[Any] = []
            for p in parts:
                try:
                    out.append(int(p))
                except ValueError:
                    return parts
            return out
        return parts

    if t in ("String[]", "Integer[]"):
        parts = [p.strip() for p in v.split(",")]
        if t == "Integer[]":
            out = []
            for p in parts:
                try:
                    out.append(int(p))
                except ValueError:
                    return parts
            return out
        return parts

    if t == "Enumeration":
        return v

    return v


def _is_xpath_rule(rule_class: str, props: Dict[str, Dict[str, Any]]) -> bool:
    """
    Heuristics for XPath-based PMD rules:
    - Rule class is PMD's XPathRule (or ends with XPathRule)
    - OR it defines an 'xpath' property (common in PMD 7 category XML)
    """
    cls = (rule_class or "").strip()
    if cls.endswith("XPathRule") or cls.endswith(".XPathRule") or cls == "XPathRule":
        return True
    if "xpath" in props:
        return True
    return False


def parse_ruleset_file(xml_path: Path) -> Tuple[str, Dict[str, Dict[str, Any]]]:
    """
    Return: (category_name, rules_dict)
    rules_dict keyed by rule id
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    if _strip_ns(root.tag) != "ruleset":
        raise ValueError(
            f"{xml_path.name}: Expected <ruleset> root, got <{root.tag}>")

    category = (root.attrib.get("name") or "").strip() or xml_path.stem

    rules_out: Dict[str, Dict[str, Any]] = {}

    for rule in _find_children(root, "rule"):
        rule_id = (rule.attrib.get("name") or "").strip()
        language = (rule.attrib.get("language") or "").strip().lower()

        if language and language != "java":
            continue
        if not rule_id:
            continue

        rule_class = (rule.attrib.get("class") or "").strip()
        message = (rule.attrib.get("message") or "").strip()
        desc = _text_of(_find_child(rule, "description"))

        prio_text = _text_of(_find_child(rule, "priority"))
        try:
            priority = int(prio_text) if prio_text else 3
        except ValueError:
            priority = 3

        # Properties
        props_block = _find_child(rule, "properties")
        props: Dict[str, Dict[str, Any]] = {}
        if props_block is not None:
            for prop in _find_children(props_block, "property"):
                pname = (prop.attrib.get("name") or "").strip()
                ptype = (prop.attrib.get("type") or "").strip() or "String"

                raw = prop.attrib.get("value")
                if raw is None:
                    val_elem = _find_child(prop, "value")
                    raw = _text_of(val_elem) if val_elem is not None else None

                default_val: Any = None if raw is None else _coerce_default(
                    raw, ptype)

                pobj: Dict[str, Any] = {"type": ptype, "default": default_val}

                pdesc = (prop.attrib.get("description") or "").strip()
                if pdesc:
                    pobj["description"] = pdesc

                if pname:
                    props[pname] = pobj

        # XPath-only filter
        if not _is_xpath_rule(rule_class, props):
            continue

        xpath_expr = props.get("xpath", {}).get("default")
        # Ensure xpath is a string if present; keep "" if missing/None
        if xpath_expr is None:
            xpath_expr = ""
        elif not isinstance(xpath_expr, str):
            xpath_expr = str(xpath_expr)

        rules_out[rule_id] = {
            "id": rule_id,
            "language": "java",
            "category": category,
            # Keep message/description/priority as primary fields
            "message": message,
            "description": desc,
            "priority": priority,
            # Promote XPath fields for your new pipeline
            "xpath": xpath_expr,
            # Keep full properties too (includes xpath/message/etc.)
            "properties": props,
            "sourceFiles": [xml_path.name],
            "ref": f"category/java/{xml_path.name}/{rule_id}",
        }

    return category, rules_out


def rule_score(r: dict) -> int:
    """Metadata-richness heuristic used to pick the best definition among duplicates."""
    score = 0
    score += 1 if r.get("message") else 0
    score += min(len(r.get("description", "")), 1000) // 50
    score += len(r.get("properties", {})) * 10
    # Prefer having an XPath expression present
    score += 20 if (r.get("xpath") or "").strip() else 0
    return score


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_dir", required=True,
                    help="Directory containing PMD category XML files")
    ap.add_argument("--out", dest="out_file", required=True,
                    help="Output JSON file path")
    ap.add_argument("--pmd-version", required=True)
    ap.add_argument("--java-version", required=True)
    ap.add_argument("--source", default="pmd-java-7.20.0.jar")
    args = ap.parse_args()

    in_dir = Path(args.in_dir)
    out_file = Path(args.out_file)

    if not in_dir.exists() or not in_dir.is_dir():
        raise SystemExit(f"Input directory not found: {in_dir}")

    xml_files = sorted([p for p in in_dir.rglob("*.xml") if p.is_file()])
    if not xml_files:
        raise SystemExit(f"No .xml files found under: {in_dir}")

    all_rules: Dict[str, Dict[str, Any]] = {}

    for xf in xml_files:
        _, rules = parse_ruleset_file(xf)
        for rid, cand in rules.items():
            if "sourceFiles" not in cand or not cand["sourceFiles"]:
                cand["sourceFiles"] = [xf.name]

            if rid not in all_rules:
                all_rules[rid] = cand
                continue

            existing = all_rules[rid]
            if "sourceFiles" not in existing or not existing["sourceFiles"]:
                existing["sourceFiles"] = []

            if rule_score(cand) > rule_score(existing):
                cand["sourceFiles"] = sorted(
                    set(existing["sourceFiles"] + cand["sourceFiles"]))
                all_rules[rid] = cand
            else:
                existing["sourceFiles"] = sorted(
                    set(existing["sourceFiles"] + cand["sourceFiles"]))
                all_rules[rid] = existing

    dupe_count = sum(1 for r in all_rules.values()
                     if len(r.get("sourceFiles", [])) > 1)
    missing_xpath = sum(1 for r in all_rules.values()
                        if not (r.get("xpath") or "").strip())

    print(f"Deduplicated: {dupe_count} rule ids appear in multiple XML files")
    print(
        f"XPath-only catalogue: {len(all_rules)} rules; {missing_xpath} have empty/missing xpath")

    catalogue = {
        "meta": {
            "tool": "pmd",
            "pmdVersion": args.pmd_version,
            "javaVersion": args.java_version,
            "source": args.source,
            "extractedFrom": str(in_dir).replace("\\", "/"),
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "xpathOnly": True,
        },
        "rules": all_rules,
    }

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(catalogue, indent=2,
                        ensure_ascii=False), encoding="utf-8")

    print(f"Wrote {len(all_rules)} XPath rules to: {out_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
