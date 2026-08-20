"""Update the public slide-delivery manifest deterministically."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default="_data/slide_modes.yml")
    parser.add_argument("--record-id", required=True)
    parser.add_argument("--mode", choices=("public", "private"), required=True)
    args = parser.parse_args()
    path = Path(args.path)
    entries: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            entries[key.strip()] = value.strip()
    entries[args.record_id] = args.mode
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Maintainer-managed delivery modes. Omitted records are public by default.\n"
        + "".join(f"{key}: {entries[key]}\n" for key in sorted(entries)),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
