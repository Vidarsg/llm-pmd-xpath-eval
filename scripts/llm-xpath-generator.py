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
import sys
import time

import requests

ZERO_SHOT_TEMPLATE = """You are an expert in PMD 7.20 Java XPath rules.

Task:
Generate exactly one XPath expression for a PMD Java rule from the rule description below.

Generation policy:
- Prefer a conservative, syntactically valid XPath over an ambitious but fragile one.
- Use the smallest AST pattern that captures the core violation.
- If the exact AST structure is uncertain, simplify instead of guessing.
- Avoid unsupported or speculative functions.

Hard requirements:
- Perform the two steps internally, but do not print the steps.
- Output exactly one XPath expression.
- Output no explanation, no prose, no markdown, no XML, no rule wrapper.
- Do not surround the answer with quotes or code fences.
- The result must be a syntactically valid XPath expression intended for PMD Java AST matching.

Rule description:
{{RULE_DESCRIPTION}}
"""

FEW_SHOT_TEMPLATE = """You are an expert in PMD 7.20 Java XPath rules.

Task:
Generate exactly one XPath expression for a PMD Java rule from the rule description below.

Learn the expected style from these official PMD examples.

Example 1
Rule description:
Avoid printStackTrace(); use a logger call instead.
XPath:
//MethodCall[ pmd-java:matchesSig("java.lang.Throwable#printStackTrace()") ]

Example 2
Rule description:
StringBuffers/StringBuilders can grow considerably, and so may become a source of memory leaks if held within objects with long lifetimes.
XPath:
//FieldDeclaration/ClassType[pmd-java:typeIs('java.lang.StringBuffer') or pmd-java:typeIs('java.lang.StringBuilder')]

Example 3
Rule description:
References to System.(out|err).print are usually intended for debugging purposes and can remain in the codebase even in production code.
XPath:
//MethodCall[ starts-with(@MethodName, 'print') ]
  /FieldAccess[ @Name = ('err', 'out') ]
  /TypeExpression[ pmd-java:typeIsExactly('java.lang.System') ]

Example 4
Rule description:
Unused labeled are unnecessary and may be confusing as you might be wondering what this label is used for.
XPath:
//LabeledStatement[let $label := @Label return
      not( (.//BreakStatement | .//ContinueStatement)[@Label = $label] )
]

Example 5
Rule description:
Java 5 introduced the varargs parameter declaration for methods and constructors. Byte arrays in any method and String arrays in public static void main(String[]) methods are ignored.
XPath:
//FormalParameters[not(parent::MethodDeclaration[@Overridden=true() or @MainMethod=true()])]
  /FormalParameter[position()=last()]
   [@Varargs=false()]
   [ArrayType[not(PrimitiveType[@Kind = "byte"] or ClassType[pmd-java:typeIs('java.lang.Byte')])]
    or VariableId[ArrayDimensions] and (PrimitiveType[not(@Kind="byte")] or ClassType[not(pmd-java:typeIs('java.lang.Byte'))])]

Generation policy:
- Prefer a conservative, syntactically valid XPath over an ambitious but fragile one.
- Use the smallest AST pattern that captures the core violation.
- If the exact AST structure is uncertain, simplify instead of guessing.
- Avoid unsupported or speculative functions.

Hard requirements:
- Perform the two steps internally, but do not print the steps.
- Output exactly one XPath expression.
- Output no explanation, no prose, no markdown, no XML, no rule wrapper.
- Do not surround the answer with quotes or code fences.
- The result must be a syntactically valid XPath expression intended for PMD Java AST matching.

Rule description:
{{RULE_DESCRIPTION}}
"""

MULTI_STEP_TEMPLATE = """You are generating a PMD 7.20 Java XPath expression.

Task:
Given a rule description, produce one syntactically valid XPath expression for PMD Java AST.

Process to follow internally:
1. Identify the smallest AST pattern that captures the rule.
2. Build the XPath using only constructs that are common in PMD 7 Java rules.
3. Check the XPath for syntax issues:
   - balanced brackets and parentheses
   - valid predicate structure
   - exactly one XPath expression
   - no prose, labels, or markdown
4. If uncertain about an AST detail, simplify the expression instead of guessing.

Allowed style:
- Prefer patterns similar to official PMD rules.
- Prefer pmd-java:typeIs / typeIsExactly / matchesSig only when clearly useful.
- Prefer conservative validity over ambitious coverage.

Hard requirements:
- Output exactly one XPath expression.
- No explanation.
- No XML wrapper.
- No code fences.
- If unsure, output a simpler valid XPath rather than a complex uncertain one.

Rule description:
{{RULE_DESCRIPTION}}
"""

PROMPT_TEMPLATES = {
    "zero-shot": ZERO_SHOT_TEMPLATE,
    "few-shot": FEW_SHOT_TEMPLATE,
    "multi-step": MULTI_STEP_TEMPLATE,
}


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
                    help="Sampling temperature (0=deterministic)")
    ap.add_argument("--prompt-style", choices=sorted(PROMPT_TEMPLATES.keys()), default="zero-shot",
                    help="Prompt template style to use")
    ap.add_argument("--api-key", default="API_KEY",
                    help="Environment variable name containing API key")
    args = ap.parse_args()
    args.output_file = resolve_output_path(args.output_file, args.prompt_style)

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
    os.makedirs(os.path.dirname(args.output_file), exist_ok=True)

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
            prompt_template = PROMPT_TEMPLATES[args.prompt_style]
            prompt = prompt_template.replace("{{RULE_DESCRIPTION}}", desc)

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
