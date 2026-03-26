import argparse
import json
from pathlib import Path

OMIT_ROW_FIELDS = {
    "rulesetPath",
    "reportPath",
    "stdoutPath",
    "stderrPath",
    "stdoutSnippet",
}

OMIT_SPEC_FIELDS = {
    "baseUrl",
}


def iter_result_files(experiment_root: Path):
    for path in sorted(experiment_root.rglob("results.jsonl")):
        if "evaluation" in path.parts:
            yield path


def load_run_spec(results_path: Path) -> dict:
    run_spec = results_path.parent.parent / "run-spec.json"
    if not run_spec.exists():
        return {}
    with run_spec.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def compact_run_spec(run_spec: dict) -> dict:
    """Keep only run metadata that is useful when comparing experiment conditions."""
    return {key: value for key, value in run_spec.items() if key not in OMIT_SPEC_FIELDS}


def compact_result_row(row: dict) -> dict:
    """Drop verbose execution-path and stdout fields from an evaluation result."""
    return {key: value for key, value in row.items() if key not in OMIT_ROW_FIELDS}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-root", required=True,
                        help="Root folder under out/experiments/<experimentName>")
    parser.add_argument("--out", required=True,
                        help="Aggregated JSONL output path")
    args = parser.parse_args()

    experiment_root = Path(args.experiment_root).resolve()
    output_path = Path(args.out).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as fout:
        for results_path in iter_result_files(experiment_root):
            run_spec = compact_run_spec(load_run_spec(results_path))
            with results_path.open("r", encoding="utf-8-sig") as fin:
                for line in fin:
                    line = line.strip().lstrip("\ufeff")
                    if not line:
                        continue
                    row = compact_result_row(json.loads(line))
                    merged = {
                        "runName": run_spec.get("runName"),
                        "inputRules": run_spec.get("inputRules"),
                        "target": run_spec.get("target"),
                        "model": run_spec.get("model"),
                        "promptStyle": run_spec.get("promptStyle"),
                        "temperature": run_spec.get("temperature"),
                        "runCount": run_spec.get("runCount"),
                        **row,
                    }
                    fout.write(json.dumps(merged, ensure_ascii=False) + "\n")

    print(f"Aggregated results written to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
