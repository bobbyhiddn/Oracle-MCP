#!/usr/bin/env python3
"""
Ordinal-MCP: An oracle communication bus for Rhode and its subagents.

This MCP server implements the ordinal computation model where:
- Level 0: Infrastructure (filesystem, network, containers)
- Level 1: Subagents (workers executing delegated tasks)
- Level 2: Orchestrator (Rhode, the lead agent)
- Level 3: Oracle (Micah, the human owner)

The bus enables upward oracle calls (asking the human) and downward
task delegation (assigning work to subagents). Messages flow through
the bus with typed requests and structured responses.

Phase 1: oracle_call — ask the human a question, wait for response.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# Configure logging to stderr (never stdout in stdio servers)
logging.basicConfig(
    level=logging.INFO,
    format="[Ordinal-MCP] %(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Bus state directory
BUS_DIR = Path(os.environ.get("ORDINAL_BUS_DIR", os.path.expanduser("~/.rhode/bus")))
REQUESTS_DIR = BUS_DIR / "requests"
RESPONSES_DIR = BUS_DIR / "responses"
HISTORY_DIR = BUS_DIR / "history"

# Ensure directories exist
for d in [BUS_DIR, REQUESTS_DIR, RESPONSES_DIR, HISTORY_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Initialize the MCP server
mcp = FastMCP("ordinal-mcp")

# --- Ordinal Levels ---
ORDINAL_LEVELS = {
    0: "infrastructure",
    1: "subagent",
    2: "orchestrator",
    3: "oracle",
}


def _write_request(request_id: str, data: dict) -> Path:
    """Write a request to the bus."""
    path = REQUESTS_DIR / f"{request_id}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    logger.info(f"Request written: {request_id}")
    return path


def _read_response(request_id: str) -> dict | None:
    """Read a response from the bus, if available."""
    path = RESPONSES_DIR / f"{request_id}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def _archive_exchange(request_id: str):
    """Move completed request/response pair to history."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_dir = HISTORY_DIR / timestamp
    archive_dir.mkdir(parents=True, exist_ok=True)

    req_path = REQUESTS_DIR / f"{request_id}.json"
    resp_path = RESPONSES_DIR / f"{request_id}.json"

    if req_path.exists():
        req_path.rename(archive_dir / f"request_{request_id}.json")
    if resp_path.exists():
        resp_path.rename(archive_dir / f"response_{request_id}.json")

    logger.info(f"Exchange archived: {request_id} -> {archive_dir}")


@mcp.tool()
async def oracle_call(
    question: str,
    context: str = "",
    urgency: str = "normal",
    timeout_seconds: int = 300,
) -> str:
    """Send a question to the oracle (Micah) and wait for a response.

    This is an upward call on the ordinal bus. Use this when you need
    human judgment, a decision, or information that cannot be computed.

    The oracle will be notified via Telegram and can respond at their
    convenience. The call will wait up to timeout_seconds for a response.

    Args:
        question: The question to ask the oracle. Be clear and specific.
        context: Optional context to help the oracle understand the situation.
        urgency: How urgent is this? One of: low, normal, high, critical.
        timeout_seconds: How long to wait for a response (default 300s / 5min).
    """
    request_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now(timezone.utc).isoformat()

    request_data = {
        "id": request_id,
        "type": "oracle_call",
        "from_level": 2,  # orchestrator level
        "to_level": 3,    # oracle level
        "question": question,
        "context": context,
        "urgency": urgency,
        "timestamp": timestamp,
        "status": "pending",
    }

    _write_request(request_id, request_data)
    logger.info(f"Oracle call dispatched: {request_id} — {question[:80]}")

    # Poll for response
    start_time = time.time()
    poll_interval = 2.0  # seconds between checks

    while (time.time() - start_time) < timeout_seconds:
        response = _read_response(request_id)
        if response is not None:
            _archive_exchange(request_id)
            answer = response.get("answer", "(no answer provided)")
            responder = response.get("responder", "oracle")
            logger.info(f"Oracle response received: {request_id} from {responder}")
            return f"Oracle response ({responder}): {answer}"

        await asyncio.sleep(poll_interval)

    # Timeout — archive the unanswered request
    request_data["status"] = "timeout"
    _write_request(request_id, request_data)
    _archive_exchange(request_id)
    logger.warning(f"Oracle call timed out: {request_id}")
    return f"Oracle call timed out after {timeout_seconds}s. The oracle did not respond. Request ID: {request_id}"


