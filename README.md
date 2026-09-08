# Computer-Use Harness

This project implements a desktop computer-use harness built around the ideas in the design brief:

- an MCP-backed `computer-control` server for mouse, keyboard, and screen interaction
- an orchestrator that decomposes a task into a DAG of sub-agents
- a small desktop shell for viewing task progress and logs
- a reusable planner/sub-task model for GUI automation loops

## Project layout

- `src/computer_use_harness/orchestrator.py` — DAG scheduler and subtask planner
- `src/computer_use_harness/mcp_server.py` — MCP server wrapper exposing the GUI tools
- `src/computer_use_harness/ui.py` — lightweight desktop shell for displaying plan status
- `tests/test_orchestrator.py` — verification tests for dependency scheduling and completion tracking

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python -m computer_use_harness.demo
```

## Example orchestration

```python
from computer_use_harness.orchestrator import Orchestrator, Subtask

orchestrator = Orchestrator([
    Subtask(id="t1", goal="Open iTunes", subtask_type="app_launcher"),
    Subtask(id="t2", goal="Start playback", subtask_type="ui_navigator", depends_on=["t1"]),
    Subtask(id="t3", goal="Verify audio is playing", subtask_type="verifier", depends_on=["t2"]),
])

print(orchestrator.execution_order())
```

## Notes

This is a solid MVP scaffold for the architecture described in the brief. The real GUI automation layer is intentionally isolated behind the MCP server, which makes it easy to swap model providers, add safety checks, or connect alternative clients later.
