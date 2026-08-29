#!/usr/bin/env python3
"""Draw the sample-aligned Figure 7 candidate for Reviewer 1, Comment 7."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "reports/comment7_sample_alignment"
DEFAULT_OUTPUT = DEFAULT_INPUT_DIR / "figure7_candidate.png"
BLUE = "#2f7fb8"


def draw_panel(
    axis: plt.Axes,
    labels: list[str],
    estimates: np.ndarray,
    lows: np.ndarray,
    highs: np.ndarray,
    title: str,
) -> None:
    x = np.arange(len(labels))
    axis.errorbar(
        x,
        estimates,
        yerr=np.vstack([estimates - lows, highs - estimates]),
        fmt="o",
        color=BLUE,
        ecolor=BLUE,
        elinewidth=1.6,
        capsize=5,
        markersize=6.5,
    )
    axis.axhline(0, color="black", linewidth=0.9)
    axis.set_xticks(x, labels)
    axis.set_title(title, loc="left", fontsize=12, fontweight="bold")
    axis.grid(axis="y", color="#d7d7d7", linestyle="--", linewidth=0.8, alpha=0.8)
    axis.spines["top"].set_visible(False)
    axis.spines["right"].set_visible(False)
    axis.tick_params(axis="both", labelsize=9.5)
    axis.margins(x=0.08)


def plot(input_dir: Path, output_path: Path) -> None:
    outcomes = pd.read_csv(input_dir / "table5_alternative_outcomes.csv")
    outcomes = outcomes.loc[outcomes["term"].eq("rural_binary")].copy()
    outcome_order = ["LIFE_SAT_Y1", "HAPPY_Y1", "WB_TODAY_Y1"]
    outcomes["order"] = outcomes["outcome"].map(
        {name: index for index, name in enumerate(outcome_order)}
    )
    outcomes = outcomes.sort_values("order")

    residence = pd.read_csv(input_dir / "figure7_four_category_common.csv")
    residence_order = [1, 2, 4]
    residence["order"] = residence["residence_category"].map(
        {value: index for index, value in enumerate(residence_order)}
    )
    residence = residence.sort_values("order")

    weighted = pd.read_csv(input_dir / "table6_weighted_common.csv")
    weighted = weighted.loc[weighted["term"].eq("rural_binary")].copy()
    weighted["order"] = weighted["weighting"].map(
        {"unweighted": 0, "ANNUAL_WEIGHT_C1": 1}
    )
    weighted = weighted.sort_values("order")

    figure, axes = plt.subplots(1, 3, figsize=(13.5, 4.6), constrained_layout=True)
    draw_panel(
        axes[0],
        [
            f"Life satisfaction\nN={int(outcomes.iloc[0]['n']):,}",
            f"Happiness\nN={int(outcomes.iloc[1]['n']):,}",
            f"Wellbeing today\nN={int(outcomes.iloc[2]['n']):,}",
        ],
        outcomes["estimate"].to_numpy(),
        outcomes["cr2_satterthwaite_ci_low"].to_numpy(),
        outcomes["cr2_satterthwaite_ci_high"].to_numpy(),
        "a. Alternative outcomes",
    )
    draw_panel(
        axes[1],
        ["Rural area/farm\n(1)", "Small town/village\n(2)", "Suburb\n(4)"],
        residence["estimate"].to_numpy(),
        residence["cr2_satterthwaite_ci_low"].to_numpy(),
        residence["cr2_satterthwaite_ci_high"].to_numpy(),
        "b. Four-category residence (ref. large city)",
    )
    draw_panel(
        axes[2],
        ["Unweighted", "Survey weighted"],
        weighted["estimate"].to_numpy(),
        weighted["cr2_satterthwaite_ci_low"].to_numpy(),
        weighted["cr2_satterthwaite_ci_high"].to_numpy(),
        "c. Survey weights (common N=183,685)",
    )
    axes[0].set_ylabel("Adjusted residence coefficient", fontsize=10.5)
    for axis in axes:
        axis.set_ylim(-0.10, 0.18)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    plot(args.input_dir, args.output)
    print(args.output)


if __name__ == "__main__":
    main()
