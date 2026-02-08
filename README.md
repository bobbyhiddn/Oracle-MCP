# Ordinal-MCP

An MCP server that implements an **ordinal communication bus** — a structured message-passing system between AI agents and humans based on ordinal levels of computation.

Built for the [Rhode](https://github.com/bobbyhiddn/Rhode) agent system. When an AI agent hits a decision boundary it can't resolve on its own, it makes an **oracle call** — a structured question sent up to the human operator. The human responds via Telegram, and the answer flows back down to the waiting agent.

## The Ordinal Model

The system defines four computational levels:

| Level | Role | Description |
|-------|------|-------------|
| **0** | Infrastructure | Filesystem, network, containers |
| **1** | Subagent | Worker agents executing delegated tasks |
| **2** | Orchestrator | Rhode — the lead agent |
| **3** | Oracle | The human operator |

Communication flows **upward** (oracle calls — asking for guidance) and **downward** (task delegation — assigning work to subagents). Messages are typed, structured, and archived.

Rhode occupies a unique position: it is both an **agent** (making oracle calls upward to the human) and an **oracle** (answering oracle calls from subagents below). This dual role is the defining feature of the ordinal architecture. When a subagent has a question, Rhode answers it immediately using its own LLM — without involving the human. When Rhode itself has a question, it escalates to Micah via Telegram. The bus routes each call to the right responder based on the caller's ordinal level.

## How It Works

There are two distinct oracle pathways, determined by who is asking:

```
Path 1: L1 → L2 (Subagent asks Orchestrator)
┌──────────┐    oracle_call(from_level=1)    ┌──────────┐
│ Subagent │ ──────────────────────────────> │  Rhode   │
│  (Lv 1)  │ <────────────────────────────── │  (Lv 2)  │
└──────────┘    immediate LLM response       └──────────┘

Path 2: L2 → L3 (Orchestrator asks Oracle)
┌──────────┐    oracle_call(from_level=2)    ┌──────────┐    Telegram     ┌──────────┐
│  Rhode   │ ──────────────────────────────> │   Bus    │ ─────────────> │  Micah   │
│  (Lv 2)  │ <────────────────────────────── │          │ <───────────── │  (Lv 3)  │
└──────────┘    response                     └──────────┘    /oracle     └──────────┘
```

**Path 1** — A subagent calls `oracle_call("How should I handle this edge case?", from_level=1)`:

1. The request is written as JSON to `~/.rhode/bus/requests/`
2. Rhode's bus monitor detects `to_level=2` and handles it internally
3. Rhode generates an answer using its own LLM (no Telegram, no human)
4. The response is written to `~/.rhode/bus/responses/`
5. The subagent receives the answer and continues
6. The exchange is archived to `~/.rhode/bus/history/`

**Path 2** — Rhode calls `oracle_call("Should I deploy to production?", from_level=2)`:

1. The request is written as JSON to `~/.rhode/bus/requests/`
2. Rhode's bus monitor detects `to_level=3` and relays to Telegram
3. Micah sees the question in Telegram and replies with `/oracle <answer>`
4. The response is written to `~/.rhode/bus/responses/`
5. Rhode receives the answer and continues
6. The exchange is archived to `~/.rhode/bus/history/`

## Routing Logic

The bus monitor in Rhode inspects the `from_level` and `to_level` fields of each request and routes accordingly:

| `from_level` | `to_level` | Route | Responder |
|:---:|:---:|---|---|
| 1 | 2 | Rhode answers immediately via LLM | `"orchestrator"` |
| 2 | 3 | Relayed to Micah via Telegram | `"oracle"` |

**Rules:**

- `to_level` is always `from_level + 1`. The bus computes this automatically.
- **L1 calls never touch Telegram.** Rhode handles them entirely in-process using the Claude Agent SDK. The subagent gets an immediate LLM-generated response.
- **L2 calls always go to Telegram.** The bus monitor formats the question and sends it to the configured Telegram chat. Micah responds with `/oracle <answer>`.
- The response JSON includes a `responder` field (`"orchestrator"` or `"oracle"`) so the caller knows who answered.
- If Rhode determines a subagent's question actually requires human judgment, it will say so in its answer. The subagent can then re-ask with `from_level=2` to escalate.

## MCP Tools

### `oracle_call`
Send a question to the oracle and wait for a response.

```
question: str             — The question to ask (be clear and specific)
context: str = ""         — Optional context for the responder
urgency: str = "normal"   — low | normal | high | critical
timeout_seconds: int = 300 — How long to wait (default 5 min)
from_level: int = 2       — Your ordinal level. 1 = subagent (answered by Rhode),
                             2 = orchestrator (answered by human via Telegram)
```

### `bus_status`
Check the current state of the bus — pending requests, responses, and history count.

### `list_pending_calls`
List all oracle calls currently waiting for a response.

### `respond_to_oracle_call`
Answer a pending oracle call (used by the oracle/orchestrator side).

```
request_id: str  — ID of the pending request
answer: str      — The response
```

### `bus_history`
View recent completed exchanges.

```
limit: int = 10  — Max number of exchanges to show
```

## CLI Tools

The [Rhode](https://github.com/bobbyhiddn/Rhode) project provides two command-line tools that interact with the ordinal bus. These are installed as entry points when Rhode is installed (`pip install -e .` or `uv sync` in the Rhode repo).

### `rhode-oracle`

Make a blocking oracle call from the command line. Writes a request to the bus, polls for a response, and prints the answer to stdout.

```bash
# Ask the human oracle (default: from_level=2)
rhode-oracle "Should I deploy the new version to production?"

# Ask with context and urgency
rhode-oracle "The CI pipeline is failing on main" --context "Tests pass locally" --urgency high

# Ask as a subagent (Rhode answers via LLM, no Telegram)
rhode-oracle "How should I handle missing config keys?" --level 1

# Set a custom timeout
rhode-oracle "Need approval for the API key rotation" --timeout 600

# Fire-and-forget (write request, don't wait for response)
rhode-oracle "FYI: nightly backup completed successfully" --no-wait
```

**Options:**

```
question              — The question to ask (positional argument)
--context, -c         — Additional context for the question
--urgency, -u         — low | normal | high | critical (default: normal)
--timeout, -t         — Timeout in seconds (default: 300)
--level, -l           — Ordinal level of caller (default: 2 = orchestrator)
--no-wait             — Write request and exit without waiting for a response
```

### `rhode-reboot`

Restart the Rhode service with task continuity. Writes a continuation prompt to `~/.rhode/reboot_prompt.json` and restarts the systemd service. When Rhode comes back up, it reads the prompt and resumes work.

```bash
# Reboot with a continuation prompt
rhode-reboot "Continue working on the Ordinal-MCP integration"

# Include context from before the reboot
rhode-reboot "Pick up task X" --context "Was halfway through refactoring agent.py"

# Write the prompt without restarting (useful for testing)
rhode-reboot "Resume after config change" --no-restart
```

**Options:**

```
prompt                — The prompt to resume with after reboot (positional argument)
--context, -c         — Additional context from before the reboot
--no-restart          — Write prompt only, don't restart the service
```

## Bus Directory Structure

```
~/.rhode/bus/
├── requests/           # Pending oracle call requests (JSON)
├── responses/          # Oracle responses (JSON)
└── history/            # Archived exchanges
    └── 20260207_143052/
        ├── request_a1b2c3d4.json
        └── response_a1b2c3d4.json
```

Configurable via the `ORDINAL_BUS_DIR` environment variable.

## JSON Protocol

All bus communication uses JSON files. Below are the schemas for requests and responses.

### Request Schema

Written to `~/.rhode/bus/requests/<request_id>.json`:

```json
{
  "id": "a1b2c3d4",
  "type": "oracle_call",
  "from_level": 1,
  "to_level": 2,
  "question": "How should I handle the missing API key?",
  "context": "The .env file exists but has no OPENAI_KEY entry",
  "urgency": "normal",
  "timestamp": "2026-02-07T14:30:52.123456+00:00",
  "status": "pending"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique request identifier (UUID prefix or timestamped) |
| `type` | string | Always `"oracle_call"` for upward queries |
| `from_level` | int | Ordinal level of the caller (1 = subagent, 2 = orchestrator) |
| `to_level` | int | Target level, always `from_level + 1` (computed automatically) |
| `question` | string | The question being asked |
| `context` | string | Optional additional context for the responder |
| `urgency` | string | One of `"low"`, `"normal"`, `"high"`, `"critical"` |
| `timestamp` | string | ISO 8601 UTC timestamp of when the request was created |
| `status` | string | `"pending"` while waiting, `"timeout"` if no response received |

### Response Schema

Written to `~/.rhode/bus/responses/<request_id>.json`:

```json
{
  "id": "a1b2c3d4",
  "type": "oracle_response",
  "question": "How should I handle the missing API key?",
  "answer": "Check the .env.example file for the expected key name, then prompt the user to set it.",
  "responder": "orchestrator",
  "timestamp": "2026-02-07T14:30:55.789012+00:00"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Matches the original request ID |
| `type` | string | Always `"oracle_response"` |
| `question` | string | Echo of the original question (for context in archives) |
| `answer` | string | The response content |
| `responder` | string | `"orchestrator"` if Rhode answered, `"oracle"` if the human answered |
| `timestamp` | string | ISO 8601 UTC timestamp of when the response was written |

### Archive Schema

After a response is written, the exchange is archived to `~/.rhode/bus/history/<request_id>.json`:

```json
{
  "request": { "...request fields..." },
  "response": { "...response fields..." },
  "archived_at": "2026-02-07T14:31:00.000000+00:00"
}
```

The request file is removed from `requests/`. The response file remains in `responses/` until the caller reads it (so the polling agent can pick it up).

## Installation

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/bobbyhiddn/Ordinal-MCP.git
cd Ordinal-MCP
uv sync
```

### Run standalone

```bash
uv run ordinal-mcp
```

### Configure as an MCP server

Add to your `.mcp.json` (e.g. in your Claude Code project root):

```json
{
  "mcpServers": {
    "ordinal-mcp": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/Ordinal-MCP", "ordinal-mcp"]
    }
  }
}
```

## Background

This implements a practical version of Turing's [O-machine](https://en.wikipedia.org/wiki/Oracle_machine) concept — a computation model where the machine can query an external oracle for answers to undecidable questions. In this system, the "undecidable questions" are judgment calls, preference decisions, and ambiguous requirements that only a human can resolve.

The ordinal levels give the system a clear hierarchy: infrastructure at the bottom, human at the top, with agents in between. Each level can call upward when it needs help and delegate downward when it can break work apart.

## License

MIT
