import json

import httpx
import pytest
from conftest import over_stdio, run
from mcp.server.fastmcp.exceptions import ToolError

from healthmcp.api import LiveAPI
from healthmcp.demo_data import KNOWN_DRUGS, TRIALS, DemoAPI
from healthmcp.server import ABOUT, clip, build_server

DRUG = KNOWN_DRUGS[0]


def call(server, name, args):
    res = run(server.call_tool(name, args))
    blocks = res[0] if isinstance(res, tuple) else res
    return json.loads(blocks[0].text)


@pytest.fixture
def server():
    return build_server(DemoAPI())


# ---- the tools, in-process
def test_label_search_and_section_with_a_source_link(server):
    found = call(server, "search_drug_labels", {"name": DRUG.lower()})
    assert found["drugs"][0]["brand_names"] == [DRUG] and found["total"] == 1
    sec = call(server, "get_label_section", {"name": DRUG, "section": "interactions"})
    assert "DRUG INTERACTIONS" in sec["text"] and sec["source_url"] and sec["truncated"] is False


def test_adverse_events_come_with_the_caveat(server):
    out = call(server, "adverse_event_summary", {"name": DRUG, "top": 3})
    assert len(out["top_reactions"]) == 3 and "not rates" in out["caveat"]
    assert out["top_reactions"][0]["reports"] >= out["top_reactions"][1]["reports"]


def test_trial_search_filters_by_status_and_details_include_eligibility(server):
    rec = call(server, "search_trials", {"condition": "hypertension", "status": "recruiting", "limit": 10})
    assert rec["trials"] and all(t["status"] == "RECRUITING" for t in rec["trials"])
    anyst = call(server, "search_trials", {"condition": "hypertension", "status": "any", "limit": 10})
    assert anyst["total"] >= rec["total"]
    d = call(server, "get_trial_details", {"nct_id": rec["trials"][0]["nct_id"]})
    assert "Inclusion Criteria" in d["eligibility"] and d["sites"] >= 1


def test_errors_are_tool_errors_the_model_can_read(server):
    with pytest.raises(ToolError, match="No drug label found"):
        run(server.call_tool("get_label_section", {"name": "Nonexistentol", "section": "warnings"}))
    with pytest.raises(ToolError, match="No trial found"):
        run(server.call_tool("get_trial_details", {"nct_id": "NCT00000000"}))


def test_inputs_are_validated_by_the_schema(server):
    for name, args in [("get_trial_details", {"nct_id": "bad"}), ("get_label_section", {"name": DRUG, "section": "dosage"}), ("search_trials", {"condition": "hypertension", "limit": 99}),
                       ("search_drug_labels", {"name": "x"})]:
        with pytest.raises(ToolError):
            run(server.call_tool(name, args))


def test_long_text_is_trimmed():
    text, cut = clip("word " * 1000)
    assert cut and len(text) <= 2000 and clip("short")[1] is False


def test_demo_data_is_fictional_and_repeatable():
    assert all(t["nct"].startswith("NCT9") for t in TRIALS)
    from healthmcp import demo_data
    assert demo_data._build(3)[0] == demo_data._build(3)[0] and demo_data._build(3)[0] != demo_data._build(4)[0]


# ---- over the real protocol
def test_a_client_discovers_five_read_only_tools_with_schemas_over_stdio():
    async def go(s):
        return (await s.list_tools()).tools
    tools = over_stdio(go)
    assert sorted(t.name for t in tools) == ["adverse_event_summary", "get_label_section", "get_trial_details", "search_drug_labels", "search_trials"]
    assert all(t.annotations.readOnlyHint is True for t in tools) and all(t.inputSchema["properties"] and t.description for t in tools)
    section = next(t for t in tools if t.name == "get_label_section").inputSchema["properties"]["section"]
    assert "dosage" not in json.dumps(section) and "interactions" in json.dumps(section)           # dosing is deliberately not offered


def test_call_a_tool_see_a_tool_error_read_the_resource_and_the_prompt_over_stdio():
    async def go(s):
        ok = await s.call_tool("search_drug_labels", {"name": DRUG})
        bad = await s.call_tool("get_label_section", {"name": "Nonexistentol", "section": "warnings"})
        res = await s.read_resource("health://about")
        prompt = await s.get_prompt("drug_safety_brief", {"drug": DRUG})
        return ok, bad, res, prompt
    ok, bad, res, prompt = over_stdio(go)
    assert not ok.isError and DRUG in ok.content[0].text
    assert bad.isError and "No drug label found" in bad.content[0].text
    assert "NOT for" in res.contents[0].text and "DEMO" in res.contents[0].text
    assert DRUG in prompt.messages[0].content.text and "dosing" in prompt.messages[0].content.text


# ---- the live backend, against a pretend network
def live(handler):
    return build_server(LiveAPI(transport=httpx.MockTransport(handler)))


def test_live_requests_are_built_the_way_openfda_and_clinicaltrials_expect():
    seen = []

    def handler(req):
        seen.append(req)
        if "drug/label" in req.url.path:
            return httpx.Response(200, json={"meta": {"results": {"total": 1}}, "results": [{"set_id": "abc", "openfda": {"brand_name": ["Advil"], "generic_name": ["IBUPROFEN"], "manufacturer_name": ["Pfizer"]},
                                                                                       "warnings": ["Warnings Stomach bleeding warning."]}]})
        return httpx.Response(200, json={"totalCount": 1, "studies": []})
    s = live(handler)
    call(s, "get_label_section", {"name": "ibuprofen", "section": "warnings"})
    call(s, "search_trials", {"condition": "type 2 diabetes", "status": "completed", "limit": 2})
    label, trials = seen
    assert label.url.host == "api.fda.gov" and 'openfda.brand_name:"ibuprofen"' in label.url.params["search"] and label.url.params["limit"] == "1"
    assert trials.url.host == "clinicaltrials.gov" and trials.url.params["filter.overallStatus"] == "COMPLETED" and trials.url.params["query.cond"] == "type 2 diabetes"


@pytest.mark.parametrize("status,words", [(404, "No drug label found"), (429, "rate limiting"), (503, "returned an error")])
def test_live_failures_become_messages_not_crashes(status, words):
    s = live(lambda req: httpx.Response(status, json={}))
    with pytest.raises(ToolError, match=words):
        run(s.call_tool("get_label_section", {"name": "ibuprofen", "section": "warnings"}))


def test_a_network_error_is_reported_plainly():
    def boom(req):
        raise httpx.ConnectError("down")
    with pytest.raises(ToolError, match="could not reach"):
        run(live(boom).call_tool("search_drug_labels", {"name": "ibuprofen"}))
