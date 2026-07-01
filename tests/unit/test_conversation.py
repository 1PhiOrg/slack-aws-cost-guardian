"""Unit tests for multi-turn conversation history threading (P3b-A)."""

from types import SimpleNamespace

from slack_aws_cost_guardian.config.schema import LLMConfig
from slack_aws_cost_guardian.llm.base import LLMMessage
from slack_aws_cost_guardian.llm.client import LLMClient
from slack_aws_cost_guardian.llm.tools.registry import ToolRegistry


class _CapturingProvider:
    """Captures the messages passed to the tool loop and returns a final answer."""

    def __init__(self):
        self.seen_messages = None

    def chat_with_tools(self, messages, tools):
        self.seen_messages = messages
        return SimpleNamespace(content="final answer", tool_calls=[], usage={})


def _client(provider) -> LLMClient:
    client = LLMClient(config=LLMConfig(), secret_name="x", region="us-east-1")
    client._provider = provider  # bypass Secrets Manager / real provider
    return client


def test_history_inserted_between_system_and_question():
    prov = _CapturingProvider()
    client = _client(prov)
    history = [
        LLMMessage(role="user", content="what did EC2 cost yesterday?"),
        LLMMessage(role="assistant", content="$42"),
    ]

    answer = client.answer_cost_question(
        question="and the day before?",
        user_context=None,
        tool_registry=ToolRegistry(),
        tools=[],
        system_prompt="SYS",
        history=history,
    )

    assert answer == "final answer"
    msgs = prov.seen_messages
    assert [m.role for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[1].content == "what did EC2 cost yesterday?"
    assert msgs[3].content == "and the day before?"


def test_no_history_is_just_system_and_question():
    prov = _CapturingProvider()
    client = _client(prov)

    client.answer_cost_question(
        question="q",
        user_context=None,
        tool_registry=ToolRegistry(),
        tools=[],
        system_prompt="SYS",
    )

    assert [m.role for m in prov.seen_messages] == ["system", "user"]