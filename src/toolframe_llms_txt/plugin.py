"""Toolframe's standalone llms.txt provider."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from re import compile as compile_regex
from types import MappingProxyType

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from toolframe_sdk import (
    AuthorizationSpec,
    OwnedResource,
    Plugin,
    PluginDefinition,
    PluginError,
)
from toolframe_sdk.http import HttpServer

_OWNER = compile_regex(r"[a-z][a-z0-9-]{0,63}\Z")
_DOCUMENT_ID = compile_regex(r"[a-z][a-z0-9_-]{0,63}\Z")


@dataclass(frozen=True, slots=True)
class _Document:
    owner: str
    document_id: str
    title: str
    content: str


@dataclass(frozen=True, slots=True)
class _Snapshot:
    documents: Mapping[tuple[str, str], _Document]
    index: tuple[_Document, ...]
    epoch: str | None


_EMPTY_SNAPSHOT = _Snapshot(MappingProxyType({}), (), None)


class LlmsProvider(Plugin):
    """Serve the selected epoch of explicitly owned llms documents."""

    def __init__(self, context):
        super().__init__(context)
        self.app: Starlette | None = None
        self.server: HttpServer | None = None
        self._staged: dict[str, Mapping[tuple[str, str], _Document]] = {}
        self._active = _EMPTY_SNAPSHOT
        self._intro = context.config.get("intro", "")

    async def activate(self):
        self.app = Starlette(
            routes=[
                Route("/llms.txt", self._serve_index, methods=["GET"]),
                Route(
                    "/llms/{owner}/{document_id}.md",
                    self._serve_document,
                    methods=["GET"],
                ),
            ]
        )
        self.server = HttpServer(self.app)
        await self.server.start()

    async def health(self):
        return {
            "runtime": "ready",
            "business": "not_provided",
            "http_url": self.server.url if self.server else None,
            "epoch": self._active.epoch,
        }

    async def dispose(self):
        try:
            if self.server:
                await self.server.close()
        finally:
            await super().dispose()

    async def prepare(self, resources: list[OwnedResource], epoch: str):
        documents: dict[tuple[str, str], _Document] = {}
        for owned in resources:
            resource = owned.resource
            if resource.kind != "llms.document":
                raise PluginError(
                    "unsupported_resource",
                    f"Unsupported resource kind: {resource.kind}",
                )
            if owned.content is None:
                raise PluginError(
                    "missing_content",
                    f"Document content is missing for {owned.key}",
                )
            if _OWNER.fullmatch(owned.owner) is None:
                raise PluginError(
                    "invalid_owner",
                    f"Invalid document owner: {owned.owner}",
                )
            if _DOCUMENT_ID.fullmatch(resource.id) is None:
                raise PluginError(
                    "invalid_document_id",
                    f"Invalid document id: {resource.id}",
                )
            key = (owned.owner, resource.id)
            if key in documents:
                raise PluginError(
                    "duplicate_resource",
                    f"Duplicate owned resource: {owned.key}",
                )
            documents[key] = _Document(
                owner=owned.owner,
                document_id=resource.id,
                title=resource.title,
                content=owned.content,
            )

        staged = MappingProxyType(documents)
        self._staged[epoch] = staged
        return {"epoch": epoch}

    async def commit(self, epoch: str):
        staged = self._staged.pop(epoch, None)
        if staged is None:
            raise PluginError("unknown_epoch", f"Unknown staged epoch: {epoch}")
        index = tuple(staged[key] for key in sorted(staged))
        self._active = _Snapshot(staged, index, epoch)
        return {"epoch": epoch}

    async def abort(self, epoch: str):
        self._staged.pop(epoch, None)
        return {"epoch": epoch}

    async def _serve_index(self, request: Request):
        del request
        snapshot = self._active
        links = "\n".join(
            f"- [{_escape_title(document.title)}]"
            f"(/llms/{document.owner}/{document.document_id}.md)"
            for document in snapshot.index
        )
        if self._intro and links:
            body = f"{self._intro}\n\n{links}"
        elif self._intro:
            body = self._intro
        else:
            body = links
        return PlainTextResponse(body, media_type="text/plain")

    async def _serve_document(self, request: Request):
        key = (request.path_params["owner"], request.path_params["document_id"])
        document = self._active.documents.get(key)
        if document is None:
            return PlainTextResponse("Not Found", status_code=404)
        return PlainTextResponse(document.content, media_type="text/markdown")


def _escape_title(title: str) -> str:
    return title.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


plugin = PluginDefinition(
    id="llms-txt",
    kind="provider",
    provider_kind="llms",
    factory="toolframe_llms_txt.plugin:LlmsProvider",
    authorization=AuthorizationSpec(),
    config_schema={
        "type": "object",
        "properties": {"intro": {"type": "string", "default": ""}},
        "additionalProperties": False,
    },
)
