#!/usr/bin/env python3
"""Fix the GFS place label for COUNTRY=25 and rebuild label-dependent descriptives.

This bounded repair preserves every analytical value other than ``country_name``.
It rebuilds only descriptive figures whose values do not depend on pending model
or sample-specification decisions. Legacy source variable and report filenames
are retained for compatibility; displayed labels come from the place crosswalk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = PROJECT_ROOT / "data/processed/gfs_cleaned.parquet"
DEFAULT_CROSSWALK = PROJECT_ROOT / "etc/place_crosswalk.csv"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports"

EXPECTED_ROWS = 207_919
EXPECTED_CODE25_ROWS = 5_022
EXPECTED_PLACES = 23
EXPECTED_COUNTRIES = 22
EXPECTED_REGIONS = 1

FIGURE_NAMES = (
    "fig_sample_country.png",
    "fig_country_rural.png",
    "fig_country_lifesat.png",
)

PALETTE = {"rural": "#2c7bb6", "neutral": "#555555"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_and_validate_crosswalk(path: Path) -> pd.DataFrame:
    crosswalk = pd.read_csv(path)
    required = ["COUNTRY", "place_name", "unit_type"]
    if list(crosswalk.columns) != required:
        raise ValueError(f"Crosswalk columns must be exactly {required}")
    if crosswalk["COUNTRY"].duplicated().any():
        raise ValueError("Crosswalk COUNTRY codes must be unique")
    if crosswalk["place_name"].duplicated().any():
        raise ValueError("Crosswalk place names must be unique")
    if set(crosswalk["unit_type"]) != {"country", "region"}:
        raise ValueError("Crosswalk unit_type must contain country and region")
    if len(crosswalk) != EXPECTED_PLACES:
        raise ValueError(f"Expected {EXPECTED_PLACES} crosswalk rows")
    if (crosswalk["unit_type"] == "country").sum() != EXPECTED_COUNTRIES:
        raise ValueError(f"Expected {EXPECTED_COUNTRIES} countries")
    if (crosswalk["unit_type"] == "region").sum() != EXPECTED_REGIONS:
        raise ValueError(f"Expected {EXPECTED_REGIONS} region")

    labels = crosswalk.set_index("COUNTRY")["place_name"]
    unit_types = crosswalk.set_index("COUNTRY")["unit_type"]
    if labels.get(25) != "China":
        raise ValueError("COUNTRY=25 must map to China")
    if labels.get(24) != "Hong Kong" or unit_types.get(24) != "region":
        raise ValueError("COUNTRY=24 must map to Hong Kong as a region")
    return crosswalk


def relabel_dataframe(df: pd.DataFrame, crosswalk: pd.DataFrame) -> pd.DataFrame:
    required = {"COUNTRY", "country_name", "URBAN_RURAL_Y1", "LIFE_SAT_Y1"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Processed data are missing columns: {sorted(missing)}")
    if len(df) != EXPECTED_ROWS:
        raise ValueError(f"Expected {EXPECTED_ROWS:,} rows, found {len(df):,}")

    observed_codes = set(df["COUNTRY"].dropna().astype(int).unique())
    crosswalk_codes = set(crosswalk["COUNTRY"].astype(int))
    if observed_codes != crosswalk_codes:
        raise ValueError(
            "Observed COUNTRY codes do not match the crosswalk: "
            f"observed={sorted(observed_codes)}, crosswalk={sorted(crosswalk_codes)}"
        )

    code25 = df["COUNTRY"].eq(25)
    if int(code25.sum()) != EXPECTED_CODE25_ROWS:
        raise ValueError(
            f"Expected {EXPECTED_CODE25_ROWS:,} COUNTRY=25 rows, found {int(code25.sum()):,}"
        )
    old_code25_labels = set(df.loc[code25, "country_name"].dropna().astype(str))
    if old_code25_labels not in ({"Unknown_25"}, {"China"}):
        raise ValueError(f"Unexpected existing COUNTRY=25 labels: {old_code25_labels}")

    mapping = crosswalk.set_index("COUNTRY")["place_name"]
    revised = df.copy()
    revised_labels = revised["COUNTRY"].map(mapping)
    if revised_labels.isna().any():
        missing_codes = sorted(revised.loc[revised_labels.isna(), "COUNTRY"].unique())
        raise ValueError(f"Unmapped COUNTRY codes: {missing_codes}")

    changed_codes = set(
        revised.loc[
            revised["country_name"].astype(str).ne(revised_labels.astype(str)), "COUNTRY"
        ].astype(int)
    )
    if not changed_codes.issubset({25}):
        raise ValueError(f"The repair would change non-25 labels: {sorted(changed_codes)}")

    revised["country_name"] = revised_labels.astype("string")
    if revised["country_name"].nunique(dropna=False) != EXPECTED_PLACES:
        raise ValueError("Revised data do not contain exactly 23 place labels")
    if revised["country_name"].astype(str).str.contains("Unknown", case=False).any():
        raise ValueError("An unknown place label remains after relabeling")
    return revised


def atomic_write_parquet(revised: pd.DataFrame, original: pd.DataFrame, path: Path) -> None:
    with tempfile.NamedTemporaryFile(
        prefix=".gfs_cleaned.country25.", suffix=".parquet", dir=path.parent, delete=False
    ) as handle:
        temp_path = Path(handle.name)
    try:
        revised.to_parquet(temp_path, index=False)
        check = pd.read_parquet(temp_path)
        if not check.drop(columns=["country_name"]).equals(
            original.drop(columns=["country_name"])
        ):
            raise ValueError("A non-label data value changed in the temporary parquet")
        if not check["country_name"].equals(revised["country_name"]):
            raise ValueError("Temporary parquet did not preserve revised place labels")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def save_figure_atomic(fig: plt.Figure, destination: Path, dpi: int = 150) -> None:
    with tempfile.NamedTemporaryFile(
        prefix=f".{destination.stem}.", suffix=".png", dir=destination.parent, delete=False
    ) as handle:
        temp_path = Path(handle.name)
    try:
        fig.savefig(temp_path, dpi=dpi, bbox_inches="tight")
        with Image.open(temp_path) as image:
            image.verify()
        os.replace(temp_path, destination)
    finally:
        if temp_path.exists():
            temp_path.unlink()
        plt.close(fig)


def apply_plot_style() -> None:
    plt.rcParams.update(
        {
            "axes.grid": True,
            "grid.alpha": 0.35,
            "grid.linestyle": "--",
            "grid.color": "#aaaaaa",
            "axes.axisbelow": True,
        }
    )


def rebuild_descriptive_figures(df: pd.DataFrame, report_dir: Path) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    apply_plot_style()

    place_n = (
        df.groupby("country_name", sort=False)
        .size()
        .rename("n")
        .reset_index()
        .sort_values("n", ascending=True)
    )
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.barh(
        place_n["country_name"],
        place_n["n"],
        color=PALETTE["neutral"],
        edgecolor="white",
        linewidth=0.4,
    )
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax.set_xlabel("Number of respondents")
    ax.tick_params(axis="y", labelsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    save_figure_atomic(fig, report_dir / "fig_sample_country.png")

    rural_valid = df.loc[df["URBAN_RURAL_Y1"].notna(), ["country_name", "URBAN_RURAL_Y1"]].copy()
    rural_valid["is_rural_area"] = rural_valid["URBAN_RURAL_Y1"].eq(1)
    place_rural = (
        rural_valid.groupby("country_name")["is_rural_area"]
        .mean()
        .rename("rural_share")
        .reset_index()
        .sort_values("rural_share", ascending=True)
    )
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.barh(
        place_rural["country_name"],
        place_rural["rural_share"] * 100,
        color=PALETTE["rural"],
        edgecolor="white",
        linewidth=0.4,
        alpha=0.85,
    )
    ax.set_xlabel("Rural share (%)")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    ax.tick_params(axis="y", labelsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    save_figure_atomic(fig, report_dir / "fig_country_rural.png")

    place_ls = (
        df.groupby("country_name")["LIFE_SAT_Y1"]
        .agg(["mean", "std", "count"])
        .assign(
            se=lambda x: x["std"] / np.sqrt(x["count"]),
            lo=lambda x: x["mean"] - 1.96 * x["se"],
            hi=lambda x: x["mean"] + 1.96 * x["se"],
        )
        .reset_index()
        .sort_values("mean", ascending=True)
    )
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.barh(
        place_ls["country_name"],
        place_ls["mean"],
        color=PALETTE["neutral"],
        alpha=0.85,
        edgecolor="white",
    )
    ax.errorbar(
        place_ls["mean"],
        place_ls["country_name"],
        xerr=[place_ls["mean"] - place_ls["lo"], place_ls["hi"] - place_ls["mean"]],
        fmt="none",
        color="black",
        capsize=3,
        linewidth=1,
    )
    ax.set_xlabel("Mean Life Satisfaction (0–10)")
    ax.set_xlim(0, 10)
    ax.tick_params(axis="y", labelsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    save_figure_atomic(fig, report_dir / "fig_country_lifesat.png")


def validate_outputs(data_path: Path, report_dir: Path) -> dict[str, object]:
    check = pd.read_parquet(data_path)
    code25_labels = check.loc[check["COUNTRY"].eq(25), "country_name"].value_counts().to_dict()
    label_counts = check["country_name"].value_counts().sort_index()
    if code25_labels != {"China": EXPECTED_CODE25_ROWS}:
        raise ValueError(f"Unexpected COUNTRY=25 validation result: {code25_labels}")
    if len(label_counts) != EXPECTED_PLACES:
        raise ValueError(f"Expected {EXPECTED_PLACES} place labels, found {len(label_counts)}")
    if any("unknown" in str(label).lower() for label in label_counts.index):
        raise ValueError("An unknown label remains in the processed data")

    figure_info = {}
    for name in FIGURE_NAMES:
        path = report_dir / name
        with Image.open(path) as image:
            image.load()
            figure_info[name] = {
                "sha256": sha256(path),
                "size": list(image.size),
                "mode": image.mode,
            }

    return {
        "data_sha256": sha256(data_path),
        "rows": len(check),
        "place_count": len(label_counts),
        "country_code_25": code25_labels,
        "hong_kong_rows": int(check["country_name"].eq("Hong Kong").sum()),
        "figures": figure_info,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write the repaired parquet and figures")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()

    data_path = args.data.resolve()
    crosswalk_path = args.crosswalk.resolve()
    report_dir = args.report_dir.resolve()
    crosswalk = load_and_validate_crosswalk(crosswalk_path)
    original = pd.read_parquet(data_path)
    revised = relabel_dataframe(original, crosswalk)

    preview = {
        "mode": "apply" if args.apply else "dry-run",
        "data_before_sha256": sha256(data_path),
        "rows": len(revised),
        "code25_rows": int(revised["COUNTRY"].eq(25).sum()),
        "place_count": int(revised["country_name"].nunique()),
        "unit_types": crosswalk["unit_type"].value_counts().to_dict(),
        "figures": list(FIGURE_NAMES),
    }
    print(json.dumps(preview, indent=2, sort_keys=True))
    if not args.apply:
        return

    atomic_write_parquet(revised, original, data_path)
    rebuild_descriptive_figures(revised, report_dir)
    print(json.dumps(validate_outputs(data_path, report_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
