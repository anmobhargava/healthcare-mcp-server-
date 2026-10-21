"""
A small demo page that talks to the server the way any MCP client does: it starts the server, asks it which tools it has (nothing about the tools is
hard-coded here), shows their descriptions and input schemas, and lets you call one. Think of it as a tiny MCP inspector.

    PYTHONPATH=src python -m healthmcp.inspector        -> http://localhost:7860     (fictional data)
    HEALTHMCP_LIVE=1 PYTHONPATH=src python -m healthmcp.inspector                    (real openFDA / ClinicalTrials.gov)
"""

import json
import os
import sys
from pathlib import Path

import gradio as gr
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .brief_agent import make_brief
from .demo_data import KNOWN_DRUGS, TRIALS

LIVE = os.environ.get("HEALTHMCP_LIVE") == "1"
SRC = str(Path(__file__).resolve().parents[1])
PARAMS = StdioServerParameters(command=sys.executable, args=["-m", "healthmcp"] + ([] if LIVE else ["--demo-data"]), env={**os.environ, "PYTHONPATH": SRC})
D, C, N = ("ibuprofen", "type 2 diabetes", "NCT01234567") if LIVE else (KNOWN_DRUGS[0], "hypertension", TRIALS[0]["nct"])
EXAMPLES = {"search_drug_labels": {"name": D, "limit": 3}, "get_label_section": {"name": D, "section": "interactions"}, "adverse_event_summary": {"name": D, "top": 5},
            "search_trials": {"condition": C, "status": "recruiting", "limit": 3}, "get_trial_details": {"nct_id": N}}


async def discover() -> list[dict]:
    async with stdio_client(PARAMS) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return [{"name": t.name, "description": t.description, "schema": t.inputSchema, "read_only": bool(t.annotations and t.annotations.readOnlyHint)} for t in (await s.list_tools()).tools]


async def call(tool: str, args_json: str) -> str:
    try:
        args = json.loads(args_json or "{}")
    except ValueError as e:
        return f"Those arguments aren't valid JSON ({e})."
    async with stdio_client(PARAMS) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool(tool, args)
    text = "\n".join(getattr(b, "text", "") for b in res.content)
    if res.isError:
        return "❌ The server returned a tool error:\n\n" + text
    return f"✅ Result:\n\n```json\n{text}\n```"


async def tool_info(tool: str):
    t = next(x for x in await discover() if x["name"] == tool)
    return (f"**{t['name']}** {'(read-only)' if t['read_only'] else ''}\n\n{t['description']}\n\n```json\n{json.dumps(t['schema'], indent=1)}\n```", json.dumps(EXAMPLES.get(tool, {}), indent=1))


def make_client():
    """An OpenAI client if there is a key, else None (the brief agent then uses its offline stand-in)."""
    if os.environ.get("OPENAI_API_KEY"):
        try:
            import openai
            return openai.OpenAI()
        except ImportError:
            pass
    return None


async def brief(drug: str) -> str:
    if not drug.strip():
        return "Enter a drug name."
    b = await make_brief(drug.strip(), make_client(), live=LIVE)
    return b.text + "\n\n---\n**What the agent did**\n\n" + "\n".join(f"- {t}" for t in b.trace)


async def build():
    tools = await discover()
    with gr.Blocks(title="Healthcare MCP server inspector") as demo:
        gr.Markdown(f"# Healthcare MCP server\nThis page starts the server and talks to it over MCP, like any client. Data: **{'live openFDA + ClinicalTrials.gov' if LIVE else 'fictional demo data'}**. "
                    "The tool list below came from the server, not from this page's code.")
        with gr.Tab("Call a tool"):
            tool = gr.Dropdown([t["name"] for t in tools], value=tools[0]["name"], label="Tool")
            info = gr.Markdown()
            args = gr.Code(language="json", label="Arguments (JSON)", lines=6)
            go = gr.Button("Call the tool", variant="primary")
            out = gr.Markdown()
            tool.change(tool_info, tool, [info, args])
            demo.load(tool_info, tool, [info, args])
            go.click(call, [tool, args], out)
        with gr.Tab("Brief agent"):
            gr.Markdown("An agent that uses the server's **resource**, **prompt** and **tools**: it reads `health://about`, takes its task from the server's `drug_safety_brief` prompt, "
                        f"then calls tools until it can write the brief. Reader: *{'an OpenAI model' if make_client() else 'offline stand-in (set OPENAI_API_KEY for a real model)'}*.")
            drug = gr.Textbox(value=D, label="Drug")
            gb = gr.Button("Write the brief", variant="primary")
            bo = gr.Markdown()
            gb.click(brief, drug, bo)
    return demo


if __name__ == "__main__":
    import asyncio
    asyncio.run(build()).launch(server_name="0.0.0.0", server_port=7860)
