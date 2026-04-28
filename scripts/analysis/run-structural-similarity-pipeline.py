import argparse
import subprocess
import sys
from pathlib import Path

"""Run the complete structural-similarity pipeline.

This script glues together the Java/Saxon XPath AST parser and the Python
similarity calculator. It supports a single generated/ground-truth pair or an
entire experiment tree containing generation/**/generated.jsonl files.

Usage example:
  python scripts/analysis/run-structural-similarity-pipeline.py \
    --experiment-root out/experiments/experiment \
    --ground-truth-asts config/pmd-official-rule-asts.jsonl \
    --catalog-path config/pmd-catalog.json
"""


def file_has_content(path: Path) -> bool:
    """Treat an existing non-empty file as a completed pipeline artifact."""
    return path.exists() and path.is_file() and path.stat().st_size > 0


def run_command(command: list[str], cwd: Path) -> None:
    """Run one subprocess and fail fast on a non-zero exit code."""
    completed = subprocess.run(command, cwd=str(cwd), check=False)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {completed.returncode}: {' '.join(command)}"
        )


def default_parser_jar(repo_root: Path) -> Path:
    """Resolve the default shaded AST-parser jar path."""
    return (
        repo_root
        / "tools"
        / "xpath-ast-parser"
        / "target"
        / "xpath-ast-parser-1.0.0-jar-with-dependencies.jar"
    ).resolve()


def build_parser_if_needed(repo_root: Path, parser_jar: Path, skip_build: bool) -> None:
    """Build the Java XPath AST parser when the jar is missing and builds are allowed."""
    # The parser is packaged as a shaded jar so the pipeline can run it without
    # separately managing Saxon/Jackson classpaths.
    if parser_jar.exists() and parser_jar.is_file():
        return
    if skip_build:
        raise FileNotFoundError(f"Parser jar not found: {parser_jar}")

    parser_project = (repo_root / "tools" / "xpath-ast-parser").resolve()
    run_command(["mvn", "clean", "package"], parser_project)

    if not parser_jar.exists():
        raise FileNotFoundError(
            f"Parser jar still not found after build: {parser_jar}")


def parse_xpath_file(
    repo_root: Path,
    java_exe: str,
    parser_jar: Path,
    input_jsonl: Path,
    output_jsonl: Path,
    force: bool,
) -> None:
    """Run the Java/Saxon parser on one XPath JSONL file."""
    if not force and file_has_content(output_jsonl):
        print(f"  Skip AST parse: {output_jsonl}")
        return

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            java_exe,
            "-jar",
            str(parser_jar),
            "--in",
            str(input_jsonl),
            "--out",
            str(output_jsonl),
        ],
        repo_root,
    )


def compute_similarity(
    repo_root: Path,
    python_exe: str,
    similarity_script: Path,
    llm_asts: Path,
    gt_asts: Path,
    catalog_path: Path,
    output_jsonl: Path,
    force: bool,
) -> None:
    """Run the Python structural-similarity computation on two AST JSONL files."""
    if not force and file_has_content(output_jsonl):
        print(f"  Skip similarity: {output_jsonl}")
        return

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            python_exe,
            str(similarity_script),
            "--llm-asts",
            str(llm_asts),
            "--ground-truth-asts",
            str(gt_asts),
            "--catalog-path",
            str(catalog_path),
            "--out",
            str(output_jsonl),
        ],
        repo_root,
    )


def process_pair(
    repo_root: Path,
    *,
    java_exe: str,
    python_exe: str,
    parser_jar: Path,
    similarity_script: Path,
    catalog_path: Path,
    llm_xpaths: Path,
    gt_xpaths: Path | None,
    gt_asts_source: Path | None,
    out_dir: Path,
    force: bool,
) -> None:
    """Run AST parsing and structural comparison for one LLM/GT XPath pair."""
    llm_asts = out_dir / "llm-xpath-asts.jsonl"
    similarity = out_dir / "structural-similarity.jsonl"

    # Ground-truth ASTs can be reused across many experiment runs, but generated
    # XPath files are parsed per run because they carry run metadata.
    parse_xpath_file(repo_root, java_exe, parser_jar,
                     llm_xpaths, llm_asts, force)
    if gt_asts_source is not None:
        gt_asts = gt_asts_source
    elif gt_xpaths is not None:
        gt_asts = out_dir / "gt-xpath-asts.jsonl"
        parse_xpath_file(repo_root, java_exe, parser_jar,
                         gt_xpaths, gt_asts, force)
    else:
        raise ValueError("Either gt_xpaths or gt_asts_source must be provided")
    compute_similarity(
        repo_root,
        python_exe,
        similarity_script,
        llm_asts,
        gt_asts,
        catalog_path,
        similarity,
        force,
    )


def find_generated_jsonl_files(experiment_root: Path) -> list[Path]:
    """Find every generated XPath JSONL produced by the experiment pipeline."""
    return sorted(experiment_root.rglob("generated.jsonl"))


