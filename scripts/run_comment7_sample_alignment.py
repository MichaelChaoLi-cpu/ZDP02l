#!/usr/bin/env python3
"""Reconcile analysis denominators for Reviewer 1, Comment 7.

This bounded audit reuses the validated Batch A data checks and CR2 estimator.
It does not modify manuscript files. With ``--apply`` it writes only auditable
CSV/JSON outputs under ``reports/comment7_sample_alignment``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import run_batch_a_core_path as core


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports/comment7_sample_alignment"
ALT_OUTCOMES = ("HAPPY_Y1", "WB_TODAY_Y1")
OUTCOME_LABELS = {
    core.OUTCOME: "Life Satisfaction",
    "HAPPY_Y1": "Happiness",
    "WB_TODAY_Y1": "Wellbeing Today",
}
FULL_CONTINUOUS = [
    core.EXPOSURE,
    "AGE_Y1",
    "income_feelings_sec",
    "EXPENSES_Y1",
    "income_pctile",
    "social_capital_within_place",
]
BASE_CONTINUOUS = [core.EXPOSURE, "AGE_Y1"]
ANALYSIS_PREDICTOR_COLUMNS = (
    core.EXPOSURE,
    "income_feelings_sec",
    "EXPENSES_Y1",
    "income_pctile",
    "PEOPLE_HELP_Y1",
    "close_to_bin",
    "TRUST_PEOPLE_Y1",
    "AGE_Y1",
    *core.CATEGORICAL_CONTROLS,
    core.PLACE,
)


def add_social_capital(sample: pd.DataFrame) -> pd.DataFrame:
    """Construct the locked, direction-corrected within-place index."""

    result = sample.copy()
    result["trust_people_sec"] = 6.0 - result["TRUST_PEOPLE_Y1"]
    z_columns: list[str] = []
    for column in ("PEOPLE_HELP_Y1", "close_to_bin", "trust_people_sec"):
        grouped = result.groupby(core.PLACE, sort=False)[column]
        means = grouped.transform("mean")
        standard_deviations = grouped.transform("std")
        if standard_deviations.le(0).any():
            raise ValueError(f"A place has zero variance in {column}")
        z_column = f"z_place__{column}"
        result[z_column] = (result[column] - means) / standard_deviations
        z_columns.append(z_column)
    result["social_capital_within_place"] = result[z_columns].mean(axis=1)
    checks = result.groupby(core.PLACE, sort=False)[z_columns].mean().abs()
    if float(checks.to_numpy().max()) > 1e-12:
        raise ValueError("Within-place Social Capital Index mean check failed")
    return result


def select_outcome_sample(source: pd.DataFrame, outcomes: tuple[str, ...]) -> pd.DataFrame:
    required = list(dict.fromkeys([*outcomes, *ANALYSIS_PREDICTOR_COLUMNS]))
    missing_columns = set(required).difference(source.columns)
    if missing_columns:
        raise ValueError(f"Source is missing columns: {sorted(missing_columns)}")
    sample = source.dropna(subset=required).copy()
    if sample[core.PLACE].nunique() != core.EXPECTED_PLACES:
        raise ValueError("Outcome-specific sample does not retain all 23 places")
    return add_social_capital(sample)


def fit_absorbed_model(
    sample: pd.DataFrame,
    outcome: str,
    continuous: list[str],
    categorical: tuple[str, ...],
    weights: pd.Series | None = None,
) -> dict[str, Any]:
    normalized_weights = core.normalized_analysis_weights(sample, weights)
    design, metadata = core.make_predictor_design(
        sample, continuous, categorical, normalized_weights
    )
    outcome_within = core.within_transform(
        sample[[outcome]], sample[core.PLACE], normalized_weights
    )[outcome]
    row_scale = (
        np.ones(len(sample), dtype=np.float64)
        if normalized_weights is None
        else np.sqrt(normalized_weights.to_numpy(dtype=np.float64))
    )
    x = design.to_numpy(dtype=np.float64) * row_scale[:, None]
    y = outcome_within.to_numpy(dtype=np.float64) * row_scale
    groups = sample[core.PLACE].astype(int).to_numpy()
    fit = core.fit_ols(x, y)
    cr2 = core.cr2_cluster_influence(x, fit.residual, groups, fit.inv_xtx)
    coefficients = pd.DataFrame(
        core.coefficient_rows(
            equation=f"{outcome}_absorbed_place_fe",
            outcome=outcome,
            names=list(design.columns),
            estimate=fit.beta,
            cr2=cr2,
        )
    )
    total_sum_squares = float(y @ y)
    residual_sum_squares = float(fit.residual @ fit.residual)
    return {
        "coefficients": coefficients,
        "within_r_squared": 1.0 - residual_sum_squares / total_sum_squares,
        "n": len(sample),
        "clusters": int(sample[core.PLACE].nunique()),
        "condition_number": fit.condition_number,
        "max_abs_within_design_place_mean": metadata[
            "max_abs_within_design_place_mean"
        ],
    }


def coefficient_record(
    fit: dict[str, Any], term: str, **labels: Any
) -> dict[str, Any]:
    row = fit["coefficients"].loc[fit["coefficients"]["term"].eq(term)]
    if len(row) != 1:
        raise ValueError(f"Expected exactly one coefficient for {term}")
    value = row.iloc[0]
    return {
        **labels,
        "term": term,
        "estimate": float(value["estimate"]),
        "cr2_se": float(value["cr2_se"]),
        "satterthwaite_df": float(value["satterthwaite_df"]),
        "cr2_satterthwaite_ci_low": float(value["cr2_satterthwaite_ci_low"]),
        "cr2_satterthwaite_ci_high": float(value["cr2_satterthwaite_ci_high"]),
        "n": int(fit["n"]),
        "clusters": int(fit["clusters"]),
        "within_r_squared": float(fit["within_r_squared"]),
    }


def explicit_place_fe_rural_estimate(sample: pd.DataFrame, outcome: str) -> float:
    """Independent point-estimate check using explicit place indicators."""

    continuous = sample[FULL_CONTINUOUS].astype(np.float64).copy()
    categorical_parts: list[pd.DataFrame] = [continuous]
    for column in core.CATEGORICAL_CONTROLS:
        values = sorted(int(value) for value in sample[column].unique())
        categorical = pd.Categorical(sample[column].astype(int), categories=values)
        dummies = pd.get_dummies(
            categorical,
            prefix=column,
            prefix_sep="__",
            drop_first=True,
            dtype=np.float64,
        )
        dummies.index = sample.index
        categorical_parts.append(dummies)
    place_values = sorted(int(value) for value in sample[core.PLACE].unique())
    place_category = pd.Categorical(
        sample[core.PLACE].astype(int), categories=place_values
    )
    place_dummies = pd.get_dummies(
        place_category,
        prefix=core.PLACE,
        prefix_sep="__",
        drop_first=True,
        dtype=np.float64,
    )
    place_dummies.index = sample.index
    categorical_parts.append(place_dummies)
    design = pd.concat(categorical_parts, axis=1)
    design.insert(0, "intercept", 1.0)
    beta, _, rank, _ = np.linalg.lstsq(
        design.to_numpy(dtype=np.float64),
        sample[outcome].to_numpy(dtype=np.float64),
        rcond=None,
    )
    if rank != design.shape[1]:
        raise ValueError("Explicit-place-FE cross-check design is rank deficient")
    return float(beta[list(design.columns).index(core.EXPOSURE)])


def existing_rural_value(
    frame: pd.DataFrame, scenario: str, model: str
) -> float:
    row = frame.loc[
        frame["scenario"].eq(scenario) & frame["model"].eq(model), "rural_estimate"
    ]
    if len(row) != 1:
        raise ValueError(f"Missing existing result for {scenario}/{model}")
    return float(row.iloc[0])


def run(output_dir: Path, apply: bool) -> dict[str, Any]:
    source, _, source_audit = core.load_and_validate_source(
        core.DEFAULT_DATA, core.DEFAULT_CROSSWALK
    )
    common, _, common_audit = core.build_common_sample(source)

    # Table 3: core economic-path equations on the one locked common sample.
    table3_rows: list[dict[str, Any]] = []
    economic_outcomes = (
        ("income_feelings_sec", "Income Security Feelings"),
        ("EXPENSES_Y1", "Expense Security"),
        ("income_pctile", "Within-Place Income Percentile"),
    )
    for outcome, label in economic_outcomes:
        fitted = fit_absorbed_model(
            common, outcome, BASE_CONTINUOUS, core.CATEGORICAL_CONTROLS
        )
        table3_rows.append(
            coefficient_record(
                fitted,
                core.EXPOSURE,
                outcome=outcome,
                outcome_label=label,
                sample_policy="locked_common_complete_case",
                weighting="unweighted",
            )
        )
    table3 = pd.DataFrame(table3_rows)

    # Table 1: the current Social Capital Index exists only on the common sample.
    social_descriptive = (
        common.groupby(core.EXPOSURE, sort=True)["social_capital_within_place"]
        .agg(["count", "mean", "std"])
        .reset_index()
    )
    urban_social = social_descriptive.loc[
        social_descriptive[core.EXPOSURE].eq(0)
    ].iloc[0]
    rural_social = social_descriptive.loc[
        social_descriptive[core.EXPOSURE].eq(1)
    ].iloc[0]
    table1_social = pd.DataFrame(
        [
            {
                "variable": "Social Capital Index",
                "sample_policy": "locked_common_complete_case",
                "rural_n": int(rural_social["count"]),
                "rural_mean": float(rural_social["mean"]),
                "rural_sd": float(rural_social["std"]),
                "urban_n": int(urban_social["count"]),
                "urban_mean": float(urban_social["mean"]),
                "urban_sd": float(urban_social["std"]),
                "difference_rural_minus_urban": float(
                    rural_social["mean"] - urban_social["mean"]
                ),
            }
        ]
    )

    # Table 5: exact outcome-specific denominators, plus a same-respondent check.
    life_fit = fit_absorbed_model(
        common, core.OUTCOME, FULL_CONTINUOUS, core.CATEGORICAL_CONTROLS
    )
    outcome_specific_samples: dict[str, pd.DataFrame] = {core.OUTCOME: common}
    outcome_specific_fits: dict[str, dict[str, Any]] = {core.OUTCOME: life_fit}
    for outcome in ALT_OUTCOMES:
        sample = select_outcome_sample(source, (outcome,))
        outcome_specific_samples[outcome] = sample
        outcome_specific_fits[outcome] = fit_absorbed_model(
            sample, outcome, FULL_CONTINUOUS, core.CATEGORICAL_CONTROLS
        )

    table5_rows: list[dict[str, Any]] = []
    explicit_checks: dict[str, Any] = {}
    for outcome in (core.OUTCOME, *ALT_OUTCOMES):
        fitted = outcome_specific_fits[outcome]
        for term in (core.EXPOSURE, "social_capital_within_place"):
            table5_rows.append(
                coefficient_record(
                    fitted,
                    term,
                    outcome=outcome,
                    outcome_label=OUTCOME_LABELS[outcome],
                    sample_policy="outcome_specific_complete_case",
                    weighting="unweighted",
                )
            )
        explicit_estimate = explicit_place_fe_rural_estimate(
            outcome_specific_samples[outcome], outcome
        )
        absorbed_estimate = float(
            fitted["coefficients"].loc[
                fitted["coefficients"]["term"].eq(core.EXPOSURE), "estimate"
            ].iloc[0]
        )
        explicit_checks[outcome] = {
            "absorbed_place_fe_rural_estimate": absorbed_estimate,
            "explicit_place_fe_rural_estimate": explicit_estimate,
            "absolute_difference": abs(absorbed_estimate - explicit_estimate),
        }
        if abs(absorbed_estimate - explicit_estimate) > 1e-10:
            raise ValueError(f"Explicit-place-FE cross-check failed for {outcome}")
    table5 = pd.DataFrame(table5_rows)

    matched = select_outcome_sample(source, (core.OUTCOME, *ALT_OUTCOMES))
    matched_rows: list[dict[str, Any]] = []
    for outcome in (core.OUTCOME, *ALT_OUTCOMES):
        fitted = fit_absorbed_model(
            matched, outcome, FULL_CONTINUOUS, core.CATEGORICAL_CONTROLS
        )
        matched_rows.append(
            coefficient_record(
                fitted,
                core.EXPOSURE,
                outcome=outcome,
                outcome_label=OUTCOME_LABELS[outcome],
                sample_policy="three_outcome_matched_complete_case",
                weighting="unweighted",
            )
        )
    table5_matched = pd.DataFrame(matched_rows)

    # Figure 7 panel b: four-category residence model on the locked common N.
    residence_columns = {
        "residence_rural_area": 1,
        "residence_small_town": 2,
        "residence_suburb": 4,
    }
    for column, category in residence_columns.items():
        common[column] = common["URBAN_RURAL_Y1"].eq(category).astype(np.float64)
    four_category_fit = fit_absorbed_model(
        common,
        core.OUTCOME,
        [
            *residence_columns,
            "AGE_Y1",
            "income_feelings_sec",
            "EXPENSES_Y1",
            "income_pctile",
            "social_capital_within_place",
        ],
        core.CATEGORICAL_CONTROLS,
    )
    figure7_four_category = pd.DataFrame(
        [
            coefficient_record(
                four_category_fit,
                column,
                residence_category=category,
                reference_category="large city",
                sample_policy="locked_common_complete_case",
                weighting="unweighted",
                outcome=core.OUTCOME,
            )
            for column, category in residence_columns.items()
        ]
    )

    # Table 6: current unweighted and survey-weighted estimates on the same N.
    weighted_fit = fit_absorbed_model(
        common,
        core.OUTCOME,
        FULL_CONTINUOUS,
        core.CATEGORICAL_CONTROLS,
        common[core.WEIGHT],
    )
    table6_rows: list[dict[str, Any]] = []
    table6_terms = (
        core.EXPOSURE,
        "income_feelings_sec",
        "EXPENSES_Y1",
        "income_pctile",
        "social_capital_within_place",
    )
    for weighting, fitted in (("unweighted", life_fit), (core.WEIGHT, weighted_fit)):
        for term in table6_terms:
            table6_rows.append(
                coefficient_record(
                    fitted,
                    term,
                    outcome=core.OUTCOME,
                    outcome_label=OUTCOME_LABELS[core.OUTCOME],
                    sample_policy="locked_common_complete_case",
                    weighting=weighting,
                )
            )
    table6 = pd.DataFrame(table6_rows)

    existing_sequence = pd.read_csv(
        PROJECT_ROOT / "reports/batch_a_core/ols_sequence_rural.csv"
    )
    existing_equations = pd.read_csv(
        PROJECT_ROOT / "reports/batch_a_core/equation_coefficients.csv"
    )
    existing_table3 = (
        existing_equations.loc[
            existing_equations["scenario"].eq("primary_common_unweighted")
            & existing_equations["term"].eq(core.EXPOSURE)
            & existing_equations["dependent_variable"].isin(
                core.MEDIATOR_NAMES[:3]
            )
        ]
        .set_index("dependent_variable")["estimate"]
        .to_dict()
    )
    table3_expected = {
        "income_feelings_sec": existing_table3["income_security_feelings"],
        "EXPENSES_Y1": existing_table3["expense_security"],
        "income_pctile": existing_table3["income_percentile_within_place"],
    }
    table3_differences = {
        row.outcome: abs(row.estimate - table3_expected[row.outcome])
        for row in table3.itertuples()
    }
    if max(table3_differences.values()) > 1e-10:
        raise ValueError("Table 3 does not reproduce the validated path equations")

    primary_existing = existing_rural_value(
        existing_sequence, "primary_common_unweighted", "M4_full"
    )
    weighted_existing = existing_rural_value(
        existing_sequence, "survey_weighted_common", "M4_full"
    )
    primary_current = float(
        table6.loc[
            table6["weighting"].eq("unweighted")
            & table6["term"].eq(core.EXPOSURE),
            "estimate",
        ].iloc[0]
    )
    weighted_current = float(
        table6.loc[
            table6["weighting"].eq(core.WEIGHT)
            & table6["term"].eq(core.EXPOSURE),
            "estimate",
        ].iloc[0]
    )
    if abs(primary_current - primary_existing) > 1e-10:
        raise ValueError("Primary common-sample model does not reproduce Batch A")
    if abs(weighted_current - weighted_existing) > 1e-10:
        raise ValueError("Weighted common-sample model does not reproduce Batch A")

    available_life_rural = int(
        source.dropna(subset=[core.OUTCOME, core.EXPOSURE]).shape[0]
    )
    available_residence = int(source[core.EXPOSURE].notna().sum())
    supplementary_sample_rows = [
        {
            "panel": "Primary-model sample construction",
            "stage": "Processed source",
            "sample_policy": "source",
            "metric": "retained N",
            "n": len(source),
            "share_of_source": len(source) / len(source),
        },
        {
            "panel": "Primary-model sample construction",
            "stage": "Residence classification observed",
            "sample_policy": "descriptive availability",
            "metric": "retained N",
            "n": available_residence,
            "share_of_source": available_residence / len(source),
        },
        {
            "panel": "Primary-model sample construction",
            "stage": "M1 available case: life satisfaction and residence",
            "sample_policy": "available-case sensitivity only",
            "metric": "retained N",
            "n": available_life_rural,
            "share_of_source": available_life_rural / len(source),
        },
        {
            "panel": "Primary-model sample construction",
            "stage": "M2 available case: M1 plus controls",
            "sample_policy": "available-case sensitivity only",
            "metric": "retained N",
            "n": 203880,
            "share_of_source": 203880 / len(source),
        },
        {
            "panel": "Primary-model sample construction",
            "stage": "M3 available case: M2 plus economic-security measures",
            "sample_policy": "available-case sensitivity only",
            "metric": "retained N",
            "n": 185924,
            "share_of_source": 185924 / len(source),
        },
        {
            "panel": "Primary-model sample construction",
            "stage": "Locked common complete-case sample used for primary M1-M4 and path models",
            "sample_policy": "primary",
            "metric": "retained N",
            "n": len(common),
            "share_of_source": len(common) / len(source),
        },
        *[
            {
                "panel": "Alternative-outcome denominators",
                "stage": f"{OUTCOME_LABELS[outcome]} outcome-specific complete case",
                "sample_policy": "robustness",
                "metric": "retained N",
                "n": len(sample),
                "share_of_source": len(sample) / len(source),
            }
            for outcome, sample in outcome_specific_samples.items()
        ],
        {
            "panel": "Alternative-outcome denominators",
            "stage": "Three-outcome matched complete-case sensitivity",
            "sample_policy": "matched-sample robustness",
            "metric": "retained N",
            "n": len(matched),
            "share_of_source": len(matched) / len(source),
        },
        *[
            {
                "panel": "Variable-level missingness before primary complete-case restriction",
                "stage": variable,
                "sample_policy": "counts are not mutually exclusive",
                "metric": "missing count",
                "n": int(missing_count),
                "share_of_source": int(missing_count) / len(source),
            }
            for variable, missing_count in sorted(
                common_audit["missing_counts_before_complete_case"].items(),
                key=lambda item: (-int(item[1]), item[0]),
            )
        ],
    ]
    supplementary_sample_table = pd.DataFrame(supplementary_sample_rows)
    summary = {
        "source_n": int(source_audit["source_rows"]),
        "source_places": int(source_audit["place_count"]),
        "life_satisfaction_and_residence_available_n": available_life_rural,
        "residence_classification_available_n": available_residence,
        "primary_common_n": int(common_audit["common_sample_n"]),
        "primary_common_share_of_source": float(common_audit["common_sample_share"]),
        "primary_common_places": int(common_audit["common_sample_place_count"]),
        "outcome_specific_ns": {
            outcome: int(len(sample))
            for outcome, sample in outcome_specific_samples.items()
        },
        "three_outcome_matched_n": int(len(matched)),
        "missing_counts_before_primary_complete_case": common_audit[
            "missing_counts_before_complete_case"
        ],
        "model_specific_available_case_ns": [205955, 203880, 185924, 183685],
        "sample_policy": {
            "primary_models": "one locked common complete-case sample",
            "available_case_sequence": "sensitivity only",
            "alternative_outcomes": "exact outcome-specific complete-case N, accompanied by a three-outcome matched-sample sensitivity",
        },
        "cross_checks": {
            "table3_absolute_differences_from_validated_path_equations": table3_differences,
            "primary_m4_absolute_difference_from_batch_a": abs(
                primary_current - primary_existing
            ),
            "weighted_m4_absolute_difference_from_batch_a": abs(
                weighted_current - weighted_existing
            ),
            "absorbed_vs_explicit_place_fe": explicit_checks,
        },
    }

    manifest = {
        "purpose": "Reviewer 1 Comment 7 sample-denominator reconciliation",
        "data_path": str(core.DEFAULT_DATA.relative_to(PROJECT_ROOT)),
        "data_sha256": core.sha256(core.DEFAULT_DATA),
        "crosswalk_path": str(core.DEFAULT_CROSSWALK.relative_to(PROJECT_ROOT)),
        "crosswalk_sha256": core.sha256(core.DEFAULT_CROSSWALK),
        "script_path": str(Path(__file__).resolve().relative_to(PROJECT_ROOT)),
        "estimator": "OLS with absorbed place fixed effects and CR2/Satterthwaite place-clustered inference",
        "controls": ["AGE_Y1", *core.CATEGORICAL_CONTROLS],
        "economic_predictors": [
            "income_feelings_sec",
            "EXPENSES_Y1",
            "income_pctile",
        ],
        "social_capital": "equal mean of direction-corrected components standardized within analytical place",
        "output_files": [
            "sample_alignment_summary.json",
            "table1_social_capital_common.csv",
            "table3_common_sample.csv",
            "table5_alternative_outcomes.csv",
            "table5_matched_sensitivity.csv",
            "table6_weighted_common.csv",
            "figure7_four_category_common.csv",
            "supplementary_table_sample_alignment.csv",
            "run_manifest.json",
        ],
    }

    if apply:
        output_dir.mkdir(parents=True, exist_ok=True)
        core.atomic_write_csv(
            table1_social, output_dir / "table1_social_capital_common.csv"
        )
        core.atomic_write_csv(table3, output_dir / "table3_common_sample.csv")
        core.atomic_write_csv(table5, output_dir / "table5_alternative_outcomes.csv")
        core.atomic_write_csv(
            table5_matched, output_dir / "table5_matched_sensitivity.csv"
        )
        core.atomic_write_csv(table6, output_dir / "table6_weighted_common.csv")
        core.atomic_write_csv(
            figure7_four_category,
            output_dir / "figure7_four_category_common.csv",
        )
        core.atomic_write_csv(
            supplementary_sample_table,
            output_dir / "supplementary_table_sample_alignment.csv",
        )
        core.atomic_write_json(summary, output_dir / "sample_alignment_summary.json")
        core.atomic_write_json(manifest, output_dir / "run_manifest.json")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write validated outputs")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run(args.output_dir, args.apply)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
