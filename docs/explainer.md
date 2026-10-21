# Giving AI tools a standard plug: a healthcare MCP server

If you want an AI agent to look things up, you normally write custom glue for every tool and every app. MCP (Model Context Protocol) is a standard that removes that: you put your tools behind one interface, and any compatible AI app can discover them and use them.

I built a small MCP server as an example. It lets an AI look up drug labels, adverse-event reports and clinical trials from two public sources (the FDA's openFDA and ClinicalTrials.gov).

## What the AI sees

When an AI app connects, the server tells it what's on offer: five tools, each with a plain description and a strict definition of what inputs it accepts. The app doesn't need to know anything about drugs in advance. It reads the list and decides what to call.

## Choices that matter

- **Everything is read-only, and the server says so**, so an app can choose to allow only safe tools.
- **There's no dosing.** The server deliberately doesn't offer dosing information, because it's easy to misread and this is for looking things up, not for advice.
- **Bad requests are caught early** (a trial ID has to look like a trial ID), and problems come back as clear messages the AI can act on, like "no drug label found, try the generic name".
- **Every answer cites its source**, long text is trimmed, and numbers like adverse-event counts always come with a reminder that they're reports, not proof a drug caused anything.

## The agent that uses it

A small AI agent comes with the server to show all three pieces working together. It reads the server's description of itself (the resource), takes its job from the server's ready-made instructions (the prompt), and gets its toolbox from the server (the tools). The AI model then decides which lookups to run, I run them over MCP, and it writes a short sourced brief. If a lookup fails, the model sees the error message and can try again.

## Try it

The demo page starts the server and talks to it exactly as an AI app would: it asks what tools exist, shows their definitions, and lets you call one, and has a second tab where the agent writes a drug brief. The demo uses made-up drugs, so nothing on it is real medical information. The same server runs on real data too.
