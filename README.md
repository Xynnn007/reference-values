# Reference Values

This repository calculates and publishes reference values for **CoCo (Confidential Containers)** artifacts.

It pulls Kata artifacts from OCI registry, unpacks the expected payload, runs calculator tools, collects `stdout`, and generates a final JSON file in Sample format.

## Repository Purpose

- Keep a declarative config of target versions and calculators in `versions.yaml`
- Reproducibly calculate reference values from CoCo-related artifacts
- Upload generated reference values as workflow artifacts and release assets
- Generate SLSA build provenance attestation for the output JSON
- Generate SBOM of the building provenances

## How It Works

1. Read `versions.yaml`
2. For each item in `artifacts`:
   - Pull artifact files from:
     - `<kata.registry>/<kata.repository>/<name>:<kata.version>-<arch>`
   - Find and extract:
     - `kata-static-<name>.tar.zst`
   - Download `calculator_url`
   - Execute calculator with `runtime` and `args`
   - Collect calculator `stdout`
3. Write final output JSON to:
   - `results/reference-values.json`

## Local Run

Prerequisites:

- `python3`
- `oras`
- Python dependency: `pyyaml`

Install dependency:

```bash
pip install pyyaml
```

Run:

```bash
python3 release.py versions.yaml results/reference-values.json
```

## GitHub Actions

Workflow file:

- `.github/workflows/reference-values.yml`

Triggers:

- `workflow_call` (no inputs, always uses repository defaults)
- `release` with `published` type

Default behavior:

- Build output with:
  - config: `versions.yaml`
  - output: `results/reference-values.json`
- Upload JSON as workflow artifact
- Generate SLSA attestation for the JSON
- On release events, upload JSON to the GitHub Release assets