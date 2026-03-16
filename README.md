# LLM-Generated PMD XPath Rule Evaluation

This repository contains a local evaluation framework for generating PMD Java XPath rules with LLMs, validating them with PMD, and comparing large experiment runs across multiple models, prompt styles, rule sets, and target repositories.

## Prerequisites

Install and configure these before running the repository scripts:

- Python (preferably `3.11` or newer)
- Java `17`
- PMD `7.20.0`
- PowerShell
- Python package: `requests`

You also need:

- an API key for an OpenAI-compatible LLM endpoint
- a valid local path to the installed PMD executable

Cross-platform notes:

- On Windows, the PowerShell command is typically `powershell` and the PMD launcher is typically `pmd.bat`
- On macOS and Linux, install PowerShell Core and run the scripts with `pwsh`
- On macOS and Linux, the PMD launcher is typically the shell script in `bin/pmd`

Install the Python dependency with:

```powershell
python -m pip install requests
```

Set the API key in your environment before running the LLM generator:

```powershell
$env:API_KEY = "your-api-key"
```

PowerShell examples by platform:

- Windows PowerShell:

```powershell
powershell -File .\scripts\validate-llm-generated-xpaths.ps1 ...
```

- macOS/Linux PowerShell Core:

```bash
pwsh -File ./scripts/validate-llm-generated-xpaths.ps1 ...
```

## Scope

The repository supports:

- generation of XPath expressions from natural-language rule descriptions
- validation of generated XPath expressions against Java targets through the PMD tool
- execution of both official and custom PMD XPath rules against local Java targets
- matrix-based experiment orchestration across targets, models, prompt styles, temperatures, and repeated runs
- aggregation of all evaluation outputs into one single JSONL file for convenient evaluation summary

## Tooling

- PMD: `7.20.0`
- Java: `17`
- Rule type: PMD XPath rules for Java code
- LLM interface: OpenAI-compatible `/v1/chat/completions`

## Repository Structure

- `scripts/`
  - [extract-pmd-catalog.py](/scripts/extract-pmd-catalog.py): extract PMD XPath metadata from the official PMD rulesets
  - [catalog-validity-check.ps1](/scripts/catalog-validity-check.ps1): validation helper for catalog extraction workflows
  - [llm-xpath-generator.py](/scripts/llm-xpath-generator.py): uses LLMs to generate XPath expressions from rule descriptions
  - [pmd-xpath-check.ps1](/scripts/pmd-xpath-check.ps1): run one XPath rule configuration against a Java target through PMD
  - [validate-llm-generated-xpaths.ps1](/scripts/validate-llm-generated-xpaths.ps1): validate one LLM generated JSONL file, or a directory of them
  - [run-catalog-on-target.ps1](/scripts/run-catalog-on-target.ps1): run the official PMD rule catalog from `pmd-catalog.json` on a Java target
  - [run-custom-rules-on-target.ps1](/scripts/run-custom-rules-on-target.ps1): run custom PMD rules (collected from GitHub) from `custom-rulesets` containing `ruleKey` and `xpath` values
  - [run-experiment-matrix.py](/scripts/run-experiment-matrix.py): orchestrate larger experiments with both LLM generation + PMD validation runs
  - [aggregate-experiment-results.py](/scripts/aggregate-experiment-results.py): flatten evaluation outputs into one JSONL file for further analysis

- `config/`
  - [pmd-catalog.json](/config/pmd-catalog.json): extracted PMD official rule catalog with all metadata
  - [pmd-official-rule-descriptions.jsonl](/config/pmd-official-rule-descriptions.jsonl): JSONL file containing only rule descriptions for the official PMD rules
  - [example-rules.jsonl](/config/example-rules.jsonl): small example rule subset
  - [experiment-matrix.json](/config/experiment-matrix.json): full experiment pipeline definition
  - `custom-rulesets/`: custom PMD rulesets collected from public GithHub repositories
- `java-classes/`: minimal example Java files for experiment testing
- `out/`: generated outputs, reports, and experiment artifacts

## Core Workflows

### 1. Generate XPath Rules with an LLM

[llm-xpath-generator.py](/scripts/llm-xpath-generator.py) reads JSONL records containing:

```json
{"ruleKey": 1, "description": "Rule description"}
```

