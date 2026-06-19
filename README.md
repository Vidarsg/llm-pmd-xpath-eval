# LLM-Generated PMD XPath Rule Evaluation

This repository contains a local evaluation framework for generating PMD Java XPath rules with large language models (LLMs), validating the generated rules with PMD, and comparing them against reference XPath rules. It supports the final thesis experiments across official PMD rules, custom jPinpoint rules, multiple Java target repositories, multiple models, zero-shot and few-shot prompting, with structural and behavioral similarity.

## Prerequisites

Install and configure these tools before running the pipeline:

- Python `3.11` or newer
- Java `17`
- Maven, used to build the XPath AST parser in `tools/xpath-ast-parser`
- PMD `7.20.0`
- PowerShell, either Windows PowerShell or PowerShell Core
- Python package `requests`
- Optional plotting packages `matplotlib` and `numpy`

Install the Python dependencies with:

```powershell
python -m pip install requests
python -m pip install matplotlib numpy
```

Set the LLM API key before running generation:

```powershell
$env:API_KEY = "your-api-key"
```

The scripts assume an OpenAI-compatible LLM endpoint. The final experiment matrix uses the IDUN LLM API endpoint configured in `config/experiment-matrix.json`.

## Repository Structure

- `config/`
  - `experiment-matrix.json`: final four-group experiment matrix.
  - `pmd-catalog.json`: extracted official PMD XPath rule catalog.
  - `pmd-official-rule-descriptions.jsonl`: official PMD rule descriptions used as LLM input.
  - `pmd-official-rule-xpaths.jsonl`: official PMD reference XPath expressions.
  - `pmd-official-rule-asts.jsonl`: normalized XPath ASTs for official PMD rules.
  - `xpath-ast-schema.md`: schema notes for normalized XPath AST records.
  - `custom-rulesets/jPinpoint/`: custom jPinpoint rule dataset, filtered rules, XPath expressions, and ASTs.
- `scripts/catalog/`: catalog extraction and catalog validation helpers.
- `scripts/generation/`: LLM-based XPath generation, including optional DSPy prompting support.
- `scripts/pmd/`: PowerShell wrappers for running PMD rule validation and reference-rule executions.
- `scripts/experiments/`: experiment matrix orchestration and result aggregation.
- `scripts/analysis/`: behavioral, structural, and plotting analysis scripts.
- `tools/xpath-ast-parser/`: Java/Maven XPath parser that normalizes Saxon XPath parse trees into JSONL AST records.
- `targets/`: recommended local location for cloned Java target repositories. This directory is ignored by Git.
- `out/`: generated reports, experiment outputs, summary tables, and figures. This directory is ignored by Git.

## Target Repositories

The experiment matrix expects the eight target repositories to exist under `targets/`:

```text
targets/commons-lang
targets/dropwizard
targets/immutables
targets/jdbi
targets/junit4
targets/liquibase
targets/picocli
targets/WebGoat
```

Clone or copy the target repositories into these paths, or edit the `targets` entries in `config/experiment-matrix.json` to match your local checkout locations. The commit hashes used for the thesis experiments are documented in the thesis material, but the target repositories themselves are not committed here.

## Core Workflows

### Generate XPath Rules

`scripts/generation/llm-xpath-generator.py` reads JSONL records with `ruleKey` and `description` fields and writes generated XPath expressions.

Supported prompt styles are:

- `zero-shot`
- `few-shot`

Example:

```powershell
python .\scripts\generation\llm-xpath-generator.py `
  --in .\config\pmd-official-rule-descriptions.jsonl `
  --out .\out\llm-output\generated.jsonl `
  --base-url https://llm.hpc.ntnu.no/ `
  --model openai/gpt-oss-120b `
  --temperature 0.7 `
  --max-tokens 1500 `
  --prompt-style zero-shot `
  --api-key API_KEY
```

### Validate Generated XPath Rules

`scripts/pmd/validate-llm-generated-xpaths.ps1` validates one generated JSONL file, or a directory of generated JSONL files, against a Java target repository.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\pmd\validate-llm-generated-xpaths.ps1 `
  -GeneratedJsonl .\out\llm-output `
  -PmdXPathCheck .\scripts\pmd\pmd-xpath-check.ps1 `
  -PmdBin "C:\path\to\pmd.bat" `
  -Target .\targets\commons-lang
```

Each validation run writes a `results.jsonl` file and one PMD JSON report per generated rule.

