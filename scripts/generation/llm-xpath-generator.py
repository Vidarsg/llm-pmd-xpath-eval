# Prompt batch generator.
# Reads JSONL: {"ruleKey":"...","description":"..."}
# Writes JSONL: {"ruleKey":"...","description":"...","xpath":"..."}
#
# Usage:
#   set API_KEY=<personal api key>
#   python .\scripts\generation\llm-xpath-generator.py --in <input JSONL file location> --out <output JSONL file location>
#     --base-url <LLM API base URL> --model <model identifier> --prompt-style <prompt style> --temperature <sampling temperature>
#     --max-tokens <maximum tokens in response> --max-rules <maximum number of rules to process, 0 for all>

import argparse
from datetime import datetime, timezone
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

Hard requirements:
- Prefer a conservative valid XPath over an ambitious fragile XPath.
- Do not invent PMD functions or AST node names.
- Do not use unsupported syntax.
- Output no explanation, no steps, no markdown, no XML wrapper, no comments.
- Do not output <think> tags or reasoning text.
- If you reason internally, do not reveal it. Output only the final raw XPath.
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

Hard requirements:
- Prefer a conservative valid XPath over an ambitious fragile XPath.
- Do not invent PMD functions or AST node names.
- Do not use unsupported syntax.
- Output no explanation, no steps, no markdown, no XML wrapper, no comments.
- Do not output <think> tags or reasoning text.
- If you reason internally, do not reveal it. Output only the final raw XPath.
- Return exactly one raw XPath expression and nothing else.

Examples:
{{RETRIEVED_EXAMPLES}}

Rule description:
{{RULE_DESCRIPTION}}
"""

DSPY_COT_INSTRUCTIONS = """You are a PMD 7.20 Java XPath rule expert.

Given a natural-language Java coding rule description, reason about the PMD Java AST internally and produce exactly one XPath expression that detects violations of the rule.

The XPath must target PMD 7 Java AST nodes and may use PMD Java XPath functions such as pmd-java:typeIs, pmd-java:typeIsExactly, pmd-java:matchesSig, pmd-java:nodeIs, pmd-java:hasAnnotation, and pmd-java:modifiers when appropriate.

PMD 7 uses XPath 3.1. Do not use any other version of XPath syntax. Do not use any PMD functions that are not supported in PMD 7.

