# Healthcare MCP server

I work in marketing analytics and I'm moving towards ML engineering. This is my third agent project, and it's about **MCP (Model Context Protocol)**: how to put a set of tools behind a standard interface so that any agent, or Claude Desktop, can find them and use them without custom glue.

This server exposes drug and clinical-trial lookups. It also ships a small LLM agent (OpenAI SDK) that uses everything the server offers: its resource, its prompt and its tools. The longer agent, with guardrails against bad tool data, is in my other repo, `agent-02-drug-trial-agent`.

## The brief agent (`src/healthmcp/brief_agent.py`)

Give it a drug name. It:
1. reads the `health://about` resource and uses it as the system message,
2. asks the server for its `drug_safety_brief` prompt and uses that as the task (the server wrote those instructions, not me),
3. lists the server's tools and hands them to the model as OpenAI functions,
4. loops: the model asks for tools, I run them over MCP, results go back, until it writes the brief.

Tool errors go back to the model as text, so it can try again. With no `OPENAI_API_KEY` an offline stand-in follows the same steps and writes the brief from the results, so everything runs for free. It isn't a language model. The model name is in the file; check it is the one you want.

## What a client sees

**Tools** (all five are marked read-only):

| Tool | What it does |
|---|---|
| `search_drug_labels` | find drug labels by brand or generic name |
| `get_label_section` | read one section of a label: indications, warnings, contraindications, interactions, adverse reactions |
| `adverse_event_summary` | the reactions most often named in adverse-event reports for a drug, with counts |
| `search_trials` | find clinical trials for a condition, filtered by status |
| `get_trial_details` | one trial's summary, phase, sponsor and eligibility criteria |

**A resource**, `health://about`: what the data is, and what the server is deliberately not for.
**A prompt**, `drug_safety_brief`: a reusable starting message that tells a model which tools to call and in what order.

Data comes from openFDA (labels, adverse-event reports) and ClinicalTrials.gov (trials). Neither needs an API key.

## Choices I made on purpose

- **Read-only, and it says so.** Every tool carries the `readOnlyHint` annotation, so a client can choose to expose only safe tools. My agent does.
- **No dosing.** There's no dosing option in `get_label_section`. Dosing text is easy to misread, and this server is for looking things up, not for advice.
- **Typed inputs.** Each tool has a schema with limits (a trial id must look like `NCT12345678`, `limit` is 1 to 10, `section` is one of five values). Bad input is rejected before any request goes out.
- **Errors a model can act on.** "No drug label found for X. Check the spelling, or try the generic name" comes back as a tool error, not a crash. Rate limits and outages are reported plainly too.
- **Trimmed results with sources.** Label sections are huge, so text is cut at 2,000 characters and flagged when it was cut. Every result says where it came from.
- **A caveat travels with the numbers.** Adverse-event counts are reports, not rates, and not proof a drug caused anything. The result says so every time.

## Two backends

- **Live** (the default): the real openFDA and ClinicalTrials.gov APIs.
- **`--demo-data`**: fictional data in the same response shape, so it runs anywhere with no network. The drug names are invented (like "Pulmotril"), the label text comes from templates, and the trial ids start with `NCT9` (real ones start with `NCT0`), so nothing can be mistaken for real medical information. The data is generated from a seed, not typed in.

The tools are written once against the API's JSON shape, so the same parsing code runs in both modes.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=src

python -m healthmcp                      # real data, over stdio
python -m healthmcp --demo-data          # fictional data
python -m healthmcp --http               # streamable HTTP on port 8000
python -m healthmcp.inspector            # demo page (tool inspector + brief agent tab), http://localhost:7860 (set HEALTHMCP_LIVE=1 for real data)
export OPENAI_API_KEY=...                # optional: a real model for the brief agent
pytest
```

**Use it from Claude Desktop** by adding this to its MCP config (adjust the path):

```json
{ "mcpServers": { "healthcare": { "command": "python", "args": ["-m", "healthmcp"], "env": { "PYTHONPATH": "/path/to/agent-03-healthcare-mcp-server/src" } } } }
```

**The demo page** (`healthmcp.inspector`) acts like a tiny MCP inspector. It starts the server, asks what tools it has (nothing about the tools is hard-coded on the page), shows their descriptions and schemas, and lets you call one.

## Checks

18 tests pass from a clean install. They cover each tool, the validation, the error messages, and the trimming. Two tests start the real server as a subprocess and talk to it over the actual MCP protocol: discovering the tools (and checking they're read-only and have no dosing option), calling one, getting a tool error, reading the resource, and fetching the prompt. The live backend is tested against a pretend network, which checks the requests it builds and how it handles 404, 429, 5xx and a dropped connection. Four more tests run the brief agent against the real server over stdio: the offline path, the OpenAI loop with a scripted fake client (checking it receives the server's resource, prompt and tools), a tool error going back to the model, and an unknown drug. I also drove the demo page in a browser.

## Honest limits

- **I haven't run the live backend against the real openFDA and ClinicalTrials.gov.** They weren't reachable from where I built this. The requests and parsing follow the APIs' documented shapes and are tested against a pretend network and fictional data, but the first real call is the real test. If a field name has changed, the error will point to it.
- **I haven't run the brief agent against the real OpenAI API.** Only a scripted fake client, so check the model name first. The offline stand-in only knows the steps in the server's prompt.
- The server uses the first label that matches a name. Drugs with many labels (many manufacturers) could return a different one than you expect.
- Trial search is a simple condition search. It doesn't handle location, age or eligibility matching.
- It's a lookup tool. It doesn't interpret anything, and I wouldn't use it for medical decisions.
- Streamable HTTP mode runs, but I didn't test it beyond starting it. stdio is the tested path.
# healthcare-mcp-server-
