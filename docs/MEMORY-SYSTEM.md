# Memory System — Design

**Status:** Design / first-class consideration (not yet built). No code changes implied by this doc.

A two-layer memory that lets the Guardian *learn* from interactions — feedback on alerts, decisions made in Slack threads — and carry that learning forward. **File-based, no embeddings, no vector database.** The simple "brain" concept, ported to AWS.

## Genesis & guiding thesis

Inherits the argument from "Your Coding Agent's grep Loop Is Just Reranking in Disguise" (D. Kuhn, 2026-06-27) and its filesystem-as-context spin-off:

- **Retrieval happens in a loop, while the model thinks** — search, read, judge, follow links, search again. That loop *is* reranking.
- **Relationships are the third ingredient** most people skip — the link graph is signal a pure-embedding pipeline flattens away.
- **Navigate vs. nearest-neighbor.** Navigate a small, legible, well-linked corpus (grep + read + follow links); reach for vectors only at large, many-dimensional scale.

This corpus is unambiguously the navigate regime, so the decision is firm and final: **no vector database, no embeddings, ever.** Folders + frontmatter + links + an index the model walks. We adopt **OKF (Open Knowledge Format)** conventions for the deep layer — directory of markdown with YAML frontmatter, one concept per file, file path as identity, markdown links as the graph.

## The two layers

The split is driven by **efficiency**, and it's the core design decision:

| | Hot memory | Deep memory |
|---|---|---|
| **Used by** | **Every cost-anomaly check** (frequent, batch) | **Only when the user engages in a conversation** (interactive) |
| **Store** | **DynamoDB item** (single read, fast) | **S3** OKF-style directory |
| **Form** | One lean blob of always-relevant facts | One concept per file, tagged, linked, indexed |
| **Cost profile** | Injected into every assessment → must stay tiny | Loaded only during conversation → can be richer |

### Layer 1 — Hot memory (DynamoDB)

A single item in the existing DynamoDB table, e.g. `PK = MEMORY#HOT`, `SK = CURRENT`, with the curated text in one attribute. Read on **every** anomaly assessment and injected into the prompt as an override/addendum to the static `config/guardian-context.md`.

- **DynamoDB, not S3** — single-digit-ms read, no S3 round-trip on the hot path. This is the speed-sensitive, always-on layer.
- **Kept lean by the curator, not by mechanics.** No rotation, no archiving, no size gymnastics. The consolidation prompt's job is to keep it short and relevant to real-time assessment — it rewrites the item each run, dropping anything stale. Simplicity is the point.
- Content = durable, cross-anomaly facts that should color every check: "prod NAT-gateway baseline is accepted — don't re-flag." "RDS prod is reserved-covered; on-demand spikes there are genuinely anomalous." "User treats <$5/day movement as noise."

### Layer 2 — Deep memory (S3, OKF-style)

One concept per file, navigated on demand **during conversation only**. The batch anomaly path never touches it. This is the brain port.

```
memory/
  INDEX.md                 # navigable index — one line per concept (path + hook + tags)
  services/                # per-AWS-service knowledge
    nat-gateway-baseline.md
  accounts/                # per-account context
    prod.md
  patterns/                # recurring cost shapes & how to read them
    month-end-batch-spike.md
  decisions/               # judgments harvested from Slack threads
    2026-06-12-accepted-s3-replication-cost.md
  vendors/                 # third-party / marketplace spend
  objectives/             # optional OKR-style cost goals (type: objective)
```

**Concept file frontmatter (OKF):**

```yaml
---
id: nat-gateway-baseline          # required — stable identity, == filename stem
type: service                     # service | account | pattern | decision | vendor | objective
title: NAT Gateway baseline spend is expected
tags: [networking, vpc, accepted-baseline]
services: [EC2-Other, NATGateway] # Cost Explorer service keys this concept touches
accounts: [prod]
status: active                    # active | superseded | expired
supersedes: []                    # ids this replaces
links: [prod, month-end-batch-spike]   # wiki-links → the relationship graph
created: 2026-06-12
source: feedback#2026-06-12        # provenance: feedback id, thread ts, or "manual"
---

NAT Gateway data-processing charges in prod run ~$X/day as a steady baseline...

**Why:** confirmed expected by the user on 2026-06-12 (feedback: "expected", ongoing).
**How to apply:** don't raise an anomaly for NATGateway under +40% vs this baseline.

Related: [[prod]], [[month-end-batch-spike]].
```

