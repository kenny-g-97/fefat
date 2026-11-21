# ADR-0025: The agent signs in with ChatGPT, and FEAT is an MCP server

Decision log: [D-111](../masterplan/DECISIONS.md), 2026-11-21

## Context

[ADR-0012](0012-in-app-agent-on-messages-api.md) built the in-app agent on Claude's Messages API with the trader's own API key, which bills each message. On 2026-11-21 you asked for a chat that spends a subscription the trader already pays for, or costs nothing.

What the vendors' pages said on 2026-11-21:

- OpenAI opened "plan usage" through Sign in with ChatGPT on 2026-09-29 to open-source projects and personal projects that run locally, for Plus and Pro plans. The app registers during the browser sign-in with no client secret, and the token it receives calls the Responses API. A paid or hosted app joins a waitlist. ([Sign in with ChatGPT](https://developers.openai.com/cookbook/topic/sign-in-with-chatgpt))
- Anthropic "does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, Max, or Ultra plan credentials on behalf of their users", and its rules for subscriptions in other programs changed several times in 2026. ([Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance))
- A program that speaks the Model Context Protocol (MCP), such as Claude Desktop, Claude Code, Codex, Cursor, or VS Code, holds its own sign-in and calls the tools of a server on the same computer. ChatGPT's own app reaches only a public HTTPS address or OpenAI's tunnel.

## Decision

- The in-app agent's model calls go to OpenAI's Responses API with the token of Sign in with ChatGPT, so the trader's plan pays. An OpenAI API key runs on the same code as the fallback. This replaces the Messages API and the Claude key of ADR-0012, and no second runtime is built for Claude.
- FEAT serves the agent's tools as an MCP server to programs on the same computer. No route is built for ChatGPT's own app, whose subscribers use the in-app chat.
- FEAT keeps its own tool loop. The registry, the proposals, the skills as files, and the `AgentRuntime` seam of ADR-0012 stand, and a write reaches the workspace only through a proposal accepted in FEAT, over MCP as in the chat.
- The Phase 8 kickoff reads the vendors' terms again, then rewrites `04-agent.md` and Phase 8's steps.

## Consequences

- The parts of `04-agent.md` that name Claude's API (cache breakpoints, compaction, replayed thinking blocks, the ledger and caps in USD) are restated for the Responses API at the kickoff. On a plan the ledger counts usage, not dollars.
- The plan-usage token is a secret and goes in the operating system's credential store, as the API key would have.
- The MCP library is a new dependency, and its transport and how a program proves itself to the local server are the kickoff's to settle with `01-architecture.md`'s security rules.
- A paid or hosted FEAT needs OpenAI's approval through its waitlist.
- One runtime is evaluated, not two. A local model on an OpenAI-style endpoint stays possible behind the seam and is in the backlog.

## How we would know it is wrong

If OpenAI withdraws plan usage from local or open-source apps, or limits it so that a working session runs out, the API key fallback bills each message as ADR-0012 did. If Anthropic permits a sign-in with a Claude plan in another program, a Claude runtime behind the seam is worth its second evaluation suite. If traders ask for the chat inside ChatGPT's own app, the MCP server needs a route past this computer and the security review that goes with it.

## Status

Accepted 2026-11-21 (D-111). Supersedes the runtime and the key of [ADR-0012](0012-in-app-agent-on-messages-api.md); the detail is written at the Phase 8 kickoff.
