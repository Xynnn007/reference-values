#!/usr/bin/env python3

import pathlib
import subprocess
import sys

import yaml


def main(config_path: str) -> int:
    config_file = pathlib.Path(config_path).resolve()
    repo_root = config_file.parent

    with open(config_file, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    kata = config["kata"]
    artifacts = config.get("artifacts", [])
    verify_script = repo_root / "verify-provenance.sh"

    source_repo = kata["source_repository"]
    source_revision = str(kata["revision"])
    workflow_digest = str(kata["workflow_digest"])
    workflow_trigger = str(kata["workflow_trigger"])
    oci_base = kata["oci"].rstrip("/")

    failures = 0
    for artifact in artifacts:
        name = artifact["name"]
        digest = str(artifact["oras_sha256"]).strip()
        if not digest:
            print(f"[ERROR] artifact '{name}' missing oras_sha256", file=sys.stderr)
            failures += 1
            continue
        if not digest.startswith("sha256:"):
            digest = f"sha256:{digest}"

        oci_artifact = f"{oci_base}/{name}@{digest}"
        cmd = [
            str(verify_script),
            "-a",
            oci_artifact,
            "-s",
            source_revision,
            "-w",
            workflow_digest,
            "-t",
            workflow_trigger,
            "-r",
            source_repo,
        ]
        print(f"[INFO] Verifying {name}: {oci_artifact}")
        proc = subprocess.run(cmd, cwd=repo_root)
        if proc.returncode != 0:
            failures += 1

    if failures:
        print(f"[ERROR] Attestation verification failed for {failures} artifact(s).")
        return 1

    print("[INFO] All artifact attestations verified successfully.")
    return 0


if __name__ == "__main__":
    config_arg = sys.argv[1] if len(sys.argv) > 1 else "versions.yaml"
    raise SystemExit(main(config_arg))
