# MiliFrame — Research Project Template

> Before you begin, read and agree to [TEAM_RULES.md](./TEAM_RULES.md).

A reproducible research project template built on **Git + DVC + Jupytext**, with a structured export interface for downstream manuscript generation via **Jiazi**.

---

## Quick Start

See [COMMANDS.md](./COMMANDS.md) for the full setup walkthrough. The short version:

```bash
# 1. Clone and rename
export myproj=YOUR_PROJECT_NAME
git clone https://github.com/MichaelChaoLi-cpu/MiliFrame-Template.git
mv MiliFrame-Template $myproj && cd $myproj

# 2. Set up environment
echo "PROJECT_ROOT=$(pwd)" >> .env
conda create -n $myproj python=3.12 -y && conda activate $myproj
pip install -r requirements.txt
pre-commit install

# 3. Pull data
dvc pull
```

---

## Repository Structure

```
myproj/
├── notebooks/          # Source .ipynb (outputs stripped by pre-commit)
├── nbs/                # Paired .py files (percent format, for Git diff)
├── data/               # Datasets (DVC-tracked, Git-ignored)
├── reports/            # Metrics and plots (DVC-tracked)
├── scripts/            # Shell utilities
├── actionplan/         # Workflow diagrams, named by version (e.g. v0.1.0.md)
├── LAWS/               # Schema definitions for artifacts and exports
├── export/             # Final artifacts for Jiazi ingestion
├── params.yaml         # Centralised experiment parameters
├── dvc.yaml            # Pipeline definition
├── experiment_log.md   # Log of completed experiments
└── pyproject.toml      # Project metadata and version
```

---

## Export & Jiazi Integration

The `export/` directory is the **sole interface** between this analysis repo and Jiazi (manuscript generation). Place all final artifacts here before handing off.

### Required layout

```
export/
├── figures/            # figXX_description.png | .jpg
├── tables/             # TableX_description.xlsx
├── code/
│   └── run_analysis.py # Reproduces all figures and tables without notebook execution
├── configs/            # (optional) params.yaml, experiment_config.yaml
├── metadata/           # variable_dictionary.yaml, dataset_dictionary.yaml
└── actionbrief.yaml    # Core interface validated against LAWS/law_actionbrief.yaml
```

### actionbrief.yaml — required fields

| Field | Description |
|-------|-------------|
| `doc_type: actionbrief` | Document type identifier |
| `version` | Schema/instance version |
| `datasetDictionary` | Keyed descriptors for every dataset used |
| `variableDictionary` | Keyed descriptors for every variable used |
| `figureDictionary` | Keyed descriptors for every exported figure |
| `tableDictionary` | Keyed descriptors for every exported table |
| `analysisStructureBrief.levels` | Ordered analytical levels (inputs → method → outputs → interpretation) |

Schema validated against [`LAWS/law_actionbrief.yaml`](./LAWS/law_actionbrief.yaml).

### Rules

- `export/` contains **only final artifacts** — no intermediate outputs.
- Every figure/table listed in `actionbrief.yaml` must physically exist in `export/figures/` or `export/tables/`.
- `run_analysis.py` must regenerate all exported artifacts without notebook execution.
- Jiazi will never modify files inside `export/`.

---

## Key Documents

| File | Purpose |
|------|---------|
| [COMMANDS.md](./COMMANDS.md) | Full setup and day-to-day command reference |
| [TEAM_RULES.md](./TEAM_RULES.md) | Branching, commit conventions, experiment workflow |
| [LAWS/law_actionbrief.yaml](./LAWS/law_actionbrief.yaml) | Schema for `export/actionbrief.yaml` |
| [LAWS/law_export_folder.yaml](./LAWS/law_export_folder.yaml) | Schema for the `export/` directory structure |
| [actionplan/](./actionplan/) | Version-tagged workflow diagrams |
| [experiment_log.md](./experiment_log.md) | Record of completed experiments |

---

## License

MIT — see [INTELLECTUAL_PROPERTY.md](./INTELLECTUAL_PROPERTY.md).
