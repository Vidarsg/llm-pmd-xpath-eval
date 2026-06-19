import argparse
from pathlib import Path


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def crop_box(size: tuple[int, int], bounds: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    width, height = size
    left, top, right, bottom = bounds
    return (
        int(width * left),
        int(height * top),
        int(width * right),
        int(height * bottom),
    )


MODEL_BOXES = {
    "operational": (0.00, 0.07, 0.50, 0.53),
    "behavioral": (0.45, 0.07, 1.00, 0.53),
    "failure": (0.00, 0.44, 0.50, 0.98),
}

TARGET_BOXES = {
    "behavioral_target": (0.00, 0.44, 0.50, 1.00),
    "behavioral_target_model": (0.44, 0.07, 1.00, 0.54),
    "target_failure": (0.44, 0.44, 1.00, 1.00),
}

STRUCTURAL_BOXES = {
    "parseable": (0.00, 0.08, 0.50, 0.55),
    "score_distribution": (0.44, 0.08, 1.00, 0.55),
    "components": (0.00, 0.44, 0.50, 1.00),
}

RULE_BOXES = {
    "rule_similarity": (0.00, 0.07, 0.50, 0.54),
    "category_similarity": (0.45, 0.07, 1.00, 0.54),
    "reference_only": (0.00, 0.47, 0.50, 1.00),
    "errors": (0.45, 0.47, 1.00, 1.00),
}


def export_from_overview(image, out_dir: Path, mapping: dict[str, tuple[float, float, float, float]], names: dict[str, str]) -> None:
    from PIL import ImageOps
    for key, bounds in mapping.items():
        out_name = names.get(key)
        if not out_name:
            continue
        out_path = out_dir / out_name
        ensure_parent(out_path)
        cropped = image.crop(crop_box(image.size, bounds))
        # Add a small white border so titles/labels near subplot edges are not
        # perceived as clipped when inserted.
        cropped = ImageOps.expand(cropped, border=18, fill="white")
        cropped.save(out_path)
        print(f"Wrote {out_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export cropped subfigures from overview PNGs."
    )
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()

    try:
        from PIL import Image
    except ImportError as exc:
        raise SystemExit(
            "This script requires Pillow. Install it with: python -m pip install pillow"
        ) from exc

    repo_root = Path(args.repo_root).resolve()
    analysis_root = repo_root / "out" / "analysis-summary"
    thesis_images = repo_root / "docs" / "thesis" / "Images"

    experiments = [
        ("Official-PMD_AllTargets_AllModels_Zero-Shot", "pmd", "zs"),
        ("Official-PMD_AllTargets_AllModels_Few-Shot", "pmd", "fs"),
        ("jPinpoint_AllTargets_AllModels_Zero-Shot", "jpp", "zs"),
        ("jPinpoint_AllTargets_AllModels_Few-Shot", "jpp", "fs"),
    ]

    for experiment, dataset, prompt in experiments:
        exp_dir = analysis_root / experiment

        model_image = Image.open(exp_dir / "model_level_overview.png")
        export_from_overview(
            model_image,
            thesis_images,
            MODEL_BOXES,
            {
                "operational": f"ov-{dataset}-{prompt}.png",
                "behavioral": f"bc-{dataset}-{prompt}.png",
                "failure": f"fm-{dataset}-{prompt}.png",
            },
        )

        target_image = Image.open(exp_dir / "target_level_overview.png")
        export_from_overview(
            target_image,
            thesis_images,
            TARGET_BOXES,
            {
                "behavioral_target": f"bct-{dataset}-{prompt}.png",
                "behavioral_target_model": f"bctm-{dataset}-{prompt}.png",
                "target_failure": f"tfp-{dataset}-{prompt}.png",
            },
        )

        structural_image = Image.open(
            exp_dir / "structural_similarity_overview.png")
        export_from_overview(
            structural_image,
            thesis_images,
            STRUCTURAL_BOXES,
            {
                "parseable": f"parsed-ast-{dataset}-{prompt}.png",
                "score_distribution": f"sc-{dataset}-{prompt}.png",
                "components": f"scomp-{dataset}-{'sz' if prompt == 'zs' and dataset == 'pmd' else prompt}.png",
            },
        )

        rule_image = Image.open(exp_dir / "rule_level_overview.png")
        rule_names = {
            "rule_similarity": f"rl-hbc-{dataset}-{prompt}.png" if dataset == "jpp" else f"rl-hbc-{prompt}.png",
            "errors": (
                f"ec-jpp-{'sz' if prompt == 'zs' else prompt}.png"
                if dataset == "jpp"
                else f"ec-{'sz' if prompt == 'zs' else prompt}.png"
            ),
        }
        if dataset == "pmd":
            rule_names["category_similarity"] = f"rlc-{'sz' if prompt == 'zs' else prompt}.png"
            rule_names["reference_only"] = f"pmdonly-{'sz' if prompt == 'zs' else prompt}.png"
        else:
            rule_names["reference_only"] = f"jpponly-{'sz' if prompt == 'zs' else prompt}.png"
        export_from_overview(rule_image, thesis_images, RULE_BOXES, rule_names)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
