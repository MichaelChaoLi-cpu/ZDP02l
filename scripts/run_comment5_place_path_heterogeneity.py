#!/usr/bin/env python3
"""Run the approved exploratory analytical-place path heterogeneity analysis.

The pooled OLS parallel path model remains primary.  This script fits the same
four-mediator observed-variable path system separately in each of the 23
analytical places on the locked common sample.  It reports place-specific
direct and indirect associations, global heterogeneity tests for the five
indirect-association estimands, and a survey-weighted sensitivity analysis.

Within-place uncertainty uses HC3 respondent-level coefficient influences and
a joint Rademacher wild-score bootstrap.  The same multiplier is used across
all mediator, direct-outcome, and total-outcome equations in each replicate so
that covariance among product terms is preserved.  All interpretations remain
cross-sectional and associational.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import tempfile
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
import numpy as np
import pandas as pd
from PIL import Image
import scipy
from scipy.optimize import brentq
from scipy.stats import chi2

from run_batch_a_core_path import (
    CATEGORICAL_CONTROLS,
    DEFAULT_CROSSWALK,
    DEFAULT_DATA,
    EXPECTED_COMMON_ROWS,
    EXPECTED_PLACES,
    EXPOSURE,
    MEDIATOR_NAMES,
    OUTCOME,
    PLACE,
    WEIGHT,
    atomic_write_csv,
    atomic_write_json,
    build_common_sample,
    effect_gradients,
    effect_values,
    fit_ols,
    load_and_validate_source,
    normalized_analysis_weights,
    sha256,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports/comment5_place_path_heterogeneity"
SCRIPT_PATH = Path(__file__).resolve()
CORE_SCRIPT_PATH = SCRIPT_PATH.with_name("run_batch_a_core_path.py")
DEFAULT_BOOTSTRAP_REPETITIONS = 4_999
DEFAULT_SEED = 20_260_830
BOOTSTRAP_CHUNK_SIZE = 128
NORMAL_975 = 1.959963984540054

EFFECT_NAMES = (
    "indirect_income_security_feelings",
    "indirect_expense_security",
    "indirect_income_percentile_within_place",
    "indirect_social_capital_within_place",
    "total_indirect_association",
    "direct_association",
    "total_association",
    "decomposed_total_association",
)
HETEROGENEITY_EFFECTS = EFFECT_NAMES[:5]
EFFECT_LABELS = {
    "indirect_income_security_feelings": "Income security\nfeelings",
    "indirect_expense_security": "Expense\nsecurity",
    "indirect_income_percentile_within_place": "Within-place\nincome percentile",
    "indirect_social_capital_within_place": "Social capital\nindex",
    "total_indirect_association": "Total indirect\nassociation",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_local_base_design(data: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build one within-place design with an intercept and observed categories."""

    parts = [
        pd.DataFrame(
            {
                "intercept": np.ones(len(data), dtype=np.float64),
                EXPOSURE: data[EXPOSURE].astype(np.float64),
                "AGE_Y1": data["AGE_Y1"].astype(np.float64),
            },
            index=data.index,
        )
    ]
    references: dict[str, int] = {}
    observed_levels: dict[str, list[int]] = {}
    for column in CATEGORICAL_CONTROLS:
        levels = sorted(int(value) for value in data[column].unique())
        if len(levels) < 2:
            raise ValueError(f"Only one observed level for {column}")
        references[column] = levels[0]
        observed_levels[column] = levels
        categorical = pd.Categorical(data[column].astype(int), categories=levels)
        dummies = pd.get_dummies(
            categorical,
            prefix=column,
            prefix_sep="__",
            drop_first=True,
            dtype=np.float64,
        )
        dummies.index = data.index
        parts.append(dummies)
    design = pd.concat(parts, axis=1)
    if design.columns.duplicated().any():
        raise ValueError("Duplicate local design columns")
    matrix = design.to_numpy(dtype=np.float64)
    rank = int(np.linalg.matrix_rank(matrix))
    if rank != matrix.shape[1]:
        raise ValueError(
            f"Rank-deficient local design: rank={rank}, columns={matrix.shape[1]}"
        )
    return design, {
        "base_columns": list(design.columns),
        "categorical_reference_codes": references,
        "categorical_observed_codes": observed_levels,
        "base_rank": rank,
        "base_parameter_count": int(matrix.shape[1]),
        "base_condition_number": float(np.linalg.cond(matrix)),
    }