and writes JSONL records containing:

```json
{"ruleKey": 1, "description": "Rule description", "xpath": "//Some/XPath"}
```

Supported prompt styles:

- `zero-shot`
- `few-shot`
- `multi-step`

Example:

```powershell
python .\scripts\llm-xpath-generator.py `
  --in .\config\pmd-official-rule-descriptions.jsonl `
  --out .\out\llm-output\generated.jsonl `
  --base-url <YOUR_LLM_API_BASE_URL> `
  --model openai/gpt-oss-120b `
  --temperature 0.7 `
  --max-tokens 2000 `
  --prompt-style zero-shot `
  --api-key <YOUR_API_Key>
```

The generator automatically places outputs under prompt-style subfolders when writing into `llm-output`, for example:

```text
out/llm-output/zero-shot/generated.jsonl
```

### 2. Validate LLM Generated XPath Rules

[validate-llm-generated-xpaths.ps1](/scripts/validate-llm-generated-xpaths.ps1) validates one generated JSONL file, or recursively validates every JSONL file under a directory, against a Java target.

Example (Windows):

```powershell
powershell -File .\scripts\validate-llm-generated-xpaths.ps1 `
  -GeneratedJsonl .\out\llm-output `
  -PmdXPathCheck .\scripts\pmd-xpath-check.ps1 `
  -PmdBin "C:\path\to\pmd.bat" `
  -Target .\java-classes
```

Example (macOS/Linux):

```bash
pwsh -File ./scripts/validate-llm-generated-xpaths.ps1 \
  -GeneratedJsonl ./out/llm-output \
  -PmdXPathCheck ./scripts/pmd-xpath-check.ps1 \
  -PmdBin "/path/to/pmd-bin-7.20.0/bin/pmd" \
  -Target ./java-classes
```

Default output layout:

```text
out/evaluated-llm-rules/
  <input-label>_<timestamp>/
    results.jsonl
    reports/
```

Each `results.jsonl` row includes PMD execution status, syntactic validity, violation counts, processing/config error flags, and snippets of potential error diagnostics.

### 3. Run One XPath Rule Directly Through the PMD tool

[pmd-xpath-check.ps1](/scripts/pmd-xpath-check.ps1) is the lowest-level PMD execution primitive. It:

- builds a temporary one-rule PMD ruleset in XML
- runs PMD with the generated ruleset against a Java target
- captures report output in JSON format
- derives `syntacticValid`, `hadConfigErrors`, and `hadProcessingErrors`
- writes a per-rule report if PMD produces one

Example (Windows):

```powershell
powershell -File .\scripts\pmd-xpath-check.ps1 `
  -PmdBin "C:\path\to\pmd.bat" `
  -Target .\java-classes `
  -XPath "//MethodCall[@MethodName='println']" `
  -Format json `
  -OutReport .\out\single-report.json
```

Example (macOS/Linux):

```bash
pwsh -File ./scripts/pmd-xpath-check.ps1 \
  -PmdBin "/path/to/pmd-bin-7.20.0/bin/pmd" \
  -Target ./java-classes \
  -XPath "//MethodCall[@MethodName='println']" \
  -Format json \
  -OutReport ./out/single-report.json
```

### 4. Run The Official PMD Rule Catalog

[run-catalog-on-target.ps1](/scripts/run-catalog-on-target.ps1) iterates over [pmd-catalog.json](/config/pmd-catalog.json), extracts each official XPath rule, runs it against a Java target, and writes:

- `results.jsonl`
- `reports/<RuleKey>.json`
- `run-metadata.json`

Example (Windows):

```powershell
powershell -File .\scripts\run-catalog-on-target.ps1 `
  -PmdBin "C:\path\to\pmd.bat" `
  -RepoPath .\java-classes
```

Example (macOS/Linux):

```bash
pwsh -File ./scripts/run-catalog-on-target.ps1 \
  -PmdBin "/path/to/pmd-bin-7.20.0/bin/pmd" \
  -RepoPath ./java-classes
