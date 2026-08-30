#!/usr/bin/env python3
"""Compute unadjusted rural-urban life-satisfaction gaps for Reviewer 1 Comment 8.

The display uses all 23 analytical places on the locked common complete-case
sample. Survey-weighted rural and urban means and their raw difference are the
proposed descriptive display because they pair directly with the adjusted
survey-weighted place coefficients in Figure 6. Unweighted raw differences are
retained as a sensitivity and validation check; neither specification includes
covariates.
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

import numpy as np
import pandas as pd
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
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports/comment8_unadjusted_place_gaps"
FIGURE6_ESTIMATES = (
    PROJECT_ROOT
    / "reports/comment6_geographic_forest/place_estimates_by_un_m49_region.csv"
)
LEGACY_RAW_GAPS = PROJECT_ROOT / "reports/tbl_country_rural_coef.csv"
FORMULA = "LIFE_SAT_Y1 ~ rural_binary"
REGION_ORDER = ("Africa", "Americas", "Asia", "Europe", "Oceania")
M49_REGION_BY_CODE = {
    1: "Americas",
    2: "Oceania",
    3: "Americas",
    4: "Africa",
    5: "Europe",
    6: "Asia",
    7: "Asia",
    8: "Asia",
    9: "Asia",
    10: "Africa",
    11: "Americas",
    12: "Africa",
    13: "Asia",
    14: "Europe",
    16: "Africa",
    17: "Europe",
    18: "Africa",
    19: "Asia",
    20: "Europe",
    22: "Americas",
    23: "Europe",
    24: "Asia",
    25: "Asia",
}


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


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    return float(np.average(values.astype(float), weights=weights.astype(float)))


def fit_place_gaps(common: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    figure6 = pd.read_csv(FIGURE6_ESTIMATES)
    if len(figure6) != EXPECTED_PLACES or figure6["place_code"].nunique() != EXPECTED_PLACES:
        raise ValueError("Figure 6 ordering source does not contain 23 unique places")

    ordering = figure6[
        ["place_code", "un_m49_region", "region_order", "within_region_order"]
    ].copy()
    if set(ordering["place_code"].astype(int)) != set(crosswalk[PLACE].astype(int)):
        raise ValueError("Figure 6 ordering source does not match the place crosswalk")

    records: list[dict[str, Any]] = []
    for row in crosswalk.itertuples(index=False):
        code = int(getattr(row, PLACE))
        place_name = str(row.place_name)
        unit_type = str(row.unit_type)
        subset = common.loc[common[PLACE].eq(code)].copy()
        residence_counts = subset["rural_binary"].value_counts()
        if not {0, 1}.issubset(residence_counts.index):
            raise ValueError(f"No rural/urban variation for {place_name}")

        rural = subset.loc[subset["rural_binary"].eq(1)]
        urban = subset.loc[subset["rural_binary"].eq(0)]
        rural_weighted_mean = weighted_mean(rural["LIFE_SAT_Y1"], rural[WEIGHT])
        urban_weighted_mean = weighted_mean(urban["LIFE_SAT_Y1"], urban[WEIGHT])
        weighted_gap = rural_weighted_mean - urban_weighted_mean
        rural_unweighted_mean = float(rural["LIFE_SAT_Y1"].mean())
        urban_unweighted_mean = float(urban["LIFE_SAT_Y1"].mean())
        unweighted_gap = rural_unweighted_mean - urban_unweighted_mean

        weighted_model = smf.wls(
            FORMULA, data=subset, weights=subset[WEIGHT].astype(float)
        ).fit(cov_type="HC3")
        unweighted_model = smf.ols(FORMULA, data=subset).fit(cov_type="HC3")
        weighted_ci_low, weighted_ci_high = (
            float(value)
            for value in weighted_model.conf_int(alpha=0.05).loc["rural_binary"]
        )
        unweighted_ci_low, unweighted_ci_high = (
            float(value)
            for value in unweighted_model.conf_int(alpha=0.05).loc["rural_binary"]
        )

        if not np.isclose(weighted_model.params["rural_binary"], weighted_gap, atol=1e-10):
            raise ValueError(f"Weighted mean-difference identity failed for {place_name}")
        if not np.isclose(unweighted_model.params["rural_binary"], unweighted_gap, atol=1e-10):
            raise ValueError(f"Unweighted mean-difference identity failed for {place_name}")

        records.append(
            {
                "place_code": code,
                "place_name": place_name,
                "unit_type": unit_type,
                "un_m49_region": M49_REGION_BY_CODE[code],
                "n": int(len(subset)),
                "rural_n": int(residence_counts.loc[1]),
                "urban_n": int(residence_counts.loc[0]),
                "rural_weighted_mean": rural_weighted_mean,
                "urban_weighted_mean": urban_weighted_mean,
                "weighted_raw_gap": weighted_gap,
                "weighted_hc3_se": float(weighted_model.bse["rural_binary"]),
                "weighted_hc3_ci_low": weighted_ci_low,
                "weighted_hc3_ci_high": weighted_ci_high,
                "weighted_hc3_p_value": float(weighted_model.pvalues["rural_binary"]),
                "rural_unweighted_mean": rural_unweighted_mean,
                "urban_unweighted_mean": urban_unweighted_mean,
                "unweighted_raw_gap": unweighted_gap,
                "unweighted_hc3_se": float(unweighted_model.bse["rural_binary"]),
                "unweighted_hc3_ci_low": unweighted_ci_low,
                "unweighted_hc3_ci_high": unweighted_ci_high,
                "unweighted_hc3_p_value": float(unweighted_model.pvalues["rural_binary"]),
            }
        )

    estimates = pd.DataFrame.from_records(records).merge(
        ordering,
        on=["place_code", "un_m49_region"],
        how="left",
        validate="one_to_one",
    )
    estimates = estimates.sort_values(
        ["region_order", "within_region_order", "place_name"]
    ).reset_index(drop=True)
    ordered_columns = [
        "place_code",
        "place_name",
        "unit_type",
        "un_m49_region",
        "region_order",
        "within_region_order",
    ] + [column for column in estimates.columns if column not in {
        "place_code", "place_name", "unit_type", "un_m49_region",
        "region_order", "within_region_order"
    }]
    return estimates[ordered_columns]


def build_table(estimates: pd.DataFrame) -> pd.DataFrame:
    def interval(row: pd.Series) -> str:
        return (
            f"{row['weighted_raw_gap']:+.3f} "
            f"[{row['weighted_hc3_ci_low']:+.3f}, {row['weighted_hc3_ci_high']:+.3f}]"
        )

    return pd.DataFrame(
        {
            "UN M49 region": estimates["un_m49_region"],
            "Analytical place": estimates["place_name"],
            "Rural n": estimates["rural_n"],
            "Urban n": estimates["urban_n"],
            "Rural weighted mean": estimates["rural_weighted_mean"].map(lambda x: f"{x:.3f}"),
            "Urban weighted mean": estimates["urban_weighted_mean"].map(lambda x: f"{x:.3f}"),
            "Unadjusted difference, R-U [95% CI]": estimates.apply(interval, axis=1),
        }
    )


def summarize(estimates: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for region in REGION_ORDER:
        selected = estimates.loc[estimates["un_m49_region"].eq(region)]
        records.append(
            {
                "scope": region,
                "places": int(len(selected)),
                "positive_weighted_raw_gaps": int(selected["weighted_raw_gap"].gt(0).sum()),
                "negative_weighted_raw_gaps": int(selected["weighted_raw_gap"].lt(0).sum()),
                "minimum_weighted_raw_gap": float(selected["weighted_raw_gap"].min()),
                "maximum_weighted_raw_gap": float(selected["weighted_raw_gap"].max()),
                "weighted_unweighted_gap_pearson_r": float(
                    selected["weighted_raw_gap"].corr(selected["unweighted_raw_gap"])
                ) if len(selected) > 1 else np.nan,
            }
        )
    records.append(
        {
            "scope": "All places",
            "places": int(len(estimates)),
            "positive_weighted_raw_gaps": int(estimates["weighted_raw_gap"].gt(0).sum()),
            "negative_weighted_raw_gaps": int(estimates["weighted_raw_gap"].lt(0).sum()),
            "minimum_weighted_raw_gap": float(estimates["weighted_raw_gap"].min()),
            "maximum_weighted_raw_gap": float(estimates["weighted_raw_gap"].max()),
            "weighted_unweighted_gap_pearson_r": float(
                estimates["weighted_raw_gap"].corr(estimates["unweighted_raw_gap"])
            ),
        }
    )
    return pd.DataFrame.from_records(records)


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
    estimates = fit_place_gaps(common, crosswalk)
    table = build_table(estimates)
    summary = summarize(estimates)

    if len(estimates) != EXPECTED_PLACES:
        raise ValueError(f"Expected {EXPECTED_PLACES} places")
    if int(estimates["n"].sum()) != EXPECTED_COMMON_ROWS:
        raise ValueError("Place Ns do not sum to the locked common sample")
    if not estimates[["rural_n", "urban_n"]].gt(0).all().all():
        raise ValueError("At least one place lacks one residence category")
    numeric = estimates.select_dtypes(include=[np.number]).drop(columns=["region_order", "within_region_order"])
    if not np.isfinite(numeric.to_numpy()).all():
        raise ValueError("Non-finite estimate detected")
    if set(estimates["un_m49_region"]) != set(REGION_ORDER):
        raise ValueError("At least one expected UN M49 region is absent")

    estimates_path = output_dir / "place_unadjusted_life_satisfaction_gaps.csv"
    table_path = output_dir / "supplementary_table_s5.csv"
    summary_path = output_dir / "region_descriptive_summary.csv"
    manifest_path = output_dir / "run_manifest.json"
    atomic_csv(estimates, estimates_path)
    atomic_csv(table, table_path)
    atomic_csv(summary, summary_path)

    legacy = pd.read_csv(LEGACY_RAW_GAPS)
    legacy_comparison = legacy.merge(
        estimates,
        left_on="Country",
        right_on="place_name",
        validate="one_to_one",
    )
    if len(legacy_comparison) != 22:
        raise ValueError("Unexpected overlap with legacy 22-place raw-gap output")

    all_summary = summary.loc[summary["scope"].eq("All places")].iloc[0]
    manifest = {
        "status": "validated_reviewer_1_comment_8_unadjusted_place_gaps",
        "proposed_display": {
            "type": "supplementary table",
            "sample": "locked common complete-case sample",
            "n": int(estimates["n"].sum()),
            "places": int(len(estimates)),
            "descriptive_estimand": "survey-weighted rural mean minus survey-weighted urban mean",
            "uncertainty": "HC3 95% confidence interval from survey-weighted OLS with residence as the only predictor",
            "covariates": "none",
            "ordering": "same UN M49 regions and within-region place order as Figure 6",
        },
        "checks": {
            "all_23_crosswalk_places_present": len(estimates) == EXPECTED_PLACES,
            "china_present": bool(estimates["place_name"].eq("China").any()),
            "hong_kong_retained_as_region": bool(
                estimates.loc[estimates["place_name"].eq("Hong Kong"), "unit_type"].eq("region").all()
            ),
            "both_residence_categories_each_place": bool(
                estimates[["rural_n", "urban_n"]].gt(0).all().all()
            ),
            "common_n_matches_locked_value": int(estimates["n"].sum()) == EXPECTED_COMMON_ROWS,
            "weighted_gap_equals_wls_binary_coefficient": True,
            "unweighted_gap_equals_ols_binary_coefficient": True,
        },
        "descriptive_summary": {
            "positive_weighted_raw_gaps": int(all_summary["positive_weighted_raw_gaps"]),
            "negative_weighted_raw_gaps": int(all_summary["negative_weighted_raw_gaps"]),
            "minimum_weighted_raw_gap": float(all_summary["minimum_weighted_raw_gap"]),
            "maximum_weighted_raw_gap": float(all_summary["maximum_weighted_raw_gap"]),
            "weighted_unweighted_gap_pearson_r": float(all_summary["weighted_unweighted_gap_pearson_r"]),
        },
        "legacy_comparison": {
            "legacy_places": int(len(legacy)),
            "overlapping_places": int(len(legacy_comparison)),
            "revised_only_places": sorted(set(estimates["place_name"]) - set(legacy["Country"])),
            "legacy_raw_gap_vs_recomputed_weighted_gap_pearson_r": float(
                legacy_comparison["Raw_gap"].corr(legacy_comparison["weighted_raw_gap"])
            ),
            "reason_for_recomputation": "Legacy output contains 22 places and omits China.",
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
        },
        "inputs": {
            "processed_data_sha256": sha256(DEFAULT_DATA),
            "place_crosswalk_sha256": sha256(DEFAULT_CROSSWALK),
            "figure6_ordering_sha256": file_sha256(FIGURE6_ESTIMATES),
            "legacy_raw_gap_sha256": file_sha256(LEGACY_RAW_GAPS),
            "script_sha256": file_sha256(SCRIPT_PATH),
        },
        "outputs": {
            estimates_path.name: file_sha256(estimates_path),
            table_path.name: file_sha256(table_path),
            summary_path.name: file_sha256(summary_path),
        },
    }
    atomic_json(manifest, manifest_path)
    print(json.dumps({
        "output_dir": str(output_dir),
        "n": int(estimates["n"].sum()),
        "places": int(len(estimates)),
        "positive_weighted_raw_gaps": int(all_summary["positive_weighted_raw_gaps"]),
        "negative_weighted_raw_gaps": int(all_summary["negative_weighted_raw_gaps"]),
        "weighted_raw_gap_range": [
            float(all_summary["minimum_weighted_raw_gap"]),
            float(all_summary["maximum_weighted_raw_gap"]),
        ],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