def hc3_focal_coefficient_influence(
    x: np.ndarray, residual: np.ndarray, focal_indices: list[int]
) -> tuple[np.ndarray, dict[str, float]]:
    """Return partial-leverage HC3 influences for focal coefficients.

    Frisch-Waugh-Lovell residualization removes all nuisance-control columns
    before the HC3 leverage adjustment.  This leaves point estimates identical
    to the full OLS model while preventing a singleton nuisance-category dummy
    from making HC3 undefined for otherwise estimable focal slopes.  The
    returned shape is ``(n, k)`` for one equation and ``(n, k, q)`` for a
    multivariate outcome, where k is the number of focal coefficients.
    """

    focal_indices = list(focal_indices)
    nuisance_indices = [
        index for index in range(x.shape[1]) if index not in focal_indices
    ]
    focal = x[:, focal_indices]
    if nuisance_indices:
        nuisance = x[:, nuisance_indices]
        projection_coefficients, _, nuisance_rank, _ = np.linalg.lstsq(
            nuisance, focal, rcond=None
        )
        if nuisance_rank != nuisance.shape[1]:
            raise ValueError("Rank-deficient nuisance-control design")
        residualized_focal = focal - nuisance @ projection_coefficients
    else:
        residualized_focal = focal
    focal_crossproduct = residualized_focal.T @ residualized_focal
    focal_rank = int(np.linalg.matrix_rank(focal_crossproduct))
    if focal_rank != len(focal_indices):
        raise ValueError("Focal coefficients are not jointly estimable")
    focal_bread = np.linalg.inv(focal_crossproduct)
    leverage = np.einsum(
        "ij,jk,ik->i", residualized_focal, focal_bread, residualized_focal
    )
    one_minus = 1.0 - leverage
    if float(one_minus.min()) <= 1e-10:
        raise ValueError(
            "HC3 leverage is singular: "
            f"minimum 1-h={float(one_minus.min()):.6g}"
        )
    bread_rows = residualized_focal @ focal_bread
    if residual.ndim == 1:
        adjusted = residual / one_minus
        influence = bread_rows * adjusted[:, None]
    else:
        adjusted = residual / one_minus[:, None]
        influence = bread_rows[:, :, None] * adjusted[:, None, :]
    if not np.isfinite(influence).all():
        raise ValueError("Non-finite HC3 coefficient influence")
    return influence, {
        "max_leverage": float(leverage.max()),
        "min_one_minus_leverage": float(one_minus.min()),
        "mean_leverage": float(leverage.mean()),
    }


def joint_wild_score_intervals(
    theta: np.ndarray,
    theta_influence: np.ndarray,
    repetitions: int,
    seed: int,
) -> dict[str, np.ndarray]:
    """Generate joint respondent-level Rademacher wild-score intervals."""

    if repetitions < 999:
        raise ValueError("Use at least 999 bootstrap repetitions")
    rng = np.random.default_rng(seed)
    effect_draws = np.empty((repetitions, len(EFFECT_NAMES)), dtype=np.float64)
    for start in range(0, repetitions, BOOTSTRAP_CHUNK_SIZE):
        stop = min(repetitions, start + BOOTSTRAP_CHUNK_SIZE)
        multipliers = rng.integers(
            0,
            2,
            size=(stop - start, theta_influence.shape[0]),
            dtype=np.int8,
        ).astype(np.float64)
        multipliers *= 2.0
        multipliers -= 1.0
        theta_draws = theta[None, :] + multipliers @ theta_influence
        effect_draws[start:stop] = effect_values(theta_draws)
    if not np.isfinite(effect_draws).all():
        raise ValueError("Non-finite wild-score bootstrap effect draw")
    effects = effect_values(theta)
    percentile_low, percentile_high = np.quantile(
        effect_draws, [0.025, 0.975], axis=0
    )
    return {
        "percentile_low": percentile_low,
        "percentile_high": percentile_high,
        "basic_low": 2.0 * effects - percentile_high,
        "basic_high": 2.0 * effects - percentile_low,
        "draw_mean": effect_draws.mean(axis=0),
        "draw_sd": effect_draws.std(axis=0, ddof=1),
    }