Return only the final raw XPath expression in the xpath output field. Do not include prose, markdown, XML, code fences, comments, or visible reasoning in the XPath value.
"""

PROMPT_TEMPLATES = {
    "zero-shot": ZERO_SHOT_TEMPLATE,
    "few-shot": FEW_SHOT_TEMPLATE,
}
DSPY_PROMPT_STYLES = {"dspy-cot"}
PROMPT_STYLE_CHOICES = sorted(set(PROMPT_TEMPLATES) | DSPY_PROMPT_STYLES)

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


def load_jsonl_records(path: str) -> list[dict]:
    """Load non-empty JSONL records from disk."""
    records = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def load_catalog_examples(catalog_path: str) -> list[dict]:
    """Load PMD examples with description/xpath pairs usable as few-shot examples."""
    if catalog_path.lower().endswith(".jsonl"):
        descriptions = load_jsonl_records(catalog_path)
        xpaths_path = re.sub(r"rule-descriptions\.jsonl$",
                             "rule-xpaths.jsonl", catalog_path)
        if xpaths_path == catalog_path or not os.path.exists(xpaths_path):
            raise FileNotFoundError(
                f"Could not infer matching XPath JSONL file for few-shot examples from {catalog_path}"
            )

        xpaths_by_key = {
            str(rec.get("ruleKey")).strip(): rec
            for rec in load_jsonl_records(xpaths_path)
            if rec.get("ruleKey") is not None and str(rec.get("ruleKey")).strip()
        }

        rules = []
        for rec in descriptions:
            rule_key = rec.get("ruleKey")
            description = (rec.get("description") or "").strip()
            if rule_key is None or not description:
                continue

            xpath_rec = xpaths_by_key.get(str(rule_key).strip())
            xpath = ((xpath_rec or {}).get("xpath") or "").strip()
            if not xpath:
                continue

            rules.append({
                "id": str(rule_key).strip(),
                "catalogId": (xpath_rec or {}).get("catalogId"),
                "description": description,
                "xpath": xpath,
                "tokens": tokenize_description(description),
            })
        return rules

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
            "catalogId": rule.get("id") or rule_id,
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
        example_id = example.get("catalogId") or example.get("id")
        parts.append(
            f"Example {index}\n"
            f"Rule id:\n{example_id}\n"
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


def parse_rate_limit_reset(response: requests.Response) -> float | None:
    """Return seconds to wait for a 429 response, if the API exposes a reset time."""
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass

    try:
        message = response.json().get("error", {}).get("message", "")
    except ValueError:
        message = response.text

    match = re.search(
        r"Limit resets at:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC",
        message,
    )
    if not match:
        return None

    reset_at = datetime.strptime(match.group(
        1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return max(0.0, (reset_at - datetime.now(timezone.utc)).total_seconds())


def post_with_retries(url: str, headers: dict, payload: dict, rule_key, args) -> requests.Response:
    """POST to the LLM API, waiting through rate limits and transient failures."""
    for attempt in range(1, args.max_retries + 2):
        try:
            response = requests.post(
                url, headers=headers, json=payload, timeout=args.timeout)
        except requests.exceptions.ReadTimeout:
            if attempt > args.max_retries:
                raise
            wait_seconds = min(args.retry_max_wait,
                               args.retry_base_wait * attempt)
            print(
                f"Read timeout for ruleKey={rule_key}; retrying in {wait_seconds:.1f}s "
                f"({attempt}/{args.max_retries})",
                file=sys.stderr,
            )
            time.sleep(wait_seconds)
            continue

        if response.status_code == 429 and attempt <= args.max_retries:
            wait_seconds = parse_rate_limit_reset(response)
            if wait_seconds is None:
                wait_seconds = min(args.retry_max_wait,
                                   args.retry_base_wait * attempt)
            wait_seconds += args.rate_limit_buffer
            print(
                f"HTTP 429 for ruleKey={rule_key}; waiting {wait_seconds:.1f}s before retry "
                f"({attempt}/{args.max_retries})",
                file=sys.stderr,
            )
            time.sleep(wait_seconds)
            continue

        if response.status_code in {500, 502, 503, 504} and attempt <= args.max_retries:
            wait_seconds = min(args.retry_max_wait,
                               args.retry_base_wait * attempt)
            print(
                f"HTTP {response.status_code} for ruleKey={rule_key}; retrying in {wait_seconds:.1f}s "
                f"({attempt}/{args.max_retries})",
                file=sys.stderr,
            )
            time.sleep(wait_seconds)
            continue

        return response

    raise RuntimeError("unreachable retry state")


def build_dspy_cot_program(args, api_key: str):
    """Configure DSPy and return a ChainOfThought program for XPath generation."""
    try:
        import dspy
    except ImportError as exc:
        raise SystemExit(
            "Prompt style 'dspy-cot' requires DSPy. Install it with: python -m pip install dspy"
        ) from exc

    lm_kwargs = {
        "api_key": api_key,
        "api_base": args.base_url,
        "max_tokens": args.max_tokens,
    }
    if args.temperature is not None:
        lm_kwargs["temperature"] = args.temperature

    lm = dspy.LM(args.model, **lm_kwargs)
    dspy.configure(lm=lm)
    signature = dspy.Signature(
        "rule : str -> xpath : str",
        instructions=DSPY_COT_INSTRUCTIONS,
    )
    program = dspy.ChainOfThought(signature)
    if args.dspy_program:
        program.load(args.dspy_program)
        print(f"Loaded DSPy program from {args.dspy_program}")
    return program


def run_dspy_with_retries(program, description: str, rule_key, args) -> str:
    """Run a DSPy program with the same retry envelope as direct API calls."""
    for attempt in range(1, args.max_retries + 2):
        try:
            prediction = program.predict(rule=description)
            xpath = getattr(prediction, "xpath", None)
            if xpath is None and isinstance(prediction, dict):
                xpath = prediction.get("xpath")
            return str(xpath or "").strip()
        except Exception as exc:
            if attempt > args.max_retries:
                raise
            wait_seconds = min(args.retry_max_wait,
                               args.retry_base_wait * attempt)
            print(
                f"DSPy generation failed for ruleKey={rule_key}: {exc}; "
                f"retrying in {wait_seconds:.1f}s ({attempt}/{args.max_retries})",
                file=sys.stderr,
            )
            time.sleep(wait_seconds)

    raise RuntimeError("unreachable DSPy retry state")


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
    ap.add_argument("--max-rules", type=int, default=0,
                    help="Maximum number of input rules to process; 0 means all rules")
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
    ap.add_argument("--prompt-style", choices=PROMPT_STYLE_CHOICES, default="zero-shot",
                    help="Prompt template style to use")
    ap.add_argument("--catalog-path", default="config/pmd-official-rule-descriptions.jsonl",
                    help="PMD example source used to retrieve dynamic few-shot examples; accepts the cleaned descriptions JSONL or the full catalog JSON")
    ap.add_argument("--few-shot-count", type=int, default=5,
                    help="Number of retrieved few-shot examples to inject for few-shot prompting")
    ap.add_argument("--dspy-program", default="",
                    help="Optional saved DSPy program JSON to load for dspy-cot prompting")
    ap.add_argument("--api-key", default="API_KEY",
                    help="Environment variable name containing API key")
    ap.add_argument("--timeout", type=int, default=300,
                    help="Per-request timeout in seconds")
    ap.add_argument("--max-retries", type=int, default=5,
                    help="Maximum retries for rate limits, timeouts, and transient server errors")
    ap.add_argument("--retry-base-wait", type=float, default=10.0,
                    help="Base wait in seconds for retry backoff when no reset time is available")
    ap.add_argument("--retry-max-wait", type=float, default=300.0,
                    help="Maximum wait in seconds for retry backoff when no reset time is available")
    ap.add_argument("--rate-limit-buffer", type=float, default=5.0,
                    help="Extra seconds to wait after a reported rate-limit reset time")
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
    dspy_program = None
    if args.prompt_style == "dspy-cot":
        dspy_program = build_dspy_cot_program(args, api_key)

    # Open input and output files
    # Process each line of the input JSONL file (one rule per line)
    with open(args.input_file, "r", encoding="utf-8-sig") as fin, open(args.output_file, "w", encoding="utf-8") as fout:
        processed_rules = 0
        for line in fin:
            line = line.strip()
            if not line:
                continue
            if args.max_rules and processed_rules >= args.max_rules:
                break

            # Parse the JSON record to extract ruleKey and description
            rec = json.loads(line)
            processed_rules += 1
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

            if args.prompt_style == "dspy-cot":
                xpath = run_dspy_with_retries(
                    dspy_program, desc, rule_key, args)
            else:
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
                endpoint_path, payload = build_request(
                    api_format, args, prompt)
                url = args.base_url.rstrip("/") + endpoint_path

                # Send the request to the LLM API
                r = post_with_retries(url, headers, payload, rule_key, args)
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
