# The Rural Happiness Paradox

## Economic insecurity and social support in rural-urban well-being disparities across 23 regions and countries

This repository contains the analysis code and revision materials for a cross-national study of the Rural Happiness Paradox: the observation that rural residents may report life satisfaction comparable to, or higher than, that of urban residents despite material disadvantages. Using the Global Flourishing Study (GFS), the study estimates rural-urban differences in life satisfaction across 22 countries and Hong Kong as a separately sampled region.

The central result is deliberately modest. In the fully adjusted primary OLS model, rural residence is associated with **0.065 points higher life satisfaction on a 0-10 scale** (95% CI: 0.001 to 0.129). This small pooled association is not universal: its magnitude and direction vary substantially across analytical places. The pathway analysis points more clearly to economic insecurity than to a rural social-capital advantage, but the cross-sectional design does not establish causal mediation.

## Research questions

The study asks:

1. Is rural residence associated with life satisfaction after accounting for compositional differences and place fixed effects?
2. Are economic insecurity and social support statistically associated with the rural-urban life-satisfaction difference?
3. Does the rural association vary across countries and regions?
4. Do the conclusions remain similar under survey weighting, multilevel estimation, ordinal outcome models, alternative outcomes, and alternative sample definitions?

## Data and analytical design

- **Source:** Global Flourishing Study, Wave 1.
- **Coverage:** 22 countries plus Hong Kong as a separately sampled region, giving 23 analytical places.
- **Processed sample:** 207,919 respondents.
- **Primary common complete-case sample:** 183,685 respondents, or 88.3% of the processed sample.
- **Primary outcome:** Life Satisfaction, measured from 0 to 10.
- **Exposure:** Rural residence, with rural area/farm and small town/village coded as rural, and large city and suburb coded as urban.
- **Individual controls:** Age, gender, marital status, employment status, and education.
- **Economic-security pathways:** Income Security Feelings, Expense Worry recoded toward greater security, and Within-Place Income Percentile.
- **Social pathway:** A within-place standardized Social Capital Index combining willingness to help, having a confidant, and interpersonal trust.
- **Primary estimator:** OLS with analytical-place fixed effects and place-clustered CR2/Satterthwaite inference.
- **Path analysis:** A parallel observed-variable path model using the same sample, controls, place fixed effects, and associational interpretation as the primary OLS analysis.

All primary models use one locked common sample so that changes across specifications are not driven by changing respondents.

## Main findings

| Analysis | Estimate | 95% confidence interval | Interpretation |
|---|---:|---:|---|
| Primary OLS, M1: rural residence + place fixed effects | +0.026 | -0.096 to 0.148 | No clear unadjusted within-place difference |
| Primary OLS, M2: + individual controls | +0.027 | -0.074 to 0.129 | Total conditional association remains imprecise |
| Primary OLS, M3: + economic-security measures | +0.064 | -0.010 to 0.139 | Rural coefficient becomes more positive after accounting for economic insecurity |
| Primary OLS, M4: + Social Capital Index | **+0.065** | **0.001 to 0.129** | Small positive fully adjusted association |
| Total indirect association across four pathways | -0.037 | -0.082 to 0.008 | Negative point estimate, but interval includes zero |
| Indirect association through Income Security Feelings | **-0.019** | **-0.032 to -0.006** | Only specific pathway whose CR2 interval excludes zero |
| Survey-weighted fully adjusted OLS | +0.063 | 0.010 to 0.116 | Closely matches the primary unweighted result |
| Multilevel fixed rural association | +0.068 | 0.013 to 0.124 | Direction and magnitude are similar to primary OLS |

### Economic insecurity

Rural residence is conditionally associated with lower Income Security Feelings (-0.038; 95% CI: -0.062 to -0.015) and a lower Within-Place Income Percentile (-0.046; 95% CI: -0.061 to -0.030). The estimate for Expense Worry, recoded so that higher values indicate greater security, is also negative (-0.055), but its interval includes zero (-0.176 to 0.066).