def fit_place_path_system(
    data: pd.DataFrame,
    *,
    place_code: int,
    place_name: str,
    unit_type: str,
    scenario: str,
    weights: pd.Series | None,
    bootstrap_repetitions: int,
    seed: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fit all path equations for one analytical place."""

    if data[PLACE].nunique() != 1 or int(data[PLACE].iloc[0]) != place_code:
        raise ValueError("Place subset does not match requested code")
    normalized_weights = normalized_analysis_weights(data, weights)
    base_frame, design_metadata = make_local_base_design(data)
    row_scale = (
        np.ones(len(data), dtype=np.float64)
        if normalized_weights is None
        else np.sqrt(normalized_weights.to_numpy(dtype=np.float64))
    )
    base_names = list(base_frame.columns)
    base_x = base_frame.to_numpy(dtype=np.float64) * row_scale[:, None]
    mediator_raw = pd.DataFrame(
        {
            "income_security_feelings": data["income_feelings_sec"],
            "expense_security": data["EXPENSES_Y1"],
            "income_percentile_within_place": data["income_pctile"],
            "social_capital_within_place": data["social_capital_within_place"],
        },
        index=data.index,
    ).to_numpy(dtype=np.float64)
    mediator_y = mediator_raw * row_scale[:, None]
    outcome_y = data[OUTCOME].to_numpy(dtype=np.float64) * row_scale

    mediator_fit = fit_ols(base_x, mediator_y)
    outcome_names = base_names + list(MEDIATOR_NAMES)
    outcome_x = np.column_stack([base_x, mediator_y])
    outcome_fit = fit_ols(outcome_x, outcome_y)
    total_fit = fit_ols(base_x, outcome_y)

    rural_index = base_names.index(EXPOSURE)
    mediator_indices = [outcome_names.index(name) for name in MEDIATOR_NAMES]
    mediator_influence, mediator_hc3 = hc3_focal_coefficient_influence(
        base_x, mediator_fit.residual, [rural_index]
    )
    outcome_influence, outcome_hc3 = hc3_focal_coefficient_influence(
        outcome_x, outcome_fit.residual, [*mediator_indices, rural_index]
    )
    total_influence, total_hc3 = hc3_focal_coefficient_influence(
        base_x, total_fit.residual, [rural_index]
    )
    a_paths = mediator_fit.beta[rural_index, :]
    b_paths = outcome_fit.beta[mediator_indices]
    direct = float(outcome_fit.beta[rural_index])
    total = float(total_fit.beta[rural_index])
    theta = np.concatenate([a_paths, b_paths, [direct, total]])
    theta_influence = np.column_stack(
        [
            mediator_influence[:, 0, 0],
            mediator_influence[:, 0, 1],
            mediator_influence[:, 0, 2],
            mediator_influence[:, 0, 3],
            outcome_influence[:, 0],
            outcome_influence[:, 1],
            outcome_influence[:, 2],
            outcome_influence[:, 3],
            outcome_influence[:, 4],
            total_influence[:, 0],
        ]
    )
    theta_covariance = theta_influence.T @ theta_influence
    effects = effect_values(theta)
    gradients = effect_gradients(theta)
    effect_covariance = gradients @ theta_covariance @ gradients.T
    effect_se = np.sqrt(np.clip(np.diag(effect_covariance), 0.0, None))
    if np.any(effect_se <= 0) or not np.isfinite(effect_se).all():
        raise ValueError("Invalid HC3 delta standard error")
    bootstrap = joint_wild_score_intervals(
        theta, theta_influence, bootstrap_repetitions, seed
    )

    identity_gap = total - float(effects[-1])
    if abs(identity_gap) > 1e-10:
        raise ValueError(
            "Linear path identity failed: "
            f"total - (direct + total indirect)={identity_gap:.3g}"
        )

    rural_n = int(data[EXPOSURE].eq(1).sum())
    urban_n = int(data[EXPOSURE].eq(0).sum())
    weighting = "unweighted" if normalized_weights is None else WEIGHT
    records: list[dict[str, Any]] = []
    for index, effect_name in enumerate(EFFECT_NAMES):
        records.append(
            {
                "scenario": scenario,
                "place_code": place_code,
                "place_name": place_name,
                "unit_type": unit_type,
                "effect": effect_name,
                "estimate": float(effects[index]),
                "hc3_delta_se": float(effect_se[index]),
                "hc3_normal_ci_low": float(
                    effects[index] - NORMAL_975 * effect_se[index]
                ),
                "hc3_normal_ci_high": float(
                    effects[index] + NORMAL_975 * effect_se[index]
                ),
                "joint_wild_basic_ci_low": float(bootstrap["basic_low"][index]),
                "joint_wild_basic_ci_high": float(bootstrap["basic_high"][index]),
                "joint_wild_percentile_ci_low": float(
                    bootstrap["percentile_low"][index]
                ),
                "joint_wild_percentile_ci_high": float(
                    bootstrap["percentile_high"][index]
                ),
                "bootstrap_draw_mean": float(bootstrap["draw_mean"][index]),
                "bootstrap_draw_sd": float(bootstrap["draw_sd"][index]),
                "n": int(len(data)),
                "rural_n": rural_n,
                "urban_n": urban_n,
                "weighting": weighting,
                "bootstrap_repetitions": bootstrap_repetitions,
                "bootstrap_seed": seed,
                "interpretation": (
                    "exploratory cross-sectional association/pathway; "
                    "not a causal mediation effect"
                ),
            }
        )

    diagnostics = {
        "scenario": scenario,
        "place_code": place_code,
        "place_name": place_name,
        "unit_type": unit_type,
        "n": int(len(data)),
        "rural_n": rural_n,
        "urban_n": urban_n,
        "rural_share": float(data[EXPOSURE].mean()),
        "weighting": weighting,
        "normalized_weight_min": (
            1.0 if normalized_weights is None else float(normalized_weights.min())
        ),
        "normalized_weight_max": (
            1.0 if normalized_weights is None else float(normalized_weights.max())
        ),
        "normalized_weight_mean": (
            1.0 if normalized_weights is None else float(normalized_weights.mean())
        ),
        **design_metadata,
        "mediator_rank": mediator_fit.rank,
        "outcome_rank": outcome_fit.rank,
        "total_rank": total_fit.rank,
        "outcome_parameter_count": int(outcome_x.shape[1]),
        "mediator_condition_number": mediator_fit.condition_number,
        "outcome_condition_number": outcome_fit.condition_number,
        "total_condition_number": total_fit.condition_number,
        "mediator_hc3_max_leverage": mediator_hc3["max_leverage"],
        "outcome_hc3_max_leverage": outcome_hc3["max_leverage"],
        "total_hc3_max_leverage": total_hc3["max_leverage"],
        "mediator_hc3_min_one_minus_leverage": mediator_hc3[
            "min_one_minus_leverage"
        ],
        "outcome_hc3_min_one_minus_leverage": outcome_hc3[
            "min_one_minus_leverage"
        ],
        "total_hc3_min_one_minus_leverage": total_hc3[
            "min_one_minus_leverage"
        ],
        "path_identity_gap": identity_gap,
        "bootstrap_repetitions": bootstrap_repetitions,
        "bootstrap_seed": seed,
        "bootstrap_multiplier": "Rademacher (-1 or +1 with equal probability)",
        "joint_bootstrap_rule": (
            "same respondent multiplier across all mediator, direct-outcome, "
            "and total-outcome equations"
        ),
    }
    return pd.DataFrame(records), diagnostics


def reml_tau_squared(estimates: np.ndarray, variances: np.ndarray) -> float:
    """Solve the standard meta-analytic REML score for tau squared."""

    if len(estimates) < 2 or np.any(variances <= 0):
        raise ValueError("REML requires at least two estimates and positive variances")

    def score(tau_squared: float) -> float:
        weights = 1.0 / (variances + tau_squared)
        mean = float(np.sum(weights * estimates) / np.sum(weights))
        residual = estimates - mean
        return float(
            np.sum((weights**2) * (residual**2))
            - (np.sum(weights) - np.sum(weights**2) / np.sum(weights))
        )

    if score(0.0) <= 0:
        return 0.0
    upper = max(float(np.var(estimates, ddof=1)), float(variances.max()), 1e-8)
    for _ in range(60):
        if score(upper) < 0:
            return float(brentq(score, 0.0, upper, xtol=1e-14, rtol=1e-12))
        upper *= 2.0
    raise ValueError("Could not bracket the REML tau-squared root")


def benjamini_hochberg(p_values: np.ndarray) -> np.ndarray:
    """Return monotone Benjamini-Hochberg adjusted p-values."""

    count = len(p_values)
    order = np.argsort(p_values)
    ranked = p_values[order]
    adjusted_ranked = ranked * count / np.arange(1, count + 1)
    adjusted_ranked = np.minimum.accumulate(adjusted_ranked[::-1])[::-1]
    adjusted_ranked = np.clip(adjusted_ranked, 0.0, 1.0)
    adjusted = np.empty(count, dtype=np.float64)
    adjusted[order] = adjusted_ranked
    return adjusted


def build_heterogeneity_tests(primary_effects: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for effect_name in HETEROGENEITY_EFFECTS:
        subset = primary_effects.loc[primary_effects["effect"].eq(effect_name)].copy()
        if len(subset) != EXPECTED_PLACES:
            raise ValueError(f"Expected 23 place estimates for {effect_name}")
        estimates = subset["estimate"].to_numpy(dtype=np.float64)
        variances = subset["hc3_delta_se"].to_numpy(dtype=np.float64) ** 2
        weights = 1.0 / variances
        fixed_mean = float(np.sum(weights * estimates) / np.sum(weights))
        fixed_se = math.sqrt(1.0 / float(np.sum(weights)))
        q_statistic = float(np.sum(weights * (estimates - fixed_mean) ** 2))
        degrees_freedom = len(estimates) - 1
        p_value = float(chi2.sf(q_statistic, degrees_freedom))
        tau_squared = reml_tau_squared(estimates, variances)
        random_weights = 1.0 / (variances + tau_squared)
        random_mean = float(
            np.sum(random_weights * estimates) / np.sum(random_weights)
        )
        random_se = math.sqrt(1.0 / float(np.sum(random_weights)))
        i_squared = (
            0.0
            if q_statistic <= 0
            else max(0.0, (q_statistic - degrees_freedom) / q_statistic) * 100.0
        )
        rows.append(
            {
                "scenario": "place_stratified_unweighted",
                "effect": effect_name,
                "places": len(estimates),
                "estimate_min": float(estimates.min()),
                "estimate_max": float(estimates.max()),
                "fixed_effect_mean": fixed_mean,
                "fixed_effect_se": fixed_se,
                "fixed_effect_ci_low": fixed_mean - NORMAL_975 * fixed_se,
                "fixed_effect_ci_high": fixed_mean + NORMAL_975 * fixed_se,
                "cochran_q": q_statistic,
                "q_df": degrees_freedom,
                "q_p_value": p_value,
                "reml_tau_squared": tau_squared,
                "i_squared_percent": i_squared,
                "random_effects_mean": random_mean,
                "random_effects_se": random_se,
                "random_effects_ci_low": random_mean - NORMAL_975 * random_se,
                "random_effects_ci_high": random_mean + NORMAL_975 * random_se,
            }
        )
    table = pd.DataFrame(rows)
    table["bh_fdr_q_value"] = benjamini_hochberg(
        table["q_p_value"].to_numpy(dtype=np.float64)
    )
    table["heterogeneity_fdr_0_05"] = table["bh_fdr_q_value"].le(0.05)
    return table


def draw_heatmap(
    primary_effects: pd.DataFrame,
    crosswalk: pd.DataFrame,
    output_path: Path,
) -> None:
    """Draw a neutral crosswalk-ordered heatmap of the five indirect effects."""

    selected = primary_effects.loc[
        primary_effects["effect"].isin(HETEROGENEITY_EFFECTS)
    ].copy()
    matrix = selected.pivot(index="place_code", columns="effect", values="estimate")
    matrix = matrix.reindex(
        index=crosswalk[PLACE].astype(int).tolist(),
        columns=list(HETEROGENEITY_EFFECTS),
    )
    if matrix.isna().any().any():
        raise ValueError("Incomplete place-by-path matrix for the heatmap")
    place_names = crosswalk.set_index(PLACE).loc[matrix.index, "place_name"].tolist()
    values = matrix.to_numpy(dtype=np.float64)
    colour_limit = float(np.quantile(np.abs(values), 0.98))
    colour_limit = max(colour_limit, 1e-6)

    plt.rcParams.update(
        {
            "axes.grid": False,
            "font.size": 9.5,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )
    figure, axis = plt.subplots(figsize=(9.3, 10.2))
    image = axis.imshow(
        values,
        aspect="auto",
        cmap="RdBu",
        norm=TwoSlopeNorm(vmin=-colour_limit, vcenter=0.0, vmax=colour_limit),
        interpolation="nearest",
    )
    axis.set_xticks(
        np.arange(len(HETEROGENEITY_EFFECTS)),
        [EFFECT_LABELS[name] for name in HETEROGENEITY_EFFECTS],
        fontsize=9,
    )
    axis.set_yticks(np.arange(len(place_names)), place_names, fontsize=8.5)
    axis.tick_params(top=True, bottom=False, labeltop=True, labelbottom=False, length=0)
    axis.set_xticks(np.arange(-0.5, len(HETEROGENEITY_EFFECTS), 1), minor=True)
    axis.set_yticks(np.arange(-0.5, len(place_names), 1), minor=True)
    axis.grid(which="minor", color="white", linestyle="-", linewidth=1.1)
    axis.tick_params(which="minor", bottom=False, left=False)
    for row in range(values.shape[0]):
        for column in range(values.shape[1]):
            value = values[row, column]
            text_colour = "white" if abs(value) >= 0.58 * colour_limit else "black"
            axis.text(
                column,
                row,
                f"{value:.3f}",
                ha="center",
                va="center",
                fontsize=6.4,
                color=text_colour,
            )
    colour_bar = figure.colorbar(image, ax=axis, fraction=0.035, pad=0.035)
    colour_bar.set_label(
        "Place-specific indirect association (life-satisfaction points)",
        fontsize=9,
    )
    colour_bar.ax.tick_params(labelsize=8)
    axis.set_title(
        "Exploratory analytical-place pathway heterogeneity",
        loc="left",
        fontsize=11.5,
        fontweight="bold",
        pad=18,
    )
    for spine in axis.spines.values():
        spine.set_visible(False)
    figure.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{output_path.stem}.",
        suffix=".png",
        dir=output_path.parent,
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
    try:
        figure.savefig(temp_path, dpi=300, bbox_inches="tight", facecolor="white")
        plt.close(figure)
        with Image.open(temp_path) as image_check:
            image_check.verify()
        os.replace(temp_path, output_path)
        output_path.chmod(0o644)
    finally:
        plt.close(figure)
        if temp_path.exists():
            temp_path.unlink()


def run_analysis(
    *,
    data_path: Path,
    crosswalk_path: Path,
    bootstrap_repetitions: int,
    seed: int,
) -> dict[str, Any]:
    frame, crosswalk, source_audit = load_and_validate_source(
        data_path, crosswalk_path
    )
    common, place_audit, sample_audit = build_common_sample(frame)
    if len(common) != EXPECTED_COMMON_ROWS or common[PLACE].nunique() != EXPECTED_PLACES:
        raise ValueError("Locked common sample validation failed")

    effect_tables: dict[str, list[pd.DataFrame]] = {
        "place_stratified_unweighted": [],
        "place_stratified_survey_weighted": [],
    }
    diagnostics: list[dict[str, Any]] = []
    for crosswalk_row in crosswalk.itertuples(index=False):
        place_code = int(crosswalk_row.COUNTRY)
        place_name = str(crosswalk_row.place_name)
        unit_type = str(crosswalk_row.unit_type)
        subset = common.loc[common[PLACE].eq(place_code)].copy()
        for scenario_index, scenario in enumerate(effect_tables):
            scenario_weights = None if scenario_index == 0 else subset[WEIGHT]
            place_seed = seed + 100_000 * scenario_index + place_code
            effect_table, diagnostic = fit_place_path_system(
                subset,
                place_code=place_code,
                place_name=place_name,
                unit_type=unit_type,
                scenario=scenario,
                weights=scenario_weights,
                bootstrap_repetitions=bootstrap_repetitions,
                seed=place_seed,
            )
            effect_tables[scenario].append(effect_table)
            diagnostics.append(diagnostic)

    primary_effects = pd.concat(
        effect_tables["place_stratified_unweighted"], ignore_index=True
    )
    weighted_effects = pd.concat(
        effect_tables["place_stratified_survey_weighted"], ignore_index=True
    )
    diagnostics_table = pd.DataFrame(diagnostics)
    heterogeneity = build_heterogeneity_tests(primary_effects)

    weighted_sensitivity_summary: dict[str, dict[str, float]] = {}
    for effect_name in HETEROGENEITY_EFFECTS:
        primary_values = primary_effects.loc[
            primary_effects["effect"].eq(effect_name), "estimate"
        ].to_numpy(dtype=np.float64)
        weighted_values = weighted_effects.loc[
            weighted_effects["effect"].eq(effect_name), "estimate"
        ].to_numpy(dtype=np.float64)
        weighted_sensitivity_summary[effect_name] = {
            "pearson_correlation": float(
                np.corrcoef(primary_values, weighted_values)[0, 1]
            ),
            "median_absolute_difference": float(
                np.median(np.abs(primary_values - weighted_values))
            ),
            "sign_concordance_proportion": float(
                np.mean(np.sign(primary_values) == np.sign(weighted_values))
            ),
        }
    heterogeneity["weighted_pearson_correlation"] = heterogeneity["effect"].map(
        {
            effect: values["pearson_correlation"]
            for effect, values in weighted_sensitivity_summary.items()
        }
    )
    heterogeneity["weighted_median_absolute_difference"] = heterogeneity[
        "effect"
    ].map(
        {
            effect: values["median_absolute_difference"]
            for effect, values in weighted_sensitivity_summary.items()
        }
    )
    heterogeneity["weighted_sign_concordance_proportion"] = heterogeneity[
        "effect"
    ].map(
        {
            effect: values["sign_concordance_proportion"]
            for effect, values in weighted_sensitivity_summary.items()
        }
    )

    return {
        "source_audit": source_audit,
        "sample_audit": sample_audit,
        "place_audit": place_audit,
        "crosswalk": crosswalk,
        "primary_effects": primary_effects,
        "weighted_effects": weighted_effects,
        "diagnostics": diagnostics_table,
        "heterogeneity": heterogeneity,
        "weighted_sensitivity_summary": weighted_sensitivity_summary,
    }


def write_outputs(
    results: dict[str, Any],
    *,
    output_dir: Path,
    data_path: Path,
    crosswalk_path: Path,
    bootstrap_repetitions: int,
    seed: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    expected_names = {
        "place_path_effects.csv",
        "path_heterogeneity_tests.csv",
        "place_path_diagnostics.csv",
        "place_path_weighted_sensitivity.csv",
        "figure_place_path_heterogeneity.png",
        "run_manifest.json",
    }
    unrecognized = {
        path.name for path in output_dir.iterdir() if path.is_file()
    }.difference(expected_names)
    if unrecognized:
        raise ValueError(f"Unrecognized files in output directory: {sorted(unrecognized)}")

    atomic_write_csv(
        results["primary_effects"], output_dir / "place_path_effects.csv"
    )
    atomic_write_csv(
        results["heterogeneity"], output_dir / "path_heterogeneity_tests.csv"
    )
    atomic_write_csv(
        results["diagnostics"], output_dir / "place_path_diagnostics.csv"
    )
    atomic_write_csv(
        results["weighted_effects"],
        output_dir / "place_path_weighted_sensitivity.csv",
    )
    draw_heatmap(
        results["primary_effects"],
        results["crosswalk"],
        output_dir / "figure_place_path_heterogeneity.png",
    )

    primary = results["primary_effects"]
    weighted = results["weighted_effects"]
    diagnostics = results["diagnostics"]
    heterogeneity = results["heterogeneity"]
    validation_gates = {
        "locked_common_n": results["sample_audit"]["common_sample_n"]
        == EXPECTED_COMMON_ROWS,
        "all_places_retained": results["sample_audit"]["common_sample_place_count"]
        == EXPECTED_PLACES,
        "primary_rows_complete": len(primary) == EXPECTED_PLACES * len(EFFECT_NAMES),
        "weighted_rows_complete": len(weighted) == EXPECTED_PLACES * len(EFFECT_NAMES),
        "diagnostic_rows_complete": len(diagnostics) == EXPECTED_PLACES * 2,
        "five_heterogeneity_tests": len(heterogeneity)
        == len(HETEROGENEITY_EFFECTS),
        "all_designs_full_rank": bool(
            (
                diagnostics["base_rank"].eq(diagnostics["base_parameter_count"])
                & diagnostics["mediator_rank"].eq(
                    diagnostics["base_parameter_count"]
                )
                & diagnostics["total_rank"].eq(
                    diagnostics["base_parameter_count"]
                )
                & diagnostics["outcome_rank"].eq(
                    diagnostics["outcome_parameter_count"]
                )
            ).all()
        ),
        "hc3_nonsingular": float(
            diagnostics[
                [
                    "mediator_hc3_min_one_minus_leverage",
                    "outcome_hc3_min_one_minus_leverage",
                    "total_hc3_min_one_minus_leverage",
                ]
            ].min().min()
        )
        > 1e-10,
        "path_identity_verified": float(diagnostics["path_identity_gap"].abs().max())
        <= 1e-10,
        "bootstrap_intervals_finite": bool(
            np.isfinite(
                pd.concat([primary, weighted], ignore_index=True)[
                    [
                        "joint_wild_basic_ci_low",
                        "joint_wild_basic_ci_high",
                        "joint_wild_percentile_ci_low",
                        "joint_wild_percentile_ci_high",
                    ]
                ].to_numpy(dtype=np.float64)
            ).all()
        ),
        "heterogeneity_statistics_finite": bool(
            np.isfinite(
                heterogeneity[
                    [
                        "cochran_q",
                        "q_p_value",
                        "reml_tau_squared",
                        "i_squared_percent",
                        "bh_fdr_q_value",
                    ]
                ].to_numpy(dtype=np.float64)
            ).all()
        ),
        "hong_kong_kept_as_region": bool(
            primary.loc[primary["place_name"].eq("Hong Kong"), "unit_type"]
            .eq("region")
            .all()
        ),
        "figure_verified": (output_dir / "figure_place_path_heterogeneity.png").is_file(),
    }
    if not all(validation_gates.values()):
        raise ValueError(f"One or more validation gates failed: {validation_gates}")

    output_files = [
        output_dir / "place_path_effects.csv",
        output_dir / "path_heterogeneity_tests.csv",
        output_dir / "place_path_diagnostics.csv",
        output_dir / "place_path_weighted_sensitivity.csv",
        output_dir / "figure_place_path_heterogeneity.png",
    ]
    manifest = {
        "status": "validated_exploratory_analytical_place_path_heterogeneity",
        "analysis_role": (
            "exploratory supplementary robustness analysis; pooled OLS parallel "
            "path model remains primary"
        ),
        "estimand": "cross-sectional direct and indirect associations",
        "places": EXPECTED_PLACES,
        "locked_common_n": EXPECTED_COMMON_ROWS,
        "parallel_mediators": list(MEDIATOR_NAMES),
        "heterogeneity_estimands": list(HETEROGENEITY_EFFECTS),
        "global_multiplicity_control": (
            "Benjamini-Hochberg FDR across five Cochran Q tests"
        ),
        "inference": {
            "within_place_covariance": (
                "partial-leverage HC3 respondent-level focal-coefficient influences"
            ),
            "joint_interval": "joint respondent-level Rademacher wild-score bootstrap",
            "bootstrap_repetitions_per_place_scenario": bootstrap_repetitions,
            "base_seed": seed,
            "heterogeneity_variance_input": "HC3 delta-method within-place variances",
            "between_place_variance": "REML tau squared",
        },
        "survey_weighted_sensitivity_summary": results[
            "weighted_sensitivity_summary"
        ],
        "source_hashes": {
            "processed_data": sha256(data_path),
            "place_crosswalk": sha256(crosswalk_path),
            "core_analysis_script": sha256(CORE_SCRIPT_PATH),
            "place_heterogeneity_script": sha256(SCRIPT_PATH),
        },
        "software": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": scipy.__version__,
            "matplotlib": matplotlib.__version__,
        },
        "outputs": {
            path.name: {"sha256": file_sha256(path), "bytes": path.stat().st_size}
            for path in output_files
        },
        "validation_gates": validation_gates,
        "interpretation_boundary": (
            "No causal, partial-mediation, full-mediation, or place-by-place "
            "significance classification is permitted."
        ),
    }
    atomic_write_json(manifest, output_dir / "run_manifest.json")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--bootstrap-repetitions", type=int, default=DEFAULT_BOOTSTRAP_REPETITIONS
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()

    data_path = args.data.resolve()
    crosswalk_path = args.crosswalk.resolve()
    output_dir = args.output_dir.resolve()
    for path in (data_path, crosswalk_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    results = run_analysis(
        data_path=data_path,
        crosswalk_path=crosswalk_path,
        bootstrap_repetitions=args.bootstrap_repetitions,
        seed=args.seed,
    )
    summary: dict[str, Any] = {
        "mode": "apply" if args.apply else "dry-run",
        "common_n": results["sample_audit"]["common_sample_n"],
        "places": results["sample_audit"]["common_sample_place_count"],
        "heterogeneity_tests": results["heterogeneity"].to_dict(orient="records"),
        "survey_weighted_sensitivity_summary": results[
            "weighted_sensitivity_summary"
        ],
    }
    if args.apply:
        manifest = write_outputs(
            results,
            output_dir=output_dir,
            data_path=data_path,
            crosswalk_path=crosswalk_path,
            bootstrap_repetitions=args.bootstrap_repetitions,
            seed=args.seed,
        )
        summary["output_dir"] = str(output_dir)
        summary["validation_gates"] = manifest["validation_gates"]
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
