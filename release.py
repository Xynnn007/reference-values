import json
import logging
import os
import pathlib
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: PyYAML. Install with `pip install pyyaml`."
    ) from exc

LOG = logging.getLogger("reference-values")


class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[36m",     # cyan
        logging.INFO: "\033[32m",      # green
        logging.WARNING: "\033[33m",   # yellow
        logging.ERROR: "\033[31m",     # red
        logging.CRITICAL: "\033[1;31m" # bold red
    }
    RESET = "\033[0m"

    def __init__(self, fmt, use_color):
        super().__init__(fmt)
        self.use_color = use_color

    def format(self, record):
        message = super().format(record)
        if not self.use_color:
            return message
        color = self.COLORS.get(record.levelno, "")
        if not color:
            return message
        return f"{color}{message}{self.RESET}"


def setup_logging():
    use_color = sys.stderr.isatty() and "NO_COLOR" not in os.environ
    handler = logging.StreamHandler()
    handler.setFormatter(
        ColorFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s - %(message)s",
            use_color=use_color,
        )
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [handler]


def read_yaml(path):
    LOG.info("Loading config: %s", path)
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_clean_dir(path):
    LOG.debug("Resetting directory: %s", path)
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)


def download_file(url, dest):
    LOG.info("Downloading file: %s -> %s", url, dest)
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


def run_oras_pull(reference, output_dir):
    LOG.info("Pulling artifact via oras: %s", reference)
    cmd = ["oras", "pull", "--output", str(output_dir), reference]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise RuntimeError(f"oras pull failed for '{reference}': {stderr}")


def extract_archive(archive_path, extract_to):
    LOG.info("Extracting archive: %s -> %s", archive_path, extract_to)
    # Use system tar for broader compression support (.tar.zst/.tar.xz).
    cmd = ["tar", "-xf", str(archive_path), "-C", str(extract_to)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise RuntimeError(
            f"Failed to extract '{archive_path}' with tar: {stderr or proc.stdout.strip()}"
        )


def render_args(args, values):
    rendered = []
    for arg in args:
        item = str(arg)
        for key, value in values.items():
            item = item.replace(f"{{{{{key}}}}}", value)
        rendered.append(item)
    return rendered


def run_tool(runtime, tool_file, args, cwd):
    cmd = [runtime, str(tool_file), *args]
    LOG.info("Running calculator (cwd=%s): %s", cwd, " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    stdout = proc.stdout.strip()
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise RuntimeError(
            f"Calculator failed with exit={proc.returncode}: {stderr or stdout}"
        )
    return stdout


def main(config_path, output_path):
    LOG.info("Starting reference value build")
    config = read_yaml(config_path)
    result_version = str(config["version"])
    kata = config["kata"]
    artifacts = config.get("artifacts", [])

    if not artifacts:
        raise RuntimeError("No artifacts configured in versions.yaml.")

    oci_base = kata["oci"].rstrip("/")
    kata_tag = str(kata["tag"])

    work_dir = pathlib.Path(config_path).resolve().parent / ".work"
    pulls_dir = work_dir / "pulls"
    extracts_dir = work_dir / "extracts"
    tools_dir = work_dir / "tools"
    ensure_clean_dir(pulls_dir)
    ensure_clean_dir(extracts_dir)
    ensure_clean_dir(tools_dir)
    LOG.info("Workspace prepared at: %s", work_dir)

    final_result = {}
    for artifact in artifacts:
        artifact_name = artifact["name"]
        artifact_arch = artifact.get("arch", "x86_64")
        reference_value_uri = artifact["reference_value_uri"]
        calculator_url = artifact["calculator_url"]
        runtime = artifact["runtime"]
        args = artifact.get("args", [])
        LOG.info("Processing artifact: %s (arch=%s)", artifact_name, artifact_arch)

        oras_digest = str(artifact["oras_sha256"]).strip()
        if not oras_digest:
            raise RuntimeError(
                f"Artifact '{artifact_name}' is missing required field 'oras_sha256'."
            )
        if not oras_digest.startswith("sha256:"):
            oras_digest = f"sha256:{oras_digest}"

        oras_reference = f"{oci_base}/{artifact_name}@{oras_digest}"
        pulled_dir = pulls_dir / artifact_name
        ensure_clean_dir(pulled_dir)
        run_oras_pull(oras_reference, pulled_dir)

        archive_name = f"kata-static-{artifact_name}.tar.zst"
        archive_path = pulled_dir / archive_name
        if not archive_path.exists():
            raise FileNotFoundError(
                f"Expected archive '{archive_name}' not found under '{pulled_dir}'."
            )

        extract_dir = extracts_dir / artifact_name
        ensure_clean_dir(extract_dir)
        extract_archive(archive_path, extract_dir)

        tool_filename = pathlib.Path(urllib.parse.urlparse(calculator_url).path).name
        tool_path = tools_dir / f"{artifact_name}-{tool_filename}"
        download_file(calculator_url, tool_path)
        tool_path.chmod(0o755)

        rendered_args = render_args(
            args,
            {
                "extract_dir": str(extract_dir),
                "name": artifact_name,
                "arch": artifact_arch,
                "kata_version": kata_tag,
            },
        )
        stdout = run_tool(runtime, tool_path, rendered_args, extract_dir)

        output_key = f"{reference_value_uri}:{result_version}"
        final_result[output_key] = stdout
        LOG.info("Collected output for key: %s", output_key)

    out_path = pathlib.Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    LOG.info("Writing output JSON: %s", out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(final_result, f, ensure_ascii=False, indent=2)
        f.write("\n")

    LOG.info("Reference value build completed: %d item(s)", len(final_result))
    print(json.dumps(final_result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    setup_logging()
    config_arg = sys.argv[1] if len(sys.argv) > 1 else "versions.yaml"
    output_arg = sys.argv[2] if len(sys.argv) > 2 else "results/output.json"
    main(config_arg, output_arg)