def inferred_structural_dir(generated_jsonl: Path) -> Path:
    """Place structural-analysis artifacts next to generation/evaluation inside the run root."""
    # generated.jsonl lives under run_root/generation/<promptStyle>/, so two
    # parents up returns the run root.
    generation_dir = generated_jsonl.parent
    run_root = generation_dir.parent.parent
    return run_root / "structural"


def main() -> int:
    """Drive AST parsing and structural similarity computation for one file pair or a whole experiment tree."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--llm-xpaths", help="Single LLM-generated XPath JSONL input")
    parser.add_argument("--ground-truth-xpaths",
                        help="Ground-truth XPath JSONL input")
    parser.add_argument("--ground-truth-asts",
                        help="Precomputed ground-truth AST JSONL input")
    parser.add_argument(
        "--out-dir", help="Output directory for single-pair mode")
    parser.add_argument(
        "--experiment-root", help="Experiment root to scan for generation/**/generated.jsonl files")
    parser.add_argument(
        "--parser-jar", help="Path to the shaded Java AST parser jar")
    parser.add_argument("--similarity-script", default="scripts/analysis/compute-xpath-structural-similarity.py",
                        help="Path to the Python similarity script")
    parser.add_argument("--catalog-path", default="config/pmd-catalog.json",
                        help="PMD catalog JSON used for fallback rule-key mapping")
    parser.add_argument("--java-exe", default="java", help="Java executable")
    parser.add_argument(
        "--python-exe", default=sys.executable, help="Python executable")
    parser.add_argument("--skip-build", action="store_true",
                        help="Do not try to build the parser jar if it is missing")
    parser.add_argument("--force", action="store_true",
                        help="Re-run stages even if outputs already exist")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent.parent
    parser_jar = Path(args.parser_jar).resolve(
    ) if args.parser_jar else default_parser_jar(repo_root)
    similarity_script = (repo_root / args.similarity_script).resolve()
    catalog_path = (repo_root / args.catalog_path).resolve()

    build_parser_if_needed(repo_root, parser_jar, args.skip_build)

    if args.ground_truth_xpaths and args.ground_truth_asts:
        raise ValueError(
            "Use either --ground-truth-xpaths or --ground-truth-asts, not both")
    gt_xpaths_arg = Path(args.ground_truth_xpaths).resolve(
    ) if args.ground_truth_xpaths else None
    gt_asts_arg = Path(args.ground_truth_asts).resolve(
    ) if args.ground_truth_asts else None

    single_mode = bool(
        args.llm_xpaths or args.ground_truth_xpaths or args.out_dir)
    batch_mode = bool(args.experiment_root)

    # Keep the modes mutually exclusive so output layout is predictable.
    if single_mode and batch_mode:
        raise ValueError(
            "Use either single-pair mode (--llm-xpaths/--ground-truth-xpaths/--out-dir) or --experiment-root, not both")

    if single_mode:
        if not args.llm_xpaths or not args.out_dir:
            raise ValueError(
                "Single-pair mode requires --llm-xpaths and --out-dir")
        if gt_xpaths_arg is None and gt_asts_arg is None:
            raise ValueError(
                "Single-pair mode requires either --ground-truth-xpaths or --ground-truth-asts")

        process_pair(
            repo_root,
            java_exe=args.java_exe,
            python_exe=args.python_exe,
            parser_jar=parser_jar,
            similarity_script=similarity_script,
            catalog_path=catalog_path,
            llm_xpaths=Path(args.llm_xpaths).resolve(),
            gt_xpaths=gt_xpaths_arg,
            gt_asts_source=gt_asts_arg,
            out_dir=Path(args.out_dir).resolve(),
            force=args.force,
        )
        print(
            f"Structural analysis written under: {Path(args.out_dir).resolve()}")
        return 0

    if batch_mode:
        experiment_root = Path(args.experiment_root).resolve()
        generated_files = find_generated_jsonl_files(experiment_root)
        if not generated_files:
            raise FileNotFoundError(
                f"No generated.jsonl files found under {experiment_root}")
        if gt_xpaths_arg is None and gt_asts_arg is None:
            raise ValueError(
                "Batch mode requires either --ground-truth-xpaths or --ground-truth-asts")

        print(
            f"Found {len(generated_files)} generated JSONL file(s) under {experiment_root}")
        for index, generated_jsonl in enumerate(generated_files, start=1):
            structural_dir = inferred_structural_dir(generated_jsonl)
            print(f"[{index}/{len(generated_files)}] {generated_jsonl}")
            process_pair(
                repo_root,
                java_exe=args.java_exe,
                python_exe=args.python_exe,
                parser_jar=parser_jar,
                similarity_script=similarity_script,
                catalog_path=catalog_path,
                llm_xpaths=generated_jsonl,
                gt_xpaths=gt_xpaths_arg,
                gt_asts_source=gt_asts_arg,
                out_dir=structural_dir,
                force=args.force,
            )

        print(
            f"Structural analysis written under experiment root: {experiment_root}")
        return 0

    raise ValueError("Specify either single-pair mode or --experiment-root")


if __name__ == "__main__":
    raise SystemExit(main())
