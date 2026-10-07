"""Composition root. Builds every dependency once; tests can swap pieces via keyword overrides."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine

from app.config import Settings
from app.crm.base import CRMProvider
from app.crm.factory import build_crm
from app.database import SessionFactory, make_engine, make_session_factory
from app.llm.anthropic_provider import AnthropicProvider
from app.llm.client import LLMClient
from app.llm.mock_provider import MockProvider
from app.llm.openai_provider import OpenAICompatProvider
from app.llm.router import ModelRouter
from app.llm.types import LLMProvider
from app.observability.telemetry import Telemetry, build_telemetry
from app.rag.embeddings import Embedder, build_embedder
from app.rag.retrieval import Retriever
from app.rag.store import VectorStore, make_client
from app.services.notify import Notifier, build_notifier
from app.storage.base import Storage
from app.storage.factory import build_storage
from app.tools.builtin import build_tool_registry
from app.tools.registry import ToolRegistry
from app.vision.analyzer import VisionAnalyzer
from app.vision.cv import build_detector
from app.viz.providers import VisualizationProvider, build_viz_provider


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "mock":
        return MockProvider()
    if settings.llm_provider == "openai":
        return OpenAICompatProvider(settings)
    return AnthropicProvider(settings)


@dataclass
class Container:
    settings: Settings
    engine: Engine
    session_factory: SessionFactory
    telemetry: Telemetry
    provider: LLMProvider
    router: ModelRouter
    tools: ToolRegistry
    llm: LLMClient
    embedder: Embedder
    store: VectorStore
    retriever: Retriever
    storage: Storage
    crm: CRMProvider
    notifier: Notifier
    viz: VisualizationProvider
    vision: VisionAnalyzer
    redis: Any | None = None
    _workflow: Any = field(default=None, repr=False)

    @property
    def workflow(self) -> Any:
        if self._workflow is None:
            from app.graph.runtime import WorkflowService

            self._workflow = WorkflowService(self)
        return self._workflow


def build_container(settings: Settings, *, provider: LLMProvider | None = None, qdrant_in_memory: bool = False,
                    engine: Engine | None = None, storage: Storage | None = None, crm: CRMProvider | None = None,
                    viz: VisualizationProvider | None = None, notifier: Notifier | None = None,
                    embedder: Embedder | None = None) -> Container:
    engine = engine or make_engine(settings.database_url)
    sf = make_session_factory(engine)
    telemetry = build_telemetry(settings, sf)
    tools = build_tool_registry(settings)
    provider = provider or build_provider(settings)
    router = ModelRouter(settings)
    llm = LLMClient(settings, provider, router, telemetry, tools)
    embedder = embedder or build_embedder(settings)
    store = VectorStore(make_client(settings, in_memory=qdrant_in_memory), embedder, settings.qdrant_collection)
    redis_client = None
    if settings.redis_url:
        import redis

        redis_client = redis.Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)
    return Container(
        settings=settings, engine=engine, session_factory=sf, telemetry=telemetry, provider=provider, router=router, tools=tools,
        llm=llm, embedder=embedder, store=store, retriever=Retriever(store, settings), storage=storage or build_storage(settings),
        crm=crm or build_crm(settings, sf), notifier=notifier or build_notifier(settings), viz=viz or build_viz_provider(settings),
        vision=VisionAnalyzer(llm, build_detector(settings.cv_detector_model)), redis=redis_client,
    )
