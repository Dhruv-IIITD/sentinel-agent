"""Application configuration (pydantic-settings).

All runtime knobs come from the environment / `.env`. Nothing here reaches out
to a database or the network — importing this module is always cheap and safe.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Effort = Literal["low", "medium", "high", "xhigh", "max"]
CheckpointBackend = Literal["auto", "memory", "postgres", "sqlite"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Reasoning model ---
    # Which LLM provider to use: "groq" (free tier) or "anthropic".
    llm_provider: Literal["anthropic", "groq"] = "groq"
    effort: Effort = "high"

    # Anthropic (Claude)
    anthropic_api_key: str = ""
    model: str = "claude-opus-4-8"

    # Groq (free tier). Pick a tool-calling-capable model.
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # --- Database (checkpointer state + audit + app data + RAG) ---
    # e.g. postgresql://user:pass@localhost:5432/hitl_agent
    database_url: str = ""

    # --- Shared cross-worker state / events (optional) ---
    redis_url: str = ""
    verification_ttl_seconds: int = 30 * 60
    # Disabled by default; positive values cap requests per client IP per minute.
    rate_limit_per_minute: int = 0
    # Disabled by default; positive values flag overdue pending approvals.
    sla_seconds: int = 0
    sla_poll_seconds: int = 15

    # --- Payment side effects ---
    payments_provider: str = "mock"
    stripe_api_key: str = ""

    # --- Operator authentication (optional) ---
    auth_enabled: bool = False
    jwt_secret: str = ""
    jwt_expire_minutes: int = 720
    operator_approval_limit: float = 100.0
    demo_user_password: str = "demo-password"

    @property
    def redis_configured(self) -> bool:
        return bool(self.redis_url)

    # --- Checkpointer backend ---
    # "auto" -> postgres when DATABASE_URL is set, else in-memory.
    # "sqlite" -> a local file (survives process restarts without Postgres).
    checkpoint_backend: CheckpointBackend = "auto"
    sqlite_path: str = "data/checkpoints.sqlite"

    # --- Guardrails ---
    # A refund/credit above this is ALWAYS gated, regardless of policy (a floor
    # the model and the policy engine cannot reason past).
    hard_refund_cap: float = 1000.0
    # Agent self-reported confidence below this escalates even auto-tier actions.
    confidence_threshold: float = 0.7

    # --- Retrieval ---
    # "keyword" (default, lexical, no deps) or "vector" (embeddings + cosine; uses
    # pgvector when a database is configured, else an in-memory vector index).
    retriever: Literal["keyword", "vector"] = "keyword"
    embedding_dim: int = 256

    # --- LiveKit (the voice surface) ---
    # The browser needs a signed token to join a room; the backend mints it.
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # Outbound approval calls. The SIP bridge is free, but a real phone number +
    # PSTN minutes come from a trunk provider (Twilio/Telnyx). With no trunk the
    # approval call still happens — in a browser room instead of over the phone.
    livekit_sip_trunk_id: str = ""
    approver_phone: str = ""
    approver_agent_name: str = "approval-agent"

    @property
    def livekit_configured(self) -> bool:
        return bool(self.livekit_url and self.livekit_api_key and self.livekit_api_secret)

    @property
    def telephony_configured(self) -> bool:
        return bool(self.livekit_sip_trunk_id and self.approver_phone)

    # --- Observability (LangSmith) ---
    langsmith_api_key: str = ""
    langsmith_tracing: bool = False
    langsmith_project: str = "hitl-agent"

    # --- App ---
    app_env: str = "development"

    @property
    def resolved_checkpoint_backend(self) -> Literal["memory", "postgres", "sqlite"]:
        if self.checkpoint_backend != "auto":
            return self.checkpoint_backend  # type: ignore[return-value]
        return "postgres" if self.database_url else "memory"

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url)

    @property
    def sqlalchemy_async_url(self) -> str:
        """SQLAlchemy async URL (psycopg3 driver) derived from DATABASE_URL."""
        url = self.database_url
        if url.startswith("postgresql+"):
            return url
        if url.startswith("postgresql://"):
            return "postgresql+psycopg://" + url[len("postgresql://") :]
        if url.startswith("postgres://"):
            return "postgresql+psycopg://" + url[len("postgres://") :]
        return url

    @property
    def sqlalchemy_sync_url(self) -> str:
        """Synchronous SQLAlchemy URL (used by Alembic)."""
        url = self.database_url
        if url.startswith("postgresql+psycopg://"):
            return url
        if url.startswith("postgresql://"):
            return "postgresql+psycopg://" + url[len("postgresql://") :]
        if url.startswith("postgres://"):
            return "postgresql+psycopg://" + url[len("postgres://") :]
        return url

    @property
    def psycopg_conninfo(self) -> str:
        """Plain libpq conninfo string for the LangGraph PostgresSaver."""
        url = self.database_url
        for prefix in ("postgresql+psycopg://", "postgresql+asyncpg://"):
            if url.startswith(prefix):
                return "postgresql://" + url[len(prefix) :]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
