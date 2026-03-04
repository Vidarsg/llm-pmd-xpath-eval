# Minimal zero-shot batch generator.
# Reads JSONL: {"ruleKey":"...","description":"..."}
# Writes JSONL: {"ruleKey":"...","description":"...","xpath":"..."}
#
# This script sends rule descriptions to an LLM using an OpenAI-compatible API,
# and generates XPath expressions without any cleanup, heuristics, or repair efforts.
# The LLM output is used exactly as received.
#
# Usage:
#   set API_KEY=<personal api key>
#   python .\scripts\zero-shot-script.py --in <input JSONL file location> --out <output JSONL file location>
#     --base-url <LLM API base URL> --model <model identifier> --max-tokens <maximum tokens in response> --temperature <sampling temperature>

import argparse
import json
import os
import sys
import time

import requests

# Prompt template that instructs the LLM to generate XPath expressions. [STILL IN DEVELOPMENT]
# The template emphasizes outputting ONLY the XPath expression without any extra formatting,
# explanations, or code fences. {{RULE_DESCRIPTION}} is a placeholder that will be replaced with the actual rule description for each request.
PROMPT_TEMPLATE = """You are generating an XPath rule expression to be used in PMD 7.20 for Java (PMD Java AST).
Goal: given a natural-language rule description, output ONLY a single XPath expression that should correctly identify code patterns violating the rule.

Hard requirements:
- Output ONLY the XPath expression, nothing else.
- Do NOT output XML, rule metadata, code fences, explanations, or commentary.
- The expression must be valid for PMD's XPath evaluation over the Java AST.
- Avoid unsupported XPath features.
- If unsure, choose a conservative expression that is syntactically valid.

Task:
Given this rule description, generate the XPath expression:

RULE_DESCRIPTION:
{{RULE_DESCRIPTION}}

Output format:
<just the XPath expression>
"""


def main() -> int:
    start_time = time.time()

    # Parse command-line arguments
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="input_file", required=True,
                    help="Input JSONL file with rule descriptions")
    ap.add_argument("--out", dest="output_file", required=True,
                    help="Output JSONL file for generated XPaths")
    ap.add_argument("--base-url", required=True, help="LLM API base URL")
    ap.add_argument("--model", required=True, help="Model identifier")
    ap.add_argument("--max-tokens", type=int, default=1500,
                    help="Maximum tokens in response")
    ap.add_argument("--temperature", type=float, default=0.0,
                    help="Sampling temperature (0=deterministic)")
    ap.add_argument("--api-key", default="API_KEY",
                    help="Environment variable name containing API key")
    args = ap.parse_args()

    # Retrieve API key from environment variable
    api_key = os.getenv(args.api_key)
    if not api_key:
        print(
            f"Missing API key {args.api_key}", file=sys.stderr)
        return 2

    # Construct the OpenAI-compatible API endpoint URL and authentication headers
    url = args.base_url.rstrip("/") + "/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}",
               "Content-Type": "application/json"}

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

            # Build the prompt by substituting the rule description into the template
            prompt = PROMPT_TEMPLATE.replace("{{RULE_DESCRIPTION}}", desc)

            # Construct the API request payload with model parameters
            payload = {
                "model": args.model,
                "temperature": args.temperature,
                "max_tokens": args.max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }

            # Send the request to the LLM API
            r = requests.post(url, headers=headers, json=payload, timeout=120)
            r.raise_for_status()  # Raise exception on HTTP error

            # Extract the generated text from the API response
            data = r.json()
            choice = data.get("choices", [{}])[0]
            msg = choice.get("message") or {}
            content = msg.get("content")

            # The gateway returns the text here when content is null
            if content is None:
                content = msg.get("reasoning_content")

            # Fallbacks for other OpenAI-compatible shapes
            if content is None:
                content = choice.get("text")

            if content is None:
                psf = msg.get("provider_specific_fields") or {}
                content = psf.get("reasoning_content") or psf.get("reasoning")

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
