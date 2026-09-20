from __future__ import annotations

import httpx
import pytest
from toolframe_sdk import OwnedResource, PluginError, Resource, RuntimeContext

from toolframe_llms_txt.plugin import LlmsProvider, plugin


def owned(
    owner: str,
    document_id: str,
    *,
    title: str = "",
    content: str | None = "",
) -> OwnedResource:
    return OwnedResource(
        owner=owner,
        generation="generation-1",
        resource=Resource(
            id=document_id,
            kind="llms.document",
            title=title,
            data={"package": "unused", "path": f"docs/{document_id}.md"},
        ),
        content=content,
    )


def unchecked_owned(
    owner: str,
    document_id: str,
    *,
    content: str | None = "",
) -> OwnedResource:
    resource = Resource.model_construct(
        id=document_id,
        kind="llms.document",
        title="",
        data={"package": "unused", "path": f"docs/{document_id}.md"},
    )
    return OwnedResource.model_construct(
        owner=owner,
        generation="generation-1",
        resource=resource,
        content=content,
    )


@pytest.fixture
def context():
    return RuntimeContext(None, plugin_id="llms-txt", generation="generation-1")


@pytest.mark.asyncio
async def test_definition_and_http_lifecycle(context):
    assert plugin.model_dump(mode="json") == {
        "id": "llms-txt",
        "api_version": 1,
        "authorization": {"scopes": {}},
        "private_secrets": [],
        "factory": "toolframe_llms_txt.plugin:LlmsProvider",
        "kind": "provider",
        "provider_kind": "llms",
        "config_schema": {
            "type": "object",
            "properties": {"intro": {"type": "string", "default": ""}},
            "additionalProperties": False,
        },
        "requires": {},
        "services": {},
        "resources": [],
        "store": None,
    }
    provider = LlmsProvider(context)
    await provider.activate()
    try:
        assert provider.server is not None
        assert (await provider.health())["http_url"] == provider.server.url
        async with httpx.AsyncClient(
            base_url=provider.server.url, trust_env=False
        ) as client:
            response = await client.get("/llms.txt")
        assert response.status_code == 200
        assert response.text == ""
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
    finally:
        await provider.dispose()
    assert provider.server.task is not None and provider.server.task.done()


@pytest.mark.asyncio
async def test_prepare_abort_and_commit_switch_index_and_documents(context):
    provider = LlmsProvider(context)
    await provider.activate()
    assert provider.server is not None
    try:
        async with httpx.AsyncClient(
            base_url=provider.server.url, trust_env=False
        ) as client:
            await provider.prepare(
                [owned("zeta", "usage", title="Z [usage]", content="zeta-v1")],
                "epoch-1",
            )
            response = await client.get("/llms.txt")
            assert response.text == ""
            assert (await client.get("/llms/zeta/usage.md")).status_code == 404

            await provider.abort("epoch-1")
            assert (await client.get("/llms.txt")).text == ""

            await provider.prepare(
                [
                    owned("zeta", "usage", title="Z [usage]", content="zeta-v2"),
                    owned("alpha", "guide", title="Alpha", content="alpha-v2"),
                ],
                "epoch-2",
            )
            assert (await client.get("/llms.txt")).text == ""
            await provider.commit("epoch-2")
            index = await client.get("/llms.txt")
            assert index.text == (
                "- [Alpha](/llms/alpha/guide.md)\n"
                "- [Z \\[usage\\]](/llms/zeta/usage.md)"
            )
            assert (await client.get("/llms/zeta/usage.md")).text == "zeta-v2"
            assert (await client.get("/llms/alpha/guide.md")).text == "alpha-v2"
            assert (await provider.health())["epoch"] == "epoch-2"
    finally:
        await provider.dispose()


@pytest.mark.asyncio
async def test_commit_withdraws_only_entries_in_new_epoch(context):
    provider = LlmsProvider(context)
    await provider.activate()
    try:
        await provider.prepare(
            [
                owned("alpha", "guide", content="alpha"),
                owned("beta", "guide", content="beta"),
            ],
            "epoch-1",
        )
        await provider.commit("epoch-1")
        await provider.prepare(
            [owned("alpha", "guide", content="alpha-new")], "epoch-2"
        )
        await provider.commit("epoch-2")
        async with httpx.AsyncClient(
            base_url=provider.server.url, trust_env=False
        ) as client:
            assert (await client.get("/llms/alpha/guide.md")).text == "alpha-new"
            assert (await client.get("/llms/beta/guide.md")).status_code == 404
            assert "beta" not in (await client.get("/llms.txt")).text
    finally:
        await provider.dispose()


@pytest.mark.asyncio
async def test_invalid_prepare_keeps_live_state_and_unknown_commit_fails(context):
    provider = LlmsProvider(context)
    await provider.activate()
    try:
        await provider.prepare([owned("alpha", "guide", content="live")], "live")
        await provider.commit("live")
        invalid_inputs = [
            [owned("alpha", "guide", content=None)],
            [unchecked_owned("Alpha", "guide")],
            [unchecked_owned("alpha", "Guide")],
            [unchecked_owned("../alpha", "guide")],
            [unchecked_owned("alpha", "../guide")],
            [owned("alpha", "guide"), owned("alpha", "guide")],
            [
                OwnedResource(
                    owner="alpha",
                    generation="g1",
                    resource=Resource(
                        id="page",
                        kind="dashboard.page",
                        data={"entrypoint": "example:page"},
                    ),
                )
            ],
        ]
        async with httpx.AsyncClient(
            base_url=provider.server.url, trust_env=False
        ) as client:
            for resources in invalid_inputs:
                with pytest.raises(PluginError):
                    await provider.prepare(resources, "candidate")
                assert (await client.get("/llms/alpha/guide.md")).text == "live"
        with pytest.raises(PluginError, match="Unknown staged epoch") as error:
            await provider.commit("missing")
        assert error.value.code == "unknown_epoch"
    finally:
        await provider.dispose()
