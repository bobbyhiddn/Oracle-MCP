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

Communication flows **upward** (oracle calls — asking the human) and **downward** (task delegation — assigning work to subagents). Messages are typed, structured, and archived.

## How It Works

```
┌──────────┐    oracle_call()    ┌──────────┐    Telegram     ┌──────────┐
│ Subagent │ ──────────────────> │   Bus    │ ─────────────> │  Human   │
│ (Lv 1-2) │ <────────────────── │ (~/.rhode│ <───────────── │  (Lv 3)  │
└──────────┘    response         │  /bus/)  │    reply       └──────────┘
                                 └──────────┘
```

1. An agent calls `oracle_call("Should I deploy to production?")`
2. The request is written as JSON to `~/.rhode/bus/requests/`
3. Rhode's bus monitor picks it up and sends it to the human via Telegram
4. The human replies in Telegram
5. The response is written to `~/.rhode/bus/responses/`
6. The agent receives the answer and continues
7. The exchange is archived to `~/.rhode/bus/history/`

## MCP Tools

### `oracle_call`
Send a question to the oracle and wait for a response.

```
question: str        — The question to ask (be clear and specific)
context: str = ""    — Optional context for the oracle
urgency: str = "normal"  — low | normal | high | critical
timeout_seconds: int = 300  — How long to wait (default 5 min)
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
