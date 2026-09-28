#!/usr/bin/env python3
"""Keep the private repository's PDF engine and reporter identical to the public ones."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHARED_SCRIPTS = ("validate_slide_pdf.py", "report_pdf_validation.py")


def main() -> None:
    destination = ROOT / "templates/private-slides/scripts"
    destination.mkdir(parents=True, exist_ok=True)
    for name in SHARED_SCRIPTS:
        (destination / name).write_bytes((ROOT / "scripts" / name).read_bytes())
        print(f"Synced {name} into the private slide template.")


if __name__ == "__main__":
    main()