`INDEX.md` is the map the model reads first when a conversation begins:

```markdown
# Deep memory index
- [services/nat-gateway-baseline](services/nat-gateway-baseline.md) — prod NAT baseline is accepted; don't re-flag · #networking #accepted-baseline
- [patterns/month-end-batch-spike](patterns/month-end-batch-spike.md) — last 3 days of month spike from batch jobs · #pattern #seasonal
```

## Substrate: how this lives in AWS (cheap, file-based)

| Concern | Choice | Why |
|---|---|---|
| Hot memory | **DynamoDB item** in the existing table | Single fast read on the every-check hot path. |
| Deep memory (durable) | **S3** (same bucket as `guardian-context.md`) | Extends the existing context-loading pattern; storage is rounding error. |
| Deep memory (working FS) | **Lambda `/tmp`** via `aws s3 sync` — only in the conversation path | S3 isn't a filesystem; sync to `/tmp` to grep/read/follow. Sub-second for a KB-scale text corpus. |
| Change signal | **DynamoDB** `FEEDBACK#` (exists) + `CHANGE#` (exists, unused) + `MEMORY#VERSION` pointer | Inputs to the curator; pointer lets conversation syncs skip when unchanged. |
| Search method | **grep + read + follow links** over `/tmp` | The navigate regime. |

**No vector DB. No OpenSearch. No Bedrock Knowledge Base. No EFS.** Pure file + DynamoDB.

## Retrieval model — split by path (this is the efficiency story)

Two completely different paths, and keeping them separate is the whole point:

### Anomaly-check path (frequent, batch) — hot only
1. Read the `MEMORY#HOT` item from DynamoDB (one fast read).
2. Inject it into the assessment prompt as an override/addendum.
3. Done. **No deep memory, no index, no `/tmp` sync, no agent loop.** Cheapest possible — one extra DynamoDB read per check.

