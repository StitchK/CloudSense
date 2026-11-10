"""Package reviewed local sources for upload to AWS CloudShell."""

from pathlib import Path
import hashlib
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def main():
    package = HERE / "lambda_sources.zip"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in sorted((ROOT / "src").rglob("*.py")):
            archive.write(source, source.relative_to(ROOT / "src"))
    bundle = HERE / "lab_bundle.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ["cloud_lab.py", "collect_usage_details.py", "collect_security.py", "run_low_load.py", "dashboard.html", "lambda_sources.zip"]:
            archive.write(HERE / name, "evaluation/" + name)
    print(bundle)
    print("sha256", hashlib.sha256(bundle.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
