#!/usr/bin/env python3
"""Run the locked Batch A OLS/path core and prespecified sensitivities.

The script is deliberately bounded to the OLS/path Batch A analysis gate. It
does not alter source or processed data, manuscript DOCX files, figures, or the
response draft. With ``--apply`` it writes auditable intermediate outputs under
``reports/batch_a_core``.

Primary specification
---------------------
* Common complete-case sample across the outcome, exposure, four mediators,
  controls, place identifier, and the three social-capital components.
* Four parallel mediators: income security feelings, expense security,
  within-place income percentile, and a place-standardized social-capital
  index.
* The trust component is reverse-coded from the codebook's 1=all to 5=none
  scale before standardization, so every component points toward more social
  capital.
* OLS with absorbed place fixed effects in every equation.
* Joint CR2-adjusted, place-clustered covariance for focal path parameters.
* Joint Webb wild-cluster score bootstrap using the same place weights across
  all equations for direct and indirect-association intervals.
* A four-model descriptive OLS sequence with place fixed effects in every
  model, plus pooled-SCI, place-by-rural/urban-income-rank, available-case, and
  survey-weight sensitivity specifications.

The path language is associational because the underlying data are
cross-sectional.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = PROJECT_ROOT / "data/processed/gfs_cleaned.parquet"
DEFAULT_CODEBOOK = PROJECT_ROOT / "data/raw/GFS_Codebook_20240208.pdf"
DEFAULT_CROSSWALK = PROJECT_ROOT / "etc/place_crosswalk.csv"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports/batch_a_core"

EXPECTED_SOURCE_ROWS = 207_919
EXPECTED_COMMON_ROWS = 183_685
EXPECTED_PLACES = 23
EXPECTED_CHINA_CODE = 25
EXPECTED_CHINA_LABEL = "China"
EXPECTED_HONG_KONG_CODE = 24
EXPECTED_HONG_KONG_LABEL = "Hong Kong"

OUTCOME = "LIFE_SAT_Y1"
EXPOSURE = "rural_binary"
PLACE = "COUNTRY"
WEIGHT = "ANNUAL_WEIGHT_C1"
RAW_MEDIATOR_COLUMNS = (
    "income_feelings_sec",
    "EXPENSES_Y1",
    "income_pctile",
    "PEOPLE_HELP_Y1",
    "close_to_bin",
    "TRUST_PEOPLE_Y1",
)
CATEGORICAL_CONTROLS = (
    "GENDER",
    "MARITAL_STATUS_Y1",
    "EMPLOYMENT_Y1",
    "EDUCATION_3_Y1",
)
REQUIRED_COLUMNS = (
    "ID",
    PLACE,
    "country_name",
    OUTCOME,
    EXPOSURE,
    "INCOME_FEELINGS_Y1",
    "income_feelings_sec",
    "EXPENSES_Y1",
    "INCOME_Y1",
    "income_pctile",
    "PEOPLE_HELP_Y1",
    "CLOSE_TO_Y1",
    "close_to_bin",
    "TRUST_PEOPLE_Y1",
    "social_capital_idx",
    WEIGHT,
    "AGE_Y1",
    *CATEGORICAL_CONTROLS,
)
COMMON_SAMPLE_COLUMNS = (
    OUTCOME,
    EXPOSURE,
    "income_feelings_sec",
    "EXPENSES_Y1",
    "income_pctile",
    "PEOPLE_HELP_Y1",
    "close_to_bin",
    "TRUST_PEOPLE_Y1",
    "AGE_Y1",
    *CATEGORICAL_CONTROLS,
    PLACE,
)
MEDIATOR_NAMES = (
    "income_security_feelings",
    "expense_security",
    "income_percentile_within_place",
    "social_capital_within_place",
)
WEBB_SUPPORT = np.array(
    [
        -math.sqrt(3.0 / 2.0),
        -1.0,
        -math.sqrt(1.0 / 2.0),
        math.sqrt(1.0 / 2.0),
        1.0,
        math.sqrt(3.0 / 2.0),
    ],
    dtype=np.float64,
)


@dataclass
class OLSResult:
    beta: np.ndarray
    residual: np.ndarray
    inv_xtx: np.ndarray
    rank: int
    condition_number: float


@dataclass
class CR2Result:
    influence: np.ndarray
    satterthwaite_df: np.ndarray
    max_cluster_leverage: float
    min_one_minus_leverage: float


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value)!r}")


def atomic_write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{path.stem}.",
        suffix=".json",
        dir=path.parent,
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(payload, handle, indent=2, sort_keys=True, default=_json_default)
        handle.write("\n")
    try:
        json.loads(temp_path.read_text(encoding="utf-8"))
        os.replace(temp_path, path)
        path.chmod(0o644)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def atomic_write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f".{path.stem}.",
        suffix=".csv",
        dir=path.parent,
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
    try:
        frame.to_csv(temp_path, index=False)
        check = pd.read_csv(temp_path)
        if check.shape != frame.shape:
            raise ValueError(f"Temporary CSV validation failed for {path.name}")
        os.replace(temp_path, path)
        path.chmod(0o644)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def validate_crosswalk(path: Path, observed_codes: set[int]) -> pd.DataFrame:
    crosswalk = pd.read_csv(path)
    expected_columns = ["COUNTRY", "place_name", "unit_type"]
    if list(crosswalk.columns) != expected_columns:
        raise ValueError(f"Crosswalk columns must be exactly {expected_columns}")
    if len(crosswalk) != EXPECTED_PLACES:
        raise ValueError(f"Expected {EXPECTED_PLACES} crosswalk rows")
    if crosswalk["COUNTRY"].duplicated().any():
        raise ValueError("Crosswalk COUNTRY codes are not unique")
    crosswalk_codes = set(crosswalk["COUNTRY"].astype(int))
    if crosswalk_codes != observed_codes:
        raise ValueError(
            "Crosswalk codes differ from processed data: "
            f"crosswalk={sorted(crosswalk_codes)}, data={sorted(observed_codes)}"
        )
    labels = crosswalk.set_index("COUNTRY")["place_name"]
    unit_types = crosswalk.set_index("COUNTRY")["unit_type"]
    if labels.get(EXPECTED_CHINA_CODE) != EXPECTED_CHINA_LABEL:
        raise ValueError("COUNTRY=25 must map to China")
    if labels.get(EXPECTED_HONG_KONG_CODE) != EXPECTED_HONG_KONG_LABEL:
        raise ValueError("COUNTRY=24 must map to Hong Kong")
    if unit_types.get(EXPECTED_HONG_KONG_CODE) != "region":
        raise ValueError("Hong Kong must be classified as a region")
    return crosswalk


def load_and_validate_source(
    data_path: Path, crosswalk_path: Path
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    frame = pd.read_parquet(data_path)
    missing = set(REQUIRED_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"Processed data missing columns: {sorted(missing)}")
    if len(frame) != EXPECTED_SOURCE_ROWS:
        raise ValueError(
            f"Expected {EXPECTED_SOURCE_ROWS:,} source rows, found {len(frame):,}"
        )

    observed_codes = set(frame[PLACE].dropna().astype(int).unique())
    crosswalk = validate_crosswalk(crosswalk_path, observed_codes)
    canonical = frame[PLACE].map(crosswalk.set_index("COUNTRY")["place_name"])
    if not frame["country_name"].astype(str).equals(canonical.astype(str)):
        mismatch = frame.loc[
            frame["country_name"].astype(str).ne(canonical.astype(str)),
            [PLACE, "country_name"],
        ]
        raise ValueError(
            "Processed place labels differ from the canonical crosswalk: "
            f"{mismatch.drop_duplicates().to_dict(orient='records')}"
        )

    recomputed_pctile = frame.groupby(PLACE, sort=False)["INCOME_Y1"].rank(
        pct=True, na_option="keep"
    )
    valid_pctile = frame["income_pctile"].notna() & recomputed_pctile.notna()
    pctile_diff = (
        frame.loc[valid_pctile, "income_pctile"] - recomputed_pctile.loc[valid_pctile]
    ).abs()
    max_pctile_diff = float(pctile_diff.max())
    if max_pctile_diff > 1e-12:
        raise ValueError(
            "income_pctile is not the reproducible within-place rank; "
            f"max absolute difference={max_pctile_diff:.3g}"
        )

    frame = frame.copy()
    frame["income_pctile_place_rural"] = frame.groupby(
        [PLACE, EXPOSURE], sort=False, dropna=False
    )["INCOME_Y1"].rank(pct=True, na_option="keep")

    audit = {
        "source_rows": len(frame),
        "source_columns": len(frame.columns) - 1,
        "place_count": len(observed_codes),
        "source_data_sha256": sha256(data_path),
        "crosswalk_sha256": sha256(crosswalk_path),
        "within_place_income_percentile_max_abs_reproduction_error": max_pctile_diff,
        "country_25_rows": int(frame[PLACE].eq(EXPECTED_CHINA_CODE).sum()),
        "country_25_label": EXPECTED_CHINA_LABEL,
        "hong_kong_rows": int(frame[PLACE].eq(EXPECTED_HONG_KONG_CODE).sum()),
        "hong_kong_unit_type": "region",
        "survey_weight_missing": int(frame[WEIGHT].isna().sum()),
        "survey_weight_nonpositive": int(frame[WEIGHT].le(0).sum()),
        "survey_weight_min": float(frame[WEIGHT].min()),
        "survey_weight_max": float(frame[WEIGHT].max()),
        "survey_weight_mean": float(frame[WEIGHT].mean()),
    }
    return frame, crosswalk, audit


def build_common_sample(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    missing_counts = frame[list(COMMON_SAMPLE_COLUMNS)].isna().sum().astype(int)
    common = frame.dropna(subset=list(COMMON_SAMPLE_COLUMNS)).copy()
    if len(common) != EXPECTED_COMMON_ROWS:
        raise ValueError(
            f"Expected locked common N={EXPECTED_COMMON_ROWS:,}, found {len(common):,}"
        )
    if common[PLACE].nunique() != EXPECTED_PLACES:
        raise ValueError("The common sample must retain all 23 places")

    income_recode_error = (
        common["income_feelings_sec"] - (5.0 - common["INCOME_FEELINGS_Y1"])
    ).abs().max()
    close_recode_error = (
        common["close_to_bin"] - common["CLOSE_TO_Y1"].map({1.0: 1.0, 2.0: 0.0})
    ).abs().max()
    if float(income_recode_error) > 1e-12:
        raise ValueError("income_feelings_sec is not the exact reverse-coded source scale")
    if float(close_recode_error) > 1e-12:
        raise ValueError("close_to_bin is not the exact 1=Yes, 2=No recode")

    common["trust_people_sec"] = 6.0 - common["TRUST_PEOPLE_Y1"]
    component_columns = ("PEOPLE_HELP_Y1", "close_to_bin", "trust_people_sec")
    within_z_columns: list[str] = []
    pooled_z_columns: list[str] = []
    for column in component_columns:
        within_name = f"z_place__{column}"
        pooled_name = f"z_pooled__{column}"
        grouped = common.groupby(PLACE, sort=False)[column]
        group_mean = grouped.transform("mean")
        group_sd = grouped.transform("std")
        if group_sd.le(0).any():
            raise ValueError(f"A place has zero variance in {column}")
        common[within_name] = (common[column] - group_mean) / group_sd
        common[pooled_name] = (common[column] - common[column].mean()) / column_sd(
            common[column]
        )
        within_z_columns.append(within_name)
        pooled_z_columns.append(pooled_name)

    common["social_capital_within_place"] = common[within_z_columns].mean(axis=1)
    common["social_capital_pooled_corrected"] = common[pooled_z_columns].mean(axis=1)

    component_checks: dict[str, dict[str, float]] = {}
    for column in within_z_columns:
        grouped_z = common.groupby(PLACE, sort=False)[column]
        component_checks[column] = {
            "max_abs_place_mean": float(grouped_z.mean().abs().max()),
            "max_abs_place_sd_minus_one": float((grouped_z.std() - 1.0).abs().max()),
        }
        if component_checks[column]["max_abs_place_mean"] > 1e-12:
            raise ValueError(f"Within-place standardization mean check failed for {column}")
        if component_checks[column]["max_abs_place_sd_minus_one"] > 1e-12:
            raise ValueError(f"Within-place standardization SD check failed for {column}")

    place_rows = (
        common.groupby([PLACE, "country_name"], sort=True)
        .agg(
            common_n=("ID", "size"),
            rural_share=(EXPOSURE, "mean"),
            life_satisfaction_mean=(OUTCOME, "mean"),
            income_security_feelings_mean=("income_feelings_sec", "mean"),
            expense_security_mean=("EXPENSES_Y1", "mean"),
            income_percentile_mean=("income_pctile", "mean"),
            social_capital_mean=("social_capital_within_place", "mean"),
        )
        .reset_index()
    )

    audit = {
        "common_sample_n": len(common),
        "common_sample_share": len(common) / len(frame),
        "common_sample_place_count": int(common[PLACE].nunique()),
        "smallest_place_n": int(place_rows["common_n"].min()),
        "largest_place_n": int(place_rows["common_n"].max()),
        "missing_counts_before_complete_case": missing_counts.to_dict(),
        "variable_direction_checks": {
            "income_feelings_sec_exact_reverse_code": bool(income_recode_error <= 1e-12),
            "income_feelings_direction": "higher = more financially secure",
            "expense_security_codebook_endpoints": "0 = worry all the time; 10 = do not ever worry",
            "expense_security_direction": "higher = more financially secure",
            "income_percentile_direction": "higher = higher bracket rank within place",
            "people_help_codebook_endpoints": "0 = never; 10 = always",
            "close_to_bin_exact_recode": bool(close_recode_error <= 1e-12),
            "trust_people_original_endpoints": "1 = all; 5 = none",
            "trust_people_correction": "trust_people_sec = 6 - TRUST_PEOPLE_Y1",
            "social_capital_direction": "higher = stronger social capital for every component",
            "life_satisfaction_codebook_endpoints": "0 = not at all satisfied; 10 = completely satisfied",
        },
        "within_place_component_z_checks": component_checks,
        "old_vs_corrected_social_capital_correlation": float(
            common["social_capital_idx"].corr(common["social_capital_within_place"])
        ),
        "primary_vs_place_rural_income_percentile_correlation": float(
            common["income_pctile"].corr(common["income_pctile_place_rural"])
        ),
    }
    return common, place_rows, audit


def column_sd(series: pd.Series) -> float:
    value = float(series.std(ddof=1))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"Invalid standard deviation for {series.name}: {value}")
    return value


def normalized_analysis_weights(
    data: pd.DataFrame, weights: pd.Series | None
) -> pd.Series | None:
    if weights is None:
        return None
    aligned = weights.reindex(data.index).astype(np.float64)
    if aligned.isna().any() or not np.isfinite(aligned.to_numpy()).all():
        raise ValueError("Analysis weights contain missing or non-finite values")
    if aligned.le(0).any():
        raise ValueError("Analysis weights must be strictly positive")
    return aligned / float(aligned.mean())


def make_predictor_design(
    data: pd.DataFrame,
    continuous_columns: list[str],
    categorical_columns: tuple[str, ...],
    weights: pd.Series | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    parts = [data[continuous_columns].astype(np.float64).copy()]
    references: dict[str, int] = {}
    for column in categorical_columns:
        values = sorted(int(value) for value in data[column].unique())
        references[column] = values[0]
        categorical = pd.Categorical(data[column].astype(int), categories=values)
        dummies = pd.get_dummies(
            categorical,
            prefix=column,
            prefix_sep="__",
            drop_first=True,
            dtype=np.float64,
        )
        dummies.index = data.index
        parts.append(dummies)
    raw = pd.concat(parts, axis=1)
    if raw.columns.duplicated().any():
        raise ValueError("Duplicate design-matrix column names")
    normalized_weights = normalized_analysis_weights(data, weights)
    within = within_transform(raw, data[PLACE], normalized_weights)
    if normalized_weights is None:
        mean_check = within.groupby(data[PLACE], sort=False).mean()
        absorption = "unweighted within-place demeaning"
    else:
        weighted = within.mul(normalized_weights, axis=0)
        mean_check = weighted.groupby(data[PLACE], sort=False).sum().div(
            normalized_weights.groupby(data[PLACE], sort=False).sum(), axis=0
        )
        absorption = "survey-weighted within-place demeaning"
    max_abs_place_mean = float(mean_check.abs().to_numpy().max())
    if max_abs_place_mean > 1e-11:
        raise ValueError("Absorbed fixed-effect design does not have zero place means")
    metadata = {
        "design_columns": list(raw.columns),
        "categorical_reference_codes": references,
        "place_fixed_effects": f"absorbed by {absorption}",
        "max_abs_within_design_place_mean": max_abs_place_mean,
    }
    return within, metadata


def make_base_design(
    common: pd.DataFrame, weights: pd.Series | None = None
) -> tuple[pd.DataFrame, dict[str, Any]]:
    within, metadata = make_predictor_design(
        common,
        [EXPOSURE, "AGE_Y1"],
        CATEGORICAL_CONTROLS,
        weights,
    )
    metadata["base_design_columns"] = metadata.pop("design_columns")
    return within, metadata


def within_transform(
    frame: pd.DataFrame,
    groups: pd.Series,
    weights: pd.Series | None = None,
) -> pd.DataFrame:
    numeric = frame.astype(np.float64)
    if weights is None:
        location = numeric.groupby(groups, sort=False).transform("mean")
        within = numeric - location
        mean_check = within.groupby(groups, sort=False).mean()
    else:
        aligned = weights.reindex(frame.index).astype(np.float64)
        group_weight = aligned.groupby(groups, sort=False).transform("sum")
        weighted_sum = numeric.mul(aligned, axis=0).groupby(
            groups, sort=False
        ).transform("sum")
        location = weighted_sum.div(group_weight, axis=0)
        within = numeric - location
        mean_check = within.mul(aligned, axis=0).groupby(
            groups, sort=False
        ).sum().div(aligned.groupby(groups, sort=False).sum(), axis=0)
    max_abs_mean = float(mean_check.abs().to_numpy().max())
    if max_abs_mean > 1e-11:
        raise ValueError(f"Within transformation failed: max place mean={max_abs_mean:.3g}")
    return within


def fit_ols(x: np.ndarray, y: np.ndarray) -> OLSResult:
    beta, _, rank, singular_values = np.linalg.lstsq(x, y, rcond=None)
    if rank != x.shape[1]:
        raise ValueError(f"Rank-deficient design: rank={rank}, columns={x.shape[1]}")
    residual = y - x @ beta
    xtx = x.T @ x
    inv_xtx = np.linalg.inv(xtx)
    condition_number = float(singular_values[0] / singular_values[-1])
    orthogonality = float(np.max(np.abs(x.T @ residual)))
    scale = max(1.0, float(np.max(np.abs(x.T @ y))))
    if orthogonality / scale > 1e-10:
        raise ValueError(
            "OLS normal-equation check failed: "
            f"relative maximum residual score={orthogonality / scale:.3g}"
        )
    return OLSResult(
        beta=beta,
        residual=residual,
        inv_xtx=inv_xtx,
        rank=int(rank),
        condition_number=condition_number,
    )


def symmetric_sqrt(matrix: np.ndarray) -> np.ndarray:
    values, vectors = np.linalg.eigh((matrix + matrix.T) / 2.0)
    if values.min() <= 0:
        raise ValueError(f"Matrix is not positive definite; min eigenvalue={values.min():.3g}")
    return (vectors * np.sqrt(values)) @ vectors.T


def cr2_cluster_influence(
    x: np.ndarray,
    residual: np.ndarray,
    groups: np.ndarray,
    inv_xtx: np.ndarray,
) -> CR2Result:
    """Return CR2 coefficient influences and design-based Satterthwaite df.

    Place fixed effects have already been absorbed. The CR2 adjustment therefore
    operates on the within-place residual subspace, avoiding the singular place-
    indicator direction while remaining algebraically equivalent for slopes.
    """

    residual_2d = residual[:, None] if residual.ndim == 1 else residual
    n_parameters = x.shape[1]
    n_equations = residual_2d.shape[1]
    unique_groups = np.unique(groups)
    n_groups = len(unique_groups)
    b_half = symmetric_sqrt(inv_xtx)
    influences = np.empty((n_groups, n_parameters, n_equations), dtype=np.float64)
    t_by_group = np.empty((n_groups, n_parameters, n_parameters), dtype=np.float64)
    norm_by_group = np.empty((n_groups, n_parameters), dtype=np.float64)
    max_leverage = 0.0
    min_one_minus = 1.0

    for group_index, group in enumerate(unique_groups):
        mask = groups == group
        xg = x[mask]
        eg = residual_2d[mask]
        xgx = xg.T @ xg
        leverage_core = (b_half @ xgx @ b_half + (b_half @ xgx @ b_half).T) / 2.0
        leverage_values, leverage_vectors = np.linalg.eigh(leverage_core)
        leverage_values = np.clip(leverage_values, 0.0, None)
        active = leverage_values > 1e-12
        active_values = leverage_values[active]
        active_vectors = leverage_vectors[:, active]
        if active_values.size:
            cluster_max = float(active_values.max())
            max_leverage = max(max_leverage, cluster_max)
            min_one_minus = min(min_one_minus, 1.0 - cluster_max)
            if cluster_max >= 1.0 - 1e-10:
                raise ValueError(
                    "CR2 leverage is singular after fixed-effect absorption: "
                    f"group={group}, max eigenvalue={cluster_max:.12f}"
                )
            roots = np.sqrt(active_values)
            u_basis = (xg @ b_half @ active_vectors) / roots
            inflation = 1.0 / np.sqrt(1.0 - active_values) - 1.0
            adjusted_residual = eg + u_basis @ (
                inflation[:, None] * (u_basis.T @ eg)
            )
        else:
            u_basis = np.empty((len(xg), 0), dtype=np.float64)
            inflation = np.empty(0, dtype=np.float64)
            adjusted_residual = eg

        adjusted_score = xg.T @ adjusted_residual
        influences[group_index] = inv_xtx @ adjusted_score

        fitted_basis = xg @ inv_xtx
        if u_basis.shape[1]:
            adjusted_fitted_basis = fitted_basis + u_basis @ (
                inflation[:, None] * (u_basis.T @ fitted_basis)
            )
        else:
            adjusted_fitted_basis = fitted_basis
        t_by_group[group_index] = xg.T @ adjusted_fitted_basis
        norm_by_group[group_index] = np.sum(adjusted_fitted_basis**2, axis=0)

    dfs = np.empty(n_parameters, dtype=np.float64)
    for parameter_index in range(n_parameters):
        t_matrix = t_by_group[:, :, parameter_index]
        psi = -(t_matrix @ inv_xtx @ t_matrix.T)
        diagonal = np.diag_indices_from(psi)
        psi[diagonal] += norm_by_group[:, parameter_index]
        numerator = float(np.trace(psi)) ** 2
        denominator = float(np.sum(psi**2))
        dfs[parameter_index] = numerator / denominator if denominator > 0 else np.nan

    if not np.isfinite(influences).all() or not np.isfinite(dfs).all():
        raise ValueError("Non-finite CR2 influence or Satterthwaite degrees of freedom")
    result_influence = influences[:, :, 0] if residual.ndim == 1 else influences
    return CR2Result(
        influence=result_influence,
        satterthwaite_df=dfs,
        max_cluster_leverage=max_leverage,
        min_one_minus_leverage=min_one_minus,
    )


def t_critical_975(df: float) -> float:
    """Accurate Cornish-Fisher approximation to the 97.5% t quantile."""

    if not math.isfinite(df) or df <= 0:
        return math.nan
    z = 1.959963984540054
    z2 = z * z
    correction_1 = (z**3 + z) / (4.0 * df)
    correction_2 = (5.0 * z**5 + 16.0 * z**3 + 3.0 * z) / (96.0 * df**2)
    correction_3 = (
        3.0 * z**7 + 19.0 * z**5 + 17.0 * z**3 - 15.0 * z
    ) / (384.0 * df**3)
    correction_4 = (
        79.0 * z**9
        + 776.0 * z**7
        + 1482.0 * z**5
        - 1920.0 * z**3
        - 945.0 * z
    ) / (92160.0 * df**4)
    return z + correction_1 + correction_2 + correction_3 + correction_4


def coefficient_rows(
    equation: str,
    outcome: str,
    names: list[str],
    estimate: np.ndarray,
    cr2: CR2Result,
) -> list[dict[str, Any]]:
    estimates = np.asarray(estimate).reshape(-1)
    if len(estimates) != len(names):
        raise ValueError("Coefficient-name length mismatch")
    if cr2.influence.ndim != 2:
        raise ValueError("coefficient_rows requires one equation's CR2 influence")
    standard_errors = np.sqrt(np.sum(cr2.influence**2, axis=0))
    rows: list[dict[str, Any]] = []
    for index, name in enumerate(names):
        df = float(cr2.satterthwaite_df[index])
        critical = t_critical_975(df)
        rows.append(
            {
                "equation": equation,
                "dependent_variable": outcome,
                "term": name,
                "estimate": float(estimates[index]),
                "cr2_se": float(standard_errors[index]),
                "satterthwaite_df": df,
                "cr2_satterthwaite_ci_low": float(
                    estimates[index] - critical * standard_errors[index]
                ),
                "cr2_satterthwaite_ci_high": float(
                    estimates[index] + critical * standard_errors[index]
                ),
            }
        )
    return rows


def effect_values(theta: np.ndarray) -> np.ndarray:
    theta_2d = theta[None, :] if theta.ndim == 1 else theta
    a_paths = theta_2d[:, 0:4]
    b_paths = theta_2d[:, 4:8]
    direct = theta_2d[:, 8]
    total = theta_2d[:, 9]
    specific = a_paths * b_paths
    total_indirect = specific.sum(axis=1)
    decomposed_total = direct + total_indirect
    effects = np.column_stack(
        [specific, total_indirect, direct, total, decomposed_total]
    )
    return effects[0] if theta.ndim == 1 else effects


def effect_gradients(theta: np.ndarray) -> np.ndarray:
    gradients = np.zeros((8, 10), dtype=np.float64)
    for index in range(4):
        gradients[index, index] = theta[4 + index]
        gradients[index, 4 + index] = theta[index]
        gradients[4, index] = theta[4 + index]
        gradients[4, 4 + index] = theta[index]
        gradients[7, index] = theta[4 + index]
        gradients[7, 4 + index] = theta[index]
    gradients[5, 8] = 1.0
    gradients[6, 9] = 1.0
    gradients[7, 8] = 1.0
    return gradients


def run_joint_webb_bootstrap(
    theta: np.ndarray,
    theta_influence: np.ndarray,
    repetitions: int,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    if repetitions < 999:
        raise ValueError("Use at least 999 bootstrap repetitions")
    rng = np.random.default_rng(seed)
    weights = rng.choice(WEBB_SUPPORT, size=(repetitions, theta_influence.shape[0]))
    theta_draws = theta[None, :] + weights @ theta_influence
    effect_draws = effect_values(theta_draws)
    if not np.isfinite(effect_draws).all():
        raise ValueError("Non-finite wild-bootstrap effect draw")
    return theta_draws, effect_draws


def run_path_model(
    common: pd.DataFrame,
    bootstrap_repetitions: int,
    seed: int,
    *,
    scenario: str = "primary_common_unweighted",
    income_percentile_column: str = "income_pctile",
    social_capital_column: str = "social_capital_within_place",
    analysis_weights: pd.Series | None = None,
    weight_label: str = "unweighted",
) -> dict[str, Any]:
    normalized_weights = normalized_analysis_weights(common, analysis_weights)
    base_design_frame, design_metadata = make_base_design(common, normalized_weights)
    groups = common[PLACE].astype(int).to_numpy()
    base_names = list(base_design_frame.columns)
    row_scale = (
        np.ones(len(common), dtype=np.float64)
        if normalized_weights is None
        else np.sqrt(normalized_weights.to_numpy(dtype=np.float64))
    )
    base_x = base_design_frame.to_numpy(dtype=np.float64) * row_scale[:, None]

    mediator_frame = pd.DataFrame(
        {
            "income_security_feelings": common["income_feelings_sec"],
            "expense_security": common["EXPENSES_Y1"],
            "income_percentile_within_place": common[income_percentile_column],
            "social_capital_within_place": common[social_capital_column],
        },
        index=common.index,
    )
    mediator_within = within_transform(
        mediator_frame, common[PLACE], normalized_weights
    )
    outcome_within = within_transform(
        common[[OUTCOME]], common[PLACE], normalized_weights
    )[OUTCOME]
    mediator_y = mediator_within.to_numpy(dtype=np.float64) * row_scale[:, None]
    outcome_y = outcome_within.to_numpy(dtype=np.float64) * row_scale

    mediator_fit = fit_ols(base_x, mediator_y)
    mediator_cr2 = cr2_cluster_influence(
        base_x, mediator_fit.residual, groups, mediator_fit.inv_xtx
    )

    outcome_names = base_names + list(MEDIATOR_NAMES)
    outcome_x = np.column_stack([base_x, mediator_y])
    outcome_fit = fit_ols(outcome_x, outcome_y)
    outcome_cr2 = cr2_cluster_influence(
        outcome_x, outcome_fit.residual, groups, outcome_fit.inv_xtx
    )

    total_fit = fit_ols(base_x, outcome_y)
    total_cr2 = cr2_cluster_influence(base_x, total_fit.residual, groups, total_fit.inv_xtx)

    rural_index = base_names.index(EXPOSURE)
    mediator_indices = [outcome_names.index(name) for name in MEDIATOR_NAMES]
    a_paths = mediator_fit.beta[rural_index, :]
    b_paths = outcome_fit.beta[mediator_indices]
    direct = float(outcome_fit.beta[rural_index])
    total = float(total_fit.beta[rural_index])
    theta = np.concatenate([a_paths, b_paths, [direct, total]])

    theta_influence = np.column_stack(
        [
            mediator_cr2.influence[:, rural_index, 0],
            mediator_cr2.influence[:, rural_index, 1],
            mediator_cr2.influence[:, rural_index, 2],
            mediator_cr2.influence[:, rural_index, 3],
            outcome_cr2.influence[:, mediator_indices[0]],
            outcome_cr2.influence[:, mediator_indices[1]],
            outcome_cr2.influence[:, mediator_indices[2]],
            outcome_cr2.influence[:, mediator_indices[3]],
            outcome_cr2.influence[:, rural_index],
            total_cr2.influence[:, rural_index],
        ]
    )
    theta_covariance = theta_influence.T @ theta_influence
    effects = effect_values(theta)
    gradients = effect_gradients(theta)
    effect_covariance = gradients @ theta_covariance @ gradients.T
    effect_se = np.sqrt(np.clip(np.diag(effect_covariance), 0.0, None))
    _, effect_draws = run_joint_webb_bootstrap(
        theta, theta_influence, bootstrap_repetitions, seed
    )

    effect_names = [
        "indirect_income_security_feelings",
        "indirect_expense_security",
        "indirect_income_percentile_within_place",
        "indirect_social_capital_within_place",
        "total_indirect_association",
        "direct_association",
        "total_association",
        "decomposed_total_association",
    ]
    percentile_low, percentile_high = np.quantile(
        effect_draws, [0.025, 0.975], axis=0
    )
    basic_low = 2.0 * effects - percentile_high
    basic_high = 2.0 * effects - percentile_low
    t22 = t_critical_975(len(np.unique(groups)) - 1)
    effect_rows = []
    for index, name in enumerate(effect_names):
        effect_rows.append(
            {
                "scenario": scenario,
                "effect": name,
                "estimate": float(effects[index]),
                "cr2_delta_se": float(effect_se[index]),
                "cr2_t_g_minus_1_ci_low": float(effects[index] - t22 * effect_se[index]),
                "cr2_t_g_minus_1_ci_high": float(effects[index] + t22 * effect_se[index]),
                "joint_webb_basic_ci_low": float(basic_low[index]),
                "joint_webb_basic_ci_high": float(basic_high[index]),
                "joint_webb_percentile_ci_low": float(percentile_low[index]),
                "joint_webb_percentile_ci_high": float(percentile_high[index]),
                "clusters": int(len(np.unique(groups))),
                "bootstrap_repetitions": int(bootstrap_repetitions),
                "weighting": weight_label,
                "income_percentile_column": income_percentile_column,
                "social_capital_column": social_capital_column,
                "interpretation": "cross-sectional association/pathway; not a causal effect",
            }
        )
    effect_table = pd.DataFrame(effect_rows)

    identity_gap = total - float(effects[7])
    if abs(identity_gap) > 1e-10:
        raise ValueError(
            "Linear path decomposition identity failed: "
            f"total - (direct + total indirect)={identity_gap:.3g}"
        )

    coefficient_records: list[dict[str, Any]] = []
    for mediator_index, mediator_name in enumerate(MEDIATOR_NAMES):
        mediator_cr2_one = CR2Result(
            influence=mediator_cr2.influence[:, :, mediator_index],
            satterthwaite_df=mediator_cr2.satterthwaite_df,
            max_cluster_leverage=mediator_cr2.max_cluster_leverage,
            min_one_minus_leverage=mediator_cr2.min_one_minus_leverage,
        )
        coefficient_records.extend(
            coefficient_rows(
                equation=f"mediator_{mediator_name}",
                outcome=mediator_name,
                names=base_names,
                estimate=mediator_fit.beta[:, mediator_index],
                cr2=mediator_cr2_one,
            )
        )
    coefficient_records.extend(
        coefficient_rows(
            equation="outcome_direct",
            outcome=OUTCOME,
            names=outcome_names,
            estimate=outcome_fit.beta,
            cr2=outcome_cr2,
        )
    )
    coefficient_records.extend(
        coefficient_rows(
            equation="outcome_total",
            outcome=OUTCOME,
            names=base_names,
            estimate=total_fit.beta,
            cr2=total_cr2,
        )
    )
    coefficient_table = pd.DataFrame(coefficient_records)
    coefficient_table.insert(0, "scenario", scenario)

    focal_terms = {
        (f"mediator_{name}", EXPOSURE) for name in MEDIATOR_NAMES
    } | {
        ("outcome_direct", name) for name in (*MEDIATOR_NAMES, EXPOSURE)
    } | {("outcome_total", EXPOSURE)}
    focal_table = coefficient_table.loc[
        [
            (equation, term) in focal_terms
            for equation, term in zip(
                coefficient_table["equation"], coefficient_table["term"]
            )
        ]
    ].reset_index(drop=True)

    bootstrap_table = pd.DataFrame(effect_draws, columns=effect_names)
    bootstrap_table.insert(0, "replicate", np.arange(1, len(bootstrap_table) + 1))
    bootstrap_table.insert(0, "scenario", scenario)

    diagnostics = {
        "scenario": scenario,
        "common_n": len(common),
        "places": int(len(np.unique(groups))),
        "weighting": weight_label,
        "weight_min_normalized": (
            1.0 if normalized_weights is None else float(normalized_weights.min())
        ),
        "weight_max_normalized": (
            1.0 if normalized_weights is None else float(normalized_weights.max())
        ),
        "weight_mean_normalized": (
            1.0 if normalized_weights is None else float(normalized_weights.mean())
        ),
        "income_percentile_column": income_percentile_column,
        "social_capital_column": social_capital_column,
        "base_parameter_count": len(base_names),
        "outcome_parameter_count": len(outcome_names),
        "mediator_model_rank": mediator_fit.rank,
        "outcome_model_rank": outcome_fit.rank,
        "total_model_rank": total_fit.rank,
        "mediator_design_condition_number": mediator_fit.condition_number,
        "outcome_design_condition_number": outcome_fit.condition_number,
        "total_design_condition_number": total_fit.condition_number,
        "mediator_cr2_max_cluster_leverage": mediator_cr2.max_cluster_leverage,
        "outcome_cr2_max_cluster_leverage": outcome_cr2.max_cluster_leverage,
        "total_cr2_max_cluster_leverage": total_cr2.max_cluster_leverage,
        "mediator_cr2_min_one_minus_leverage": mediator_cr2.min_one_minus_leverage,
        "outcome_cr2_min_one_minus_leverage": outcome_cr2.min_one_minus_leverage,
        "total_cr2_min_one_minus_leverage": total_cr2.min_one_minus_leverage,
        "minimum_satterthwaite_df": float(
            min(
                mediator_cr2.satterthwaite_df.min(),
                outcome_cr2.satterthwaite_df.min(),
                total_cr2.satterthwaite_df.min(),
            )
        ),
        "maximum_satterthwaite_df": float(
            max(
                mediator_cr2.satterthwaite_df.max(),
                outcome_cr2.satterthwaite_df.max(),
                total_cr2.satterthwaite_df.max(),
            )
        ),
        "path_identity_gap": identity_gap,
        "bootstrap_seed": seed,
        "bootstrap_repetitions": bootstrap_repetitions,
        "bootstrap_weight_distribution": "Webb six-point, equal probability",
        "joint_bootstrap_rule": "same place weight used across all mediator, direct-outcome, and total-outcome equations",
        "bootstrap_interval_note": "Basic and percentile intervals are both retained because nonlinear product terms can make the two differ; final substantive wording must not depend on only one interval construction.",
        **design_metadata,
    }
    return {
        "effect_table": effect_table,
        "coefficient_table": coefficient_table,
        "focal_table": focal_table,
        "bootstrap_table": bootstrap_table,
        "diagnostics": diagnostics,
    }


SEQUENCE_MODELS = (
    {
        "model": "M1_place_fe",
        "label": "Rural residence + place fixed effects",
        "include_controls": False,
        "include_economic": False,
        "include_social_capital": False,
    },
    {
        "model": "M2_demographic",
        "label": "M1 + demographic and socioeconomic controls",
        "include_controls": True,
        "include_economic": False,
        "include_social_capital": False,
    },
    {
        "model": "M3_economic",
        "label": "M2 + three economic-security measures",
        "include_controls": True,
        "include_economic": True,
        "include_social_capital": False,
    },
    {
        "model": "M4_full",
        "label": "M3 + Social Capital Index",
        "include_controls": True,
        "include_economic": True,
        "include_social_capital": True,
    },
)


def sequence_predictors(
    model_spec: dict[str, Any],
    income_percentile_column: str,
    social_capital_column: str,
) -> tuple[list[str], tuple[str, ...]]:
    continuous = [EXPOSURE]
    categorical: tuple[str, ...] = ()
    if model_spec["include_controls"]:
        continuous.append("AGE_Y1")
        categorical = CATEGORICAL_CONTROLS
    if model_spec["include_economic"]:
        continuous.extend(
            ["income_feelings_sec", "EXPENSES_Y1", income_percentile_column]
        )
    if model_spec["include_social_capital"]:
        continuous.append(social_capital_column)
    return continuous, categorical


def run_sequence_model(
    sample: pd.DataFrame,
    model_spec: dict[str, Any],
    *,
    scenario: str,
    sample_policy: str,
    income_percentile_column: str,
    social_capital_column: str,
    analysis_weights: pd.Series | None,
    weight_label: str,
    bootstrap_repetitions: int,
    seed: int,
) -> dict[str, Any]:
    continuous, categorical = sequence_predictors(
        model_spec, income_percentile_column, social_capital_column
    )
    normalized_weights = normalized_analysis_weights(sample, analysis_weights)
    design_frame, design_metadata = make_predictor_design(
        sample, continuous, categorical, normalized_weights
    )
    outcome_within = within_transform(
        sample[[OUTCOME]], sample[PLACE], normalized_weights
    )[OUTCOME]
    row_scale = (
        np.ones(len(sample), dtype=np.float64)
        if normalized_weights is None
        else np.sqrt(normalized_weights.to_numpy(dtype=np.float64))
    )
    x = design_frame.to_numpy(dtype=np.float64) * row_scale[:, None]
    y = outcome_within.to_numpy(dtype=np.float64) * row_scale
    groups = sample[PLACE].astype(int).to_numpy()
    fit = fit_ols(x, y)
    cr2 = cr2_cluster_influence(x, fit.residual, groups, fit.inv_xtx)
    names = list(design_frame.columns)
    records = coefficient_rows(
        equation=model_spec["model"],
        outcome=OUTCOME,
        names=names,
        estimate=fit.beta,
        cr2=cr2,
    )
    coefficient_table = pd.DataFrame(records)
    coefficient_table.insert(0, "scenario", scenario)
    coefficient_table.insert(1, "sample_policy", sample_policy)
    coefficient_table.insert(2, "weighting", weight_label)

    rural_index = names.index(EXPOSURE)
    rural_estimate = float(fit.beta[rural_index])
    rural_influence = cr2.influence[:, rural_index]
    rng = np.random.default_rng(seed)
    webb_weights = rng.choice(
        WEBB_SUPPORT, size=(bootstrap_repetitions, len(np.unique(groups)))
    )
    rural_draws = rural_estimate + webb_weights @ rural_influence
    percentile_low, percentile_high = np.quantile(rural_draws, [0.025, 0.975])
    basic_low = 2.0 * rural_estimate - percentile_high
    basic_high = 2.0 * rural_estimate - percentile_low
    rural_coefficient = coefficient_table.loc[
        coefficient_table["term"].eq(EXPOSURE)
    ].iloc[0]
    total_sum_squares = float(y @ y)
    residual_sum_squares = float(fit.residual @ fit.residual)
    if total_sum_squares <= 0:
        raise ValueError("Within-place outcome has zero total sum of squares")
    rural_row = {
        "scenario": scenario,
        "model": model_spec["model"],
        "model_label": model_spec["label"],
        "sample_policy": sample_policy,
        "weighting": weight_label,
        "income_percentile_column": (
            income_percentile_column if model_spec["include_economic"] else "not_in_model"
        ),
        "social_capital_column": (
            social_capital_column
            if model_spec["include_social_capital"]
            else "not_in_model"
        ),
        "n": len(sample),
        "clusters": int(len(np.unique(groups))),
        "rural_estimate": rural_estimate,
        "cr2_se": float(rural_coefficient["cr2_se"]),
        "satterthwaite_df": float(rural_coefficient["satterthwaite_df"]),
        "cr2_satterthwaite_ci_low": float(
            rural_coefficient["cr2_satterthwaite_ci_low"]
        ),
        "cr2_satterthwaite_ci_high": float(
            rural_coefficient["cr2_satterthwaite_ci_high"]
        ),
        "joint_webb_basic_ci_low": float(basic_low),
        "joint_webb_basic_ci_high": float(basic_high),
        "joint_webb_percentile_ci_low": float(percentile_low),
        "joint_webb_percentile_ci_high": float(percentile_high),
        "within_r_squared": 1.0 - residual_sum_squares / total_sum_squares,
        "parameter_count": len(names),
        "rank": fit.rank,
        "condition_number": fit.condition_number,
        "cr2_max_cluster_leverage": cr2.max_cluster_leverage,
        "cr2_min_one_minus_leverage": cr2.min_one_minus_leverage,
    }
    draw_table = pd.DataFrame(
        {
            "scenario": scenario,
            "model": model_spec["model"],
            "replicate": np.arange(1, bootstrap_repetitions + 1),
            "rural_estimate_draw": rural_draws,
        }
    )
    diagnostics = {
        "scenario": scenario,
        "model": model_spec["model"],
        "n": len(sample),
        "clusters": int(len(np.unique(groups))),
        "rank": fit.rank,
        "parameter_count": len(names),
        "condition_number": fit.condition_number,
        "cr2_max_cluster_leverage": cr2.max_cluster_leverage,
        "cr2_min_one_minus_leverage": cr2.min_one_minus_leverage,
        "weight_mean_normalized": (
            1.0 if normalized_weights is None else float(normalized_weights.mean())
        ),
        **design_metadata,
    }
    return {
        "rural_row": rural_row,
        "coefficient_table": coefficient_table,
        "draw_table": draw_table,
        "diagnostics": diagnostics,
    }


def select_sequence_sample(
    source: pd.DataFrame,
    common: pd.DataFrame,
    model_spec: dict[str, Any],
    *,
    sample_policy: str,
    income_percentile_column: str,
    social_capital_column: str,
) -> pd.DataFrame:
    if sample_policy == "locked_common_complete_case":
        return common
    if sample_policy != "model_specific_available_case":
        raise ValueError(f"Unknown sample policy: {sample_policy}")
    if model_spec["include_social_capital"]:
        return common
    continuous, categorical = sequence_predictors(
        model_spec, income_percentile_column, social_capital_column
    )
    required = [OUTCOME, PLACE, *continuous, *categorical]
    available = source.dropna(subset=required).copy()
    if available[PLACE].nunique() != EXPECTED_PLACES:
        raise ValueError(
            f"Available-case {model_spec['model']} does not retain all places"
        )
    return available


def run_ols_sequence(
    source: pd.DataFrame,
    common: pd.DataFrame,
    *,
    scenario: str,
    sample_policy: str,
    income_percentile_column: str = "income_pctile",
    social_capital_column: str = "social_capital_within_place",
    weight_column: str | None = None,
    bootstrap_repetitions: int,
    seed: int,
) -> dict[str, Any]:
    rural_rows: list[dict[str, Any]] = []
    coefficient_tables: list[pd.DataFrame] = []
    draw_tables: list[pd.DataFrame] = []
    diagnostics: list[dict[str, Any]] = []
    for model_index, model_spec in enumerate(SEQUENCE_MODELS):
        sample = select_sequence_sample(
            source,
            common,
            model_spec,
            sample_policy=sample_policy,
            income_percentile_column=income_percentile_column,
            social_capital_column=social_capital_column,
        )
        weights = None if weight_column is None else sample[weight_column]
        result = run_sequence_model(
            sample,
            model_spec,
            scenario=scenario,
            sample_policy=sample_policy,
            income_percentile_column=income_percentile_column,
            social_capital_column=social_capital_column,
            analysis_weights=weights,
            weight_label="unweighted" if weight_column is None else weight_column,
            bootstrap_repetitions=bootstrap_repetitions,
            seed=seed + model_index,
        )
        rural_rows.append(result["rural_row"])
        coefficient_tables.append(result["coefficient_table"])
        draw_tables.append(result["draw_table"])
        diagnostics.append(result["diagnostics"])
    rural_table = pd.DataFrame(rural_rows)
    rural_table["change_from_m1"] = (
        rural_table["rural_estimate"] - float(rural_table.iloc[0]["rural_estimate"])
    )
    rural_table["change_from_previous"] = rural_table["rural_estimate"].diff()
    return {
        "rural_table": rural_table,
        "coefficient_table": pd.concat(coefficient_tables, ignore_index=True),
        "draw_table": pd.concat(draw_tables, ignore_index=True),
        "diagnostics": diagnostics,
    }


def interval_excludes_zero(low: float, high: float) -> bool:
    return bool(low > 0 or high < 0)


def build_sensitivity_summary(
    path_effects: pd.DataFrame,
    sequence_rural: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    comparison = path_effects.copy()
    primary_estimates = (
        comparison.loc[
            comparison["scenario"].eq("primary_common_unweighted"),
            ["effect", "estimate"],
        ]
        .set_index("effect")["estimate"]
        .to_dict()
    )
    comparison["difference_from_primary"] = [
        estimate - primary_estimates[effect]
        for effect, estimate in zip(comparison["effect"], comparison["estimate"])
    ]
    comparison["cr2_delta_excludes_zero"] = [
        interval_excludes_zero(low, high)
        for low, high in zip(
            comparison["cr2_t_g_minus_1_ci_low"],
            comparison["cr2_t_g_minus_1_ci_high"],
        )
    ]
    comparison["webb_basic_excludes_zero"] = [
        interval_excludes_zero(low, high)
        for low, high in zip(
            comparison["joint_webb_basic_ci_low"],
            comparison["joint_webb_basic_ci_high"],
        )
    ]
    comparison["webb_percentile_excludes_zero"] = [
        interval_excludes_zero(low, high)
        for low, high in zip(
            comparison["joint_webb_percentile_ci_low"],
            comparison["joint_webb_percentile_ci_high"],
        )
    ]

    key_effects = {
        "total_indirect_association",
        "direct_association",
        "total_association",
    }
    path_summary = comparison.loc[
        comparison["effect"].isin(key_effects),
        [
            "scenario",
            "effect",
            "estimate",
            "difference_from_primary",
            "cr2_delta_excludes_zero",
            "webb_basic_excludes_zero",
            "webb_percentile_excludes_zero",
        ],
    ].to_dict(orient="records")
    final_models = sequence_rural.loc[
        sequence_rural["model"].eq("M4_full"),
        [
            "scenario",
            "sample_policy",
            "weighting",
            "n",
            "rural_estimate",
            "cr2_satterthwaite_ci_low",
            "cr2_satterthwaite_ci_high",
        ],
    ].to_dict(orient="records")
    available_ns = sequence_rural.loc[
        sequence_rural["scenario"].eq("available_case_unweighted"),
        ["model", "n"],
    ].to_dict(orient="records")
    summary = {
        "path_key_effects": path_summary,
        "sequence_final_models": final_models,
        "available_case_model_ns": available_ns,
        "interpretation_gate": "Sensitivity outputs are diagnostic only until ordered-logit and multilevel robustness are complete.",
    }
    return comparison, summary


def build_model_specification(
    data_path: Path,
    codebook_path: Path,
    crosswalk_path: Path,
    bootstrap_repetitions: int,
    seed: int,
) -> dict[str, Any]:
    return {
        "analysis_stage": "Batch A OLS/path core plus prespecified sensitivities",
        "estimand": "cross-sectional direct and indirect associations",
        "outcome": OUTCOME,
        "exposure": EXPOSURE,
        "parallel_mediators": list(MEDIATOR_NAMES),
        "serial_mediator_paths": False,
        "sample": "one locked complete-case sample shared by all equations",
        "controls": ["AGE_Y1", *CATEGORICAL_CONTROLS],
        "place_fixed_effects": "absorbed in every equation",
        "primary_estimator": "unweighted OLS",
        "reduced_ols_sequence": [
            {"model": item["model"], "label": item["label"]}
            for item in SEQUENCE_MODELS
        ],
        "sequence_role": "descriptive nested adjustment; not mediation evidence",
        "cluster": PLACE,
        "cluster_robust_method": "CR2 on absorbed fixed-effect residual subspace",
        "linear_coefficient_df": "Bell-McCaffrey-type Satterthwaite approximation",
        "indirect_interval": "joint CR2-adjusted Webb wild-cluster score bootstrap; basic and percentile intervals both reported",
        "bootstrap_repetitions": bootstrap_repetitions,
        "bootstrap_seed": seed,
        "income_percentile_primary": "within-place percentile created before complete-case restriction",
        "income_percentile_sensitivity": "within-place-by-rural/urban percentile; not a mediator in the primary model",
        "social_capital_primary": "equal mean of three place-standardized components on the common sample",
        "social_capital_component_directions": {
            "PEOPLE_HELP_Y1": "as coded; higher means help more often",
            "close_to_bin": "1=yes, 0=no",
            "trust_people_sec": "6 - TRUST_PEOPLE_Y1; higher means more people trust one another",
        },
        "social_capital_sensitivity": "pooled component standardization using corrected trust direction",
        "sample_sensitivity": "model-specific available-case OLS sequence with exact N for each model",
        "weight_sensitivity": f"{WEIGHT}-weighted OLS sequence and parallel path system on the locked common sample",
        "sensitivity_path_scenarios": [
            "primary_common_unweighted",
            "pooled_sci_common_unweighted",
            "survey_weighted_common",
        ],
        "income_percentile_sensitivity_role": "the place-by-rural/urban percentile is used only in the descriptive OLS sensitivity sequence and is not assigned an indirect path",
        "forbidden_interpretations": [
            "causal mediation",
            "partial mediation",
            "full mediation",
        ],
        "source_paths": {
            "processed_data": str(data_path),
            "codebook": str(codebook_path),
            "place_crosswalk": str(crosswalk_path),
        },
    }


def write_outputs(
    output_dir: Path,
    source_audit: dict[str, Any],
    sample_audit: dict[str, Any],
    place_audit: pd.DataFrame,
    model_specification: dict[str, Any],
    path_results: dict[str, dict[str, Any]],
    sequence_results: dict[str, dict[str, Any]],
    sensitivity_comparison: pd.DataFrame,
    sensitivity_summary: dict[str, Any],
    data_path: Path,
    codebook_path: Path,
    crosswalk_path: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    primary_results = path_results["primary_common_unweighted"]
    all_path_effects = pd.concat(
        [result["effect_table"] for result in path_results.values()],
        ignore_index=True,
    )
    all_path_focal = pd.concat(
        [result["focal_table"] for result in path_results.values()],
        ignore_index=True,
    )
    all_path_coefficients = pd.concat(
        [result["coefficient_table"] for result in path_results.values()],
        ignore_index=True,
    )
    all_path_draws = pd.concat(
        [result["bootstrap_table"] for result in path_results.values()],
        ignore_index=True,
    )
    all_sequence_rural = pd.concat(
        [result["rural_table"] for result in sequence_results.values()],
        ignore_index=True,
    )
    all_sequence_coefficients = pd.concat(
        [result["coefficient_table"] for result in sequence_results.values()],
        ignore_index=True,
    )
    all_sequence_draws = pd.concat(
        [result["draw_table"] for result in sequence_results.values()],
        ignore_index=True,
    )
    sample_payload = {**source_audit, **sample_audit}
    atomic_write_json(sample_payload, output_dir / "sample_audit.json")
    atomic_write_csv(place_audit, output_dir / "place_sample_audit.csv")
    atomic_write_json(model_specification, output_dir / "model_specification.json")
    atomic_write_csv(primary_results["effect_table"], output_dir / "path_effects.csv")
    atomic_write_csv(primary_results["focal_table"], output_dir / "focal_paths.csv")
    atomic_write_csv(
        primary_results["coefficient_table"], output_dir / "equation_coefficients.csv"
    )
    atomic_write_csv(
        primary_results["bootstrap_table"], output_dir / "bootstrap_effect_draws.csv"
    )
    atomic_write_json(primary_results["diagnostics"], output_dir / "diagnostics.json")
    atomic_write_csv(all_path_effects, output_dir / "path_sensitivity_effects.csv")
    atomic_write_csv(all_path_focal, output_dir / "path_sensitivity_focal_paths.csv")
    atomic_write_csv(
        all_path_coefficients, output_dir / "path_sensitivity_coefficients.csv"
    )
    atomic_write_csv(
        all_path_draws, output_dir / "path_sensitivity_bootstrap_draws.csv"
    )
    atomic_write_json(
        {scenario: result["diagnostics"] for scenario, result in path_results.items()},
        output_dir / "path_sensitivity_diagnostics.json",
    )
    atomic_write_csv(all_sequence_rural, output_dir / "ols_sequence_rural.csv")
    atomic_write_csv(
        all_sequence_coefficients, output_dir / "ols_sequence_coefficients.csv"
    )
    atomic_write_csv(
        all_sequence_draws, output_dir / "ols_sequence_bootstrap_draws.csv"
    )
    atomic_write_json(
        {
            scenario: result["diagnostics"]
            for scenario, result in sequence_results.items()
        },
        output_dir / "ols_sequence_diagnostics.json",
    )
    atomic_write_csv(
        sensitivity_comparison, output_dir / "path_sensitivity_comparison.csv"
    )
    atomic_write_json(sensitivity_summary, output_dir / "sensitivity_summary.json")

    def sequence_value(scenario: str, model: str, column: str) -> float:
        table = sequence_results[scenario]["rural_table"]
        return float(table.loc[table["model"].eq(model), column].iloc[0])

    def path_effect_value(scenario: str, effect: str) -> float:
        table = path_results[scenario]["effect_table"]
        return float(table.loc[table["effect"].eq(effect), "estimate"].iloc[0])

    available_ns = sequence_results["available_case_unweighted"]["rural_table"][
        "n"
    ].astype(int).tolist()
    all_sequence_diagnostics = [
        diagnostic
        for result in sequence_results.values()
        for diagnostic in result["diagnostics"]
    ]
    path_scenarios_expected = {
        "primary_common_unweighted",
        "pooled_sci_common_unweighted",
        "survey_weighted_common",
    }
    sequence_scenarios_expected = {
        "primary_common_unweighted",
        "pooled_sci_common_unweighted",
        "place_rural_income_common_unweighted",
        "available_case_unweighted",
        "survey_weighted_common",
    }

    output_files = sorted(
        path for path in output_dir.iterdir() if path.is_file() and path.name != "run_manifest.json"
    )
    manifest = {
        "status": "validated_ols_path_and_sensitivity_outputs",
        "source_hashes": {
            "processed_data": sha256(data_path),
            "codebook": sha256(codebook_path),
            "place_crosswalk": sha256(crosswalk_path),
            "analysis_script": sha256(Path(__file__).resolve()),
        },
        "outputs": {
            path.name: {"sha256": sha256(path), "bytes": path.stat().st_size}
            for path in output_files
        },
        "validation_gates": {
            "locked_common_n": sample_audit["common_sample_n"] == EXPECTED_COMMON_ROWS,
            "all_places_retained": sample_audit["common_sample_place_count"]
            == EXPECTED_PLACES,
            "income_percentile_reproduced": source_audit[
                "within_place_income_percentile_max_abs_reproduction_error"
            ]
            <= 1e-12,
            "component_directions_verified": True,
            "survey_weights_valid": source_audit["survey_weight_missing"] == 0
            and source_audit["survey_weight_nonpositive"] == 0,
            "place_standardization_verified": all(
                check["max_abs_place_mean"] <= 1e-12
                and check["max_abs_place_sd_minus_one"] <= 1e-12
                for check in sample_audit["within_place_component_z_checks"].values()
            ),
            "ols_designs_full_rank": all(
                primary_results["diagnostics"][key]
                == primary_results["diagnostics"][expected_key]
                for key, expected_key in (
                    ("mediator_model_rank", "base_parameter_count"),
                    ("outcome_model_rank", "outcome_parameter_count"),
                    ("total_model_rank", "base_parameter_count"),
                )
            ),
            "cr2_nonsingular": min(
                result["diagnostics"][key]
                for result in path_results.values()
                for key in (
                    "mediator_cr2_min_one_minus_leverage",
                    "outcome_cr2_min_one_minus_leverage",
                    "total_cr2_min_one_minus_leverage",
                )
            )
            > 1e-10,
            "path_identity_verified": all(
                abs(result["diagnostics"]["path_identity_gap"]) <= 1e-10
                for result in path_results.values()
            ),
            "path_scenarios_complete": set(path_results) == path_scenarios_expected,
            "sequence_scenarios_complete": set(sequence_results)
            == sequence_scenarios_expected,
            "joint_path_bootstrap_complete": len(all_path_draws)
            == len(path_results) * model_specification["bootstrap_repetitions"],
            "sequence_bootstrap_complete": len(all_sequence_draws)
            == len(sequence_results)
            * len(SEQUENCE_MODELS)
            * model_specification["bootstrap_repetitions"],
            "sequence_designs_full_rank": all(
                item["rank"] == item["parameter_count"]
                for item in all_sequence_diagnostics
            ),
            "sequence_cr2_nonsingular": min(
                item["cr2_min_one_minus_leverage"]
                for item in all_sequence_diagnostics
            )
            > 1e-10,
            "available_case_n_monotone": all(
                earlier >= later
                for earlier, later in zip(available_ns, available_ns[1:])
            )
            and available_ns[-1] == EXPECTED_COMMON_ROWS,
            "primary_sequence_matches_path_direct": abs(
                sequence_value(
                    "primary_common_unweighted", "M4_full", "rural_estimate"
                )
                - path_effect_value(
                    "primary_common_unweighted", "direct_association"
                )
            )
            <= 1e-10,
            "pooled_sci_sequence_matches_path_direct": abs(
                sequence_value(
                    "pooled_sci_common_unweighted", "M4_full", "rural_estimate"
                )
                - path_effect_value(
                    "pooled_sci_common_unweighted", "direct_association"
                )
            )
            <= 1e-10,
            "weighted_sequence_matches_path_direct": abs(
                sequence_value(
                    "survey_weighted_common", "M4_full", "rural_estimate"
                )
                - path_effect_value("survey_weighted_common", "direct_association")
            )
            <= 1e-10,
            "available_final_matches_primary_final": abs(
                sequence_value(
                    "available_case_unweighted", "M4_full", "rural_estimate"
                )
                - sequence_value(
                    "primary_common_unweighted", "M4_full", "rural_estimate"
                )
            )
            <= 1e-10,
            "place_rural_income_not_used_as_path_mediator": all(
                result["diagnostics"]["income_percentile_column"]
                != "income_pctile_place_rural"
                for result in path_results.values()
            ),
        },
        "scope_gate": "OLS/path sensitivities validated; ordered-logit, multilevel robustness, and all manuscript edits remain paused.",
    }
    if not all(manifest["validation_gates"].values()):
        raise ValueError(f"One or more validation gates failed: {manifest['validation_gates']}")
    atomic_write_json(manifest, output_dir / "run_manifest.json")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write validated intermediate outputs under reports/batch_a_core",
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
    for path in (data_path, codebook_path, crosswalk_path):
        if not path.is_file():
            raise FileNotFoundError(path)

    frame, _, source_audit = load_and_validate_source(data_path, crosswalk_path)
    common, place_audit, sample_audit = build_common_sample(frame)
    specification = build_model_specification(
        data_path,
        codebook_path,
        crosswalk_path,
        args.bootstrap_repetitions,
        args.seed,
    )
    path_results = {
        "primary_common_unweighted": run_path_model(
            common,
            args.bootstrap_repetitions,
            args.seed,
            scenario="primary_common_unweighted",
        ),
        "pooled_sci_common_unweighted": run_path_model(
            common,
            args.bootstrap_repetitions,
            args.seed,
            scenario="pooled_sci_common_unweighted",
            social_capital_column="social_capital_pooled_corrected",
        ),
        "survey_weighted_common": run_path_model(
            common,
            args.bootstrap_repetitions,
            args.seed,
            scenario="survey_weighted_common",
            analysis_weights=common[WEIGHT],
            weight_label=WEIGHT,
        ),
    }
    sequence_results = {
        "primary_common_unweighted": run_ols_sequence(
            frame,
            common,
            scenario="primary_common_unweighted",
            sample_policy="locked_common_complete_case",
            bootstrap_repetitions=args.bootstrap_repetitions,
            seed=args.seed,
        ),
        "pooled_sci_common_unweighted": run_ols_sequence(
            frame,
            common,
            scenario="pooled_sci_common_unweighted",
            sample_policy="locked_common_complete_case",
            social_capital_column="social_capital_pooled_corrected",
            bootstrap_repetitions=args.bootstrap_repetitions,
            seed=args.seed,
        ),
        "place_rural_income_common_unweighted": run_ols_sequence(
            frame,
            common,
            scenario="place_rural_income_common_unweighted",
            sample_policy="locked_common_complete_case",
            income_percentile_column="income_pctile_place_rural",
            bootstrap_repetitions=args.bootstrap_repetitions,
            seed=args.seed,
        ),
        "available_case_unweighted": run_ols_sequence(
            frame,
            common,
            scenario="available_case_unweighted",
            sample_policy="model_specific_available_case",
            bootstrap_repetitions=args.bootstrap_repetitions,
            seed=args.seed,
        ),
        "survey_weighted_common": run_ols_sequence(
            frame,
            common,
            scenario="survey_weighted_common",
            sample_policy="locked_common_complete_case",
            weight_column=WEIGHT,
            bootstrap_repetitions=args.bootstrap_repetitions,
            seed=args.seed,
        ),
    }
    all_path_effects = pd.concat(
        [result["effect_table"] for result in path_results.values()],
        ignore_index=True,
    )
    all_sequence_rural = pd.concat(
        [result["rural_table"] for result in sequence_results.values()],
        ignore_index=True,
    )
    sensitivity_comparison, sensitivity_summary = build_sensitivity_summary(
        all_path_effects, all_sequence_rural
    )
    primary_results = path_results["primary_common_unweighted"]
    summary = {
        "mode": "apply" if args.apply else "dry-run",
        "common_n": sample_audit["common_sample_n"],
        "places": sample_audit["common_sample_place_count"],
        "primary_effects": primary_results["effect_table"].to_dict(orient="records"),
        "path_sensitivity_key_effects": sensitivity_summary["path_key_effects"],
        "ols_sequence": all_sequence_rural.to_dict(orient="records"),
        "path_identity_gap": primary_results["diagnostics"]["path_identity_gap"],
        "trust_direction_correction_applied": True,
    }
    if args.apply:
        manifest = write_outputs(
            output_dir,
            source_audit,
            sample_audit,
            place_audit,
            specification,
            path_results,
            sequence_results,
            sensitivity_comparison,
            sensitivity_summary,
            data_path,
            codebook_path,
            crosswalk_path,
        )
        summary["output_dir"] = str(output_dir)
        summary["validation_gates"] = manifest["validation_gates"]
    print(json.dumps(summary, indent=2, sort_keys=True, default=_json_default))


if __name__ == "__main__":
    main()
