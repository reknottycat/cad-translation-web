"""Assemble the source runtime delivery through the canonical release filter."""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import tarfile
import tempfile

from release_manifest import audit_directory, copy_tree_into, write_tools_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    with tempfile.TemporaryDirectory(prefix="cad_source_release_") as directory:
        stage = Path(directory)
        for source, target in (("backend", "backend"), ("frontend/dist", "frontend/dist"),
                               ("tools", "tools"), ("docs/modern", "docs/modern"),
                               ("agent-harness", "cli")):
            copy_tree_into(stage, root / source, target)
        shutil.copyfile(root / "requirements.txt", stage / "requirements.txt")
        write_tools_manifest(stage / "tools")
        audit_directory(stage, required=("backend/app/main.py", "frontend/dist/index.html"))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(args.output, "w:gz") as archive:
            for item in sorted(stage.rglob("*")):
                if item.is_file():
                    archive.add(item, arcname=item.relative_to(stage).as_posix(), recursive=False)
    print(f"source release ready: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