```

### 5. Run Custom XPath Rule Sets

[run-custom-rules-on-target.ps1](/scripts/run-custom-rules-on-target.ps1) accepts JSONL/JSON files where the only required fields are `ruleKey` and `xpath`.

Minimal JSONL example:

```json
{"ruleKey": 1, "xpath": "//MethodCall[@MethodName='println']"}
```

Example (Windows):

```powershell
powershell -File .\scripts\run-custom-rules-on-target.ps1 `
  -PmdBin "C:\path\to\pmd.bat" `
  -RepoPath .\java-classes `
  -RulesPath .\config\custom-rulesets\<A_CUSTOM_RULESET>
```

Example (macOS/Linux):

```bash
pwsh -File ./scripts/run-custom-rules-on-target.ps1 \
  -PmdBin "/path/to/pmd-bin-7.20.0/bin/pmd" \
  -RepoPath ./java-classes \
  -RulesPath ./config/custom-rulesets/<A_CUSTOM_RULESET>
```

Default output layout:

```text
out/custom-run_<target>_<timestamp>/
  results.jsonl
  reports/
  run-metadata.json
```

## Matrix-Based Experiment Runs

[experiment-matrix.json](/config/experiment-matrix.json) defines a pipeline for larger experiments. One config file represents an entire experimental strategy, not one single run.

Each `runs` entry can define:

- one `inputRules`
- one or more `targets`
- one or more `models`
- one or more `promptStyles`
- one or more `temperatures`
- `runCount`
- `maxTokens`

[run-experiment-matrix.py](/scripts/run-experiment-matrix.py) expands the matrix across all combinations and runs generation and validation sequentially.

Example:

```powershell
python .\scripts\run-experiment-matrix.py `
  --config .\config\experiment-matrix.json `
  --pmd-bin "C:\path\to\pmd.bat"
```

Useful flags:

- `--skip-generation`
- `--skip-validation`
- `--force`

Output layout:

```text
out/experiments/<experimentName>/<runName>/<target>/<promptStyle>/<model>/temp_<temperature>/runCount_<n>/
  run-spec.json
  generation/
    <promptStyle>/
      generated.jsonl
  evaluation/
    results.jsonl
    reports/
```

The runner skips generation or validation if the expected output file already exists and is non-empty, unless `--force` is provided.

## Result Aggregation

[aggregate-experiment-results.py](/scripts/aggregate-experiment-results.py) traverses an experiment folder, reads each evaluation `results.jsonl`, merges in the corresponding `run-spec.json`, and writes a compact aggregate JSONL file.

Example:

```powershell
python .\scripts\aggregate-experiment-results.py `
  --experiment-root .\out\experiments\default-matrix `
  --out .\out\experiments\default-matrix\aggregated-results.jsonl
```

Verbose path/debug fields like `reportPath`, `rulesetPath`, `stdoutPath`, and `stdoutSnippet` are intentionally omitted from the aggregate, preserving only fields relevant for the analysis.

## Input Formats

### Rule Description JSONL

Used by the LLM:

```json
{"ruleKey": 1, "description": "Avoid printStackTrace(); use a logger instead."}
```

### Generated XPath JSONL

Used for validation:

```json
{"ruleKey": 1, "description": "Avoid printStackTrace(); use a logger instead.", "xpath": "//MethodCall[...]"}
```

## Notes

- This framework assumes an OpenAI-compatible LLM endpoint.
- `-PmdBin` must point to a real PMD executable; placeholder values will now fail fast.
- The PMD wrappers are intentionally one-rule-at-a-time so that each XPath gets isolated diagnostics and a separate report file.

## Typical End-to-End Flow

1. Prepare a JSONL file containing descriptions of PMD rules.
2. Use LLMs to generate XPath candidates with [llm-xpath-generator.py](/scripts/llm-xpath-generator.py).
3. Validate LLM-generated XPath expressions with [validate-llm-generated-xpaths.ps1](/scripts/validate-llm-generated-xpaths.ps1).
4. Run PMD on ground truth rules with [run-catalog-on-target.ps1](/scripts/run-catalog-on-target.ps1) or [run-custom-rules-on-target.ps1](/scripts/run-custom-rules-on-target.ps1).
5. Use [run-experiment-matrix.py](/scripts/run-experiment-matrix.py) for repeated large-scale experiments.
6. Aggregate the results with [aggregate-experiment-results.py](/scripts/aggregate-experiment-results.py).