@mcp.tool()
def bus_status() -> str:
    """Check the current status of the ordinal bus.

    Returns information about pending requests, recent responses,
    and bus health.
    """
    pending_requests = list(REQUESTS_DIR.glob("*.json"))
    pending_responses = list(RESPONSES_DIR.glob("*.json"))
    history_entries = list(HISTORY_DIR.iterdir())

    status_lines = [
        "=== Ordinal Bus Status ===",
        f"Bus directory: {BUS_DIR}",
        f"Pending requests: {len(pending_requests)}",
        f"Pending responses: {len(pending_responses)}",
        f"Historical exchanges: {len(history_entries)}",
        "",
    ]

    if pending_requests:
        status_lines.append("--- Pending Requests ---")
        for req_path in sorted(pending_requests):
            with open(req_path) as f:
                req = json.load(f)
            status_lines.append(
                f"  [{req.get('id', '?')}] {req.get('urgency', 'normal').upper()}: "
                f"{req.get('question', '?')[:60]}"
            )
        status_lines.append("")

    return "\n".join(status_lines)


@mcp.tool()
def respond_to_oracle_call(request_id: str, answer: str) -> str:
    """Respond to a pending oracle call.

    This is used by the oracle (Micah) or the orchestrator (Rhode) to
    answer a pending question on the bus.

    Args:
        request_id: The ID of the request to respond to.
        answer: The answer to the question.
    """
    req_path = REQUESTS_DIR / f"{request_id}.json"
    if not req_path.exists():
        return f"No pending request found with ID: {request_id}"

    with open(req_path) as f:
        request_data = json.load(f)

    response_data = {
        "id": request_id,
        "type": "oracle_response",
        "question": request_data.get("question", ""),
        "answer": answer,
        "responder": "oracle",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    resp_path = RESPONSES_DIR / f"{request_id}.json"
    with open(resp_path, "w") as f:
        json.dump(response_data, f, indent=2, default=str)

    logger.info(f"Response written for request: {request_id}")
    return f"Response recorded for request {request_id}. The caller will receive it shortly."


@mcp.tool()
def list_pending_calls() -> str:
    """List all pending oracle calls waiting for a response.

    Use this to see what questions are waiting on the bus.
    """
    pending = list(REQUESTS_DIR.glob("*.json"))

    if not pending:
        return "No pending oracle calls on the bus."

    lines = ["=== Pending Oracle Calls ===", ""]
    for req_path in sorted(pending):
        with open(req_path) as f:
            req = json.load(f)

        lines.append(f"Request ID: {req.get('id', '?')}")
        lines.append(f"  Question: {req.get('question', '?')}")
        lines.append(f"  Context: {req.get('context', '(none)')}")
        lines.append(f"  Urgency: {req.get('urgency', 'normal')}")
        lines.append(f"  Time: {req.get('timestamp', '?')}")
        lines.append(f"  Status: {req.get('status', 'pending')}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def bus_history(limit: int = 10) -> str:
    """View recent oracle call history.

    Args:
        limit: Maximum number of historical exchanges to show (default 10).
    """
    history_dirs = sorted(HISTORY_DIR.iterdir(), reverse=True)[:limit]

    if not history_dirs:
        return "No history on the bus yet."

    lines = ["=== Ordinal Bus History ===", ""]
    for hist_dir in history_dirs:
        if not hist_dir.is_dir():
            continue
        req_files = list(hist_dir.glob("request_*.json"))
        resp_files = list(hist_dir.glob("response_*.json"))

        for req_file in req_files:
            with open(req_file) as f:
                req = json.load(f)
            lines.append(f"[{req.get('id', '?')}] Q: {req.get('question', '?')[:80]}")
            lines.append(f"  Urgency: {req.get('urgency', 'normal')} | Status: {req.get('status', '?')}")

        for resp_file in resp_files:
            with open(resp_file) as f:
                resp = json.load(f)
            lines.append(f"  A: {resp.get('answer', '(no answer)')[:80]}")
            lines.append(f"  Responder: {resp.get('responder', '?')}")

        lines.append(f"  Archived: {hist_dir.name}")
        lines.append("")

    return "\n".join(lines)


def main():
    """Run the Ordinal-MCP server on stdio transport."""
    logger.info("Ordinal-MCP starting...")
    logger.info(f"Bus directory: {BUS_DIR}")
    logger.info(f"Ordinal levels: {ORDINAL_LEVELS}")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
