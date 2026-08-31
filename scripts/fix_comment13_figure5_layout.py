#!/usr/bin/env python3
"""Prepare a Figure 5 layout correction for Reviewer 1, Comment 13.

The script reuses the validated four-outcome table from Reviewer 1, Comment 4,
keeps every estimate and confidence interval unchanged, and moves each panel
subtitle above the plotting area so that the zero reference line cannot cross
the subtitle. It does not modify any manuscript DOCX.
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


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    PROJECT_ROOT
    / "reports/comment4_parallel_path_presentation/table3_pathway_outcomes.csv"
)
PRIOR_FIGURE = (
    PROJECT_ROOT
    / "reports/comment4_parallel_path_presentation/figure5_candidate.png"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports/comment13_figure5_layout"

EXPECTED_OUTCOMES = [
    "income_feelings_sec",
    "EXPENSES_Y1",
    "income_pctile",
    "social_capital_within_place",
]

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


def load_and_validate_table(path: Path) -> pd.DataFrame:
    table = pd.read_csv(path)
    required = {
        "outcome",
        "estimate",
        "cr2_satterthwaite_ci_low",
        "cr2_satterthwaite_ci_high",
        "n",
        "clusters",
    }
    missing = required.difference(table.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
    if table["outcome"].tolist() != EXPECTED_OUTCOMES:
        raise ValueError("Figure 5 outcomes or order differ from the validated table")
    if table["n"].astype(int).tolist() != [183685] * 4:
        raise ValueError("Figure 5 no longer uses the locked common sample")
    if table["clusters"].astype(int).tolist() != [23] * 4:
        raise ValueError("Figure 5 no longer retains all 23 analytical places")
    if not (
        table["cr2_satterthwaite_ci_low"]
        .le(table["estimate"])
        .all()
        and table["estimate"]
        .le(table["cr2_satterthwaite_ci_high"])
        .all()
    ):
        raise ValueError("At least one point estimate falls outside its interval")
    return table


def build_figure(table: pd.DataFrame, output: Path) -> dict[str, object]:
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
    titles = []
    zero_lines = []
    for ax, letter, (_, row) in zip(axes.flat, "abcd", table.iterrows()):
        estimate = float(row["estimate"])
        low = float(row["cr2_satterthwaite_ci_low"])
        high = float(row["cr2_satterthwaite_ci_high"])
        zero_line = ax.axhline(0, color="black", linewidth=0.8, linestyle="-")
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
        title = ax.set_title(
            f"{letter}: {PANEL_LABELS[row['outcome']]}",
            loc="left",
            pad=8,
            fontsize=10,
            fontweight="bold",
        )
        padding = max(0.008, (high - low) * 0.18)
        ax.set_ylim(min(low - padding, -padding), max(high + padding, padding))
        titles.append(title)
        zero_lines.append(zero_line)

    fig.tight_layout(h_pad=2.4, w_pad=1.6)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    gaps = []
    for ax, title, _zero_line in zip(axes.flat, titles, zero_lines):
        title_box = title.get_window_extent(renderer=renderer)
        zero_y = ax.transData.transform((0, 0))[1]
        gaps.append(float(title_box.y0 - zero_y))
    if min(gaps) <= 0:
        raise ValueError(f"A zero reference line still intersects a subtitle: {gaps}")

    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return {
        "title_reference_line_gaps_pixels": gaps,
        "minimum_title_reference_line_gap_pixels": min(gaps),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    table = load_and_validate_table(args.input)
    output = args.output_dir / "figure5_layout_corrected.png"
    layout_checks = build_figure(table, output)
    dimensions = Image.open(output).size
    manifest = {
        "purpose": "Reviewer 1 Comment 13 Figure 5 reference-line correction",
        "manuscript_modified": False,
        "change_scope": (
            "Panel subtitles moved above the plotting areas; estimates, "
            "confidence intervals, panel order, labels, and plot style unchanged."
        ),
        "sample_n": int(table["n"].iloc[0]),
        "place_clusters": int(table["clusters"].iloc[0]),
        "input": {
            str(args.input.relative_to(PROJECT_ROOT)): sha256(args.input),
            str(PRIOR_FIGURE.relative_to(PROJECT_ROOT)): sha256(PRIOR_FIGURE),
        },
        "checks": {
            "outcome_order_unchanged": table["outcome"].tolist()
            == EXPECTED_OUTCOMES,
            "estimates_and_intervals_reused_without_transformation": True,
            **layout_checks,
        },
        "output": {
            output.name: {
                "sha256": sha256(output),
                "dimensions": list(dimensions),
            }
        },
    }
    manifest_path = args.output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
