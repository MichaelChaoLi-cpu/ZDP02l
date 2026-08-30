#!/usr/bin/env python3
"""Build the Reviewer 2 Comment 6 grouped place-level forest-plot candidate.

The manuscript's pooled unweighted OLS model remains primary.  This script
re-estimates the already described survey-weighted, place-stratified OLS
display on the locked common complete-case sample and groups all 23 analytical
places by the United Nations M49 continental region.  Region membership is a
predefined display device, not a tested moderator or a cultural mechanism.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import tempfile
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image
import scipy
import statsmodels
import statsmodels.formula.api as smf

from run_batch_a_core_path import (
    DEFAULT_CROSSWALK,
    DEFAULT_DATA,
    EXPECTED_COMMON_ROWS,
    EXPECTED_PLACES,
    PLACE,
    WEIGHT,
    build_common_sample,
    load_and_validate_source,
    sha256,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports/comment6_geographic_forest"
LEGACY_FIGURE_TABLE = PROJECT_ROOT / "reports/tbl_country_rural_coef.csv"
M49_SOURCE_URL = "https://unstats.un.org/unsd/methodology/m49/overview/"
M49_ACCESS_DATE = "2026-08-30"
REGION_ORDER = ("Africa", "Americas", "Asia", "Europe", "Oceania")
M49_REGION_BY_CODE = {
    1: "Americas",       # Argentina
    2: "Oceania",       # Australia
    3: "Americas",       # Brazil
    4: "Africa",         # Egypt
    5: "Europe",         # Germany
    6: "Asia",           # India
    7: "Asia",           # Indonesia
    8: "Asia",           # Israel
    9: "Asia",           # Japan
    10: "Africa",        # Kenya
    11: "Americas",      # Mexico
    12: "Africa",        # Nigeria
    13: "Asia",          # Philippines
    14: "Europe",        # Poland
    16: "Africa",        # South Africa
    17: "Europe",        # Spain
    18: "Africa",        # Tanzania
    19: "Asia",          # Turkey
    20: "Europe",        # United Kingdom
    22: "Americas",      # United States
    23: "Europe",        # Sweden
    24: "Asia",          # Hong Kong (region)
    25: "Asia",          # China
}
FORMULA = (
    "LIFE_SAT_Y1 ~ rural_binary + AGE_Y1 + C(GENDER) + "
    "C(MARITAL_STATUS_Y1) + C(EMPLOYMENT_Y1) + C(EDUCATION_3_Y1)"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(handle)
    temporary_path = Path(temporary)
    try:
        frame.to_csv(temporary_path, index=False)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def atomic_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(handle)
    temporary_path = Path(temporary)
    try:
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def fit_place_estimates(common: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    expected_codes = set(int(code) for code in crosswalk[PLACE])
    if expected_codes != set(M49_REGION_BY_CODE):
        raise ValueError("The UN M49 region map does not match the validated crosswalk")

    records: list[dict[str, Any]] = []
    for row in crosswalk.itertuples(index=False):
        code = int(getattr(row, PLACE))
        place_name = str(row.place_name)
        unit_type = str(row.unit_type)
        subset = common.loc[common[PLACE].eq(code)].copy()
        if subset.empty:
            raise ValueError(f"No locked-common-sample rows for {place_name}")
        residence_counts = subset["rural_binary"].value_counts()
        if not {0, 1}.issubset(residence_counts.index):
            raise ValueError(f"No rural/urban variation for {place_name}")
        model = smf.wls(
            FORMULA,
            data=subset,
            weights=subset[WEIGHT].astype(float),
        ).fit(cov_type="HC3")
        estimate = float(model.params["rural_binary"])
        standard_error = float(model.bse["rural_binary"])
        ci_low, ci_high = (
            float(value) for value in model.conf_int(alpha=0.05).loc["rural_binary"]
        )
        records.append(
            {
                "place_code": code,
                "place_name": place_name,
                "unit_type": unit_type,
                "un_m49_region": M49_REGION_BY_CODE[code],
                "n": int(model.nobs),
                "rural_n": int(residence_counts.loc[1]),
                "urban_n": int(residence_counts.loc[0]),
                "estimate": estimate,
                "std_error_hc3": standard_error,
                "ci_low_hc3": ci_low,
                "ci_high_hc3": ci_high,
                "p_value_hc3": float(model.pvalues["rural_binary"]),
            }
        )

    estimates = pd.DataFrame.from_records(records)
    region_rank = {region: rank for rank, region in enumerate(REGION_ORDER)}
    estimates["region_order"] = estimates["un_m49_region"].map(region_rank)
    estimates = estimates.sort_values(
        ["region_order", "estimate", "place_name"],
        ascending=[True, False, True],
    ).reset_index(drop=True)
    estimates["within_region_order"] = estimates.groupby(
        "un_m49_region", sort=False
    ).cumcount() + 1
    return estimates[
        [
            "place_code",
            "place_name",
            "unit_type",
            "un_m49_region",
            "region_order",
            "within_region_order",
            "n",
            "rural_n",
            "urban_n",
            "estimate",
            "std_error_hc3",
            "ci_low_hc3",
            "ci_high_hc3",
            "p_value_hc3",
        ]
    ]


def summarize_regions(estimates: pd.DataFrame) -> pd.DataFrame:
    summaries: list[dict[str, Any]] = []
    for region in REGION_ORDER:
        selected = estimates.loc[estimates["un_m49_region"].eq(region)]
        summaries.append(
            {
                "un_m49_region": region,
                "places": int(len(selected)),
                "positive_point_estimates": int(selected["estimate"].gt(0).sum()),
                "negative_point_estimates": int(selected["estimate"].lt(0).sum()),
                "minimum_estimate": float(selected["estimate"].min()),
                "maximum_estimate": float(selected["estimate"].max()),
                "unweighted_mean_estimate": float(selected["estimate"].mean()),
            }
        )
    return pd.DataFrame.from_records(summaries)


def build_figure(estimates: pd.DataFrame, output: Path) -> None:
    plt.rcParams.update(
        {
            "axes.grid": True,
            "grid.alpha": 0.35,
            "grid.linestyle": "--",
            "grid.color": "#aaaaaa",
            "axes.axisbelow": True,
            "figure.facecolor": "white",
            "font.size": 10,
        }
    )
    figure, axis = plt.subplots(figsize=(9.0, 10.8))

    low = float(estimates["ci_low_hc3"].min())
    high = float(estimates["ci_high_hc3"].max())
    x_min = np.floor((low - 0.04) * 10.0) / 10.0
    x_max = np.ceil((high + 0.04) * 10.0) / 10.0
    span = x_max - x_min

    point_rows: list[tuple[float, pd.Series]] = []
    group_bands: list[tuple[str, float, float, float]] = []
    cursor = 0.0
    for region_index, region in enumerate(REGION_ORDER):
        selected = estimates.loc[estimates["un_m49_region"].eq(region)]
        header_y = cursor
        cursor += 0.78
        first_point = cursor
        for _, row in selected.iterrows():
            point_rows.append((cursor, row))
            cursor += 1.0
        last_point = cursor - 1.0
        group_bands.append((region, header_y, first_point - 0.38, last_point + 0.48))
        cursor += 0.42 if region_index < len(REGION_ORDER) - 1 else 0.0

    for region_index, (region, header_y, band_start, band_end) in enumerate(group_bands):
        if region_index % 2 == 0:
            axis.axhspan(band_start, band_end, color="#f5f7fa", zorder=0)
        axis.text(
            x_min + 0.012 * span,
            header_y,
            region,
            va="center",
            ha="left",
            fontsize=10.2,
            fontweight="bold",
            color="#333333",
        )

    y_positions: list[float] = []
    y_labels: list[str] = []
    for y_position, row in point_rows:
        estimate = float(row["estimate"])
        colour = "#d62728" if estimate < 0 else "#1f77b4"
        axis.errorbar(
            estimate,
            y_position,
            xerr=[
                [estimate - float(row["ci_low_hc3"])],
                [float(row["ci_high_hc3"]) - estimate],
            ],
            fmt="o",
            color=colour,
            markersize=5.2,
            elinewidth=1.15,
            capsize=3,
            capthick=1.1,
            zorder=3,
        )
        y_positions.append(y_position)
        y_labels.append(str(row["place_name"]))

    axis.axvline(0, color="black", linewidth=0.9, linestyle="--", alpha=0.72)
    axis.set_yticks(y_positions)
    axis.set_yticklabels(y_labels, fontsize=8.8)
    axis.set_xlim(x_min, x_max)
    axis.set_ylim(cursor + 0.65, -0.55)
    axis.set_xlabel(
        "Adjusted rural–urban coefficient (life satisfaction)", fontsize=9.7
    )
    axis.tick_params(axis="x", labelsize=9)
    axis.spines[["top", "right"]].set_visible(False)
    axis.set_title(
        "Place-level rural–urban coefficients grouped by UN M49 region",
        loc="left",
        fontsize=11.2,
        fontweight="bold",
        pad=12,
    )
    figure.subplots_adjust(left=0.25, right=0.98, top=0.955, bottom=0.055)

    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".png", dir=output.parent
    )
    os.close(handle)
    temporary_path = Path(temporary)
    try:
        figure.savefig(temporary_path, dpi=180, facecolor="white")
        plt.close(figure)
        os.replace(temporary_path, output)
    finally:
        temporary_path.unlink(missing_ok=True)
        plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    frame, crosswalk, source_audit = load_and_validate_source(
        DEFAULT_DATA, DEFAULT_CROSSWALK
    )
    common, place_audit, sample_audit = build_common_sample(frame)
    estimates = fit_place_estimates(common, crosswalk)
    summaries = summarize_regions(estimates)

    if len(estimates) != EXPECTED_PLACES:
        raise ValueError(f"Expected {EXPECTED_PLACES} place estimates")
    if int(estimates["n"].sum()) != EXPECTED_COMMON_ROWS:
        raise ValueError("Place-specific Ns do not sum to the locked common sample")
    if estimates["place_code"].nunique() != EXPECTED_PLACES:
        raise ValueError("Place codes are not unique")
    if estimates.isna().any().any() or not np.isfinite(
        estimates.select_dtypes(include=[np.number]).to_numpy()
    ).all():
        raise ValueError("Non-finite place-level result")
    if set(estimates["un_m49_region"]) != set(REGION_ORDER):
        raise ValueError("At least one expected UN M49 region is absent")

    estimates_path = output_dir / "place_estimates_by_un_m49_region.csv"
    summaries_path = output_dir / "region_descriptive_summary.csv"
    figure_path = output_dir / "figure6_grouped_candidate.png"
    manifest_path = output_dir / "run_manifest.json"
    atomic_csv(estimates, estimates_path)
    atomic_csv(summaries, summaries_path)
    build_figure(estimates, figure_path)

    legacy = pd.read_csv(LEGACY_FIGURE_TABLE)
    legacy_comparison = legacy.merge(
        estimates,
        left_on="Country",
        right_on="place_name",
        validate="one_to_one",
    )
    legacy_only = sorted(set(legacy["Country"]) - set(estimates["place_name"]))
    revised_only = sorted(set(estimates["place_name"]) - set(legacy["Country"]))
    if len(legacy_comparison) != 22 or legacy_only or revised_only != ["China"]:
        raise ValueError("Unexpected legacy Figure 6 place-roster comparison")

    manifest = {
        "status": "validated_reviewer_2_comment_6_grouped_display_candidate",
        "primary_model_unchanged": True,
        "display_model": {
            "estimator": "survey-weighted place-stratified OLS",
            "formula": FORMULA,
            "uncertainty": "HC3 95% confidence intervals",
            "sample": "locked common complete-case sample",
            "n": int(estimates["n"].sum()),
            "places": int(len(estimates)),
        },
        "grouping": {
            "scheme": "UN M49 continental geographic regions",
            "source_url": M49_SOURCE_URL,
            "access_date": M49_ACCESS_DATE,
            "region_order": list(REGION_ORDER),
            "within_region_order": "descending adjusted rural-residence coefficient",
            "interpretation_boundary": (
                "Descriptive display only; region is not modeled as a moderator and "
                "does not identify a historical or cultural mechanism."
            ),
        },
        "checks": {
            "all_23_crosswalk_places_present": len(estimates) == EXPECTED_PLACES,
            "china_present": bool(estimates["place_name"].eq("China").any()),
            "hong_kong_retained_as_region": bool(
                estimates.loc[estimates["place_name"].eq("Hong Kong"), "unit_type"]
                .eq("region")
                .all()
            ),
            "both_residence_categories_each_place": bool(
                estimates[["rural_n", "urban_n"]].gt(0).all().all()
            ),
            "common_n_matches_locked_value": int(estimates["n"].sum())
            == EXPECTED_COMMON_ROWS,
            "figure_dimensions": list(Image.open(figure_path).size),
        },
        "legacy_figure_comparison": {
            "legacy_places": int(len(legacy)),
            "revised_places": int(len(estimates)),
            "overlapping_places": int(len(legacy_comparison)),
            "legacy_only_places": legacy_only,
            "revised_only_places": revised_only,
            "estimate_pearson_r": float(
                legacy_comparison["Adj_coef"].corr(legacy_comparison["estimate"])
            ),
            "median_absolute_estimate_difference": float(
                (
                    legacy_comparison["Adj_coef"]
                    - legacy_comparison["estimate"]
                )
                .abs()
                .median()
            ),
            "reason_for_reestimation": (
                "The legacy display source has 22 places and omits China; the revised "
                "display uses all 23 places on the locked common sample described in "
                "the live manuscript."
            ),
        },
        "source_audit": source_audit,
        "sample_audit": sample_audit,
        "place_audit_rows": int(len(place_audit)),
        "software": {
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "statsmodels": statsmodels.__version__,
            "matplotlib": matplotlib.__version__,
        },
        "inputs": {
            "processed_data_sha256": sha256(DEFAULT_DATA),
            "place_crosswalk_sha256": sha256(DEFAULT_CROSSWALK),
            "legacy_figure_table_sha256": file_sha256(LEGACY_FIGURE_TABLE),
            "script_sha256": file_sha256(SCRIPT_PATH),
        },
        "outputs": {
            estimates_path.name: file_sha256(estimates_path),
            summaries_path.name: file_sha256(summaries_path),
            figure_path.name: file_sha256(figure_path),
        },
    }
    atomic_json(manifest, manifest_path)
    print(json.dumps({
        "output_dir": str(output_dir),
        "n": int(estimates["n"].sum()),
        "places": int(len(estimates)),
        "figure_dimensions": list(Image.open(figure_path).size),
        "estimate_range": [
            float(estimates["estimate"].min()),
            float(estimates["estimate"].max()),
        ],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
