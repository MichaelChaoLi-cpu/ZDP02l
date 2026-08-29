"""Rebuild the two Reviewer 1 / Comment 9 figures with terminology-only label changes.

Figure 5 is regenerated from the original model specification and processed data.
Figure 6 is regenerated from the existing validated map panel and the frozen
place-coefficient table.  No estimates, confidence intervals, place ordering,
dimensions, colours, or other labels are changed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.image import imread
import numpy as np
import pandas as pd
from PIL import Image
import statsmodels.formula.api as smf


ROOT = Path(__file__).resolve().parents[1]


def build_figure5(output: Path) -> dict:
    df = pd.read_parquet(ROOT / "data/processed/gfs_cleaned.parquet")
    rural = "rural_binary"
    weight = "ANNUAL_WEIGHT_C1"
    demo_controls = "AGE_Y1 + C(GENDER) + C(MARITAL_STATUS_Y1) + C(EMPLOYMENT_Y1)"
    country_fe = "C(COUNTRY)"
    outcomes = {
        "income_feelings_sec": "Income Feelings (security, 1–4)",
        "EXPENSES_Y1": "Expenses Worry (security, 0–10)",
        "income_pctile": "Income Percentile (within-place, 0–1)",
    }

    models = {}
    for variable, label in outcomes.items():
        columns = [
            variable,
            rural,
            "AGE_Y1",
            "GENDER",
            "MARITAL_STATUS_Y1",
            "EMPLOYMENT_Y1",
            "EDUCATION_3_Y1",
            "COUNTRY",
            weight,
        ]
        model_data = df[columns].dropna()
        formula = (
            f"{variable} ~ {rural} + {demo_controls} + "
            f"C(EDUCATION_3_Y1) + {country_fe}"
        )
        models[label] = smf.ols(formula, data=model_data).fit(cov_type="HC3")

    plt.rcParams.update(
        {
            "axes.grid": True,
            "grid.alpha": 0.35,
            "grid.linestyle": "--",
            "grid.color": "#aaaaaa",
            "axes.axisbelow": True,
        }
    )
    # The source file is 1755 px wide at 150 dpi under the project font stack.
    # This width preserves that exact export dimension with current Matplotlib.
    fig, axes = plt.subplots(1, 3, figsize=(12 + 12.5 / 150, 4))
    audit = []
    for ax, letter, (label, result) in zip(axes, "abc", models.items()):
        coefficient = float(result.params[rural])
        low, high = (float(x) for x in result.conf_int(alpha=0.05).loc[rural])
        ax.axhline(0, color="black", linewidth=0.8, linestyle="-")
        ax.errorbar(
            [0],
            [coefficient],
            yerr=[[coefficient - low], [high - coefficient]],
            fmt="o",
            color="#2c7bb6",
            capsize=5,
            linewidth=1.5,
            markersize=6,
            zorder=3,
        )
        ax.set_xticks([0])
        ax.set_xticklabels(["Full\nmodel"], rotation=20, ha="right", fontsize=9)
        ax.set_ylabel("Coefficient (Rural vs Urban)")
        ax.spines[["top", "right"]].set_visible(False)
        ax.text(
            0.03,
            0.97,
            f"{letter}: {label}",
            transform=ax.transAxes,
            va="top",
            ha="left",
            fontsize=9.5,
            fontweight="bold",
        )
        ax.set_xticks([])
        audit.append(
            {
                "label": label,
                "coefficient": coefficient,
                "ci_low": low,
                "ci_high": high,
                "n": int(result.nobs),
            }
        )

    plt.tight_layout()
    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return {"output": str(output), "values": audit}


def build_figure6(output: Path) -> dict:
    plt.rcParams.update(
        {
            "axes.grid": True,
            "grid.alpha": 0.35,
            "grid.linestyle": "--",
            "grid.color": "#aaaaaa",
            "axes.axisbelow": True,
            "figure.dpi": 150,
            "font.size": 10,
        }
    )
    coefficients = pd.read_csv(ROOT / "reports/tbl_country_rural_coef.csv")
    forest = coefficients.sort_values("Adj_coef").reset_index(drop=True)
    map_image = imread(ROOT / "reports/fig_map_adj_coef.png")

    fig, axes = plt.subplots(
        2,
        1,
        figsize=(9, 11),
        gridspec_kw={"height_ratios": [1, 1.6]},
    )
    axes[0].imshow(map_image)
    axes[0].axis("off")
    axes[0].text(
        0.03,
        0.97,
        "a: Adjusted rural coefficient (world map)",
        transform=axes[0].transAxes,
        va="top",
        ha="left",
        fontsize=9.5,
        fontweight="bold",
    )

    colours = ["#d62728" if value < 0 else "#1f77b4" for value in forest["Adj_coef"]]
    for index, row in forest.iterrows():
        axes[1].errorbar(
            row["Adj_coef"],
            index,
            xerr=[
                [row["Adj_coef"] - row["CI_lo"]],
                [row["CI_hi"] - row["Adj_coef"]],
            ],
            fmt="o",
            color=colours[index],
            markersize=5,
            elinewidth=1.1,
            capsize=3,
            capthick=1.1,
        )
    axes[1].axvline(0, color="black", linewidth=0.9, linestyle="--", alpha=0.7)
    axes[1].set_yticks(range(len(forest)))
    axes[1].set_yticklabels(forest["Country"], fontsize=8.5)
    axes[1].set_xlabel("Adjusted rural–urban coefficient (life satisfaction)", fontsize=9.5)
    axes[1].tick_params(axis="x", labelsize=9)
    axes[1].text(
        0.03,
        0.97,
        "b: Forest plot by place",
        transform=axes[1].transAxes,
        va="top",
        ha="left",
        fontsize=9.5,
        fontweight="bold",
    )

    plt.tight_layout(h_pad=1.5)
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return {
        "output": str(output),
        "place_order": forest["Country"].tolist(),
        "values": forest[["Country", "Adj_coef", "CI_lo", "CI_hi"]].to_dict("records"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    figure5 = args.output_dir / "fig_coef_econ_rural.png"
    figure6 = args.output_dir / "fig_country_composite.png"
    audit = {
        "figure5": build_figure5(figure5),
        "figure6": build_figure6(figure6),
    }
    audit["dimensions"] = {
        "figure5": Image.open(figure5).size,
        "figure6": Image.open(figure6).size,
    }
    (args.output_dir / "terminology_figure_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit["dimensions"], ensure_ascii=False))


if __name__ == "__main__":
    main()
