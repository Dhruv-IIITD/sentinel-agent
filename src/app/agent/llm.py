"""Chat model factory.

Provider-pluggable: `LLM_PROVIDER=groq` (free tier, open models via
langchain-groq) or `anthropic` (Claude). Constructed lazily so importing the
package never requires an API key; tests inject a fake model and never call this.

Only a tool-calling-capable model works, since the agent binds tools — Groq's
`llama-3.3-70b-versatile` (the default) supports it. Note: the risk-routing
safety is *structural* (policy + hard-cap gate high-stakes actions regardless of
which model is used), so a cheaper model can't bypass approvals.
"""

from __future__ import annotations

from functools import lru_cache

from ..config import settings


@lru_cache
def get_model():
    provider = settings.llm_provider.lower()

    if provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=settings.groq_model,
            api_key=settings.groq_api_key or None,
            max_tokens=4096,
            timeout=60,
            max_retries=2,
        )

    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model=settings.model,
        api_key=settings.anthropic_api_key,
        max_tokens=4096,
        timeout=60,
        max_retries=2,
    )
