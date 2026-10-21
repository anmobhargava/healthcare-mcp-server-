"""
An agent that uses this server the way an MCP client is meant to, with all three kinds of thing the server offers:

  resource  health://about          -> read first, and used as the system message (so the server tells the model what its data is and isn't)
  prompt    drug_safety_brief(drug) -> becomes the task. The server wrote the instructions, not me.
  tools     list_tools()            -> turned into OpenAI function definitions. Nothing about the tools is hard-coded here.

Then the usual loop: the model asks for tools, I run them over MCP, the results go back, until it writes the brief.

The model is an OpenAI one (OPENAI_API_KEY). With no key, a stand-in follows the same steps the prompt lists and writes the brief from the results, so
the page and tests run for free. The stand-in is not a language model.

This is the small version. The longer one, with guardrails against bad tool data, is Agent 2.
"""

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MODEL = "gpt-4o-mini"          # check this is the model you want before using the live path
MAX_STEPS = 6


@dataclass
class Brief:
    text: str
    trace: list[str] = field(default_factory=list)       # what the agent did, in order, for the demo page


def server_params(live: bool = False) -> StdioServerParameters:
    src = str(Path(__file__).resolve().parents[1])
    return StdioServerParameters(command=sys.executable, args=["-m", "healthmcp"] + ([] if live else ["--demo-data"]), env={**os.environ, "PYTHONPATH": src})


async def make_brief(drug: str, client=None, live: bool = False, model: str = MODEL) -> Brief:
    """client = an openai.OpenAI() (or anything shaped like it). None means use the offline stand-in."""
    async with stdio_client(server_params(live)) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return await run(s, drug, client, model)


async def run(session, drug: str, client, model: str = MODEL) -> Brief:
    trace = []
    about = (await session.read_resource("health://about")).contents[0].text
    trace.append("read resource health://about")
    task = (await session.get_prompt("drug_safety_brief", {"drug": drug})).messages[0].content.text
    trace.append("got prompt drug_safety_brief from the server")
    tools = (await session.list_tools()).tools
    trace.append("discovered tools: " + ", ".join(t.name for t in tools))
    if client is None:
        return await offline(session, drug, trace)

    defs = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.inputSchema}} for t in tools]
    messages = [{"role": "system", "content": about}, {"role": "user", "content": task}]
    for _ in range(MAX_STEPS):
        reply = (await asyncio.to_thread(client.chat.completions.create, model=model, messages=messages, tools=defs, max_completion_tokens=700)).choices[0].message
        if not reply.tool_calls:
            return Brief((reply.content or "").strip(), trace)
        messages.append({"role": "assistant", "content": reply.content, "tool_calls": [
            {"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments}} for c in reply.tool_calls]})
        for c in reply.tool_calls:
            args = _args(c.function.arguments)
            trace.append(f"model called {c.function.name}({json.dumps(args)})")
            messages.append({"role": "tool", "tool_call_id": c.id, "content": await _run_tool(session, c.function.name, args)})
    return Brief("I ran out of steps before finishing the brief.", trace)


def _args(raw: str) -> dict:
    try:
        out = json.loads(raw or "{}")
    except ValueError:
        return {}
    return out if isinstance(out, dict) else {}


async def _run_tool(session, name: str, args: dict) -> str:
    """A tool error goes back to the model as text it can act on (e.g. 'try the generic name'), not as a crash."""
    try:
        res = await session.call_tool(name, args)
    except Exception as e:                                  # noqa: BLE001 - the model should see any failure
        return f"ERROR: {e}"
    text = "\n".join(getattr(b, "text", "") for b in res.content)
    return ("ERROR: " + text) if res.isError else text


async def offline(session, drug: str, trace: list[str]) -> Brief:
    """Follows the order the prompt lists: confirm the drug, warnings, interactions, adverse events."""
    out = {}
    for name, args in [("search_drug_labels", {"name": drug}), ("get_label_section", {"name": drug, "section": "warnings"}),
                       ("get_label_section", {"name": drug, "section": "interactions"}), ("adverse_event_summary", {"name": drug})]:
        trace.append(f"stand-in called {name}({json.dumps(args)})")
        text = await _run_tool(session, name, args)
        if text.startswith("ERROR:"):
            return Brief(f"I couldn't build a brief for {drug}: {text[7:].strip()}", trace)
        out[(name, args.get("section"))] = json.loads(text)
    found, warn, inter, ae = out[("search_drug_labels", None)]["drugs"][0], out[("get_label_section", "warnings")], out[("get_label_section", "interactions")], out[("adverse_event_summary", None)]
    reacts = ", ".join(f"{x['reaction'].lower()} ({x['reports']:,})" for x in ae["top_reactions"][:5])
    text = (f"**{', '.join(found['brand_names'])}** ({', '.join(found['generic_names'])}), made by {found['manufacturer']}.\n\n"
            f"**Warnings:** {warn['text']}\n\n**Interactions:** {inter['text']}\n\n**Most-reported reactions:** {reacts}. These are report counts, not rates, and don't show the drug caused them.\n\n"
            f"Sources: {warn['source_url']}, {inter['source_url']} ({warn['source']}). This is information, not medical advice.")
    return Brief(text, trace)
