"""Make upstream's structured agents use Anthropic's native structured output.

TradingAgents binds the Trader, Research Manager and Portfolio Manager with
``llm.with_structured_output(schema)``. ``langchain_anthropic`` defaults that to
forced tool calling, which Claude Opus 5.5 / Sonnet 5.5 / Fable 5.1 reject and which
is unreliable with thinking enabled: it warns, the call may return no tool call, and
upstream then pays for a second free-text call. ``method="json_schema"`` uses the API's
``output_config.format`` instead, which these models support. Callers that pass an
explicit ``method`` are left alone, and upstream's free-text fallback stays in place.
"""
from __future__ import annotations

_PATCHED_FLAG = "_ta_claude_json_schema_default"


def use_json_schema_structured_output() -> None:
    """Default ``with_structured_output`` to ``json_schema`` on upstream's Anthropic client."""
    from tradingagents.llm_clients.anthropic_client import NormalizedChatAnthropic

    if getattr(NormalizedChatAnthropic, _PATCHED_FLAG, False):
        return
    original = NormalizedChatAnthropic.with_structured_output

    def with_structured_output(self, schema, *, method=None, **kwargs):
        return original(self, schema, method=method or "json_schema", **kwargs)

    NormalizedChatAnthropic.with_structured_output = with_structured_output
    setattr(NormalizedChatAnthropic, _PATCHED_FLAG, True)