### Conversation path (interactive, rare) — deep navigation
Engaged only when the user actually talks to the bot in a Slack thread (issue #16). Here we can afford the loop:
1. Sync `memory/` from S3 to `/tmp` (skip if `MEMORY#VERSION` unchanged since last sync).
2. Load `INDEX.md` into context; let the model navigate — grep, read concepts, follow `[[links]]`, reason — to answer or to make a decision.
3. On thread close, harvest durable knowledge back into deep memory (see write path).

### Lightweight-framework angle (the conversation loop only)
The conversation navigation loop is the one place an agent framework would actually do work. This is a chance to act on the inbox idea — **the "micro-agent" shift: heavyweight (LangChain) ceding to lightweight (Pydantic AI, HuggingFace smolagents)** (writing idea, B-bucket "adopt/abandon judgment," firmed 2026-06-29).

- **Candidate:** drive the conversation grep/read/follow loop with **Pydantic AI** or **smolagents** instead of hand-rolling or pulling in LangChain.
- **Rule:** only if it genuinely earns its place — less glue code, clean tool definitions, typed outputs. If hand-rolled Anthropic tool-use is simpler, do that. We don't add a dependency to feed an article; we add it if it's the right call *and then* it feeds the article.
- **Payoff if it works:** a real, own-code, build-in-public case study for the adopt/abandon post — adopted a lightweight framework where a heavyweight would've been overkill, on a tool Dan owns end to end.
- **Scope it tight:** the framework lives only in the conversation Lambda. The hot path stays a plain DynamoDB read + prompt inject — no framework anywhere near the every-check path.

## Write path — how memories are created

1. **Raw signal (already captured).** `FEEDBACK#` items from Slack buttons; the unused `CHANGE#` change log.
2. **Thread harvest.** On thread close (inactivity timeout or explicit `🧠` / `/remember`), summarize the thread into a **candidate** deep-memory concept.
3. **Consolidation (the curator).** Scheduled on the existing daily/weekly EventBridge cadence. Reads recent feedback + change log + thread candidates + the current hot item + `INDEX.md`, then: rewrites the lean `MEMORY#HOT` item, and writes/updates/prunes deep concept files in S3. Bumps `MEMORY#VERSION`.

```
FEEDBACK# / CHANGE#  ─┐
thread harvest       ─┼─► Consolidation (LLM) ─► MEMORY#HOT (DynamoDB, rewritten lean)
current hot + index  ─┘                          └─► memory/*.md + INDEX.md (S3)
                                                  └─► bump MEMORY#VERSION
```

## OKF (confirmed) and optional OKR

Deep memory uses **OKF** as its storage format. If goal-tracking is wanted later, **OKR**-style objectives slot in as `type: objective` concept files ("monthly spend < $X", "no idle NAT gateways") that conversations can reason against. Same format, just another concept type. Don't seed any to start.

## Cost reality

- **Hot path:** one DynamoDB read + a small prompt addendum per check. Negligible.
- **Conversation path:** only runs when a human is actually talking — naturally rare, so token spend is bounded by engagement, not by schedule.
- **Curator:** a few K tokens in/out per scheduled run; cents/day. Use a small (Haiku-class) model — the task is organize, not reason.

## What this reuses vs. adds

- **Reuses:** `config/loader.py` S3 context pattern; existing `FEEDBACK#` capture; the `CHANGE#` schema marked "future use"; EventBridge daily/weekly schedules; the single DynamoDB table.
- **Adds:** `MEMORY#HOT` + `MEMORY#VERSION` items; `memory/` in S3; hot-injection into `llm/prompts/analysis_prompts.py`; a consolidation Lambda; conversation-path deep navigation in the Slack bot (optionally on a lightweight framework).

Capture and injection point already exist. The missing pieces are the **curator** and the **conversation/harvest path**.

## Build plan — curator first

Ship the every-check path first. It's the smaller build, it makes anomaly detection smarter immediately, and it stands entirely on infrastructure that already exists (feedback capture, the DynamoDB table, EventBridge schedules, the S3 context-loading pattern). The conversation/deep path — and the lightweight-framework experiment — comes after, when there's appetite for the bigger lift.

### Phase 0 — Hot memory plumbing (no intelligence yet)
Prove the read/inject path with a hand-written hot memory before any LLM curation.
- Add `MEMORY#HOT` / `CURRENT` item to the table; seed it manually with a few known facts.
- In `analysis_prompts.py`, inject the hot text into the assessment prompt via the block in prompt #1 (after `guardian-context.md`).
- Add `MEMORY#VERSION` pointer item (used later by the conversation path; harmless now).
- **Done when:** a manually-edited hot fact visibly changes an anomaly assessment (e.g. seed "prod NAT baseline is accepted" and confirm a NAT bump stops surfacing).

### Phase 1 — The curator (the actual learning loop)
Make hot memory write itself from real signal.
- New consolidation Lambda on an EventBridge schedule (start daily; reuse the existing cadence wiring).
- Inputs: recent `FEEDBACK#` items + `CHANGE#` log + current `MEMORY#HOT`. (No deep memory yet — curator only maintains the hot item in this phase.)
- Uses curator prompt #2, but with `concept_writes`/`index_md` ignored for now — it only rewrites `hot_memory_text`.
- Curator model: Haiku-class.
- Write the new hot text back to `MEMORY#HOT`; log `notes` for an audit trail.
- **Done when:** clicking "expected" on a recurring alert causes that pattern to stop being surfaced on the next check, with no human editing the hot item.

### Phase 2 — Deep memory store (write side, still no conversation)
Start accumulating the OKF corpus so there's something to navigate later.
- Stand up the `memory/` prefix in S3 with `INDEX.md`.
- Extend the curator to also emit `concept_writes` + `index_md` (full prompt #2) — feedback that's durable-but-not-hot becomes deep concepts instead of bloating hot.
- Bump `MEMORY#VERSION` on every deep write.
- **Done when:** the curator is filing tagged, linked concept files in S3 and keeping `INDEX.md` accurate — even though nothing reads them yet.

### Phase 3 — Conversation path (the big lift + framework experiment)
Make deep memory readable, and harvest new memories from threads.
- Slack bot thread = a session. On engagement: `s3 sync memory/ → /tmp` (skip if `MEMORY#VERSION` unchanged), load `INDEX.md`, navigate via `grep_memory` / `read_concept` / `follow_link`.
- On thread close: run thread-harvest prompt #3 → candidate concept → fed to the curator.
- **Framework bake-off happens here:** Pydantic AI vs smolagents vs hand-rolled Anthropic tool-use, scoped to this Lambda only. Adopt one only if it's genuinely simpler. This is the build-in-public case study for the adopt/abandon post.
- **Done when:** a user can ask the bot "why did EC2 jump last Tuesday?" and it navigates deep memory to answer, and a decision made in that thread shows up as a new concept after the next curator run.

### Phase 4 — Context expansion via MCP (reach beyond our own memory)
Let the conversation agent pull in *live external context* when a question needs more than the system already knows. **The MCP server is a pluggable slot, not a specific integration** — GitHub is just the first one worth wiring. Any hosted MCP server fits the same pattern:

| Hosted MCP | What it lets the agent reach | Example question it unlocks |
|---|---|---|
| GitHub | code, PRs, issues | "Did a code change cause this S3 bump?" |
| Linear / Jira | tickets, change context | "Is this spike tied to the migration ticket?" |
| Slack | prior discussion/history | "Did we already talk about this RDS cost?" |
| AWS docs / pricing MCP | service docs, current pricing | "Is this a price change or a usage change?" |
| Internal runbook / wiki MCP | ops context | "What's the documented owner of this account?" |

The same three lines of config swap in any of them — the design below is server-agnostic.

- **Use the Messages API MCP connector, not client-side MCP.** Anthropic makes the MCP connection and runs the tool loop server-side; the integration is just extra parameters on the existing `client.messages.create(...)` call — no MCP client library, no connection management, no new infrastructure. Client-side MCP (running the MCP SDK in-Lambda) is more code and only earns its place for local servers or fine-grained connection control — not needed to reach a remote hosted server.

  ```python
  # MCP servers are config, not code — drive this list from settings/Secrets Manager.
  MCP_SERVERS = [
      {"type": "url", "name": "github", "url": "https://api.githubcopilot.com/mcp/",
       "authorization_token": secrets["GITHUB_MCP_TOKEN"]},
      # add Linear, Slack, an AWS-docs MCP, … here — same shape, one entry each
  ]

  client.beta.messages.create(
      model="claude-opus-4-8",
      max_tokens=4096,
      betas=["mcp-client-2025-11-20"],
      mcp_servers=MCP_SERVERS,
      tools=[{"type": "mcp_toolset", "mcp_server_name": s["name"]} for s in MCP_SERVERS],
      messages=[...],
  )
  ```
  Both halves are required — every entry in `mcp_servers` must be referenced by a matching `mcp_toolset` entry in `tools`, or the request is rejected.

- **Conversation path only — never the anomaly check.** MCP tool results (issue bodies, file contents, docs) land in the context window and the server-side loop burns tokens. Acceptable when a human is digging in; not acceptable 4× daily on every assessment.
- **Composes with deep memory.** The conversation agent can hold *both* the local deep-memory tools (grep/read over `/tmp`) and any attached MCP toolsets in the same turn: memory says what was decided before; MCP lets it verify against the live source ("this NAT spike lines up with the VPC change in PR #214 — let me read it").
- **Start with one, grow the slot.** Wire GitHub first (richest cost-causation signal), prove the pattern, then add servers as questions demand them. Each new server is one `mcp_servers` entry + its credential — no architectural change.
- **Auth = least privilege, reuse the existing pattern.** Each server's credential (e.g. a fine-grained GitHub PAT scoped `Contents: Read` + `Issues: Read`; a Linear/Slack token; etc.) stored in Secrets Manager via the same `.env` → Secrets Manager sync already in place. Read-only scopes only.
- **Gotchas (apply to every server):** the connector is **beta and first-party Claude API only** (not Bedrock/Vertex) — fine today since we call the direct API, but a constraint if the LLM calls ever move. No auto-offload of large tool results on the Messages API connector (unlike managed agents), so keep queries scoped (a specific PR / ticket / doc, not "dump everything"). More attached servers = more tool schemas in context and a wider surface for the model to wander — attach the few that fit the conversation, not everything available. The connector is raw request params — it needs **no** lightweight framework, so the Phase 3 framework decision and this are independent.
- **Done when:** in a Slack thread, the bot can answer a cost question by reaching into at least one external source (GitHub to start) and tying it to the cost movement — and a conclusion drawn that way can be harvested into deep memory like any other. Adding a second MCP server is then a config change, not a build.

**Value delivered by phase:** P0 = manual override works · P1 = the system learns from feedback automatically (this is the headline) · P2 = learning is organized and durable · P3 = the user can converse with the memory · P4 = the agent can reach past its own memory into live external context (GitHub, Linear, Slack, docs, …) when a question demands it.

---

# Draft prompts

Ready to lift into `src/slack_aws_cost_guardian/llm/prompts/` when built. Placeholders in `{{double_braces}}`.

## 1. Hot-memory injection (every anomaly check)

Appended to the assessment system prompt after `guardian-context.md`. **Hot only — no deep index on this path.**

```text
## Learned memory (override / addendum to the context above)

Curated memory from prior interactions and user feedback. It OVERRIDES the
static context where they conflict. Treat it as established fact about THIS
user's infrastructure and preferences when judging whether something is an
anomaly worth surfacing.

{{hot_memory_text}}
```

## 2. Consolidation / curation prompt (the curator)

```text
You are the memory curator for an AWS cost-monitoring agent. You maintain a tiny
"hot" memory (read on EVERY cost check, so it must stay lean) and an organized
deep memory of concepts (read only during conversations). You do NOT analyze
costs; you organize what has been learned about this user's infrastructure.

INPUTS
- Recent feedback (user responses to anomaly alerts): {{recent_feedback_json}}
- Recent acknowledged changes (change log): {{recent_changes_json}}
- New thread-harvest candidates: {{thread_candidates}}
- Current hot memory: {{hot_memory_text}}
- Current deep-memory index (INDEX.md): {{index_md_contents}}
- Bodies of deep concepts you may need to update: {{relevant_concept_bodies}}

PRINCIPLES
- HOT MEMORY IS TINY. Only facts that should influence EVERY future cost check
  belong there. Rewrite it lean every run — drop anything stale, redundant, or
  too specific. No archiving, no rotation; you ARE the pruning. Aim for a short,
  scannable set of statements, not a log.
- One concept per deep file. Never duplicate — UPDATE an existing concept, or
  mark it `superseded` and write a successor that lists `supersedes`.
- Link liberally: every concept lists related ids in `links`.
- Record provenance (`source`); for decisions/feedback add **Why** and
  **How to apply** lines concrete enough to change a future assessment.
- Expire concepts contradicted by newer feedback.
- Prefer doing nothing over inventing. If a signal isn't durable, skip it.

OUTPUT — strict JSON, no prose:
{
  "hot_memory_text": "<full new lean hot memory, or null to leave unchanged>",
  "concept_writes": [
    {
      "path": "services/nat-gateway-baseline.md",
      "action": "create | update | supersede | expire",
      "frontmatter": { "id": "...", "type": "...", "title": "...", "tags": [...],
                       "services": [...], "accounts": [...], "status": "...",
                       "supersedes": [...], "links": [...], "created": "...",
                       "source": "..." },
      "body": "<markdown body incl. Why / How to apply / Related links>"
    }
  ],
  "index_md": "<full new contents of INDEX.md reflecting all writes>",
  "notes": "<one line: what changed and why, for the audit log>"
}
```

## 3. Thread-harvest prompt (Slack thread → candidate concept)

```text
A user and the cost-monitoring agent had a conversation in a Slack thread.
Extract any DURABLE knowledge worth remembering for future cost assessments —
decisions made, expectations set, infrastructure context. Ignore chit-chat,
one-off acknowledgements, and anything obvious from billing data.

THREAD:
{{thread_transcript}}

If nothing durable was decided, return {"keep": false}.
Otherwise return a candidate concept for the curator to file:
{
  "keep": true,
  "type": "decision | service | account | pattern | objective",
  "title": "<short, specific>",
  "summary": "<2-4 sentences of the durable fact>",
  "why": "<why this is true / who decided it>",
  "how_to_apply": "<concretely, how a future assessment should change>",
  "services": [...], "accounts": [...], "tags": [...]
}
```

## 4. Conversation navigation (deep-memory path)

The conversation agent is given the deep-memory `INDEX.md` plus tools over the
`/tmp` corpus: `grep_memory(pattern)`, `read_concept(id)`, `follow_link(id)`.
It navigates the graph to answer or decide, then the thread-harvest prompt (#3)
runs on close. This loop is the candidate home for a **lightweight agent
framework** (Pydantic AI / smolagents) — scoped to this Lambda only.

---

## Open decisions (resolve at build time)

1. **Conversation path first, or curator first?** Curator + hot injection delivers value with zero conversation work; the deep/conversation path is the bigger build (and the framework experiment).
2. **Lightweight framework: Pydantic AI vs smolagents vs hand-rolled tool-use** — decide when building the conversation loop; only adopt if it's genuinely simpler.
3. **Seed OKR objectives or not** — pure-OKF to start.
4. **Consolidation cadence** — daily vs weekly. Daily keeps hot fresh; cheap either way.
5. **Curator model** — Haiku-class recommended.