The parallel path model gives negative point estimates for all four indirect associations. The strongest evidence concerns Income Security Feelings: its indirect estimate is -0.019 (95% CI: -0.032 to -0.006). The total indirect estimate is -0.037, but its CR2 interval includes zero. These results are best read as inconsistent conditional pathways, not as proof of partial or full mediation.

### Social capital

The Social Capital Index is strongly and positively associated with life satisfaction in the outcome equation (+0.853; 95% CI: 0.750 to 0.956). However, rural residence is not precisely associated with the index (-0.009; 95% CI: -0.035 to 0.017), and the social-capital indirect association is also imprecise (-0.008; 95% CI: -0.029 to 0.014).

The study therefore does **not** find evidence that stronger rural social capital explains or buffers rural-urban differences in life satisfaction. Social capital remains an important correlate of well-being across residential settings, but not a demonstrated rural pathway in these data.

### Place-level heterogeneity

The pooled estimate conceals substantial variation. Adjusted rural-residence coefficients are positive in Kenya (+0.489), Tanzania (+0.390), and Poland (+0.209), but negative in Israel (-0.252) and Japan (-0.186). Positive and negative estimates coexist within broad UN M49 geographic regions, so the findings do not support a simple continent-wide pattern.

The multilevel model estimates a random rural-slope standard deviation of 0.111, with partially pooled place slopes ranging from -0.095 to +0.348. Exploratory tests of the five indirect-association estimands also show pronounced heterogeneity (I² approximately 87% to 89%), and the total indirect estimates range from -0.219 to +0.163 across places.

These comparisons document context dependence; they do not identify which cultural, institutional, historical, or policy factors generate the differences.

## Robustness and sensitivity checks

- **Survey weighting:** The weighted M4 estimate is +0.063 (95% CI: 0.010 to 0.116), close to the primary estimate of +0.065.
- **Multilevel model:** A random-intercept, random-rural-slope model produces a fixed rural estimate of +0.068 (95% CI: 0.013 to 0.124).
- **Four-category ordinal outcome:** A proportional-odds model gives an odds ratio of 1.069 (95% CI: 1.018 to 1.122), but the proportional-odds assumption is rejected. The partial proportional-odds expected-category-score average marginal effect is +0.015 (95% CI: -0.001 to 0.032), so the ordinal evidence is more cautious than the OLS result.
- **Alternative outcomes:** Rural coefficients are +0.052 for Happiness (95% CI: -0.007 to 0.111) and +0.028 for Wellbeing Today (95% CI: -0.033 to 0.090). Both intervals include zero.
- **Alternative constructions and samples:** Results were checked using survey weights, model-specific available cases, pooled rather than within-place social-capital standardization, alternative income rankings, and matched alternative-outcome samples.
- **Bootstrap inference:** Joint Webb wild-cluster score bootstrap intervals were used as a sensitivity check for the small number of place clusters.

## Interpretation boundaries

This is a cross-sectional observational study. Its direct and indirect quantities are conditional associations, not causal effects. The analysis does not establish that moving between rural and urban settings changes well-being, that economic insecurity causally mediates the residential association, or that interventions targeting the measured pathways would necessarily increase life satisfaction.

The 23 analytical places are geographically diverse but not globally representative. The analysis also lacks harmonized place-level measures that could explain the observed heterogeneity, and the binary rural-urban measure necessarily simplifies residential diversity. The results therefore support context-specific interpretation rather than a universal rural advantage or disadvantage.

## Repository organization

