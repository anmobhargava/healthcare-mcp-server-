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


