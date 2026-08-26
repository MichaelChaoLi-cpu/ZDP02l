#!/usr/bin/env python3
"""Run the locked Batch A ordered-logit and multilevel robustness models.

This script imports the validated sample and variable-construction functions
from ``run_batch_a_core_path.py``.  It does not modify the processed data,
manuscript, response draft, tables, or figures.  With ``--apply`` it writes
auditable robustness outputs under ``reports/batch_a_core``.

Models
------
* A four-category place-fixed-effect proportional-odds logit on the locked
  common sample, with small-cluster CR1/t(22) and joint Webb score-bootstrap
  inference.  The categories are 0--4, 5--6, 7--8, and 9--10.
* A partial proportional-odds diagnostic model that allows only the rural
  coefficient to differ across cumulative cutoffs.  A cluster-robust Wald F
  test determines whether the fallback is required.
* The same ordered models on all eleven original outcome categories as an
  original-scale sensitivity analysis.
* A linear mixed model with a place random intercept and a place-varying rural
  slope, fitted by maximum likelihood on the same common sample.

OLS remains the primary model.  Every robustness interpretation is bounded to
cross-sectional association.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import tempfile
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import scipy
from scipy.optimize import minimize
from scipy.special import expit
from scipy.stats import chi2, f as f_distribution
import statsmodels
from statsmodels.miscmodels.ordinal_model import OrderedModel
from statsmodels.regression.mixed_linear_model import MixedLM

from run_batch_a_core_path import (
    CATEGORICAL_CONTROLS,
    DEFAULT_CODEBOOK,
    DEFAULT_CROSSWALK,
    DEFAULT_DATA,
    DEFAULT_OUTPUT_DIR,
    EXPECTED_COMMON_ROWS,
    EXPECTED_PLACES,
    EXPOSURE,
    OUTCOME,
    PLACE,
    WEBB_SUPPORT,
    atomic_write_csv,
    atomic_write_json,
    build_common_sample,
    load_and_validate_source,
    sha256,
    t_critical_975,
)


ROBUSTNESS_SCRIPT = Path(__file__).resolve()
CORE_SCRIPT = ROBUSTNESS_SCRIPT.with_name("run_batch_a_core_path.py")
FULL_CONTINUOUS = (
    EXPOSURE,
    "AGE_Y1",
    "income_feelings_sec",
    "EXPENSES_Y1",
    "income_pctile",
    "social_capital_within_place",
)
STANDARDIZED_CONTINUOUS = tuple(
    column for column in FULL_CONTINUOUS if column != EXPOSURE
)
ORIGINAL_OUTCOME_LEVELS = tuple(range(11))
FOUR_CATEGORY_LEVELS = tuple(range(4))
FOUR_CATEGORY_OUTCOME = "life_satisfaction_four_category"
FOUR_CATEGORY_DEFINITIONS = (
    {"category": 0, "label": "Low", "original_score_min": 0, "original_score_max": 4},
    {"category": 1, "label": "Moderate", "original_score_min": 5, "original_score_max": 6},
    {"category": 2, "label": "High", "original_score_min": 7, "original_score_max": 8},
    {"category": 3, "label": "Very high", "original_score_min": 9, "original_score_max": 10},
)
FOUR_CATEGORY_CUTOFF_LABELS = ("0-4|5-6", "5-6|7-8", "7-8|9-10")


@dataclass
class LikelihoodFit:
    params: np.ndarray
    log_likelihood: float
    converged: bool
    optimizer_success: bool
    optimizer_message: str
    iterations: int
    function_evaluations: int
    gradient_max_abs: float
    gradient_max_abs_per_observation: float
    newton_step_max_abs: float
    newton_decrement_squared: float
    hessian: np.ndarray
    hessian_inverse: np.ndarray
    hessian_min_eigenvalue: float
    hessian_max_eigenvalue: float
    hessian_condition_number: float
    hessian_symmetry_error: float
    hessian_inverse_error: float
    minimum_fitted_probability: float


def inverse_threshold_transform(thresholds: np.ndarray) -> np.ndarray:
    thresholds = np.asarray(thresholds, dtype=np.float64)
    differences = np.diff(thresholds)
    if not np.all(differences > 0):
        raise ValueError("Threshold starting values must be strictly increasing")
    return np.concatenate(([thresholds[0]], np.log(differences)))


def transform_thresholds(
    parameters: np.ndarray, n_cutpoints: int
) -> np.ndarray:
    parameters = np.asarray(parameters, dtype=np.float64)
    if len(parameters) != n_cutpoints:
        raise ValueError("Unexpected number of threshold parameters")
    increments = np.concatenate(([parameters[0]], np.exp(parameters[1:])))
    thresholds = np.cumsum(increments)
    if not np.all(np.diff(thresholds) > 0):
        raise ValueError("Transformed thresholds are not strictly increasing")
    return thresholds


def threshold_jacobian(
    parameters: np.ndarray, n_cutpoints: int
) -> np.ndarray:
    parameters = np.asarray(parameters, dtype=np.float64)
    jacobian = np.zeros((n_cutpoints, n_cutpoints), dtype=np.float64)
    jacobian[:, 0] = 1.0
    for column in range(1, n_cutpoints):
        jacobian[column:, column] = math.exp(float(parameters[column]))
    return jacobian


def ordered_probability_parts(
    eta: np.ndarray,
    y: np.ndarray,
    thresholds: np.ndarray,
    n_cutpoints: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    upper_argument = np.full(len(y), np.inf, dtype=np.float64)
    lower_argument = np.full(len(y), -np.inf, dtype=np.float64)
    has_upper = y < n_cutpoints
    has_lower = y > 0
    upper_argument[has_upper] = thresholds[y[has_upper]] - eta[has_upper]
    lower_argument[has_lower] = thresholds[y[has_lower] - 1] - eta[has_lower]
    upper_cdf = expit(upper_argument)
    lower_cdf = expit(lower_argument)
    upper_density = upper_cdf * (1.0 - upper_cdf)
    lower_density = lower_cdf * (1.0 - lower_cdf)
    probability = upper_cdf - lower_cdf
    return probability, upper_density, lower_density, has_upper, has_lower


def cutoff_score_matrix(
    y: np.ndarray,
    probability: np.ndarray,
    upper_density: np.ndarray,
    lower_density: np.ndarray,
    has_upper: np.ndarray,
    has_lower: np.ndarray,
    n_cutpoints: int,
) -> np.ndarray:
    scores = np.zeros((len(y), n_cutpoints), dtype=np.float64)
    rows = np.arange(len(y))
    scores[rows[has_upper], y[has_upper]] += (
        upper_density[has_upper] / probability[has_upper]
    )
    scores[rows[has_lower], y[has_lower] - 1] -= (
        lower_density[has_lower] / probability[has_lower]
    )
    return scores


def make_full_design(
    common: pd.DataFrame, *, include_place_fixed_effects: bool
) -> tuple[pd.DataFrame, dict[str, Any]]:
    design = pd.DataFrame(index=common.index)
    scale_metadata: dict[str, dict[str, float]] = {}
    design[EXPOSURE] = common[EXPOSURE].astype(np.float64)
    for column in STANDARDIZED_CONTINUOUS:
        mean = float(common[column].mean())
        standard_deviation = float(common[column].std(ddof=1))
        if not math.isfinite(standard_deviation) or standard_deviation <= 0:
            raise ValueError(f"Invalid standard deviation for {column}")
        design[column] = (common[column].astype(np.float64) - mean) / standard_deviation
        scale_metadata[column] = {
            "mean": mean,
            "sample_standard_deviation": standard_deviation,
        }

    references: dict[str, int] = {}
    categorical_columns = list(CATEGORICAL_CONTROLS)
    if include_place_fixed_effects:
        categorical_columns.append(PLACE)
    for column in categorical_columns:
        levels = sorted(int(value) for value in common[column].unique())
        references[column] = levels[0]
        category = pd.Categorical(common[column].astype(int), categories=levels)
        dummies = pd.get_dummies(
            category,
            prefix=column,
            prefix_sep="__",
            drop_first=True,
            dtype=np.float64,
        )
        dummies.index = common.index
        design = pd.concat([design, dummies], axis=1)

    if design.columns.duplicated().any():
        raise ValueError("Duplicate columns in the explicit robustness design")
    matrix = design.to_numpy(dtype=np.float64)
    rank = int(np.linalg.matrix_rank(matrix))
    if rank != matrix.shape[1]:
        raise ValueError(
            f"Robustness design is rank deficient: rank={rank}, columns={matrix.shape[1]}"
        )
    metadata = {
        "columns": list(design.columns),
        "categorical_reference_codes": references,
        "continuous_standardization": scale_metadata,
        "place_fixed_effects": include_place_fixed_effects,
        "rank": rank,
        "parameter_count_without_intercept": int(matrix.shape[1]),
        "condition_number": float(np.linalg.cond(matrix)),
    }
    return design, metadata


def central_difference_hessian(
    score_function: Callable[[np.ndarray], np.ndarray], params: np.ndarray
) -> tuple[np.ndarray, float]:
    params = np.asarray(params, dtype=np.float64)
    parameter_count = len(params)
    hessian = np.empty((parameter_count, parameter_count), dtype=np.float64)
    for column in range(parameter_count):
        step = 2.5e-5 * max(1.0, abs(float(params[column])))
        plus = params.copy()
        minus = params.copy()
        plus[column] += step
        minus[column] -= step
        hessian[:, column] = (
            score_function(plus) - score_function(minus)
        ) / (2.0 * step)
    symmetry_error = float(np.max(np.abs(hessian - hessian.T)))
    hessian = (hessian + hessian.T) / 2.0
    return hessian, symmetry_error


def finalize_likelihood_fit(
    result: Any,
    gradient_function: Callable[[np.ndarray], np.ndarray],
    minimum_probability_function: Callable[[np.ndarray], float],
    observation_count: int,
) -> LikelihoodFit:
    params = np.asarray(result.x, dtype=np.float64)
    gradient = np.asarray(gradient_function(params), dtype=np.float64)
    hessian, symmetry_error = central_difference_hessian(
        gradient_function, params
    )
    eigenvalues = np.linalg.eigvalsh(hessian)
    minimum_eigenvalue = float(eigenvalues.min())
    maximum_eigenvalue = float(eigenvalues.max())
    if minimum_eigenvalue <= 0:
        raise ValueError(
            "Likelihood Hessian is not positive definite: "
            f"minimum eigenvalue={minimum_eigenvalue:.6g}"
        )
    hessian_inverse = np.linalg.inv(hessian)
    inverse_error = float(
        np.max(np.abs(hessian @ hessian_inverse - np.eye(len(params))))
    )
    gradient_max_abs = float(np.max(np.abs(gradient)))
    gradient_max_abs_per_observation = gradient_max_abs / observation_count
    newton_step = hessian_inverse @ gradient
    newton_step_max_abs = float(np.max(np.abs(newton_step)))
    newton_decrement_squared = float(gradient @ newton_step)
    converged = bool(
        result.success
        and gradient_max_abs_per_observation <= 1e-6
        and newton_step_max_abs <= 5e-3
        and newton_decrement_squared <= 1e-3
    )
    if not converged:
        raise ValueError(
            "Likelihood optimizer did not converge: "
            f"message={result.message}; max_abs_gradient={gradient_max_abs:.6g}; "
            f"per_observation={gradient_max_abs_per_observation:.6g}; "
            f"max_abs_newton_step={newton_step_max_abs:.6g}; "
            f"newton_decrement_squared={newton_decrement_squared:.6g}"
        )
    return LikelihoodFit(
        params=params,
        log_likelihood=float(-result.fun),
        converged=converged,
        optimizer_success=bool(result.success),
        optimizer_message=str(result.message),
        iterations=int(getattr(result, "nit", -1)),
        function_evaluations=int(getattr(result, "nfev", -1)),
        gradient_max_abs=gradient_max_abs,
        gradient_max_abs_per_observation=gradient_max_abs_per_observation,
        newton_step_max_abs=newton_step_max_abs,
        newton_decrement_squared=newton_decrement_squared,
        hessian=hessian,
        hessian_inverse=hessian_inverse,
        hessian_min_eigenvalue=minimum_eigenvalue,
        hessian_max_eigenvalue=maximum_eigenvalue,
        hessian_condition_number=float(maximum_eigenvalue / minimum_eigenvalue),
        hessian_symmetry_error=symmetry_error,
        hessian_inverse_error=inverse_error,
        minimum_fitted_probability=float(minimum_probability_function(params)),
    )


def fit_proportional_odds(
    x: np.ndarray, y: np.ndarray, n_cutpoints: int
) -> tuple[LikelihoodFit, np.ndarray]:
    parameter_count = x.shape[1]
    cumulative = np.array(
        [np.mean(y <= cutoff) for cutoff in range(n_cutpoints)],
        dtype=np.float64,
    )
    cumulative = np.clip(cumulative, 1e-5, 1.0 - 1e-5)
    initial_thresholds = np.log(cumulative / (1.0 - cumulative))
    initial = np.concatenate(
        [
            np.zeros(parameter_count, dtype=np.float64),
            inverse_threshold_transform(initial_thresholds),
        ]
    )

    def objective(params: np.ndarray) -> tuple[float, np.ndarray]:
        beta = params[:parameter_count]
        q = params[parameter_count:]
        thresholds = transform_thresholds(q, n_cutpoints)
        eta = x @ beta
        probability, upper_density, lower_density, has_upper, has_lower = (
            ordered_probability_parts(eta, y, thresholds, n_cutpoints)
        )
        if np.any(probability <= 0) or not np.isfinite(probability).all():
            return 1e100, np.zeros_like(params)
        eta_score = (lower_density - upper_density) / probability
        beta_score = x.T @ eta_score
        raw_cutoff_score = np.zeros(n_cutpoints, dtype=np.float64)
        np.add.at(
            raw_cutoff_score,
            y[has_upper],
            upper_density[has_upper] / probability[has_upper],
        )
        np.add.at(
            raw_cutoff_score,
            y[has_lower] - 1,
            -lower_density[has_lower] / probability[has_lower],
        )
        q_score = threshold_jacobian(q, n_cutpoints).T @ raw_cutoff_score
        score = np.concatenate([beta_score, q_score])
        return float(-np.log(probability).sum()), -score

    result = minimize(
        objective,
        initial,
        method="L-BFGS-B",
        jac=True,
        options={
            "maxiter": 750,
            "maxls": 60,
            "maxcor": 30,
            "ftol": 1e-13,
            "gtol": 1e-7,
        },
    )

    def gradient(params: np.ndarray) -> np.ndarray:
        return objective(params)[1]

    def minimum_probability(params: np.ndarray) -> float:
        beta = params[:parameter_count]
        thresholds = transform_thresholds(
            params[parameter_count:], n_cutpoints
        )
        probability = ordered_probability_parts(
            x @ beta, y, thresholds, n_cutpoints
        )[0]
        return float(probability.min())

    fit = finalize_likelihood_fit(
        result, gradient, minimum_probability, len(y)
    )
    return fit, transform_thresholds(
        fit.params[parameter_count:], n_cutpoints
    )


def aggregate_po_cluster_scores(
    x: np.ndarray,
    y: np.ndarray,
    groups: np.ndarray,
    params: np.ndarray,
    n_cutpoints: int,
) -> tuple[np.ndarray, np.ndarray]:
    parameter_count = x.shape[1]
    beta = params[:parameter_count]
    q = params[parameter_count:]
    thresholds = transform_thresholds(q, n_cutpoints)
    probability, upper_density, lower_density, has_upper, has_lower = (
        ordered_probability_parts(x @ beta, y, thresholds, n_cutpoints)
    )
    eta_score = (lower_density - upper_density) / probability
    cutoff_scores = cutoff_score_matrix(
        y,
        probability,
        upper_density,
        lower_density,
        has_upper,
        has_lower,
        n_cutpoints,
    )
    q_scores = cutoff_scores @ threshold_jacobian(q, n_cutpoints)
    unique_groups = np.unique(groups)
    cluster_scores = np.empty(
        (len(unique_groups), len(params)), dtype=np.float64
    )
    for index, group in enumerate(unique_groups):
        mask = groups == group
        cluster_scores[index, :parameter_count] = x[mask].T @ eta_score[mask]
        cluster_scores[index, parameter_count:] = q_scores[mask].sum(axis=0)
    full_score = cluster_scores.sum(axis=0)
    return cluster_scores, full_score


def cr1_covariance(
    hessian_inverse: np.ndarray,
    cluster_scores: np.ndarray,
    observation_count: int,
) -> tuple[np.ndarray, np.ndarray, float]:
    clusters = cluster_scores.shape[0]
    parameter_count = cluster_scores.shape[1]
    if clusters <= 1 or observation_count <= parameter_count:
        raise ValueError("Insufficient clusters or residual degrees of freedom")
    influence = cluster_scores @ hessian_inverse
    correction = (clusters / (clusters - 1.0)) * (
        (observation_count - 1.0) / (observation_count - parameter_count)
    )
    covariance = correction * (influence.T @ influence)
    covariance = (covariance + covariance.T) / 2.0
    return covariance, influence, float(correction)


def expected_score_ame_po(
    x: np.ndarray,
    rural_index: int,
    params: np.ndarray,
    n_cutpoints: int,
) -> tuple[float, np.ndarray]:
    parameter_count = x.shape[1]
    beta = params[:parameter_count]
    q = params[parameter_count:]
    thresholds = transform_thresholds(q, n_cutpoints)
    rural = x[:, rural_index]
    eta = x @ beta
    eta_one = eta + beta[rural_index] * (1.0 - rural)
    eta_zero = eta - beta[rural_index] * rural
    probability_at_or_above_one = expit(eta_one[:, None] - thresholds[None, :])
    probability_at_or_above_zero = expit(eta_zero[:, None] - thresholds[None, :])
    expected_one = probability_at_or_above_one.sum(axis=1)
    expected_zero = probability_at_or_above_zero.sum(axis=1)
    ame = float(np.mean(expected_one - expected_zero))

    density_one = probability_at_or_above_one * (
        1.0 - probability_at_or_above_one
    )
    density_zero = probability_at_or_above_zero * (
        1.0 - probability_at_or_above_zero
    )
    derivative_one = density_one.sum(axis=1)
    derivative_zero = density_zero.sum(axis=1)
    x_one = x.copy()
    x_zero = x.copy()
    x_one[:, rural_index] = 1.0
    x_zero[:, rural_index] = 0.0
    beta_gradient = np.mean(
        derivative_one[:, None] * x_one
        - derivative_zero[:, None] * x_zero,
        axis=0,
    )
    raw_threshold_gradient = np.mean(-density_one + density_zero, axis=0)
    q_gradient = (
        threshold_jacobian(q, n_cutpoints).T @ raw_threshold_gradient
    )
    gradient = np.concatenate([beta_gradient, q_gradient])
    return ame, gradient


def fit_partial_proportional_odds(
    x: np.ndarray,
    y: np.ndarray,
    rural_index: int,
    po_fit: LikelihoodFit,
    po_thresholds: np.ndarray,
    n_cutpoints: int,
) -> tuple[LikelihoodFit, np.ndarray, np.ndarray, np.ndarray]:
    rural = x[:, rural_index]
    z = np.delete(x, rural_index, axis=1)
    po_beta = po_fit.params[: x.shape[1]]
    beta_common_start = np.delete(po_beta, rural_index)
    thresholds_zero_start = po_thresholds
    thresholds_one_start = po_thresholds - po_beta[rural_index]
    initial = np.concatenate(
        [
            beta_common_start,
            inverse_threshold_transform(thresholds_zero_start),
            inverse_threshold_transform(thresholds_one_start),
        ]
    )
    common_parameter_count = z.shape[1]

    def unpack(
        params: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        beta = params[:common_parameter_count]
        q_zero = params[
            common_parameter_count : common_parameter_count + n_cutpoints
        ]
        q_one = params[common_parameter_count + n_cutpoints :]
        return (
            beta,
            q_zero,
            q_one,
            transform_thresholds(q_zero, n_cutpoints),
            transform_thresholds(q_one, n_cutpoints),
        )

    def objective(params: np.ndarray) -> tuple[float, np.ndarray]:
        beta, q_zero, q_one, thresholds_zero, thresholds_one = unpack(params)
        eta = z @ beta
        probability = np.empty(len(y), dtype=np.float64)
        eta_score = np.empty(len(y), dtype=np.float64)
        raw_zero = np.zeros(n_cutpoints, dtype=np.float64)
        raw_one = np.zeros(n_cutpoints, dtype=np.float64)
        for rural_value, thresholds, raw_score in (
            (0.0, thresholds_zero, raw_zero),
            (1.0, thresholds_one, raw_one),
        ):
            mask = rural == rural_value
            local_y = y[mask]
            parts = ordered_probability_parts(
                eta[mask], local_y, thresholds, n_cutpoints
            )
            local_probability, upper_density, lower_density, has_upper, has_lower = (
                parts
            )
            probability[mask] = local_probability
            eta_score[mask] = (
                lower_density - upper_density
            ) / local_probability
            np.add.at(
                raw_score,
                local_y[has_upper],
                upper_density[has_upper] / local_probability[has_upper],
            )
            np.add.at(
                raw_score,
                local_y[has_lower] - 1,
                -lower_density[has_lower] / local_probability[has_lower],
            )
        if np.any(probability <= 0) or not np.isfinite(probability).all():
            return 1e100, np.zeros_like(params)
        beta_score = z.T @ eta_score
        q_zero_score = threshold_jacobian(q_zero, n_cutpoints).T @ raw_zero
        q_one_score = threshold_jacobian(q_one, n_cutpoints).T @ raw_one
        score = np.concatenate([beta_score, q_zero_score, q_one_score])
        return float(-np.log(probability).sum()), -score

    result = minimize(
        objective,
        initial,
        method="L-BFGS-B",
        jac=True,
        options={
            "maxiter": 900,
            "maxls": 60,
            "maxcor": 35,
            "ftol": 1e-13,
            "gtol": 1e-7,
        },
    )

    def gradient(params: np.ndarray) -> np.ndarray:
        return objective(params)[1]

    def minimum_probability(params: np.ndarray) -> float:
        beta, _, _, thresholds_zero, thresholds_one = unpack(params)
        eta = z @ beta
        probability = np.empty(len(y), dtype=np.float64)
        for rural_value, thresholds in (
            (0.0, thresholds_zero),
            (1.0, thresholds_one),
        ):
            mask = rural == rural_value
            probability[mask] = ordered_probability_parts(
                eta[mask], y[mask], thresholds, n_cutpoints
            )[0]
        return float(probability.min())

    fit = finalize_likelihood_fit(
        result, gradient, minimum_probability, len(y)
    )
    _, _, _, thresholds_zero, thresholds_one = unpack(fit.params)
    return fit, z, thresholds_zero, thresholds_one


def aggregate_ppo_cluster_scores(
    z: np.ndarray,
    y: np.ndarray,
    rural: np.ndarray,
    groups: np.ndarray,
    params: np.ndarray,
    n_cutpoints: int,
) -> tuple[np.ndarray, np.ndarray]:
    common_parameter_count = z.shape[1]
    beta = params[:common_parameter_count]
    q_zero = params[
        common_parameter_count : common_parameter_count + n_cutpoints
    ]
    q_one = params[common_parameter_count + n_cutpoints :]
    thresholds_zero = transform_thresholds(q_zero, n_cutpoints)
    thresholds_one = transform_thresholds(q_one, n_cutpoints)
    eta = z @ beta
    eta_score = np.empty(len(y), dtype=np.float64)
    q_score = np.zeros((len(y), 2 * n_cutpoints), dtype=np.float64)
    for rural_value, q, thresholds, offset in (
        (0.0, q_zero, thresholds_zero, 0),
        (1.0, q_one, thresholds_one, n_cutpoints),
    ):
        mask = rural == rural_value
        local_y = y[mask]
        parts = ordered_probability_parts(
            eta[mask], local_y, thresholds, n_cutpoints
        )
        probability, upper_density, lower_density, has_upper, has_lower = parts
        eta_score[mask] = (lower_density - upper_density) / probability
        cutoff_scores = cutoff_score_matrix(
            local_y,
            probability,
            upper_density,
            lower_density,
            has_upper,
            has_lower,
            n_cutpoints,
        )
        q_score[np.ix_(mask, np.arange(offset, offset + n_cutpoints))] = (
            cutoff_scores @ threshold_jacobian(q, n_cutpoints)
        )
    unique_groups = np.unique(groups)
    cluster_scores = np.empty(
        (len(unique_groups), len(params)), dtype=np.float64
    )
    for index, group in enumerate(unique_groups):
        mask = groups == group
        cluster_scores[index, :common_parameter_count] = z[mask].T @ eta_score[mask]
        cluster_scores[index, common_parameter_count:] = q_score[mask].sum(axis=0)
    return cluster_scores, cluster_scores.sum(axis=0)


def ppo_rural_contrasts(
    params: np.ndarray, common_parameter_count: int, n_cutpoints: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    q_zero = params[
        common_parameter_count : common_parameter_count + n_cutpoints
    ]
    q_one = params[common_parameter_count + n_cutpoints :]
    thresholds_zero = transform_thresholds(q_zero, n_cutpoints)
    thresholds_one = transform_thresholds(q_one, n_cutpoints)
    gamma = thresholds_zero - thresholds_one
    gamma_jacobian = np.zeros(
        (n_cutpoints, len(params)), dtype=np.float64
    )
    gamma_jacobian[
        :, common_parameter_count : common_parameter_count + n_cutpoints
    ] = threshold_jacobian(q_zero, n_cutpoints)
    gamma_jacobian[:, common_parameter_count + n_cutpoints :] = (
        -threshold_jacobian(q_one, n_cutpoints)
    )
    return gamma, gamma_jacobian, thresholds_zero, thresholds_one


def expected_score_ame_ppo(
    z: np.ndarray, params: np.ndarray, n_cutpoints: int
) -> tuple[float, np.ndarray]:
    common_parameter_count = z.shape[1]
    beta = params[:common_parameter_count]
    gamma, _, thresholds_zero, thresholds_one = ppo_rural_contrasts(
        params, common_parameter_count, n_cutpoints
    )
    del gamma
    q_zero = params[
        common_parameter_count : common_parameter_count + n_cutpoints
    ]
    q_one = params[common_parameter_count + n_cutpoints :]
    eta = z @ beta
    cumulative_one = expit(eta[:, None] - thresholds_one[None, :])
    cumulative_zero = expit(eta[:, None] - thresholds_zero[None, :])
    expected_one = cumulative_one.sum(axis=1)
    expected_zero = cumulative_zero.sum(axis=1)
    ame = float(np.mean(expected_one - expected_zero))
    density_one = cumulative_one * (1.0 - cumulative_one)
    density_zero = cumulative_zero * (1.0 - cumulative_zero)
    beta_gradient = np.mean(
        (density_one.sum(axis=1) - density_zero.sum(axis=1))[:, None] * z,
        axis=0,
    )
    raw_zero_gradient = np.mean(density_zero, axis=0)
    raw_one_gradient = -np.mean(density_one, axis=0)
    q_zero_gradient = (
        threshold_jacobian(q_zero, n_cutpoints).T @ raw_zero_gradient
    )
    q_one_gradient = (
        threshold_jacobian(q_one, n_cutpoints).T @ raw_one_gradient
    )
    return ame, np.concatenate(
        [beta_gradient, q_zero_gradient, q_one_gradient]
    )


def wald_nonparallel_test(
    gamma: np.ndarray,
    gamma_covariance: np.ndarray,
    clusters: int,
) -> dict[str, Any]:
    n_cutpoints = len(gamma)
    contrast = np.zeros((n_cutpoints - 1, n_cutpoints), dtype=np.float64)
    for row in range(n_cutpoints - 1):
        contrast[row, 0] = -1.0
        contrast[row, row + 1] = 1.0
    difference = contrast @ gamma
    covariance = contrast @ gamma_covariance @ contrast.T
    rank = int(np.linalg.matrix_rank(covariance, tol=1e-10))
    if rank != n_cutpoints - 1:
        raise ValueError(
            f"Nonparallel Wald covariance rank={rank}; expected {n_cutpoints - 1}"
        )
    wald_chi_square = float(difference @ np.linalg.solve(covariance, difference))
    numerator_df = n_cutpoints - 1
    denominator_df = clusters - numerator_df
    if denominator_df <= 0:
        raise ValueError("Too few clusters for the nonparallel Wald F test")
    wald_f = wald_chi_square / numerator_df
    p_value = float(
        f_distribution.sf(wald_f, numerator_df, denominator_df)
    )
    return {
        "null_hypothesis": "the rural log-odds coefficient is equal across all cumulative cutoffs",
        "wald_chi_square": wald_chi_square,
        "numerator_df": numerator_df,
        "wald_f": wald_f,
        "denominator_df": denominator_df,
        "cluster_robust_p_value": p_value,
        "fallback_trigger": "cluster-robust Wald F p < 0.05",
        "partial_proportional_odds_fallback_required": bool(p_value < 0.05),
    }


def interval_row(
    estimate: float,
    gradient: np.ndarray,
    covariance: np.ndarray,
    influence: np.ndarray,
    webb_weights: np.ndarray,
    clusters: int,
) -> dict[str, Any]:
    variance = float(gradient @ covariance @ gradient)
    if variance < -1e-12:
        raise ValueError(f"Negative delta variance: {variance}")
    standard_error = math.sqrt(max(variance, 0.0))
    critical = t_critical_975(clusters - 1)
    cluster_influence = influence @ gradient
    draws = estimate + webb_weights @ cluster_influence
    percentile_low, percentile_high = np.quantile(draws, [0.025, 0.975])
    basic_low = 2.0 * estimate - percentile_high
    basic_high = 2.0 * estimate - percentile_low
    return {
        "estimate": float(estimate),
        "cluster_cr1_se": float(standard_error),
        "cluster_t_df": clusters - 1,
        "cluster_cr1_t_ci_low": float(estimate - critical * standard_error),
        "cluster_cr1_t_ci_high": float(estimate + critical * standard_error),
        "joint_webb_basic_ci_low": float(basic_low),
        "joint_webb_basic_ci_high": float(basic_high),
        "joint_webb_percentile_ci_low": float(percentile_low),
        "joint_webb_percentile_ci_high": float(percentile_high),
        "draws": draws,
        "cluster_influence": cluster_influence,
    }


def build_four_category_outcome(
    common: pd.DataFrame,
) -> tuple[np.ndarray, pd.DataFrame]:
    original = common[OUTCOME].to_numpy(dtype=np.float64)
    if not np.array_equal(original, original.astype(np.int64).astype(np.float64)):
        raise ValueError("Life-satisfaction outcome contains non-integer values")
    if np.any((original < 0) | (original > 10)):
        raise ValueError("Life-satisfaction outcome is outside 0 through 10")
    category = np.select(
        [original <= 4, original <= 6, original <= 8],
        [0, 1, 2],
        default=3,
    ).astype(np.int64)
    rural = common[EXPOSURE].to_numpy(dtype=np.float64)
    rows: list[dict[str, Any]] = []
    for definition in FOUR_CATEGORY_DEFINITIONS:
        value = int(definition["category"])
        mask = category == value
        rows.append(
            {
                **definition,
                "n": int(mask.sum()),
                "share": float(mask.mean()),
                "urban_n": int(np.sum(mask & (rural == 0))),
                "rural_n": int(np.sum(mask & (rural == 1))),
            }
        )
    audit = pd.DataFrame(rows)
    if int(audit["n"].sum()) != len(common):
        raise ValueError("Four-category audit does not cover the common sample")
    if tuple(sorted(np.unique(category))) != FOUR_CATEGORY_LEVELS:
        raise ValueError("Four-category outcome does not contain all four levels")
    return category, audit


def run_ordered_robustness(
    common: pd.DataFrame,
    ordered_outcome: np.ndarray,
    outcome_levels: tuple[int, ...],
    cutoff_labels: tuple[str, ...],
    outcome_encoding: str,
    analysis_role: str,
    bootstrap_repetitions: int,
    seed: int,
) -> dict[str, Any]:
    design_frame, design_metadata = make_full_design(
        common, include_place_fixed_effects=True
    )
    x = design_frame.to_numpy(dtype=np.float64)
    y_float = np.asarray(ordered_outcome, dtype=np.float64)
    if len(y_float) != len(common):
        raise ValueError("Ordered outcome length does not match common sample")
    y = y_float.astype(np.int64)
    if not np.array_equal(y_float, y.astype(np.float64)):
        raise ValueError("Ordered outcome contains non-integer values")
    if tuple(sorted(np.unique(y))) != outcome_levels:
        raise ValueError("Ordered outcome does not contain every declared level")
    n_cutpoints = len(outcome_levels) - 1
    if n_cutpoints < 2 or len(cutoff_labels) != n_cutpoints:
        raise ValueError("Invalid ordered outcome levels or cutoff labels")
    groups = common[PLACE].astype(int).to_numpy()
    clusters = len(np.unique(groups))
    rural_index = list(design_frame.columns).index(EXPOSURE)

    po_fit, po_thresholds = fit_proportional_odds(x, y, n_cutpoints)
    statsmodels_po = OrderedModel(y, x, distr="logit")
    statsmodels_log_likelihood = float(statsmodels_po.loglike(po_fit.params))
    statsmodels_probability = statsmodels_po.predict(po_fit.params)
    statsmodels_probability_row_sum_error = float(
        np.max(np.abs(statsmodels_probability.sum(axis=1) - 1.0))
    )
    x_one_crosscheck = x.copy()
    x_zero_crosscheck = x.copy()
    x_one_crosscheck[:, rural_index] = 1.0
    x_zero_crosscheck[:, rural_index] = 0.0
    statsmodels_expected_one = (
        statsmodels_po.predict(po_fit.params, exog=x_one_crosscheck)
        * np.arange(len(outcome_levels), dtype=np.float64)
    ).sum(axis=1)
    statsmodels_expected_zero = (
        statsmodels_po.predict(po_fit.params, exog=x_zero_crosscheck)
        * np.arange(len(outcome_levels), dtype=np.float64)
    ).sum(axis=1)
    statsmodels_ame = float(
        np.mean(statsmodels_expected_one - statsmodels_expected_zero)
    )
    po_cluster_scores, po_full_score = aggregate_po_cluster_scores(
        x, y, groups, po_fit.params, n_cutpoints
    )
    po_covariance, po_influence, po_cr1_correction = cr1_covariance(
        po_fit.hessian_inverse, po_cluster_scores, len(common)
    )

    rng = np.random.default_rng(seed)
    webb_weights = rng.choice(
        WEBB_SUPPORT, size=(bootstrap_repetitions, clusters)
    )
    rural_gradient = np.zeros(len(po_fit.params), dtype=np.float64)
    rural_gradient[rural_index] = 1.0
    rural_estimate = float(po_fit.params[rural_index])
    rural_interval = interval_row(
        rural_estimate,
        rural_gradient,
        po_covariance,
        po_influence,
        webb_weights,
        clusters,
    )
    po_ame, po_ame_gradient = expected_score_ame_po(
        x, rural_index, po_fit.params, n_cutpoints
    )
    po_ame_interval = interval_row(
        po_ame,
        po_ame_gradient,
        po_covariance,
        po_influence,
        webb_weights,
        clusters,
    )

    ppo_fit, z, ppo_thresholds_zero, ppo_thresholds_one = (
        fit_partial_proportional_odds(
            x, y, rural_index, po_fit, po_thresholds, n_cutpoints
        )
    )
    rural = x[:, rural_index]
    ppo_cluster_scores, ppo_full_score = aggregate_ppo_cluster_scores(
        z, y, rural, groups, ppo_fit.params, n_cutpoints
    )
    ppo_covariance, ppo_influence, ppo_cr1_correction = cr1_covariance(
        ppo_fit.hessian_inverse, ppo_cluster_scores, len(common)
    )
    gamma, gamma_jacobian, _, _ = ppo_rural_contrasts(
        ppo_fit.params, z.shape[1], n_cutpoints
    )
    gamma_covariance = gamma_jacobian @ ppo_covariance @ gamma_jacobian.T
    nonparallel_test = wald_nonparallel_test(
        gamma, gamma_covariance, clusters
    )
    ppo_ame, ppo_ame_gradient = expected_score_ame_ppo(
        z, ppo_fit.params, n_cutpoints
    )
    ppo_ame_interval = interval_row(
        ppo_ame,
        ppo_ame_gradient,
        ppo_covariance,
        ppo_influence,
        webb_weights,
        clusters,
    )

    critical = t_critical_975(clusters - 1)
    coefficient_rows: list[dict[str, Any]] = []
    for index, term in enumerate(design_frame.columns):
        standard_error = math.sqrt(max(float(po_covariance[index, index]), 0.0))
        estimate = float(po_fit.params[index])
        coefficient_rows.append(
            {
                "term": term,
                "estimate_log_odds": estimate,
                "cluster_cr1_se": standard_error,
                "cluster_t_df": clusters - 1,
                "cluster_cr1_t_ci_low": estimate - critical * standard_error,
                "cluster_cr1_t_ci_high": estimate + critical * standard_error,
                "proportional_odds_ratio": math.exp(estimate),
                "proportional_odds_ratio_ci_low": math.exp(
                    estimate - critical * standard_error
                ),
                "proportional_odds_ratio_ci_high": math.exp(
                    estimate + critical * standard_error
                ),
            }
        )
    coefficient_table = pd.DataFrame(coefficient_rows)

    q = po_fit.params[x.shape[1] :]
    threshold_jac = threshold_jacobian(q, n_cutpoints)
    threshold_gradient = np.zeros(
        (n_cutpoints, len(po_fit.params)), dtype=np.float64
    )
    threshold_gradient[:, x.shape[1] :] = threshold_jac
    threshold_covariance = threshold_gradient @ po_covariance @ threshold_gradient.T
    threshold_rows = []
    for cutoff, estimate in enumerate(po_thresholds):
        standard_error = math.sqrt(
            max(float(threshold_covariance[cutoff, cutoff]), 0.0)
        )
        threshold_rows.append(
            {
                "cutoff": cutoff_labels[cutoff],
                "threshold": float(estimate),
                "cluster_cr1_se": standard_error,
                "cluster_t_df": clusters - 1,
                "cluster_cr1_t_ci_low": float(estimate - critical * standard_error),
                "cluster_cr1_t_ci_high": float(estimate + critical * standard_error),
            }
        )
    threshold_table = pd.DataFrame(threshold_rows)

    ppo_rows = []
    for cutoff, estimate in enumerate(gamma):
        standard_error = math.sqrt(
            max(float(gamma_covariance[cutoff, cutoff]), 0.0)
        )
        ppo_rows.append(
            {
                "cutoff": cutoff_labels[cutoff],
                "rural_log_odds": float(estimate),
                "cluster_cr1_se": standard_error,
                "cluster_t_df": clusters - 1,
                "cluster_cr1_t_ci_low": float(estimate - critical * standard_error),
                "cluster_cr1_t_ci_high": float(estimate + critical * standard_error),
                "rural_odds_ratio": math.exp(float(estimate)),
                "rural_odds_ratio_ci_low": math.exp(
                    float(estimate - critical * standard_error)
                ),
                "rural_odds_ratio_ci_high": math.exp(
                    float(estimate + critical * standard_error)
                ),
            }
        )
    ppo_table = pd.DataFrame(ppo_rows)

    webb_table = pd.DataFrame(
        {
            "replicate": np.arange(1, bootstrap_repetitions + 1),
            "po_rural_log_odds_draw": rural_interval.pop("draws"),
            "po_expected_score_ame_draw": po_ame_interval.pop("draws"),
            "ppo_expected_score_ame_draw": ppo_ame_interval.pop("draws"),
        }
    )
    rural_interval.pop("cluster_influence")
    po_ame_interval.pop("cluster_influence")
    ppo_ame_interval.pop("cluster_influence")

    likelihood_ratio = 2.0 * (
        ppo_fit.log_likelihood - po_fit.log_likelihood
    )
    if likelihood_ratio < -1e-6:
        raise ValueError("Partial proportional-odds log likelihood is below PO")
    likelihood_ratio = max(likelihood_ratio, 0.0)
    fallback_required = nonparallel_test[
        "partial_proportional_odds_fallback_required"
    ]
    selected_ame = ppo_ame_interval if fallback_required else po_ame_interval
    selected_model = (
        "partial_proportional_odds_rural_nonparallel"
        if fallback_required
        else "proportional_odds"
    )
    summary = {
        "n": len(common),
        "clusters": clusters,
        "outcome_levels": list(outcome_levels),
        "outcome_encoding": outcome_encoding,
        "analysis_role": analysis_role,
        "place_fixed_effects": True,
        "full_specification": True,
        "cluster_inference": "CR1 finite-sample correction with t(G-1) coefficient intervals; joint Webb six-point cluster score bootstrap",
        "cr1_correction": po_cr1_correction,
        "po_optimizer": {
            "converged": po_fit.converged,
            "optimizer_success": po_fit.optimizer_success,
            "message": po_fit.optimizer_message,
            "iterations": po_fit.iterations,
            "function_evaluations": po_fit.function_evaluations,
            "gradient_max_abs": po_fit.gradient_max_abs,
            "gradient_max_abs_per_observation": po_fit.gradient_max_abs_per_observation,
            "newton_step_max_abs": po_fit.newton_step_max_abs,
            "newton_decrement_squared": po_fit.newton_decrement_squared,
            "aggregated_score_max_abs": float(np.max(np.abs(po_full_score))),
        },
        "po_diagnostics": {
            "log_likelihood": po_fit.log_likelihood,
            "minimum_fitted_probability": po_fit.minimum_fitted_probability,
            "hessian_min_eigenvalue": po_fit.hessian_min_eigenvalue,
            "hessian_max_eigenvalue": po_fit.hessian_max_eigenvalue,
            "hessian_condition_number": po_fit.hessian_condition_number,
            "hessian_symmetry_error_before_symmetrization": po_fit.hessian_symmetry_error,
            "hessian_inverse_error": po_fit.hessian_inverse_error,
        },
        "statsmodels_orderedmodel_crosscheck": {
            "statsmodels_log_likelihood": statsmodels_log_likelihood,
            "pipeline_log_likelihood": po_fit.log_likelihood,
            "absolute_log_likelihood_difference": abs(
                statsmodels_log_likelihood - po_fit.log_likelihood
            ),
            "maximum_probability_row_sum_error": statsmodels_probability_row_sum_error,
            "minimum_probability_across_all_categories": float(
                statsmodels_probability.min()
            ),
            "statsmodels_expected_score_ame": statsmodels_ame,
            "absolute_ame_difference": abs(statsmodels_ame - po_ame),
        },
        "po_rural_log_odds": rural_interval,
        "po_rural_odds_ratio": {
            "estimate": math.exp(rural_interval["estimate"]),
            "cluster_cr1_t_ci_low": math.exp(
                rural_interval["cluster_cr1_t_ci_low"]
            ),
            "cluster_cr1_t_ci_high": math.exp(
                rural_interval["cluster_cr1_t_ci_high"]
            ),
            "joint_webb_basic_ci_low": math.exp(
                rural_interval["joint_webb_basic_ci_low"]
            ),
            "joint_webb_basic_ci_high": math.exp(
                rural_interval["joint_webb_basic_ci_high"]
            ),
            "joint_webb_percentile_ci_low": math.exp(
                rural_interval["joint_webb_percentile_ci_low"]
            ),
            "joint_webb_percentile_ci_high": math.exp(
                rural_interval["joint_webb_percentile_ci_high"]
            ),
        },
        "po_expected_score_ame": po_ame_interval,
        "partial_proportional_odds_optimizer": {
            "converged": ppo_fit.converged,
            "optimizer_success": ppo_fit.optimizer_success,
            "message": ppo_fit.optimizer_message,
            "iterations": ppo_fit.iterations,
            "function_evaluations": ppo_fit.function_evaluations,
            "gradient_max_abs": ppo_fit.gradient_max_abs,
            "gradient_max_abs_per_observation": ppo_fit.gradient_max_abs_per_observation,
            "newton_step_max_abs": ppo_fit.newton_step_max_abs,
            "newton_decrement_squared": ppo_fit.newton_decrement_squared,
            "aggregated_score_max_abs": float(np.max(np.abs(ppo_full_score))),
            "cr1_correction": ppo_cr1_correction,
        },
        "partial_proportional_odds_diagnostics": {
            "log_likelihood": ppo_fit.log_likelihood,
            "minimum_fitted_probability": ppo_fit.minimum_fitted_probability,
            "hessian_min_eigenvalue": ppo_fit.hessian_min_eigenvalue,
            "hessian_max_eigenvalue": ppo_fit.hessian_max_eigenvalue,
            "hessian_condition_number": ppo_fit.hessian_condition_number,
            "hessian_symmetry_error_before_symmetrization": ppo_fit.hessian_symmetry_error,
            "hessian_inverse_error": ppo_fit.hessian_inverse_error,
            "likelihood_ratio_vs_po": likelihood_ratio,
            "likelihood_ratio_df": n_cutpoints - 1,
            "likelihood_ratio_chi_square_p_value_nonclustered": float(
                chi2.sf(likelihood_ratio, n_cutpoints - 1)
            ),
            "thresholds_rural_zero_strictly_increasing": bool(
                np.all(np.diff(ppo_thresholds_zero) > 0)
            ),
            "thresholds_rural_one_strictly_increasing": bool(
                np.all(np.diff(ppo_thresholds_one) > 0)
            ),
        },
        "proportional_odds_test": nonparallel_test,
        "ppo_rural_log_odds_min": float(gamma.min()),
        "ppo_rural_log_odds_max": float(gamma.max()),
        "ppo_expected_score_ame": ppo_ame_interval,
        "selected_ordered_model_for_robustness_interpretation": selected_model,
        "selected_expected_score_ame": selected_ame,
        "bootstrap_repetitions": bootstrap_repetitions,
        "bootstrap_seed": seed,
        "design": design_metadata,
        "interpretation": "cross-sectional robustness association; OLS remains primary",
    }
    return {
        "summary": summary,
        "coefficient_table": coefficient_table,
        "threshold_table": threshold_table,
        "ppo_table": ppo_table,
        "webb_table": webb_table,
    }


def run_multilevel_robustness(common: pd.DataFrame) -> dict[str, Any]:
    fixed_frame, design_metadata = make_full_design(
        common, include_place_fixed_effects=False
    )
    fixed_frame.insert(0, "Intercept", 1.0)
    x = fixed_frame.to_numpy(dtype=np.float64)
    y = common[OUTCOME].to_numpy(dtype=np.float64)
    groups = common[PLACE].astype(int).to_numpy()
    random_design = np.column_stack(
        [np.ones(len(common), dtype=np.float64), common[EXPOSURE].to_numpy(float)]
    )
    model = MixedLM(
        y,
        x,
        groups=groups,
        exog_re=random_design,
        use_sqrt=True,
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = model.fit(
            reml=False,
            method=["lbfgs", "bfgs", "cg"],
            maxiter=1_000,
            full_output=True,
            disp=False,
        )
    warning_messages = sorted({str(item.message) for item in caught})
    if not bool(result.converged):
        raise ValueError(
            "Random-intercept/rural-random-slope model did not converge: "
            + " | ".join(warning_messages)
        )

    fixed_names = list(fixed_frame.columns)
    rural_index = fixed_names.index(EXPOSURE)
    fixed_effects = np.asarray(result.fe_params, dtype=np.float64)
    fixed_standard_errors = np.asarray(result.bse_fe, dtype=np.float64)
    rural_estimate = float(fixed_effects[rural_index])
    rural_se = float(fixed_standard_errors[rural_index])
    critical = t_critical_975(EXPECTED_PLACES - 1)
    covariance_random = np.asarray(result.cov_re, dtype=np.float64)
    random_eigenvalues = np.linalg.eigvalsh(covariance_random)
    random_minimum = float(random_eigenvalues.min())
    random_maximum = float(random_eigenvalues.max())
    singularity_ratio = (
        0.0 if random_maximum <= 0 else random_minimum / random_maximum
    )
    singular = bool(random_minimum <= 1e-8 or singularity_ratio <= 1e-6)
    intercept_variance = float(covariance_random[0, 0])
    slope_variance = float(covariance_random[1, 1])
    covariance_intercept_slope = float(covariance_random[0, 1])
    if intercept_variance <= 0 or slope_variance <= 0:
        random_correlation = float("nan")
    else:
        random_correlation = covariance_intercept_slope / math.sqrt(
            intercept_variance * slope_variance
        )

    fixed_rows = []
    for name, estimate, standard_error in zip(
        fixed_names, fixed_effects, fixed_standard_errors
    ):
        fixed_rows.append(
            {
                "term": name,
                "estimate": float(estimate),
                "model_based_se": float(standard_error),
                "small_cluster_t_df": EXPECTED_PLACES - 1,
                "model_based_t_ci_low": float(estimate - critical * standard_error),
                "model_based_t_ci_high": float(estimate + critical * standard_error),
            }
        )
    fixed_table = pd.DataFrame(fixed_rows)

    random_rows = []
    crosswalk_names = (
        common[[PLACE, "country_name"]]
        .drop_duplicates()
        .set_index(PLACE)["country_name"]
        .to_dict()
    )
    random_effects = result.random_effects
    for group in sorted(random_effects, key=int):
        values = np.asarray(random_effects[group], dtype=np.float64)
        if len(values) != 2:
            raise ValueError("Expected two random effects per place")
        random_rows.append(
            {
                PLACE: int(group),
                "place_name": str(crosswalk_names[int(group)]),
                "random_intercept": float(values[0]),
                "random_rural_slope": float(values[1]),
                "place_specific_rural_slope": float(rural_estimate + values[1]),
            }
        )
    random_table = pd.DataFrame(random_rows)

    hessian_minimum_eigenvalue: float | None = None
    hessian_maximum_eigenvalue: float | None = None
    hessian_flag: bool | None = None
    score_max_abs: float | None = None
    try:
        hessian, hessian_flag = model.hessian(result.params_object)
        information_eigenvalues = np.linalg.eigvalsh(
            -(np.asarray(hessian, dtype=np.float64) + np.asarray(hessian).T) / 2.0
        )
        hessian_minimum_eigenvalue = float(information_eigenvalues.min())
        hessian_maximum_eigenvalue = float(information_eigenvalues.max())
        score = np.asarray(model.score(result.params_object), dtype=np.float64)
        score_max_abs = float(np.max(np.abs(score)))
    except Exception as exc:
        warning_messages.append(f"post-fit Hessian/score diagnostic unavailable: {exc}")

    history = getattr(result, "hist", None)
    optimizer_history = []
    if history:
        for item in history:
            optimizer_history.append(
                {
                    key: (
                        value.tolist()
                        if isinstance(value, np.ndarray)
                        else value.item()
                        if isinstance(value, np.generic)
                        else value
                    )
                    for key, value in item.items()
                }
            )

    summary = {
        "n": len(common),
        "places": int(len(np.unique(groups))),
        "estimator": "Gaussian linear mixed model fitted by maximum likelihood",
        "fixed_effects": [name for name in fixed_names if name != "Intercept"],
        "random_effects": "correlated place random intercept and rural random slope",
        "converged": bool(result.converged),
        "warnings": warning_messages,
        "optimizer_history": optimizer_history,
        "log_likelihood": float(result.llf),
        "aic": float(result.aic),
        "bic": float(result.bic),
        "residual_variance": float(result.scale),
        "residual_standard_deviation": math.sqrt(float(result.scale)),
        "random_intercept_variance": intercept_variance,
        "random_intercept_standard_deviation": math.sqrt(
            max(intercept_variance, 0.0)
        ),
        "random_rural_slope_variance": slope_variance,
        "random_rural_slope_standard_deviation": math.sqrt(
            max(slope_variance, 0.0)
        ),
        "random_intercept_slope_covariance": covariance_intercept_slope,
        "random_intercept_slope_correlation": random_correlation,
        "random_covariance_min_eigenvalue": random_minimum,
        "random_covariance_max_eigenvalue": random_maximum,
        "random_covariance_eigenvalue_ratio": singularity_ratio,
        "singular_random_effect_fit": singular,
        "fixed_rural_association": {
            "estimate": rural_estimate,
            "model_based_se": rural_se,
            "small_cluster_t_df": EXPECTED_PLACES - 1,
            "model_based_t_ci_low": rural_estimate - critical * rural_se,
            "model_based_t_ci_high": rural_estimate + critical * rural_se,
        },
        "place_specific_rural_slope_min": float(
            random_table["place_specific_rural_slope"].min()
        ),
        "place_specific_rural_slope_max": float(
            random_table["place_specific_rural_slope"].max()
        ),
        "place_specific_rural_slope_median": float(
            random_table["place_specific_rural_slope"].median()
        ),
        "postfit_information_min_eigenvalue": hessian_minimum_eigenvalue,
        "postfit_information_max_eigenvalue": hessian_maximum_eigenvalue,
        "postfit_hessian_singularity_flag": hessian_flag,
        "postfit_score_max_abs": score_max_abs,
        "design": design_metadata,
        "interpretation": "cross-sectional robustness and place-heterogeneity model; OLS with place fixed effects remains primary",
    }
    return {
        "summary": summary,
        "fixed_table": fixed_table,
        "random_table": random_table,
    }


def build_specification(
    data_path: Path,
    codebook_path: Path,
    crosswalk_path: Path,
    bootstrap_repetitions: int,
    seed: int,
) -> dict[str, Any]:
    return {
        "analysis_stage": "Batch A ordered-logit and multilevel robustness",
        "primary_model_unchanged": "OLS with absorbed place fixed effects and CR2/Satterthwaite inference",
        "sample": f"locked common complete-case sample, expected N={EXPECTED_COMMON_ROWS}",
        "outcome": OUTCOME,
        "outcome_scale": "integer scores 0 through 10; OLS remains on the original scale",
        "exposure": EXPOSURE,
        "controls": [
            "AGE_Y1",
            *CATEGORICAL_CONTROLS,
            "income_feelings_sec",
            "EXPENSES_Y1",
            "income_pctile",
            "social_capital_within_place",
        ],
        "ordered_logit": {
            "primary_outcome_encoding": "four ordered categories: 0-4 Low, 5-6 Moderate, 7-8 High, and 9-10 Very high",
            "primary_robustness_specification": "four-category proportional-odds logit with explicit place fixed effects",
            "inference": "place-cluster CR1 with t(G-1), plus joint Webb six-point cluster score bootstrap",
            "reported_scales": [
                "proportional odds ratio for a higher four-category life-satisfaction level",
                "average discrete change in expected four-category score when rural changes 0 to 1",
            ],
            "proportional_odds_diagnostic": "cluster-robust Wald F test of equality of the rural cumulative-logit coefficients",
            "fallback": "partial proportional-odds model with rural-specific ordered cutpoints; all other slopes remain proportional",
            "fallback_rule": "use the partial proportional-odds expected-score contrast if cluster-robust Wald F p < 0.05",
            "original_scale_sensitivity": "repeat the proportional-odds diagnostic and partial proportional-odds fallback on all eleven original categories 0 through 10",
            "binary_recoding": "not used",
        },
        "multilevel": {
            "estimator": "Gaussian linear mixed model by maximum likelihood",
            "fixed_specification": "same full covariate specification as primary M4, without place fixed-effect dummies",
            "random_structure": "correlated random intercept and rural random slope by place",
            "fixed_rural_interval": "model-based standard error with t(G-1) critical value",
            "role": "robustness and place heterogeneity; not the primary model",
        },
        "bootstrap_repetitions": bootstrap_repetitions,
        "bootstrap_seed": seed,
        "source_paths": {
            "processed_data": str(data_path),
            "codebook": str(codebook_path),
            "place_crosswalk": str(crosswalk_path),
            "core_analysis_script": str(CORE_SCRIPT),
            "robustness_script": str(ROBUSTNESS_SCRIPT),
        },
        "forbidden_interpretations": [
            "causal effect",
            "causal mediation",
            "partial mediation",
            "full mediation",
        ],
    }


def ordered_validation_gates(
    prefix: str,
    ordered_results: dict[str, Any],
    bootstrap_repetitions: int,
) -> dict[str, bool]:
    summary = ordered_results["summary"]
    return {
        f"{prefix}_po_converged": summary["po_optimizer"]["converged"],
        f"{prefix}_po_score_small": summary["po_optimizer"][
            "gradient_max_abs_per_observation"
        ]
        <= 1e-6
        and summary["po_optimizer"]["newton_step_max_abs"] <= 5e-3
        and summary["po_optimizer"]["newton_decrement_squared"] <= 1e-3,
        f"{prefix}_po_hessian_positive_definite": summary["po_diagnostics"][
            "hessian_min_eigenvalue"
        ]
        > 0,
        f"{prefix}_probabilities_positive": summary["po_diagnostics"][
            "minimum_fitted_probability"
        ]
        > 0,
        f"{prefix}_statsmodels_exact_crosscheck": summary[
            "statsmodels_orderedmodel_crosscheck"
        ]["absolute_log_likelihood_difference"]
        <= 1e-8
        and summary["statsmodels_orderedmodel_crosscheck"][
            "maximum_probability_row_sum_error"
        ]
        <= 1e-12
        and summary["statsmodels_orderedmodel_crosscheck"][
            "absolute_ame_difference"
        ]
        <= 1e-10,
        f"{prefix}_partial_po_converged": summary[
            "partial_proportional_odds_optimizer"
        ]["converged"],
        f"{prefix}_partial_po_score_small": summary[
            "partial_proportional_odds_optimizer"
        ]["gradient_max_abs_per_observation"]
        <= 1e-6
        and summary["partial_proportional_odds_optimizer"][
            "newton_step_max_abs"
        ]
        <= 5e-3
        and summary["partial_proportional_odds_optimizer"][
            "newton_decrement_squared"
        ]
        <= 1e-3,
        f"{prefix}_partial_po_hessian_positive_definite": summary[
            "partial_proportional_odds_diagnostics"
        ]["hessian_min_eigenvalue"]
        > 0,
        f"{prefix}_partial_po_ordered_thresholds": summary[
            "partial_proportional_odds_diagnostics"
        ]["thresholds_rural_zero_strictly_increasing"]
        and summary["partial_proportional_odds_diagnostics"][
            "thresholds_rural_one_strictly_increasing"
        ],
        f"{prefix}_proportional_odds_test_computed": math.isfinite(
            summary["proportional_odds_test"]["cluster_robust_p_value"]
        ),
        f"{prefix}_selected_ame_finite": math.isfinite(
            summary["selected_expected_score_ame"]["estimate"]
        ),
        f"{prefix}_bootstrap_complete": len(ordered_results["webb_table"])
        == bootstrap_repetitions,
    }


def write_outputs(
    output_dir: Path,
    specification: dict[str, Any],
    primary_ordered_results: dict[str, Any],
    sensitivity_ordered_results: dict[str, Any],
    category_audit: pd.DataFrame,
    multilevel_results: dict[str, Any],
    source_audit: dict[str, Any],
    sample_audit: dict[str, Any],
    data_path: Path,
    codebook_path: Path,
    crosswalk_path: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        specification, output_dir / "robustness_model_specification.json"
    )
    atomic_write_json(
        primary_ordered_results["summary"],
        output_dir / "ordered_logit_summary.json",
    )
    atomic_write_csv(
        primary_ordered_results["coefficient_table"],
        output_dir / "ordered_logit_coefficients.csv",
    )
    atomic_write_csv(
        primary_ordered_results["threshold_table"],
        output_dir / "ordered_logit_thresholds.csv",
    )
    atomic_write_csv(
        primary_ordered_results["ppo_table"],
        output_dir / "ordered_logit_nonparallel_rural.csv",
    )
    atomic_write_csv(
        primary_ordered_results["webb_table"],
        output_dir / "ordered_logit_webb_draws.csv",
    )
    atomic_write_csv(category_audit, output_dir / "ordered_logit_category_audit.csv")
    atomic_write_json(
        sensitivity_ordered_results["summary"],
        output_dir / "ordered_logit_11cat_sensitivity_summary.json",
    )
    atomic_write_csv(
        sensitivity_ordered_results["coefficient_table"],
        output_dir / "ordered_logit_11cat_sensitivity_coefficients.csv",
    )
    atomic_write_csv(
        sensitivity_ordered_results["threshold_table"],
        output_dir / "ordered_logit_11cat_sensitivity_thresholds.csv",
    )
    atomic_write_csv(
        sensitivity_ordered_results["ppo_table"],
        output_dir / "ordered_logit_11cat_sensitivity_nonparallel_rural.csv",
    )
    atomic_write_csv(
        sensitivity_ordered_results["webb_table"],
        output_dir / "ordered_logit_11cat_sensitivity_webb_draws.csv",
    )
    atomic_write_json(
        multilevel_results["summary"], output_dir / "multilevel_summary.json"
    )
    atomic_write_csv(
        multilevel_results["fixed_table"],
        output_dir / "multilevel_fixed_effects.csv",
    )
    atomic_write_csv(
        multilevel_results["random_table"],
        output_dir / "multilevel_place_random_effects.csv",
    )

    core_manifest_path = output_dir / "run_manifest.json"
    if not core_manifest_path.is_file():
        raise FileNotFoundError(
            "Validated OLS/path core manifest is required before robustness output"
        )
    core_manifest = json.loads(core_manifest_path.read_text(encoding="utf-8"))
    primary_ols_table = pd.read_csv(output_dir / "ols_sequence_rural.csv")
    primary_ols = primary_ols_table.loc[
        primary_ols_table["scenario"].eq("primary_common_unweighted")
        & primary_ols_table["model"].eq("M4_full")
    ]
    if len(primary_ols) != 1:
        raise ValueError("Cannot identify the unique primary M4 OLS estimate")
    primary_ols_estimate = float(primary_ols.iloc[0]["rural_estimate"])

    primary_ordered_summary = primary_ordered_results["summary"]
    sensitivity_ordered_summary = sensitivity_ordered_results["summary"]
    multilevel_summary = multilevel_results["summary"]
    output_names = [
        "robustness_model_specification.json",
        "ordered_logit_summary.json",
        "ordered_logit_coefficients.csv",
        "ordered_logit_thresholds.csv",
        "ordered_logit_nonparallel_rural.csv",
        "ordered_logit_webb_draws.csv",
        "ordered_logit_category_audit.csv",
        "ordered_logit_11cat_sensitivity_summary.json",
        "ordered_logit_11cat_sensitivity_coefficients.csv",
        "ordered_logit_11cat_sensitivity_thresholds.csv",
        "ordered_logit_11cat_sensitivity_nonparallel_rural.csv",
        "ordered_logit_11cat_sensitivity_webb_draws.csv",
        "multilevel_summary.json",
        "multilevel_fixed_effects.csv",
        "multilevel_place_random_effects.csv",
    ]
    output_files = [output_dir / name for name in output_names]
    validation_gates = {
        "core_manifest_validated": core_manifest.get("status")
        == "validated_ols_path_and_sensitivity_outputs"
        and all(core_manifest.get("validation_gates", {}).values()),
        "source_hash_matches_core": core_manifest["source_hashes"][
            "processed_data"
        ]
        == sha256(data_path),
        "locked_common_n": sample_audit["common_sample_n"]
        == EXPECTED_COMMON_ROWS,
        "all_places_retained": sample_audit["common_sample_place_count"]
        == EXPECTED_PLACES,
        "four_category_audit_complete": len(category_audit) == 4
        and int(category_audit["n"].sum()) == EXPECTED_COMMON_ROWS
        and bool((category_audit["n"] > 0).all()),
        **ordered_validation_gates(
            "four_category_ordered",
            primary_ordered_results,
            specification["bootstrap_repetitions"],
        ),
        **ordered_validation_gates(
            "eleven_category_sensitivity",
            sensitivity_ordered_results,
            specification["bootstrap_repetitions"],
        ),
        "multilevel_converged": multilevel_summary["converged"],
        "multilevel_random_effects_complete": len(
            multilevel_results["random_table"]
        )
        == EXPECTED_PLACES,
        "multilevel_random_covariance_valid": multilevel_summary[
            "random_covariance_min_eigenvalue"
        ]
        >= -1e-10,
        "primary_ols_unchanged_and_finite": math.isfinite(primary_ols_estimate),
    }
    if not all(validation_gates.values()):
        failed = [name for name, passed in validation_gates.items() if not passed]
        raise ValueError(f"Robustness validation gates failed: {failed}")

    selected_ordered_ame = primary_ordered_summary[
        "selected_expected_score_ame"
    ]["estimate"]
    sensitivity_selected_ame = sensitivity_ordered_summary[
        "selected_expected_score_ame"
    ]["estimate"]
    multilevel_estimate = multilevel_summary["fixed_rural_association"][
        "estimate"
    ]
    manifest = {
        "status": "validated_four_category_ordered_eleven_category_sensitivity_and_multilevel_robustness",
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": scipy.__version__,
            "statsmodels": statsmodels.__version__,
        },
        "source_hashes": {
            "processed_data": sha256(data_path),
            "codebook": sha256(codebook_path),
            "place_crosswalk": sha256(crosswalk_path),
            "core_analysis_script": sha256(CORE_SCRIPT),
            "robustness_script": sha256(ROBUSTNESS_SCRIPT),
            "core_manifest": sha256(core_manifest_path),
        },
        "outputs": {
            path.name: {"sha256": sha256(path), "bytes": path.stat().st_size}
            for path in output_files
        },
        "validation_gates": validation_gates,
        "comparison": {
            "primary_ols_rural_estimate_0_to_10_points": primary_ols_estimate,
            "selected_four_category_expected_score_ame_0_to_3_categories": selected_ordered_ame,
            "selected_eleven_category_sensitivity_expected_score_ame_0_to_10_points": sensitivity_selected_ame,
            "multilevel_fixed_rural_estimate_0_to_10_points": multilevel_estimate,
            "four_category_ordered_direction_matches_ols": bool(
                np.sign(selected_ordered_ame) == np.sign(primary_ols_estimate)
            ),
            "eleven_category_sensitivity_direction_matches_ols": bool(
                np.sign(sensitivity_selected_ame)
                == np.sign(primary_ols_estimate)
            ),
            "multilevel_direction_matches_ols": bool(
                np.sign(multilevel_estimate) == np.sign(primary_ols_estimate)
            ),
        },
        "scope_gate": "Four-category ordered robustness, eleven-category ordered sensitivity, and multilevel robustness are computationally validated; manuscript, response, tables, and figures remain untouched pending result interpretation and revision routing.",
        "source_audit": {
            "source_rows": source_audit["source_rows"],
            "place_count": source_audit["place_count"],
        },
    }
    atomic_write_json(manifest, output_dir / "robustness_manifest.json")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write validated robustness outputs under reports/batch_a_core",
    )
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--codebook", type=Path, default=DEFAULT_CODEBOOK)
    parser.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--bootstrap-repetitions", type=int, default=4_999)
    parser.add_argument("--seed", type=int, default=20_260_825)
    args = parser.parse_args()

    data_path = args.data.resolve()
    codebook_path = args.codebook.resolve()
    crosswalk_path = args.crosswalk.resolve()
    output_dir = args.output_dir.resolve()
    for path in (data_path, codebook_path, crosswalk_path, CORE_SCRIPT):
        if not path.is_file():
            raise FileNotFoundError(path)

    frame, _, source_audit = load_and_validate_source(data_path, crosswalk_path)
    common, _, sample_audit = build_common_sample(frame)
    specification = build_specification(
        data_path,
        codebook_path,
        crosswalk_path,
        args.bootstrap_repetitions,
        args.seed,
    )
    four_category_outcome, category_audit = build_four_category_outcome(common)
    primary_ordered_results = run_ordered_robustness(
        common,
        four_category_outcome,
        FOUR_CATEGORY_LEVELS,
        FOUR_CATEGORY_CUTOFF_LABELS,
        "0-4 Low; 5-6 Moderate; 7-8 High; 9-10 Very high",
        "primary ordinal robustness analysis",
        args.bootstrap_repetitions,
        args.seed,
    )
    original_outcome = common[OUTCOME].to_numpy(dtype=np.float64)
    sensitivity_ordered_results = run_ordered_robustness(
        common,
        original_outcome,
        ORIGINAL_OUTCOME_LEVELS,
        tuple(f"{cutoff}|{cutoff + 1}" for cutoff in range(10)),
        "eleven original categories 0 through 10",
        "original-scale ordinal sensitivity analysis",
        args.bootstrap_repetitions,
        args.seed,
    )
    multilevel_results = run_multilevel_robustness(common)
    summary = {
        "mode": "apply" if args.apply else "dry-run",
        "common_n": sample_audit["common_sample_n"],
        "places": sample_audit["common_sample_place_count"],
        "primary_model": "OLS remains primary",
        "four_category_ordered": primary_ordered_results["summary"],
        "eleven_category_ordered_sensitivity": sensitivity_ordered_results[
            "summary"
        ],
        "four_category_audit": category_audit.to_dict(orient="records"),
        "multilevel": multilevel_results["summary"],
    }
    if args.apply:
        manifest = write_outputs(
            output_dir,
            specification,
            primary_ordered_results,
            sensitivity_ordered_results,
            category_audit,
            multilevel_results,
            source_audit,
            sample_audit,
            data_path,
            codebook_path,
            crosswalk_path,
        )
        summary["output_dir"] = str(output_dir)
        summary["validation_gates"] = manifest["validation_gates"]
        summary["comparison"] = manifest["comparison"]
    print(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
