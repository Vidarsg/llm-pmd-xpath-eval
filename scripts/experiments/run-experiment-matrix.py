import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import product
from pathlib import Path
from threading import Lock

"""Expand and run an LLM XPath generation experiment matrix.

The matrix config defines runs across models, targets, prompt styles,
temperatures, and repeats. This driver creates a reproducible output directory
for each condition, launches generation, and then validates generated XPath
rules with the PMD validation script.

Usage example:
  python scripts/experiments/run-experiment-matrix.py \
    --config config/experiment-matrix.json \
    --pmd-bin C:/tools/pmd-bin-7.20.0/bin/pmd.bat \
    --jobs 2

Resume without rerunning completed outputs by omitting --force.

Pilot runs can set "maxRules": 10 in a run entry to process only the first
10 input rules.

DSPy runs can set "dspyProgram": "out/dspy/pmd-xpath-cot-optimized.json"
to load a precompiled DSPy program during generation.
"""


GENERATION_LOCKS: dict[str, Lock] = {}
GENERATION_LOCKS_LOCK = Lock()
GENERATED_THIS_RUN: set[str] = set()


def sanitize(value: str) -> str:
    """Convert a run parameter into a filesystem-safe path segment."""
    safe = []
    for char in str(value):
        if char.isalnum() or char in ("-", "_", "."):
            safe.append(char)
        else:
            safe.append("_")
    return "".join(safe).strip("._") or "value"


