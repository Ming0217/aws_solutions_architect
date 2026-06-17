---
title: Direct API vs CLI vs MCP (and how they relate to AWS)
type: note
date: 2026-06-11
source: "Article: Building agents that reach production systems with MCP (claude.com)"
tags:
  - aws
  - mcp
  - api
  - cli
  - agents
  - tooling
---

# Direct API vs CLI vs MCP (and how they relate to AWS)

> Related: [[notes/2026-06-11-what-sdks-really-are|What SDKs really are]]
> · [[learning-plan/08-automation-iac/cli-vs-cloudformation-vs-cdk|CLI vs CloudFormation vs CDK]]

## Important framing

The [article](https://claude.com/blog/building-agents-that-reach-production-systems-with-mcp)
is about connecting **AI agents (LLMs)** to external systems — *not* the general
developer ways of calling AWS. Keeping that straight resolves most of the confusion.

## The three approaches (from the article)

The key distinction is **whether there's a common layer between agents and services, and
how far that layer reaches.**

- **Direct API calls** — the agent issues HTTP requests itself (code sandbox or generic
  function-calling). Where most teams start; fine for one agent ↔ one service. At scale
  there's no shared layer, so every agent–service pair is a bespoke integration with its
  own auth and edge cases — the **M×N integration problem**.
- **CLI** — the agent runs a command-line tool in a shell. Fast, lightweight, reuses
  existing tooling; great where there's a filesystem + shell (local, sandboxed
  containers). But it's a *thin* common layer: can't reach mobile/web/cloud platforms
  without a container, and auth is usually a credential file on disk. Best for quick,
  local, permissive integrations.
- **MCP (Model Context Protocol)** — the common layer *as a protocol*. The agent connects
  to a server exposing a system's capabilities, with auth, discovery, and semantics
  standardized. One remote server reaches any compatible client (Claude, ChatGPT, Cursor,
  VS Code) in any environment. More upfront work, but portable and feature-rich.

Conclusion: cloud-hosted production agents reaching cloud systems behind auth land on
**MCP**; mature setups ship **all three** — API as the foundation, CLI for local-first,
MCP for cloud agents.

## AWS-relevant patterns for MCP servers

- **Group tools around intent, not endpoints** — a few well-described tools beat a 1:1
  API mirror.
- **For huge API surfaces use code orchestration** — the article names **AWS**,
  Cloudflare, and Kubernetes. Instead of thousands of tools, expose a thin surface that
  accepts code; the agent writes a short script, the server runs it in a sandbox, and
  only the result returns. (Cloudflare covers ~2,500 endpoints with two tools.)

## How it fits "ways to interact with AWS"

| Method | Who/what uses it | What it is |
| --- | --- | --- |
| Management Console | a human | point-and-click GUI |
| Direct API calls / SDKs | program code | call the AWS service API (SDK wraps it) |
| CLI | human or script in a shell | command-line wrapper over the same API |
| CloudFormation / CDK | program / templates | infrastructure as code, over the API |
| MCP server | an AI agent / LLM | standardized protocol so an agent can use the service |

**Key insight:** API calls, SDKs, CLI, and IaC are all developer/program front-ends that
ultimately hit the **same AWS service APIs**. **MCP is a different category** — a layer
so *AI agents* can reach systems in a portable, standardized way. MCP doesn't replace the
API; like everything else it sits on top of it (an AWS MCP server still calls the AWS API
underneath).
