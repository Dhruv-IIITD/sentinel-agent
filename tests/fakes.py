"""Test doubles."""

from __future__ import annotations

from langchain_core.messages import AIMessage


class FakeModel:
    """A scripted chat model: `bind_tools` is a no-op, `ainvoke` pops responses.

    Shared across graph instances in a test so a "restart" (new graph, same
    model) continues the same script.
    """

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self._i = 0

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001
        return self

    async def ainvoke(self, messages, *args, **kwargs):  # noqa: ANN001
        if self._i >= len(self._responses):
            return AIMessage(content="(done)")
        response = self._responses[self._i]
        self._i += 1
        return response
