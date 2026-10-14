# Toolframe llms.txt provider

`toolframe-llms-txt` is the standalone Toolframe provider for serving the
selected set of `llms.document` resources. The provider owns the public
`/llms.txt` index and the linked `/llms/{owner}/{document}.md` documents; it
serves document text supplied in `OwnedResource.content` and never opens a
package path or scans a filesystem at request time.

## Install

Install the provider into a running [Toolframe application](https://github.com/toolframe/toolframe-core#readme):

```sh
toolframe --home APP plugin add pypi:toolframe-llms-txt==0.2.1 --enable
```

Core resolves dependencies and manages the provider's isolated Python environment.
The Entry Register template already includes this provider.

Each `prepare` call validates and stages a complete immutable document set for
its epoch. Staging and aborting leave the current HTTP responses unchanged.
`commit` atomically selects one staged epoch, replacing the index and its
documents together. A later epoch can contain fewer or no documents, which
withdraws entries from the live provider. Other staged epochs remain available
until they are committed or aborted.

The optional `intro` configuration string is placed before the deterministic,
owner and document ID sorted link list.

From this directory, install the development environment and run the checks:

```sh
uv sync --group dev
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
uv build --wheel
```

For the complete, isolated CI check (including sdist/wheel metadata, licenses,
real dependency installation, and installed-wheel HTTP checks), run:

```sh
bash scripts/ci.sh
```

This requires Python 3.14.7, uv 0.12.8, and a sibling `toolframe-sdk` Git
checkout containing the pinned SDK revision. It leaves the working development
environment untouched. See [CI and publishing](docs/ci.md) for the dependency
pin, workflow triggers, release commands, and required external setup.

For release validation and Trusted Publisher setup, see [releasing](docs/releasing.md).

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