def read_json(path: Path) -> dict:
    """Load a JSON configuration file into a Python dictionary."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def file_has_content(path: Path) -> bool:
    """Treat an existing non-empty file as a completed stage artifact."""
    return path.exists() and path.is_file() and path.stat().st_size > 0


def ensure_dir(path: Path) -> None:
    """Create a directory tree if it does not already exist."""
    path.mkdir(parents=True, exist_ok=True)


def powershell_executable() -> str:
    """Resolve the PowerShell executable used to launch validation runs."""
    return os.environ.get("COMSPEC_POWERSHELL") or "powershell"


def run_command(command: list[str], cwd: Path) -> None:
    """Run one subprocess and fail fast if the command exits non-zero."""
    completed = subprocess.run(command, cwd=str(cwd), check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {completed.returncode}: {' '.join(command)}")


def format_duration(seconds: float) -> str:
    """Format elapsed wall-clock seconds as HH:MM:SS."""
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def generation_lock(path: Path) -> Lock:
    """Return one in-process lock per generated output path."""
    key = str(path.resolve())
    with GENERATION_LOCKS_LOCK:
        if key not in GENERATION_LOCKS:
            GENERATION_LOCKS[key] = Lock()
        return GENERATION_LOCKS[key]


def run_condition(
    index: int,
    total: int,
    spec: dict,
    repo_root: Path,
    experiment_root: Path,
    generator_script: Path,
    validator_script: Path,
    pmd_bin: Path,
    skip_generation: bool,
    skip_validation: bool,
    force: bool,
) -> None:
    """Run generation and validation for one fully expanded experiment condition."""
    model_slug = sanitize(spec["model"])
    target_slug = sanitize(Path(spec["target"]).name)
    input_slug = sanitize(Path(spec["inputRules"]).stem)
    prompt_style = sanitize(spec["promptStyle"])
    temp_slug = sanitize(str(spec["temperature"]))
    runCount_slug = f"runCount_{spec['runCount']}"
    run_root = (
        experiment_root
        / sanitize(spec["runName"])
        / target_slug
        / prompt_style
        / model_slug
        / f"temp_{temp_slug}"
        / runCount_slug
    )
    generation_dir = (
        experiment_root
        / sanitize(spec["runName"])
        / "_generation"
        / input_slug
        / model_slug
        / f"temp_{temp_slug}"
        / runCount_slug
        / prompt_style
    )
    evaluation_dir = run_root / "evaluation"
    generated_jsonl = generation_dir / "generated.jsonl"
    validation_results = evaluation_dir / "results.jsonl"
    run_spec_path = run_root / "run-spec.json"

    ensure_dir(generation_dir)
    ensure_dir(evaluation_dir)

    # Store resolved absolute paths in run-spec.json so later analysis can
    # locate generated files, reports, and the exact target used.
    resolved_spec = {
        **spec,
        "index": index,
        "inputRules": str((repo_root / spec["inputRules"]).resolve()),
        "target": str((repo_root / spec["target"]).resolve()),
        "generatorScript": str(generator_script),
        "validatorScript": str(validator_script),
        "pmdBin": str(pmd_bin),
        "generatedJsonl": str(generated_jsonl),
        "evaluationDir": str(evaluation_dir),
    }
    write_run_spec(run_spec_path, resolved_spec)

    condition_label = (
        f"[{index}/{total}] {spec['runName']} | target={spec['target']} | "
        f"{spec['promptStyle']} | {spec['model']} | temp={spec['temperature']} | "
        f"runCount={spec['runCount']}"
    )
    print(condition_label, flush=True)

    if not skip_generation:
        with generation_lock(generated_jsonl):
            generated_key = str(generated_jsonl.resolve())
            should_generate = (
                (force and generated_key not in GENERATED_THIS_RUN)
                or (not force and not file_has_content(generated_jsonl))
            )
            if should_generate:
                # Generation is target-independent, so this shared output is
                # reused for validation across all target repositories.
                command = [
                    sys.executable,
                    str(generator_script),
                    "--in",
                    resolved_spec["inputRules"],
                    "--out",
                    str(generated_jsonl),
                    "--base-url",
                    spec["baseUrl"],
                    "--model",
                    spec["model"],
                    "--max-tokens",
                    str(spec["maxTokens"]),
                    "--max-rules",
                    str(spec["maxRules"]),
                    "--temperature",
                    str(spec["temperature"]),
                    "--prompt-style",
                    spec["promptStyle"],
                    "--api-key",
                    spec["apiKeyEnv"],
                ]
                if spec.get("dspyProgram"):
                    command.extend(["--dspy-program", str((repo_root / spec["dspyProgram"]).resolve())])
                run_command(command, repo_root)
                GENERATED_THIS_RUN.add(generated_key)
            else:
                print(f"  Skip generation: {generated_jsonl}", flush=True)

    if not skip_validation:
        if force or not file_has_content(validation_results):
            # Validation runs through PowerShell because the PMD wrapper is
            # implemented as a repository-local .ps1 script.
            command = [
                powershell_executable(),
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(validator_script),
                "-GeneratedJsonl",
                str(generated_jsonl),
                "-PmdXPathCheck",
                str((repo_root / "scripts/pmd/pmd-xpath-check.ps1").resolve()),
                "-PmdBin",
                str(pmd_bin),
                "-Target",
                resolved_spec["target"],
                "-OutDir",
                str(evaluation_dir),
            ]
            run_command(command, repo_root)
        else:
            print(f"  Skip validation: {validation_results}", flush=True)


def build_run_specs(config: dict) -> list[dict]:
    """Expand the experiment matrix into one concrete run spec per condition."""
    specs = []
    for run in config["runs"]:
        runCount = int(run.get("runCount", 1))
        max_tokens = int(run.get("maxTokens", 1500))
        max_rules = int(run.get("maxRules", 0))
        dspy_program = str(run.get("dspyProgram", "")).strip()
        prompt_styles = run["promptStyles"]
        temperatures = run["temperatures"]
        targets = run.get("targets")
        if targets is None:
            targets = [run["target"]]
        if not targets:
            raise ValueError(f"Run '{run['name']}' must define at least one target")
        if runCount < 1:
            raise ValueError(f"Run '{run['name']}' must have runCount >= 1")
        if max_rules < 0:
            raise ValueError(f"Run '{run['name']}' must have maxRules >= 0")

        # Cartesian-product expansion makes each generated spec a single,
        # reproducible condition with one model/target/prompt/temperature/repeat.
        for model, target, prompt_style, temperature, repeat_index in product(
            run["models"], targets, prompt_styles, temperatures, range(1, runCount + 1)
        ):
            specs.append(
                {
                    "runName": run["name"],
                    "inputRules": run["inputRules"],
                    "target": target,
                    "model": model["name"],
                    "baseUrl": model["baseUrl"],
                    "apiKeyEnv": model.get("apiKeyEnv", "API_KEY"),
                    "promptStyle": prompt_style,
                    "temperature": temperature,
                    "runCount": repeat_index,
                    "maxTokens": max_tokens,
                    "maxRules": max_rules,
                    "dspyProgram": str(model.get("dspyProgram") or dspy_program),
                }
            )
    return specs


def write_run_spec(path: Path, spec: dict) -> None:
    """Persist the resolved run parameters next to the generated artifacts."""
    with path.open("w", encoding="utf-8") as handle:
        json.dump(spec, handle, indent=2)


def main() -> int:
    """Drive generation and validation for every run defined in the matrix."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True,
                        help="Path to experiment matrix JSON")
    parser.add_argument("--pmd-bin", required=True,
                        help="Path to pmd.bat / pmd.sh")
    parser.add_argument("--skip-generation", action="store_true",
                        help="Skip LLM generation stage")
    parser.add_argument("--skip-validation",
                        action="store_true", help="Skip validation stage")
    parser.add_argument("--force", action="store_true",
                        help="Re-run stages even if outputs already exist")
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Number of run conditions to execute concurrently; default is 1",
    )
    args = parser.parse_args()
    if args.jobs < 1:
        raise SystemExit("--jobs must be >= 1")

    repo_root = Path(__file__).resolve().parent.parent.parent
    config_path = (repo_root / args.config).resolve()
    pmd_bin = (repo_root / args.pmd_bin).resolve()

    config = read_json(config_path)
    output_root = (repo_root / config.get("outputRoot",
                   "out/experiments")).resolve()
    experiment_root = output_root / sanitize(config["experimentName"])
    generator_script = (repo_root / config.get("generatorScript",
                        "scripts/generation/llm-xpath-generator.py")).resolve()
    validator_script = (repo_root / config.get("validatorScript",
                        "scripts/pmd/validate-llm-generated-xpaths.ps1")).resolve()

    ensure_dir(experiment_root)
    specs = build_run_specs(config)

    print(f"Loaded {len(specs)} run condition(s) from {config_path}")
    started_at = time.perf_counter()

    if args.jobs == 1:
        for index, spec in enumerate(specs, start=1):
            run_condition(
                index=index,
                total=len(specs),
                spec=spec,
                repo_root=repo_root,
                experiment_root=experiment_root,
                generator_script=generator_script,
                validator_script=validator_script,
                pmd_bin=pmd_bin,
                skip_generation=args.skip_generation,
                skip_validation=args.skip_validation,
                force=args.force,
            )
    else:
        print(f"Running up to {args.jobs} condition(s) concurrently")
        failures = []
        with ThreadPoolExecutor(max_workers=args.jobs) as executor:
            future_to_label = {}
            for index, spec in enumerate(specs, start=1):
                label = (
                    f"[{index}/{len(specs)}] {spec['promptStyle']} | {spec['model']} | "
                    f"temp={spec['temperature']} | runCount={spec['runCount']}"
                )
                future = executor.submit(
                    run_condition,
                    index=index,
                    total=len(specs),
                    spec=spec,
                    repo_root=repo_root,
                    experiment_root=experiment_root,
                    generator_script=generator_script,
                    validator_script=validator_script,
                    pmd_bin=pmd_bin,
                    skip_generation=args.skip_generation,
                    skip_validation=args.skip_validation,
                    force=args.force,
                )
                future_to_label[future] = label

            for future in as_completed(future_to_label):
                label = future_to_label[future]
                try:
                    future.result()
                except Exception as exc:
                    failures.append((label, exc))
                    print(f"FAILED: {label}: {exc}", file=sys.stderr, flush=True)

        if failures:
            details = "\n".join(f"- {label}: {exc}" for label, exc in failures)
            raise RuntimeError(f"{len(failures)} condition(s) failed:\n{details}")

    elapsed = time.perf_counter() - started_at
    print(f"Experiment outputs written under: {experiment_root}")
    print(f"Total experiment runtime: {format_duration(elapsed)} ({elapsed:.2f} seconds)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