| Path | Contents |
|---|---|
| [`scripts/run_batch_a_core_path.py`](scripts/run_batch_a_core_path.py) | Primary OLS sequence, parallel path model, CR2 inference, bootstrap inference, and prespecified sensitivity models |
| [`scripts/run_batch_a_robustness.py`](scripts/run_batch_a_robustness.py) | Four-category and 11-category ordinal models plus multilevel robustness |
| [`scripts/run_comment5_place_path_heterogeneity.py`](scripts/run_comment5_place_path_heterogeneity.py) | Exploratory place-specific pathway estimates and heterogeneity tests |
| [`scripts/run_comment7_sample_alignment.py`](scripts/run_comment7_sample_alignment.py) | Sample-denominator reconciliation, alternative outcomes, and weighting comparisons |
| [`scripts/run_comment6_geographic_forest.py`](scripts/run_comment6_geographic_forest.py) | Adjusted place-specific estimates grouped descriptively by UN M49 region |
| [`scripts/run_comment8_unadjusted_place_gaps.py`](scripts/run_comment8_unadjusted_place_gaps.py) | Survey-weighted unadjusted rural-urban gaps for all 23 places |
| [`etc/place_crosswalk.csv`](etc/place_crosswalk.csv) | Audited mapping of GFS place codes, place names, unit types, and UN M49 regions |
| `reports/batch_a_core/` | Validated model outputs, diagnostics, bootstrap draws, specifications, and run manifests |
| `reports/comment5_place_path_heterogeneity/` | Place-specific pathway results and heterogeneity outputs |
| `reports/comment7_sample_alignment/` | Sample-alignment, alternative-outcome, and weighted-model outputs |
| `Rev/revision/` | Local clean manuscript, marked-up manuscript, standalone supplement, response letter, and final figure assets |
| [`Rev/revision/response-draft.md`](Rev/revision/response-draft.md) | Version-controlled response to reviewers |

Generated reports, source data, and Word files are intentionally excluded from Git. They remain available in an authorized local workspace but are not redistributed through the public repository.

## Reproducing the analyses

### 1. Prepare the environment

The validated runs used Python 3.12.11 with NumPy 2.4.2, pandas 3.0.1, SciPy 1.17.1, statsmodels 0.14.6, Matplotlib 3.10.8, and PyArrow 23.0.1. The working conda environment for this project is `ZDP02n`:

```bash
conda activate ZDP02n
python -m pip install -r requirements.txt
```

For a new environment, install the analysis packages not yet pinned in `requirements.txt`:

```bash
conda create -n zdp02l python=3.12 -y
conda activate zdp02l
python -m pip install -r requirements.txt
python -m pip install pandas==3.0.1 scipy==1.17.1 statsmodels==0.14.6
```

### 2. Supply the restricted inputs

The scripts expect the following local files:

```text
data/processed/gfs_cleaned.parquet
data/raw/GFS_Codebook_20240208.pdf
etc/place_crosswalk.csv
```

The GFS data are not publicly downloadable and cannot be redistributed under the applicable data-use agreement. Researchers should request access through the official Global Flourishing Study process. The public analysis entry points begin from the validated processed Parquet file, so an authorized, schema-compatible copy at the path above is a prerequisite. The place crosswalk is version controlled in this repository.

### 3. Run the validated analyses

Run commands from the repository root:

```bash
# Primary OLS sequence and parallel path analysis
python scripts/run_batch_a_core_path.py --apply

# Ordinal and multilevel robustness models
python scripts/run_batch_a_robustness.py --apply

# Place-specific pathway heterogeneity
python scripts/run_comment5_place_path_heterogeneity.py --apply

# Sample alignment, weighting, and alternative outcomes
python scripts/run_comment7_sample_alignment.py --apply
```

Each primary script validates sample sizes, place coverage, design-matrix rank, numerical diagnostics, and output completeness before writing results. Default bootstrap analyses use 4,999 repetitions and may take substantial time. Use the scripts' `--bootstrap-repetitions` option only for development checks; final estimates should use the validated default.

The model and run manifests under `reports/` record input hashes, software versions, estimands, inference choices, output hashes, and validation gates. These manifests are the authoritative audit trail for computational reproduction.

## Manuscript and outputs

The final study package contains:

- a clean revised manuscript;
- a marked-up revised manuscript;
- a standalone supplementary-materials document;
- a point-by-point response to reviewers;
- six main tables and three main figures; and
- Supplementary Tables S1-S5 and Supplementary Figure S1.

The public code repository supports the study's Data Availability statement, while restricted GFS microdata remain subject to provider approval.

## License

Project code and documentation are released under the terms described in [`INTELLECTUAL_PROPERTY.md`](INTELLECTUAL_PROPERTY.md). Third-party data, publications, and software remain subject to their own licenses and data-use conditions.
