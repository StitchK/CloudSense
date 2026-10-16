#!/usr/bin/env python3
"""Build a Lambda zip containing the Ingest handler and shared modules."""

from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
PACKAGE_PATHS = (
    SOURCE_ROOT / "common",
    SOURCE_ROOT / "ingest",
)


def build_package(output_path: Path) -> tuple[Path, str, int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(
        output_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for package_root in PACKAGE_PATHS:
            for source_file in sorted(package_root.rglob("*.py")):
                archive.write(
                    source_file,
                    source_file.relative_to(SOURCE_ROOT).as_posix(),
                )

    payload = output_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    return output_path, digest, len(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "dist" / "cloudsense-ingest.zip",
    )
    args = parser.parse_args()

    output_path, digest, size = build_package(args.output.resolve())
    print(f"package={output_path}")
    print(f"size_bytes={size}")
    print(f"sha256={digest}")
    print("handler=ingest.app.lambda_handler")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
