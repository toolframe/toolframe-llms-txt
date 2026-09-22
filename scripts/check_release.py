"""Reject publishing unless the workflow ref exactly matches project.version."""

import os
import sys
import tomllib
from pathlib import Path


def main() -> None:
    repository = os.environ.get("PUBLISH_REPOSITORY", "testpypi")
    if repository not in {"testpypi", "pypi"}:
        raise SystemExit("Publishing repository must be testpypi or pypi.")
    project_file = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(project_file.read_text())["project"]
    expected = f"refs/tags/v{project['version']}"
    if len(sys.argv) != 2 or sys.argv[1] != expected:
        raise SystemExit(
            f"Publishing requires the tag {expected}; branches are rejected."
        )
    print(f"Validated release ref: {expected}")


if __name__ == "__main__":
    main()
