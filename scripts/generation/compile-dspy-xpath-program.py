"""Compile a reusable DSPy ChainOfThought program for PMD XPath generation.

This script is intended to be run separately from the experiment matrix. It
uses official PMD description/XPath pairs as DSPy examples and saves a program
for later experiment runs. By default, it stores the official examples directly
as demos instead of allowing DSPy to bootstrap generated demos.

Usage example:
  python scripts/generation/compile-dspy-xpath-program.py \
    --descriptions config/pmd-official-rule-descriptions.jsonl \
    --xpaths config/pmd-official-rule-xpaths.jsonl \
    --out-program out/dspy/pmd-xpath-cot-optimized.json \
    --out-prompt out/dspy/pmd-xpath-cot-optimized.md \
    --base-url https://llm.hpc.ntnu.no/ \
    --model openai/openai/gpt-oss-120b \
    --max-train-examples 5 \
    --compile-mode official-demos
"""

import argparse
import importlib.util
import json
import os
import random
import re
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    """Load non-empty JSONL records."""
    rows = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_generator_module(repo_root: Path):
    """Import constants from llm-xpath-generator.py without renaming the file."""
    module_path = repo_root / "scripts" / "generation" / "llm-xpath-generator.py"
    spec = importlib.util.spec_from_file_location(
        "llm_xpath_generator", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def xpath_tokens(value: str) -> set[str]:
    """Tokenize XPath strings for a lightweight optimizer metric."""
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_.#:-]*|//?|==|!=|<=|>=|[()[\]@=*|]", value or ""))


def xpath_similarity_metric(example, prediction, trace=None) -> float:
    """Score predictions by token overlap with the reference XPath."""
    expected = xpath_tokens(getattr(example, "xpath", ""))
    actual = xpath_tokens(getattr(prediction, "xpath", ""))
    predicted_xpath = getattr(prediction, "xpath", "")
    if re.search(r"//AST[A-Z]", predicted_xpath or ""):
        return 0.0
    if not expected and not actual:
        return 1.0
    if not expected or not actual:
        return 0.0

    precision = len(expected & actual) / len(actual)
    recall = len(expected & actual) / len(expected)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def build_trainset(dspy, descriptions_path: Path, xpaths_path: Path, max_examples: int, seed: int, exclude_rule_keys: set[str]):
    """Pair description and XPath records into DSPy examples."""
    descriptions = read_jsonl(descriptions_path)
    xpaths_by_key = {
        str(row.get("ruleKey")).strip(): row
        for row in read_jsonl(xpaths_path)
        if row.get("ruleKey") is not None
    }

    examples = []
    for row in descriptions:
        rule_key = str(row.get("ruleKey")).strip()
        if not rule_key or rule_key in exclude_rule_keys:
            continue
        xpath = str((xpaths_by_key.get(rule_key) or {}
                     ).get("xpath") or "").strip()
        description = str(row.get("description") or "").strip()
        if not xpath or not description:
            continue
        examples.append(dspy.Example(rule=description,
                        xpath=xpath).with_inputs("rule"))

    rng = random.Random(seed)
    rng.shuffle(examples)
    if max_examples > 0:
        examples = examples[:max_examples]
    return examples


def attach_official_demos(program, trainset: list) -> object:
    """Attach official examples directly as DSPy demos without bootstrapping."""
    if hasattr(program, "predict"):
        program.predict.demos = trainset
        return program
    raise AttributeError(
        "Expected DSPy ChainOfThought program to expose a predict module")


def render_prompt_summary(program) -> str:
    """Write a readable summary of the saved DSPy instructions and demos."""
    signature = program.predict.signature
    lines = [signature.instructions.strip(), ""]
    demos = getattr(program.predict, "demos", []) or []
    if demos:
        lines.append("## Official DSPy Demos")
        lines.append("")
    for index, demo in enumerate(demos, start=1):
        lines.append(f"### Demo {index}")
        lines.append("")
        lines.append("Rule:")
        lines.append(str(getattr(demo, "rule", "")).strip())
        lines.append("")
        if getattr(demo, "reasoning", None):
            lines.append("Reasoning:")
            lines.append(str(getattr(demo, "reasoning", "")).strip())
            lines.append("")
        lines.append("XPath:")
        lines.append(str(getattr(demo, "xpath", "")).strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--descriptions", default="config/pmd-official-rule-descriptions.jsonl")
    parser.add_argument(
        "--xpaths", default="config/pmd-official-rule-xpaths.jsonl")
    parser.add_argument("--out-program", required=True)
    parser.add_argument("--out-prompt", default="")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key", default="API_KEY")
    parser.add_argument("--max-tokens", type=int, default=3000)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--omit-temperature", action="store_true")
    parser.add_argument("--max-train-examples", type=int, default=40)
    parser.add_argument("--exclude-rule-keys", default="",
                        help="Comma-separated rule keys to exclude from optimization")
    parser.add_argument(
        "--compile-mode",
        choices=("official-demos", "mipro"),
        default="official-demos",
        help="official-demos stores the official examples directly; mipro runs DSPy MIPROv2 optimization",
    )
    parser.add_argument(
        "--auto", choices=("light", "medium", "heavy"), default="light")
    parser.add_argument("--num-threads", type=int, default=4)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    try:
        import dspy
    except ImportError as exc:
        raise SystemExit(
            "This script requires DSPy. Install it with: python -m pip install dspy") from exc

    api_key = os.getenv(args.api_key)
    if not api_key:
        raise SystemExit(f"Missing API key {args.api_key}")

    repo_root = Path(__file__).resolve().parent.parent.parent
    generator = load_generator_module(repo_root)

    lm_kwargs = {
        "api_key": api_key,
        "api_base": args.base_url,
        "max_tokens": args.max_tokens,
    }
    if not args.omit_temperature:
        lm_kwargs["temperature"] = args.temperature
    dspy.configure(lm=dspy.LM(args.model, **lm_kwargs))

    signature = dspy.Signature(
        "rule : str -> xpath : str",
        instructions=generator.DSPY_COT_INSTRUCTIONS,
    )
    program = dspy.ChainOfThought(signature)

    exclude_rule_keys = {
        value.strip()
        for value in args.exclude_rule_keys.split(",")
        if value.strip()
    }
    trainset = build_trainset(
        dspy,
        (repo_root / args.descriptions).resolve(),
        (repo_root / args.xpaths).resolve(),
        args.max_train_examples,
        args.seed,
        exclude_rule_keys,
    )
    if not trainset:
        raise SystemExit("No DSPy training examples were loaded")

    print(f"Compiling DSPy program with {len(trainset)} training example(s)")
    if args.compile_mode == "official-demos":
        optimized_program = attach_official_demos(program, trainset)
        print("Using official examples directly as DSPy demos; no bootstrapped demos were generated")
    else:
        optimizer = dspy.MIPROv2(
            metric=xpath_similarity_metric,
            auto=args.auto,
            num_threads=args.num_threads,
        )
        optimized_program = optimizer.compile(program, trainset=trainset)

    out_program = (repo_root / args.out_program).resolve()
    out_program.parent.mkdir(parents=True, exist_ok=True)
    optimized_program.save(str(out_program))
    print(f"Wrote optimized DSPy program to {out_program}")

    if args.out_prompt:
        out_prompt = (repo_root / args.out_prompt).resolve()
        out_prompt.parent.mkdir(parents=True, exist_ok=True)
        prompt = render_prompt_summary(optimized_program)
        out_prompt.write_text(prompt, encoding="utf-8")
        print(f"Wrote optimized prompt to {out_prompt}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
