# 04 — The in-app agent

The agent is Claude, embedded in FEFAT, working only through FEFAT's own tools. It writes features and strategies, analyses backtests, ingests alternative data, and sets up prop simulations — and never changes anything without a decision from you.

## 1. Runtime: a tool loop on the Messages API

- **Library:** the official `anthropic` Python SDK (1.x). The loop uses the SDK's beta tool runner (`client.beta.messages.tool_runner` with `@beta_tool` functions) or an equivalent manual loop; both are documented in the `claude-api` skill bundled with Claude Code, which every agent step must read before writing code. That reference is authoritative over anything recalled from training.
- **Model:** `claude-opus-5-5` by default; `claude-sonnet-5-5` as the "cheap mode" you can select; model ids are configuration, never hard-coded in more than one place.
- **Thinking and effort:** adaptive thinking; effort set explicitly per turn kind (`medium` for chat, `high` for analysis and code proposals).
- **Streaming:** always; token deltas are relayed to the client through the turn's event stream; `eager_input_streaming` on tools whose inputs can be large (code).
- **Prompt caching:** stable prefix (system prompt, tool definitions, skill index) with cache breakpoints; volatile context (page context, dates) goes in the user message.
- **Append-only transcript:** every API content block (including thinking blocks) is stored in `agent_transcript` in order and replayed byte-identical. Nothing is edited after the fact; the system prompt and tool list are frozen per session and only change through the API's tool-change mechanism or a new session.
- **Long sessions:** server-side compaction (the API's compaction beta); the compaction blocks are stored and replayed like any other block.
- **Refusals and fallbacks:** `stop_reason == "refusal"` is handled (no tool runs, the user sees a plain message); the server-side fallback option is enabled by default.
- **No forced tool choice:** the prompt names the tool to use; tools declare `strict: true` input schemas; the loop verifies that an expected call happened.
- **Limits:** `max_turns` per user message, a per-turn budget in USD, a monthly cap per workspace; the turn stops cleanly with a message when a cap is hit.

## 2. Sessions and persistence

- A session binds a **context**: a feature, a strategy version, a run, a prop simulation, an upload (from Phase 10), or the workspace. A short summary of the context is appended inside each user message when it changes; it is never placed in the system prompt (so the cached prefix stays stable) and earlier messages are never rewritten (so the transcript stays append-only, which current models require).
- Tables: `agent_sessions`, `agent_turns`, `agent_messages` (what the UI shows), `agent_transcript` (what the API sees), `agent_tool_calls`, `usage_ledger`.
- One active turn per session. A turn is a job (`agent_turn`), so it survives a closed browser tab and can be followed from another device by attaching to stream `turn:<id>`.
- Stop: the UI's Stop button cancels the job; the partial assistant message is kept and marked interrupted.

## 3. Tools

All tools come from one registry: `ToolSpec(name, description, input_model, handler(ctx, args), read_only, consent: none|proposal|confirm_cost, timeout_s)`. The registry generates the API tool definitions (`strict` JSON schemas from the Pydantic input models) and the `@beta_tool` handlers. `ctx` carries the workspace and session from the server, never from the model. Tool results are compact text (tables, JSON summaries), with optional PNG blocks for charts; large outputs are truncated with a note and a pointer.

| Group | Tools |
| --- | --- |
| Read | `list_documents`, `read_document` (feature or strategy version, rule set, prop strategy), `list_runs`, `list_backtest_files` (saved runs and imported trade logs, with their path fidelity), `get_run_summary`, `query_run_data` (DuckDB SQL over a run's artifacts; read-only; row cap), `compare_runs`, `get_trade_context` (bars and features around a trade), `list_datasets`, `describe_dataset`, `inspect_upload` (Phase 10; schema and samples, labelled as data), `wait_for_job` |
| Execute | `preview_feature` (runs the executor; returns stats and a chart), `validate_code` (lint, leak check), `run_python` (executor sandbox over an upload or dataset; no network), `run_backtest`, `run_study`, `run_prop_sim` (on an existing backtest file — a saved run or an imported trade log; it never re-runs the strategy) — each returns a job id and, after `wait_for_job`, the summary. Cost-bearing ones above a time threshold use `consent: confirm_cost` |
| Write | `propose_change` (new version of a feature, strategy, rule set, prop strategy, or recipe: content, diff, validation), `propose_new`, `propose_recipe` and `register_dataset` (Phase 10, both through proposals), `add_note` |
| Skills | `load_skill(name)` returns the body of a skill |

No shell, no file access, no web browsing in the first release. "Import from URL" is a server feature (Phase 10) that stores an untrusted upload; the agent then inspects it like any upload.

## 4. Skills

- `python/fefat_app/src/fefat_app/agent/skills/<name>/SKILL.md`, the same format as Claude's Agent Skills (frontmatter `name` and `description`, then the body), plus optional reference files loaded through `load_skill`.
- The system prompt holds only the index (name + description); the body is loaded on demand. Users can add skills under `workspaces/default/skills/`.
- First release: `fefat-features` (the feature API, point-in-time rules, examples, pitfalls), `fefat-signal-strategies` (the `SignalStrategy` API, execution templates, common patterns), `backtest-analysis` (what to look at, in what order; using `query_run_data`; overfitting warnings), `alt-data-ingestion` (inspect, align on publication time, lag, register), `prop-rules-and-policies` (the rule schema, prop strategies, choosing a backtest file and reading its path fidelity, how to configure a simulation, what results mean), `optimization-hygiene` (trial counts, holdouts, walk-forward).

## 5. Proposals: consent as a first-class object

1. The agent calls `propose_change`. The server stores a proposal (`pending`) with the full content, a diff against the base version, and the validation results (lint, leak check, syntax), returns "awaiting your review", and the turn ends with a short message.
2. You open the proposal (side-by-side diff, unified in a narrow window), optionally with a comment.
3. `POST /proposals/{id}/decision`: on **accept**, one transaction creates the immutable new version (only if the base is still the latest; otherwise the proposal is marked `stale` and the agent is told to rebase) and records the decision; on **reject**, the comment is stored.
4. A new turn is queued automatically carrying the outcome ("Proposal 12 accepted → strategy v5 created" or "rejected: too tight a stop"), so the agent continues (for example by starting the backtest you asked for).

Cost-bearing actions (long studies, large imports) use the same object with `consent: confirm_cost`. Everything is in the audit log (`agent_tool_calls`, `proposals`).

## 6. Cost tracking

- Every turn stores token counts (input, output, cache read, cache write) and a USD estimate from a price table in `config.toml`; the settings page shows spend by day and by session.
- Caps: per turn, per day, per month. Exceeding one stops cleanly.
- Your API key is stored in the OS credential store (`keyring`) and never logged. The settings page tests the key with a tiny request.

## 7. Safety

- Uploaded files, imported market data and trade logs, dataset contents, and web-fetched pages are **untrusted data**: tool results that contain them are labelled as data, and the system prompt instructs the model accordingly.
- The agent cannot write anything except through proposals; it cannot run arbitrary code outside the executor sandbox (no network, workspace-only file access, time and memory limits).
- Chat markdown renders without remote images (CSP `img-src 'self' data: blob:`), and links are shown as text.
- Phase 8 includes consent-bypass tests (a hostile upload instructing the agent to "save this strategy now") and injection tests.

## 8. Phone

Deferred (D-53): the chat as a full-screen sheet carrying the page's context, and proposals decided on the phone, return with the backlog's phone item. Long turns continue server-side already, so a closed tab can come back.

## 9. The `AgentRuntime` seam

`AgentRuntime.run_turn(session, user_message, tools, emit) -> TurnResult`. The Messages API implementation is the first release. Alternatives behind the same interface: the Claude Agent SDK (if FEFAT ever runs on a server where its bundled CLI is available) and Anthropic's Managed Agents (hosted). See `appendix/research-agent-surfaces.md` for the comparison.