### Run One XPath Rule Directly

`scripts/pmd/pmd-xpath-check.ps1` is the lowest-level PMD execution wrapper. It creates a temporary one-rule PMD ruleset, runs PMD, captures the JSON report, and records configuration and processing errors.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\pmd\pmd-xpath-check.ps1 `
  -PmdBin "C:\path\to\pmd.bat" `
  -Target .\targets\commons-lang `
  -XPath "//MethodCall[@MethodName='println']" `
  -Format json `
  -OutReport .\out\single-report.json
```

### Run Reference Rules

Run the official PMD catalog against one target:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\pmd\run-catalog-on-target.ps1 `
  -PmdBin "C:\path\to\pmd.bat" `
  -RepoPath .\targets\commons-lang `
  -CatalogPath .\config\pmd-catalog.json
```

Run the custom jPinpoint XPath rules against one target:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\pmd\run-custom-rules-on-target.ps1 `
  -PmdBin "C:\path\to\pmd.bat" `
  -RepoPath .\targets\commons-lang `
  -RulesPath .\config\custom-rulesets\jPinpoint\jpinpoint-rule-xpaths.jsonl
```

Default output layouts:

```text
out/catalog-runs/catalog-run_<target>_<timestamp>/
  results.jsonl
  reports/
  run-metadata.json

out/custom-runs/custom-run_<target>_<timestamp>/
  results.jsonl
  reports/
  run-metadata.json
```

## Matrix-Based Experiments

`config/experiment-matrix.json` defines the final four experiment groups:

- official PMD rules with zero-shot prompting
- official PMD rules with few-shot prompting
- custom jPinpoint rules with zero-shot prompting
- custom jPinpoint rules with few-shot prompting

Each group is expanded across all configured targets, models, temperatures, and repeated runs.

Run the full matrix:

```powershell
python .\scripts\experiments\run-experiment-matrix.py `
  --config .\config\experiment-matrix.json `
  --pmd-bin "C:\path\to\pmd.bat"
```

Useful flags:

- `--skip-generation`
- `--skip-validation`
- `--force`
- `--jobs <n>`

Output layout:

```text
out/experiments/<experimentName>/<runName>/<target>/<promptStyle>/<model>/temp_<temperature>/runCount_<n>/
  run-spec.json
  evaluation/
    results.jsonl
    reports/

out/experiments/<experimentName>/<runName>/_generation/<inputRules>/<model>/temp_<temperature>/runCount_<n>/<promptStyle>/
  generated.jsonl
```

Generation output is shared across targets because generation depends on the rule descriptions, model, prompt style, temperature, and run count, but not on a target repository.

## Result Aggregation

Flatten one experiment tree into a compact JSONL file:

```powershell
python .\scripts\experiments\aggregate-experiment-results.py `
  --experiment-root .\out\experiments\Final-Experiment `
  --out .\out\experiments\Final-Experiment\aggregated-results.jsonl
```

The aggregate intentionally omits verbose diagnostic paths and snippets while preserving the fields needed by the analysis scripts.

## Structural Similarity

Build the XPath AST parser:

```powershell
Push-Location .\tools\xpath-ast-parser
mvn clean package
Pop-Location
```

Parse one JSONL file containing `xpath` fields:

```powershell
java -jar .\tools\xpath-ast-parser\target\xpath-ast-parser-1.0.0-jar-with-dependencies.jar `
  --in .\config\pmd-official-rule-xpaths.jsonl `
  --out .\out\pmd-official-rule-asts.jsonl
```

Run structural parsing and similarity scoring for a whole experiment tree:

```powershell
python .\scripts\analysis\run-structural-similarity-pipeline.py `
  --experiment-root .\out\experiments\Final-Experiment `
  --reference-asts .\config\pmd-official-rule-asts.jsonl
```

For jPinpoint runs, use:

```powershell
python .\scripts\analysis\run-structural-similarity-pipeline.py `
  --experiment-root .\out\experiments\Final-Experiment `
  --reference-asts .\config\custom-rulesets\jPinpoint\jpinpoint-rule-asts.jsonl
```

The lower-level metric script is `scripts/analysis/compute-xpath-structural-similarity.py`. It compares node-label counters, edge-label counters, and scalar AST features, then combines those components into `overallStructuralSimilarity`.

## Summary Tables and Figures

Compare aggregated LLM results with reference PMD reports:

