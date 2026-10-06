# CI and publishing

## Local validation

Install Python 3.14.7 and uv 0.12.8, then run from this repository:

```sh
bash scripts/ci.sh
```

The SDK source defaults to `../toolframe-sdk`. It must be a Git checkout that
contains commit `871416a9f9cbcfa79298235781ff193e1ad08a12`. The script uses
`git archive` of that exact commit, so concurrent or uncommitted SDK changes do
not affect this validation. To choose another checkout or retain the validated
distributions, pass paths explicitly:

```sh
bash scripts/ci.sh /path/to/toolframe-sdk /tmp/new-llms-txt-distributions
```

The output directory must not exist. Relative output paths are relative to this
repository. `CI_KEEP_TEMP=1 bash scripts/ci.sh` retains the temporary workspace
and prints its path for inspection; otherwise it is removed on exit.

Every run starts with a fresh workspace, uv cache, development environment,
dependency wheel directory, and runtime environment. It copies the current
provider sources without `.venv`, `dist`, or caches and exports the SDK pin.
Neither repository's existing development environment or lockfile is changed.
The checks are:

1. `uv sync --locked --group dev` with Python 3.14.7.
2. `ruff check src tests scripts`, `ruff format --check src tests scripts`,
   `bash -n scripts/ci.sh`, and the existing `pytest -q` provider suite.
3. `uv build --no-sources` for the sdist and wheel. With no format selection,
   uv builds the wheel from that sdist.
4. `twine==7.0.0 check --strict` on both artifacts. Twine 7 supports the
   Metadata-Version 2.5 emitted by the current build backend; 6.2.0 rejects it.
5. A new SDK wheel built from the pinned sources with `uv build --no-sources
   --wheel`, then an empty virtual environment receiving both explicit wheels
   with normal dependency resolution and `uv pip check`. Starlette, uvicorn,
   Pydantic, JSON Schema, and their runtime dependencies are actually installed.
6. `python -I scripts/check_wheel.py` outside the source tree verifies the
   installed version, plugin entry point, imports from the runtime environment,
   and exact `LICENSE`/`NOTICE` contents in both distributions. A real localhost
   HTTP server checks the empty index, staging, commit, document content and
   MIME types, withdrawal/404 responses, and shutdown using runtime packages
   plus the standard library only.

The script fails at the first unsuccessful check. It does not use `--no-deps`,
skip existing tests, or publish anything. Index access is required even if a
developer already has packages cached. `PYTHON_VERSION` may explicitly override
the local interpreter request; GitHub uses 3.14.7.

To check workflow and shell syntax locally, install
[actionlint](https://github.com/rhysd/actionlint) 1.7.12 and run:

```sh
actionlint .github/workflows/ci.yml .github/workflows/publish.yml
bash -n scripts/ci.sh
git diff --check
```

## GitHub workflows

`ci.yml` runs on pushes, pull requests, manual dispatch, and calls from the
publish workflow. It uses `ubuntu-24.04`, Python 3.14.7, uv 0.12.8, read-only
repository permissions, SHA-pinned actions, a 20-minute timeout, and the same
local script. Only successfully validated provider distributions are uploaded
as the `python-distributions` artifact, retained for seven days. The SDK wheel
is a validation dependency and is not part of that upload.

The required sibling checkout is
`${TOOLFRAME_REPOSITORY_OWNER}/toolframe-sdk`, where the repository variable
`TOOLFRAME_REPOSITORY_OWNER` defaults to `github.repository_owner`. In a fork PR
run on the upstream repository, this is the upstream owner, never the PR
author's owner. The SDK checkout is fixed to the full commit above. There is
no `pull_request_target` execution or shared reusable-workflow concurrency
group that could cancel the publish caller.

`publish.yml` runs only on manual dispatch. Its `repository` input selects
`testpypi` (default) or `pypi`. It first requires `GITHUB_REF` to equal
`refs/tags/v<project.version>` exactly; branch runs and mismatched tags fail.
The release guard also rejects any index input other than those two choices.
It calls CI from the same workflow revision and checks out `github.sha`, then
downloads the artifacts from that run without rebuilding them. Only the final
job has `id-token: write`, uses the selected GitHub environment, and invokes
the PyPA publishing action with the appropriate index URL. Publication runs
for the same tag and index queue without cancelling one another.

## External setup before running remotely

1. Create/configure the actual GitHub `toolframe-llms-txt` repository and enable
   Actions. Push these workflows to its default branch and include them in the
   release tag. No GitHub remote or owner is assumed by these files.
2. Make `toolframe-sdk` and the pinned commit available under the chosen owner.
   Set the `TOOLFRAME_REPOSITORY_OWNER` repository variable only when that owner
   differs. The supplied sibling checkout assumes the SDK repository is public;
   the default `GITHUB_TOKEN` does not grant access to a different private
   repository. Private sibling access needs a separately designed credential
   and fork-PR policy before this workflow can use it.
3. Create GitHub environments named exactly `testpypi` and `pypi`. Configure
   reviewers and allowed release tags as appropriate for the repository.
4. On TestPyPI and PyPI separately, add a GitHub Trusted Publisher for the
   `toolframe-llms-txt` project (or a pending publisher for a new project):

   | Publisher field | Value |
   | --- | --- |
   | Owner | The actual GitHub owner of this repository |
   | Repository | `toolframe-llms-txt` |
   | Workflow filename | `publish.yml` |
   | Environment | `testpypi` on TestPyPI; `pypi` on PyPI |

   No PyPI API token is needed. Set up both services independently.
5. Publish `toolframe-sdk==0.2.0` to the target index before claiming consumers
   can install this provider from that index alone. CI supplies its own SDK
   wheel; it does not establish that the SDK is publicly released. TestPyPI
   may also lack the public third-party dependencies used by the provider.

For the current version `0.2.0`, an authorized maintainer can create and push
`v0.2.0` at the desired verified commit, then request publication using GitHub
CLI from this repository:

```sh
gh workflow run publish.yml --ref v0.2.0 -f repository=testpypi
# After inspecting the TestPyPI result, publish the same verified release:
gh workflow run publish.yml --ref v0.2.0 -f repository=pypi
```

Change the example tag when `project.version` changes. Running the workflow on
a branch does not publish. Existing index versions/files cannot simply be
replaced; choose the intended release version before tagging.

The local tag guard can be checked without creating a Git tag:

```sh
python3.14 scripts/check_release.py refs/tags/v0.2.0
# Expected to fail:
python3.14 scripts/check_release.py refs/heads/main
python3.14 scripts/check_release.py refs/tags/v9.9.9
```

Local macOS verification and actionlint do not execute a GitHub-hosted Ubuntu
run or an OIDC upload. This package check also does not establish platform
support for the full Toolframe application. No remote push, release, package
upload, environment configuration, or Trusted Publisher registration is
performed by the local validation command.
