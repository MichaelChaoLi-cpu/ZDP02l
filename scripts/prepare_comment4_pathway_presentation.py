#!/usr/bin/env python3
"""Prepare the symmetric first-stage pathway display for Reviewer 1, Comment 4.

The script does not modify any manuscript DOCX. It reuses the validated locked
common-sample equations, independently recomputes the Social Capital Index
first-stage fit through the Comment 7 absorbed-FE helper, verifies it against
the Batch A focal path output, and writes a four-outcome table plus a Figure 5
candidate in the manuscript's established coefficient-plot style.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from PIL import Image

import run_batch_a_core_path as core
import run_comment7_sample_alignment as sample_alignment


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports/comment4_parallel_path_presentation"
COMMENT7_TABLE3 = (
    PROJECT_ROOT / "reports/comment7_sample_alignment/table3_common_sample.csv"
)
BATCH_A_FOCAL = PROJECT_ROOT / "reports/batch_a_core/focal_paths.csv"

DISPLAY_LABELS = {
    "income_feelings_sec": "Income Security Feelings",
    "EXPENSES_Y1": "Expense Worry",
    "income_pctile": "Within-Place Income Percentile",
    "social_capital_within_place": "Social Capital Index",
}

PANEL_LABELS = {
    "income_feelings_sec": "Income Security Feelings\n(security, 1–4)",
    "EXPENSES_Y1": "Expense Worry\n(security, 0–10)",
    "income_pctile": "Within-Place Income Percentile\n(0–1)",
    "social_capital_within_place": "Social Capital Index\n(within-place standardized)",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_table() -> tuple[pd.DataFrame, dict[str, float]]:
    table = pd.read_csv(COMMENT7_TABLE3)
    expected_economic = ["income_feelings_sec", "EXPENSES_Y1", "income_pctile"]
    if table["outcome"].tolist() != expected_economic:
        raise ValueError("Comment 7 Table 3 outcomes are not in the expected order")

    source, _, _ = core.load_and_validate_source(
        core.DEFAULT_DATA, core.DEFAULT_CROSSWALK
    )
    common, _, _ = core.build_common_sample(source)
    social_fit = sample_alignment.fit_absorbed_model(
        common,
        "social_capital_within_place",
        sample_alignment.BASE_CONTINUOUS,
        core.CATEGORICAL_CONTROLS,
    )
    social_row = sample_alignment.coefficient_record(
        social_fit,
        core.EXPOSURE,
        outcome="social_capital_within_place",
        outcome_label="Social Capital Index",
        sample_policy="locked_common_complete_case",
        weighting="unweighted",
    )
    table = pd.concat([table, pd.DataFrame([social_row])], ignore_index=True)
    table["outcome_label"] = table["outcome"].map(DISPLAY_LABELS)

    focal = pd.read_csv(BATCH_A_FOCAL)
    focal = focal.loc[
        focal["term"].eq(core.EXPOSURE)
        & focal["equation"].str.startswith("mediator_")
    ].reset_index(drop=True)
    if len(focal) != 4:
        raise ValueError("Expected four Batch A first-stage focal coefficients")
    batch_social = focal.loc[
        focal["dependent_variable"].eq("social_capital_within_place")
    ].iloc[0]
    checks = {
        "social_estimate_absolute_difference_from_batch_a": abs(
            float(social_row["estimate"]) - float(batch_social["estimate"])
        ),
        "social_ci_low_absolute_difference_from_batch_a": abs(
            float(social_row["cr2_satterthwaite_ci_low"])
            - float(batch_social["cr2_satterthwaite_ci_low"])
        ),
        "social_ci_high_absolute_difference_from_batch_a": abs(
            float(social_row["cr2_satterthwaite_ci_high"])
            - float(batch_social["cr2_satterthwaite_ci_high"])
        ),
    }
    if max(checks.values()) > 1e-10:
        raise ValueError(f"Social Capital cross-check failed: {checks}")
    if set(table["n"].astype(int)) != {core.EXPECTED_COMMON_ROWS}:
        raise ValueError("All four first-stage equations must use the locked common N")
    if set(table["clusters"].astype(int)) != {core.EXPECTED_PLACES}:
        raise ValueError("All four first-stage equations must retain 23 places")
    return table, checks


def build_figure(table: pd.DataFrame, output: Path) -> None:
    plt.rcParams.update(
        {
            "axes.grid": True,
            "grid.alpha": 0.35,
            "grid.linestyle": "--",
            "grid.color": "#aaaaaa",
            "axes.axisbelow": True,
        }
    )
    fig, axes = plt.subplots(2, 2, figsize=(12, 7.5))
    for ax, letter, (_, row) in zip(axes.flat, "abcd", table.iterrows()):
        estimate = float(row["estimate"])
        low = float(row["cr2_satterthwaite_ci_low"])
        high = float(row["cr2_satterthwaite_ci_high"])
        ax.axhline(0, color="black", linewidth=0.8, linestyle="-")
        ax.errorbar(
            [0],
            [estimate],
            yerr=[[estimate - low], [high - estimate]],
            fmt="o",
            color="#2c7bb6",
            capsize=5,
            linewidth=1.5,
            markersize=6,
            zorder=3,
        )
        ax.set_xticks([])
        ax.set_ylabel("Coefficient (Rural vs Urban)")
        ax.spines[["top", "right"]].set_visible(False)
        ax.text(
            0.03,
            0.97,
            f"{letter}: {PANEL_LABELS[row['outcome']]}",
            transform=ax.transAxes,
            va="top",
            ha="left",
            fontsize=10,
            fontweight="bold",
        )
        padding = max(0.008, (high - low) * 0.18)
        ax.set_ylim(min(low - padding, -padding), max(high + padding, padding))

    plt.tight_layout()
    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    table, checks = build_table()
    table_path = args.output_dir / "table3_pathway_outcomes.csv"
    figure_path = args.output_dir / "figure5_candidate.png"
    table.to_csv(table_path, index=False)
    build_figure(table, figure_path)

    dimensions = Image.open(figure_path).size
    manifest = {
        "purpose": "Reviewer 1 Comment 4 symmetric first-stage pathway presentation",
        "manuscript_modified": False,
        "estimator": (
            "OLS with absorbed place fixed effects and place-clustered "
            "CR2/Satterthwaite inference"
        ),
        "sample_n": int(table["n"].iloc[0]),
        "place_clusters": int(table["clusters"].iloc[0]),
        "outcomes": table["outcome_label"].tolist(),
        "cross_checks": checks,
        "inputs": {
            str(COMMENT7_TABLE3.relative_to(PROJECT_ROOT)): sha256(COMMENT7_TABLE3),
            str(BATCH_A_FOCAL.relative_to(PROJECT_ROOT)): sha256(BATCH_A_FOCAL),
            str(core.DEFAULT_DATA.relative_to(PROJECT_ROOT)): sha256(core.DEFAULT_DATA),
        },
        "outputs": {
            table_path.name: {"sha256": sha256(table_path)},
            figure_path.name: {
                "sha256": sha256(figure_path),
                "dimensions": list(dimensions),
            },
        },
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