```powershell
python .\scripts\analysis\summarize-experiment-vs-reference.py `
  --aggregated-results .\out\experiments\Final-Experiment\aggregated-results.jsonl `
  --experiment-root .\out\experiments\Final-Experiment `
  --reference-root .\out\catalog-runs `
  --catalog-path .\config\pmd-catalog.json `
  --out-dir .\out\analysis-summary\Official-PMD_AllTargets_AllModels_Zero-Shot
```

Use `--reference-root .\out\custom-runs` for jPinpoint summaries. The summarizer accepts both `catalog-run_<target>/results.jsonl` and `custom-run_<target>/results.jsonl` layouts. Output filenames still use `behavioral_agreement_*` for compatibility with earlier scripts, but the thesis text refers to the metric as behavioral similarity.

Common summary outputs:

```text
syntax_execution_summary.csv
syntax_execution_summary.md
behavioral_agreement_summary.csv
behavioral_agreement_summary.md
behavioral_agreement_per_rule.csv
behavioral_agreement_per_rule.md
structural_similarity_summary.csv
structural_similarity_summary.md
structural_similarity_per_rule.csv
structural_similarity_per_rule.md
```

Generate visual overview figures:

```powershell
python .\scripts\analysis\plot-model-level-overview.py `
  --syntax-summary .\out\analysis-summary\<experiment>\syntax_execution_summary.csv `
  --behavior-summary .\out\analysis-summary\<experiment>\behavioral_agreement_summary.csv `
  --out-figure .\out\analysis-summary\<experiment>\model_level_overview.png

python .\scripts\analysis\plot-target-level-overview.py `
  --syntax-summary .\out\analysis-summary\<experiment>\syntax_execution_summary.csv `
  --behavior-summary .\out\analysis-summary\<experiment>\behavioral_agreement_summary.csv `
  --out-figure .\out\analysis-summary\<experiment>\target_level_overview.png

python .\scripts\analysis\plot-rule-level-overview.py `
  --behavior-per-rule .\out\analysis-summary\<experiment>\behavioral_agreement_per_rule.csv `
  --out-figure .\out\analysis-summary\<experiment>\rule_level_overview.png

python .\scripts\analysis\plot-structural-similarity-overview.py `
  --structural-summary .\out\analysis-summary\<experiment>\structural_similarity_summary.csv `
  --structural-per-rule .\out\analysis-summary\<experiment>\structural_similarity_per_rule.csv `
  --out-figure .\out\analysis-summary\<experiment>\structural_similarity_overview.png
```

`plot-aggregated-overview.py` is kept as a broader combined overview script, but the figures are primarily produced by the model-level, target-level, rule-level, and structural-similarity plotting scripts.

## Input Formats

Rule description input:

```json
{"ruleKey": 1, "description": "Avoid printStackTrace(); use a logger instead."}
```

Generated XPath output:

```json
{"ruleKey": 1, "description": "Avoid printStackTrace(); use a logger instead.", "xpath": "//MethodCall[...]"}
```

XPath AST record:

```json
{"ruleKey": 1, "xpath": "//MethodCall[@MethodName='println']", "parseSuccess": true, "parseError": null, "ast": {"kind": "PathExpr", "children": []}}
```

## Typical End-to-End Flow

1. Clone the Java target repositories into `targets/` or edit `config/experiment-matrix.json`.
2. Set `API_KEY` and confirm `PmdBin` points to PMD `7.20.0`.
3. Run reference rules with `run-catalog-on-target.ps1` or `run-custom-rules-on-target.ps1`.
4. Run the experiment matrix with `run-experiment-matrix.py`.
5. Aggregate validation outputs with `aggregate-experiment-results.py`.
6. Run structural parsing and similarity with `run-structural-similarity-pipeline.py`.
7. Generate summary CSV/Markdown files with `summarize-experiment-vs-reference.py`.
8. Generate figures with the plotting scripts in `scripts/analysis/`.

## Notes

- `docs/`, `out/`, `targets/`, Maven build outputs, and Python bytecode caches are ignored by Git.
- The PMD wrappers intentionally run one rule at a time so each generated XPath expression receives isolated diagnostics and a separate report file.
- Configuration errors mean PMD could not load the generated rule. Processing errors mean PMD loaded the rule but failed while applying it to a target repository.
- Generated experiment outputs can be large and should preferably be archived separately.
