# Prompt batch generator.
# Reads JSONL: {"ruleKey":"...","description":"..."}
# Writes JSONL: {"ruleKey":"...","description":"...","xpath":"..."}
#
# Usage:
#   set API_KEY=<personal api key>
#   python .\scripts\llm-xpath-generator.py --in <input JSONL file location> --out <output JSONL file location>
#     --base-url <LLM API base URL> --model <model identifier> --max-tokens <maximum tokens in response> --temperature <sampling temperature>

import argparse
import json
import os
import re
import sys
import time

import requests

ZERO_SHOT_TEMPLATE = """You are an expert in PMD 7.20 Java XPath rules.

Task:
Generate exactly one PMD Java XPath expression from the rule description below.

Technical context:
- PMD version: 7.20
- Target language: Java
- XPath version: XPath 3.1 as used by PMD 7
- PMD Java functions commonly used:
  - pmd-java:typeIs('ClassName')
  - pmd-java:typeIsExactly('ClassName')
  - pmd-java:matchesSig('Signature')
  - pmd-java:nodeIs('NodeName')
  - pmd-java:hasAnnotation('AnnotationName')
  - pmd-java:modifiers()

Generation procedure:
1. Identify the main violating AST construct.
2. Choose the narrowest stable AST node as the anchor.
3. Add only the predicates needed to express the violation.
4. If the rule requires type or signature reasoning, use PMD Java functions only when clearly justified.
5. If uncertain about an AST detail, simplify instead of guessing.

Hard requirements:
- Prefer a conservative valid XPath over an ambitious fragile XPath.
- Do not invent PMD functions or AST node names.
- Do not use unsupported syntax.
- Output no explanation, no steps, no markdown, no XML wrapper, no comments.
- Return exactly one raw XPath expression and nothing else.

Rule description:
{{RULE_DESCRIPTION}}
"""

FEW_SHOT_TEMPLATE = """You are an expert in PMD 7.20 Java XPath rules.

Task:
Generate exactly one PMD Java XPath expression from the rule description below.

Technical context:
- PMD version: 7.20
- Target language: Java
- XPath version: XPath 3.1 as used by PMD 7
- PMD Java functions commonly used:
  - pmd-java:typeIs('ClassName')
  - pmd-java:typeIsExactly('ClassName')
  - pmd-java:matchesSig('Signature')
  - pmd-java:nodeIs('NodeName')
  - pmd-java:hasAnnotation('AnnotationName')
  - pmd-java:modifiers()

Generation procedure:
1. Identify the main violating AST construct.
2. Choose the narrowest stable AST node as the anchor.
3. Add only the predicates needed to express the violation.
4. If the rule requires type or signature reasoning, use PMD Java functions only when clearly justified.
5. If uncertain about an AST detail, simplify instead of guessing.

Hard requirements:
- Prefer a conservative valid XPath over an ambitious fragile XPath.
- Do not invent PMD functions or AST node names.
- Do not use unsupported syntax.
- Output no explanation, no steps, no markdown, no XML wrapper, no comments.
- Return exactly one raw XPath expression and nothing else.

Examples:
{{RETRIEVED_EXAMPLES}}

Rule description:
{{RULE_DESCRIPTION}}
"""

MULTI_STEP_TEMPLATE = """You are generating a PMD 7.20 Java XPath expression.

Task:
Generate exactly one PMD Java XPath expression from the rule description below.

Follow this process internally:

Step 1: AST verification planning
Given the rule description, derive the minimal verification steps needed on a Java AST.
For each step, identify:
- which AST node or subtree should be inspected
- what property, attribute, relationship, or type condition must hold
- whether the step narrows the match or excludes false positives

Step 2: XPath construction
Translate those verification steps into one XPath expression.
- Start from the narrowest stable AST anchor you can justify
- Encode each verification step as a predicate, path constraint, or function call
- Prefer patterns commonly used in official PMD Java XPath rules

Step 3: Syntax self-check
Before answering, verify that the XPath:
- has balanced brackets and parentheses
- contains valid predicates
- is exactly one XPath expression
- contains no prose, labels, markdown, code fences, or XML wrapper

Hard requirements:
- Prefer a conservative valid XPath over an ambitious fragile XPath.
- Do not invent PMD functions or AST node names.
- Do not use unsupported syntax.
- Output no explanation, no steps, no markdown, no XML wrapper, no comments.
- Return exactly one raw XPath expression and nothing else.

Rule description:
{{RULE_DESCRIPTION}}
"""

PROMPT_TEMPLATES = {
    "zero-shot": ZERO_SHOT_TEMPLATE,
    "few-shot": FEW_SHOT_TEMPLATE,
    "multi-step": MULTI_STEP_TEMPLATE,
}

STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "if", "in",
    "into", "is", "it", "its", "no", "not", "of", "on", "or", "that", "the",
    "their", "then", "this", "to", "use", "used", "using", "when", "where",
    "which", "with", "without",
}


def tokenize_description(text: str) -> set[str]:
    """Tokenize rule descriptions for simple retrieval scoring."""
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_.#-]*", text.lower())
    return {token for token in tokens if token not in STOP_WORDS and len(token) > 2}


def load_catalog_examples(catalog_path: str) -> list[dict]:
    """Load PMD catalog rules with description/xpath pairs usable as few-shot examples."""
    with open(catalog_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    rules = []
    for rule_id, rule in (data.get("rules") or {}).items():
        description = (rule.get("description") or "").strip()
        xpath = (rule.get("xpath") or "").strip()
        if not description or not xpath:
            continue

        rules.append({
            "id": rule.get("id") or rule_id,
            "description": description,
            "xpath": xpath,
            "tokens": tokenize_description(description),
        })

    return rules


def score_example(query_tokens: set[str], example_tokens: set[str]) -> tuple[int, int]:
    """Rank examples by token overlap and then by example specificity."""
    overlap = len(query_tokens & example_tokens)
    return overlap, len(example_tokens)


def select_retrieved_examples(description: str, catalog_rules: list[dict], limit: int, excluded_ids: set[str] | None = None) -> list[dict]:
    """Pick the closest catalog examples for the current rule description."""
    query_tokens = tokenize_description(description)
    excluded_ids = excluded_ids or set()
    ranked = sorted(
        catalog_rules,
        key=lambda rule: score_example(query_tokens, rule["tokens"]),
        reverse=True,
    )

    selected = []
    for rule in ranked:
        if str(rule["id"]).strip() in excluded_ids:
            continue
        if rule["description"].strip() == description.strip():
            continue
        if score_example(query_tokens, rule["tokens"])[0] == 0 and selected:
            break
        selected.append(rule)
        if len(selected) >= limit:
            break

    if selected:
        return selected

    return ranked[:limit]


def format_retrieved_examples(examples: list[dict]) -> str:
    """Render retrieved PMD rules into the few-shot prompt block."""
    parts = []
    for index, example in enumerate(examples, start=1):
        parts.append(
            f"Example {index}\n"
            f"Rule description:\n{example['description']}\n"
            f"XPath:\n{example['xpath']}"
        )
    return "\n\n".join(parts)


def resolve_api_format(base_url: str, model: str, api_format: str) -> str:
    """Use the Responses API by default for OpenAI GPT-5 family models."""
    if api_format != "auto":
        return api_format

    if "api.openai.com" in base_url.rstrip("/").lower() and model.lower().startswith("gpt-5"):
        return "responses"

    return "chat"


def build_request(api_format: str, args, prompt: str) -> tuple[str, dict]:
    """Build the endpoint path and payload for the selected API shape."""
    if api_format == "responses":
        payload = {
            "model": args.model,
            "input": prompt,
            "max_output_tokens": args.max_tokens,
        }
        if args.temperature is not None:
            payload["temperature"] = args.temperature
        if args.reasoning_effort:
            payload["reasoning"] = {"effort": args.reasoning_effort}
        if args.verbosity:
            payload["text"] = {"format": {"type": "text"},
                               "verbosity": args.verbosity}
        return "/v1/responses", payload

    payload = {
        "model": args.model,
        "max_tokens": args.max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if args.temperature is not None:
        payload["temperature"] = args.temperature
    return "/v1/chat/completions", payload


def extract_content(api_format: str, data: dict) -> str | None:
    """Extract text from either Responses API or Chat Completions API output."""
    if api_format == "responses":
        output_text = data.get("output_text")
        if output_text:
            return output_text

        for item in data.get("output", []):
            for content in item.get("content", []):
                text = content.get("text")
                if text:
                    return text
        return None

    choice = data.get("choices", [{}])[0]
    msg = choice.get("message") or {}
    content = msg.get("content")

    if content is None:
        content = msg.get("reasoning_content")

    if content is None:
        content = choice.get("text")

    if content is None:
        psf = msg.get("provider_specific_fields") or {}
        content = psf.get("reasoning_content") or psf.get("reasoning")

    return content


def resolve_output_path(output_file: str, prompt_style: str) -> str:
    """Place outputs under a prompt-style subfolder when writing into llm-output."""
    output_dir = os.path.dirname(output_file)
    filename = os.path.basename(output_file)

    if not output_dir:
        return os.path.join(prompt_style, filename)

    if os.path.basename(os.path.normpath(output_dir)) == prompt_style:
        return output_file

    return os.path.join(output_dir, prompt_style, filename)


def main() -> int:
    start_time = time.time()

    # Parse command-line arguments
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="input_file", required=True,
                    help="Input JSONL file with rule descriptions")
    ap.add_argument("--out", dest="output_file", required=True,
                    help="Output JSONL file for generated XPaths; the file is written under a prompt-style subfolder")
    ap.add_argument("--base-url", required=True, help="LLM API base URL")
    ap.add_argument("--model", required=True, help="Model identifier")
    ap.add_argument("--max-tokens", type=int, default=1500,
                    help="Maximum tokens in response")
    ap.add_argument("--temperature", type=float, default=0.7,
                    help="Sampling temperature (omit for models/endpoints that reject it)")
    ap.add_argument("--api-format", choices=("auto", "chat", "responses"), default="auto",
                    help="API payload shape; auto uses Responses API for OpenAI GPT-5 models")
    ap.add_argument("--reasoning-effort", choices=("none", "minimal", "low", "medium", "high"), default="",
                    help="Responses API only: reasoning effort level")
    ap.add_argument("--verbosity", choices=("low", "medium", "high"), default="",
                    help="Responses API only: text verbosity level")
    ap.add_argument("--omit-temperature", action="store_true",
                    help="Do not send the temperature parameter")
    ap.add_argument("--prompt-style", choices=sorted(PROMPT_TEMPLATES.keys()), default="zero-shot",
                    help="Prompt template style to use")
    ap.add_argument("--catalog-path", default="config/pmd-catalog.json",
                    help="PMD catalog JSON used to retrieve dynamic few-shot examples")
    ap.add_argument("--few-shot-count", type=int, default=5,
                    help="Number of retrieved few-shot examples to inject for few-shot prompting")
    ap.add_argument("--api-key", default="API_KEY",
                    help="Environment variable name containing API key")
    args = ap.parse_args()
    args.output_file = resolve_output_path(args.output_file, args.prompt_style)
    if args.omit_temperature:
        args.temperature = None

    # Retrieve API key from environment variable
    api_key = os.getenv(args.api_key)
    if not api_key:
        print(
            f"Missing API key {args.api_key}", file=sys.stderr)
        return 2

    headers = {"Authorization": f"Bearer {api_key}",
               "Content-Type": "application/json"}
    os.makedirs(os.path.dirname(args.output_file), exist_ok=True)
    catalog_rules = []
    if args.prompt_style == "few-shot":
        catalog_rules = load_catalog_examples(args.catalog_path)

    # Open input and output files
    # Process each line of the input JSONL file (one rule per line)
    with open(args.input_file, "r", encoding="utf-8") as fin, open(args.output_file, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue

            # Parse the JSON record to extract ruleKey and description
            rec = json.loads(line)
            rule_key = rec.get("ruleKey")
            desc = (rec.get("description") or "").strip()
            excluded_ids = {
                str(value).strip()
                for value in (
                    rec.get("catalogId"),
                    rec.get("ruleId"),
                    rec.get("id"),
                    rule_key,
                )
                if value is not None and str(value).strip()
            }

            # Build the prompt by substituting the rule description into the template
            prompt_template = PROMPT_TEMPLATES[args.prompt_style]
            prompt = prompt_template.replace("{{RULE_DESCRIPTION}}", desc)
            if args.prompt_style == "few-shot":
                retrieved_examples = select_retrieved_examples(
                    desc, catalog_rules, args.few_shot_count, excluded_ids)
                prompt = prompt.replace(
                    "{{RETRIEVED_EXAMPLES}}",
                    format_retrieved_examples(retrieved_examples),
                )

            api_format = resolve_api_format(
                args.base_url, args.model, args.api_format)
            endpoint_path, payload = build_request(api_format, args, prompt)
            url = args.base_url.rstrip("/") + endpoint_path

            # Send the request to the LLM API
            r = requests.post(url, headers=headers, json=payload, timeout=120)
            if not r.ok:
                print(
                    f"HTTP {r.status_code} for ruleKey = {rule_key}", file=sys.stderr)
                print(r.text, file=sys.stderr)
                r.raise_for_status()

            # Extract the generated text from the API response
            data = r.json()
            content = extract_content(api_format, data)

            if content is None:
                print("WARNING: No content returned for ruleKey =",
                      rule_key, file=sys.stderr)
                print(json.dumps(data, ensure_ascii=False), file=sys.stderr)
                content = ""

            xpath = str(content).strip()

            # Write the result as a single-line JSON object to the output file
            out = {"ruleKey": rule_key, "description": desc, "xpath": xpath}
            fout.write(json.dumps(out, ensure_ascii=False) + "\n")

    elapsed = time.time() - start_time
    print(f"Completed in {elapsed:.2f} seconds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
