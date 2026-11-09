"""Upstream's structured agents use Anthropic json_schema output, with no forced-tool warning."""
import warnings

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from tradingagents.agents.schemas import PortfolioDecision, TraderProposal
from tradingagents.llm_clients.anthropic_client import NormalizedChatAnthropic

from ta_claude import runner  # noqa: F401  (importing runner applies the patch)
from ta_claude.config import build_config
from ta_claude.llm import use_json_schema_structured_output


def _llm(model="claude-opus-5-5"):
    return NormalizedChatAnthropic(model=model, api_key="test", effort="high")


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-sonnet-5", "claude-sonnet-5-5"])
@pytest.mark.parametrize("schema", [TraderProposal, PortfolioDecision])
def test_structured_binding_uses_output_config_without_warning(model, schema):
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # the forced-tool warning would raise here
        chain = _llm(model).with_structured_output(schema)
    binding = chain.first
    assert binding.kwargs["output_config"]["format"]["type"] == "json_schema"
    assert "tools" not in binding.kwargs and "tool_choice" not in binding.kwargs


def test_explicit_method_is_respected_and_patch_is_idempotent():
    use_json_schema_structured_output()
    use_json_schema_structured_output()
    chain = NormalizedChatAnthropic(model="claude-sonnet-5", api_key="test").with_structured_output(
        TraderProposal, method="function_calling")
    assert "tools" in chain.first.kwargs


def test_text_response_with_thinking_block_parses_to_schema(monkeypatch):
    payload = ('{"action": "Hold", "reasoning": "Flat 20/50 regime; wait for confirmation.", '
               '"entry_price": null, "stop_loss": null, "position_sizing": null}')

    def fake_generate(self, messages, stop=None, run_manager=None, **kwargs):
        assert kwargs["output_config"]["format"]["type"] == "json_schema"
        message = AIMessage(content=[{"type": "thinking", "thinking": "..."}, {"type": "text", "text": payload}])
        return ChatResult(generations=[ChatGeneration(message=message)])

    monkeypatch.setattr(NormalizedChatAnthropic, "_generate", fake_generate)
    result = _llm().with_structured_output(TraderProposal).invoke("plan")
    assert isinstance(result, TraderProposal) and result.action.value == "Hold"


def test_real_graph_builds_without_structured_output_warning(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        runner.TaClaudeGraph(["market"], build_config())
