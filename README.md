# Toolframe llms.txt provider

`toolframe-llms-txt` is the standalone Toolframe provider for serving the
selected set of `llms.document` resources. The provider owns the public
`/llms.txt` index and the linked `/llms/{owner}/{document}.md` documents; it
serves document text supplied in `OwnedResource.content` and never opens a
package path or scans a filesystem at request time.

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
