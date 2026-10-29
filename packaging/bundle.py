#!/usr/bin/env python3
"""Create a clean source archive without repository, cache, or local config data."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "CornerNote.zip"
INCLUDE = ("README.md", "LICENSE", "config.example.json", "corner-note",
           "cornernote.desktop", "install.sh", "uninstall.sh", "src", "packaging")
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache"}


def main() -> None:
    """Create the distributable archive from source files."""
    with ZipFile(OUTPUT, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for entry in INCLUDE:
            source = ROOT / entry
            paths = [source] if source.is_file() else sorted(source.rglob("*"))
            for path in paths:
                if not path.is_file() or any(part in EXCLUDE_DIRS for part in path.parts):
                    continue
                if path == OUTPUT or path.name == "config.json":
                    continue
                archive.write(path, Path("CornerNote") / path.relative_to(ROOT))
    print(f"Created {OUTPUT}")


if __name__ == "__main__":
    main()
