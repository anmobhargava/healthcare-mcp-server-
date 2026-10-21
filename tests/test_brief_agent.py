import json
from types import SimpleNamespace as NS

from conftest import over_stdio
from healthmcp.brief_agent import run
from healthmcp.demo_data import KNOWN_DRUGS

D = KNOWN_DRUGS[0]


class FakeOpenAI:
    """Plays back scripted OpenAI-style replies and records the requests."""
    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        self.requests.append({**kw, "messages": list(kw["messages"])})
        return NS(choices=[NS(message=self.replies.pop(0))])


def call(id, tool, **args):
    return NS(content=None, tool_calls=[NS(id=id, function=NS(name=tool, arguments=json.dumps(args)))])


def test_offline_brief_follows_the_prompt_and_uses_all_three_mcp_features():
    b = over_stdio(lambda s: run(s, D, None))
    assert D in b.text and "Warnings" in b.text and "Interactions" in b.text and "not rates" in b.text and "demo:" in b.text
    assert b.trace[0].startswith("read resource") and "prompt drug_safety_brief" in b.trace[1] and "discovered tools" in b.trace[2]


def test_openai_loop_gets_the_server_prompt_and_resource_and_runs_tools_over_mcp():
    client = FakeOpenAI([call("a", "search_drug_labels", name=D), call("b", "get_label_section", name=D, section="warnings"), NS(content="Brief written.", tool_calls=None)])
    b = over_stdio(lambda s: run(s, D, client))
    assert b.text == "Brief written."
    first = client.requests[0]
    assert "Healthcare lookup server" in first["messages"][0]["content"] and "Give a short, sourced safety brief" in first["messages"][1]["content"]   # resource + prompt from the server
    assert sorted(t["function"]["name"] for t in first["tools"]) == ["adverse_event_summary", "get_label_section", "get_trial_details", "search_drug_labels", "search_trials"]
    last = client.requests[2]["messages"]
    assert [m["role"] for m in last] == ["system", "user", "assistant", "tool", "assistant", "tool"] and "can cause insomnia" in last[-1]["content"]


def test_a_tool_error_goes_back_to_the_model_as_text():
    client = FakeOpenAI([call("a", "get_label_section", name="Nonexistentol", section="warnings"), NS(content="Could not find it.", tool_calls=None)])
    over_stdio(lambda s: run(s, "Nonexistentol", client))
    assert client.requests[1]["messages"][-1]["content"].startswith("ERROR: ")


def test_offline_brief_for_an_unknown_drug_says_so():
    b = over_stdio(lambda s: run(s, "Nonexistentol", None))
    assert "couldn't build a brief" in b.text
