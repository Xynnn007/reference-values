#!/usr/bin/env python3

import json
import pathlib
import subprocess
import sys

try:
    from ruamel.yaml import YAML  # type: ignore[reportMissingImports]
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: ruamel.yaml. Install with `pip install ruamel.yaml`."
    ) from exc


def resolve_digest(reference: str) -> str:
    cmd = ["oras", "manifest", "fetch", "--descriptor", reference]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Failed to resolve digest for {reference}: {proc.stderr.strip()}")

    descriptor = json.loads(proc.stdout)
    digest = descriptor.get("digest", "")
    if not digest.startswith("sha256:"):
        raise RuntimeError(f"Unexpected digest for {reference}: {digest}")
    return digest


def main(config_path: str, kata_tag: str) -> int:
    config_file = pathlib.Path(config_path).resolve()
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)

    with open(config_file, "r", encoding="utf-8") as f:
        config = yaml.load(f)

    kata = config["kata"]
    artifacts = config.get("artifacts", [])
    oci_base = str(kata["oci"]).rstrip("/")

    kata["tag"] = kata_tag

    for artifact in artifacts:
        name = artifact["name"]
        arch = artifact.get("arch", "x86_64")
        ref = f"{oci_base}/{name}:{kata_tag}-{arch}"
        digest = resolve_digest(ref)
        artifact["oras_sha256"] = digest
        print(f"[INFO] {name}: {ref} -> {digest}")

    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(config, f)

    print(f"[INFO] Updated digests in {config_file}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: update-oras-digests.py <versions.yaml> <kata-tag>", file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
