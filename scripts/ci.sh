#!/usr/bin/env bash
# Run the same isolated checks locally and on GitHub Actions.
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
sdk_repo=${1:-"$repo_root/../toolframe-sdk"}
dist_output=${2:-}
sdk_revision=871416a9f9cbcfa79298235781ff193e1ad08a12

if (( $# > 2 )); then
  printf 'Usage: bash scripts/ci.sh [sdk-repository] [new-distribution-directory]\n' >&2
  exit 2
fi
if [[ -n "$dist_output" && "$dist_output" != /* ]]; then
  dist_output="$repo_root/$dist_output"
fi
if [[ -n "$dist_output" && -e "$dist_output" ]]; then
  printf 'Distribution output must not already exist: %s\n' "$dist_output" >&2
  exit 2
fi
sdk_repo=$(cd -- "$sdk_repo" && pwd)
git -C "$sdk_repo" cat-file -e "$sdk_revision^{commit}"

# Ignore the caller's active development environment.
unset VIRTUAL_ENV PYTHONPATH PYTHONHOME UV_PROJECT_ENVIRONMENT
python=$(uv python find --system --no-project "${PYTHON_VERSION:-3.14.7}")
workspace=$(mktemp -d "${TMPDIR:-/tmp}/toolframe-llms-txt-ci.XXXXXX")
cleanup() {
  if [[ ${CI_KEEP_TEMP:-0} == 1 ]]; then
    printf 'Kept isolated workspace: %s\n' "$workspace"
  else
    rm -rf -- "$workspace"
  fi
}
trap cleanup EXIT
printf 'Isolated workspace: %s\nSDK revision: %s\n' "$workspace" "$sdk_revision"
"$python" --version
uv --version
export UV_CACHE_DIR="$workspace/uv-cache"

"$python" - "$repo_root" "$workspace/toolframe-llms-txt" <<'PY'
import shutil
import sys

shutil.copytree(
    sys.argv[1],
    sys.argv[2],
    ignore=shutil.ignore_patterns(
        ".git", ".venv", "dist", "__pycache__", ".pytest_cache", ".ruff_cache",
        "*.egg-info", ".coverage", ".DS_Store",
    ),
)
PY
mkdir "$workspace/toolframe-sdk"
git -C "$sdk_repo" archive "$sdk_revision" | tar -x -C "$workspace/toolframe-sdk"

cd "$workspace/toolframe-llms-txt"
bash -n scripts/ci.sh
uv sync --locked --group dev --python "$python"
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
.venv/bin/python -m pytest -q

# uv builds a wheel from the newly built sdist when neither format is selected.
uv build --no-sources --python "$python" --out-dir "$workspace/dist"
uv tool run --isolated --python "$python" --from twine==7.0.0 \
  twine check --strict "$workspace/dist/"*.whl "$workspace/dist/"*.tar.gz
uv build --no-sources --wheel --python "$python" \
  --out-dir "$workspace/dependency-wheels" "$workspace/toolframe-sdk"

uv venv --python "$python" "$workspace/wheel-venv"
wheel_python="$workspace/wheel-venv/bin/python"
uv pip install --no-sources --python "$wheel_python" \
  "$workspace/dist/"*.whl "$workspace/dependency-wheels/"*.whl
uv pip check --python "$wheel_python"

# Leave the source tree and use isolated imports. Only runtime dependencies are
# installed here; neither editable packages nor the test tools are available.
cd "$workspace"
"$wheel_python" -I "$workspace/toolframe-llms-txt/scripts/check_wheel.py" \
  "$workspace/dist" "$workspace/toolframe-llms-txt"

if [[ -n "$dist_output" ]]; then
  "$python" - "$workspace/dist" "$dist_output" "$repo_root" <<'PY'
from pathlib import Path
import shutil
import sys

destination = Path(sys.argv[2])
if not destination.is_absolute():
    destination = Path(sys.argv[3]) / destination
destination.mkdir(parents=True, exist_ok=False)
for artifact in Path(sys.argv[1]).iterdir():
    if artifact.name.endswith((".whl", ".tar.gz")):
        shutil.copy2(artifact, destination / artifact.name)
print(f"Validated distributions: {destination}")
PY
fi
printf 'All provider, distribution, and installed-wheel checks passed.\n'
