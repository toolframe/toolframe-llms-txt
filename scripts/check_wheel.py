"""Check distribution licenses and exercise a clean wheel's public HTTP API."""

import asyncio
import sys
import tarfile
import tomllib
from importlib.metadata import distribution, version
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, build_opener
from zipfile import ZipFile

import starlette
import toolframe_sdk
import uvicorn
from toolframe_sdk import OwnedResource, Resource, RuntimeContext

import toolframe_llms_txt


def check_distributions(dist_dir: Path, source: Path) -> None:
    project = tomllib.loads((source / "pyproject.toml").read_text())["project"]
    assert version(project["name"]) == project["version"]
    wheels = list(dist_dir.glob("*.whl"))
    sdists = list(dist_dir.glob("*.tar.gz"))
    assert len(wheels) == len(sdists) == 1
    with ZipFile(wheels[0]) as wheel, tarfile.open(sdists[0]) as sdist:
        for filename in ("LICENSE", "NOTICE"):
            expected = (source / filename).read_bytes()
            wheel_path = next(
                name
                for name in wheel.namelist()
                if name.endswith(f".dist-info/licenses/{filename}")
            )
            assert wheel.read(wheel_path) == expected
            sdist_path = f"{sdists[0].name.removesuffix('.tar.gz')}/{filename}"
            with sdist.extractfile(sdist_path) as license_file:
                assert license_file.read() == expected
    for module in (toolframe_llms_txt, toolframe_sdk, starlette, uvicorn):
        location = Path(module.__file__).resolve()
        assert location.is_relative_to(Path(sys.prefix).resolve()), location
        print(f"Installed import: {module.__name__} = {location}")
    entry_points = distribution(project["name"]).entry_points
    entry = next(
        entry
        for entry in entry_points
        if entry.group == "toolframe.plugins" and entry.name == "llms-txt"
    )
    assert entry.load() is toolframe_llms_txt.plugin
    print("Distribution metadata, plugin entry point, LICENSE and NOTICE passed.")


async def check_http() -> None:
    context = RuntimeContext(None, plugin_id="llms-txt", generation="wheel-smoke")
    provider = toolframe_llms_txt.LlmsProvider(context)
    opener = build_opener(ProxyHandler({}))

    def request(path: str) -> tuple[int, str, str]:
        try:
            response = opener.open(provider.server.url + path, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return (
                response.status,
                response.headers["Content-Type"],
                response.read().decode("utf-8"),
            )

    async def get(path: str) -> tuple[int, str, str]:
        return await asyncio.to_thread(request, path)

    try:
        await provider.activate()
        assert await get("/llms.txt") == (200, "text/plain; charset=utf-8", "")
        document = OwnedResource(
            owner="smoke",
            generation="wheel-smoke",
            resource=Resource(
                id="guide",
                kind="llms.document",
                title="Guide",
                data={"package": "unused", "path": "docs/guide.md"},
            ),
            content="# Installed wheel\n",
        )
        await provider.prepare([document], "ready")
        assert (await get("/llms.txt"))[2] == ""
        assert (await get("/llms/smoke/guide.md"))[0] == 404
        await provider.commit("ready")
        assert (await get("/llms.txt"))[2] == "- [Guide](/llms/smoke/guide.md)"
        assert await get("/llms/smoke/guide.md") == (
            200,
            "text/markdown; charset=utf-8",
            "# Installed wheel\n",
        )
        assert (await provider.health())["epoch"] == "ready"
        await provider.prepare([], "withdraw")
        await provider.commit("withdraw")
        assert (await get("/llms.txt"))[2] == ""
        assert (await get("/llms/smoke/guide.md"))[0] == 404
    finally:
        await provider.dispose()
    assert provider.server.task.done()
    print("Installed-wheel HTTP lifecycle, content types and epoch withdrawal passed.")


if __name__ == "__main__":
    check_distributions(Path(sys.argv[1]), Path(sys.argv[2]))
    asyncio.run(check_http())
