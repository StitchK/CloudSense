"""Build the standalone Lambda3 zip; boto3 is provided by the Lambda runtime."""

import argparse
import hashlib
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_package(output_path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in sorted((PROJECT_ROOT / "src" / "query").glob("*.py")):
            archive.write(source, source.relative_to(PROJECT_ROOT / "src"))
    return hashlib.sha256(output_path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=PROJECT_ROOT / "dist" / "cloudsense-query.zip"
    )
    args = parser.parse_args()
    print(f"sha256={build_package(args.output)}")
    print(f"package={args.output.resolve()}")
    print("handler=query.app.lambda_handler")


if __name__ == "__main__":
    main()
