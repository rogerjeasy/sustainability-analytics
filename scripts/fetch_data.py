#!/usr/bin/env python
"""Fetch every raw input declared in config/sources.yml.

    make fetch          download whatever is missing or corrupt
    make fetch-check    report status only, download nothing

Downloads are verified against committed checksums, so a truncated or
wrong-version file fails loudly rather than silently producing a broken panel.
"""

from __future__ import annotations

import argparse
import sys

from wildfires.config import project_root
from wildfires.fetch import download, load_manifest, verify

_MARK = {"ok": "OK     ", "missing": "MISSING", "corrupt": "CORRUPT"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report status only; download nothing")
    parser.add_argument("--force", action="store_true",
                        help="re-download even when the local file verifies")
    parser.add_argument("--only", metavar="SUBSTRING",
                        help="restrict to sources whose target path contains this")
    args = parser.parse_args()

    root = project_root()
    sources = load_manifest()
    if args.only:
        sources = [s for s in sources if args.only in str(s.target)]
        if not sources:
            print(f"No source matches --only {args.only!r}")
            return 1

    failed = 0
    for source in sources:
        state = verify(source)
        relative = source.target.relative_to(root)

        if args.check:
            print(f"[{_MARK[state]}] {source.name}\n           {relative}")
            failed += state != "ok"
            continue

        if state == "ok" and not args.force:
            print(f"[OK     ] {source.name}")
            continue

        size_mb = source.bytes / 1_000_000
        print(f"[FETCH  ] {source.name}  ({size_mb:.1f} MB)")
        if download(source, force=args.force) != "ok":
            failed += 1

    total = len(sources)
    print(f"\n{total - failed}/{total} sources ready.")
    if failed:
        print("Re-run `make fetch` to retry. See data/README.md for provenance.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
