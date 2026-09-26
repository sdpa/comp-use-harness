from __future__ import annotations

from computer_use_harness.orchestrator import Orchestrator, Subtask


if __name__ == "__main__":
    orchestrator = Orchestrator(
        [
            Subtask(id="t1", goal="Ensure iTunes is open and focused", subtask_type="app_launcher"),
            Subtask(id="t2", goal="Start music playback", subtask_type="ui_navigator", depends_on=["t1"]),
            Subtask(id="t3", goal="Confirm playback is active", subtask_type="verifier", depends_on=["t2"]),
        ]
    )

    print("Execution order:", orchestrator.execution_order())
    orchestrator.complete_subtask("t1", evidence="itunes-window-open")
    orchestrator.complete_subtask("t2", evidence="play-button-clicked")
    orchestrator.complete_subtask("t3", evidence="playback-confirmed")
    print("Completed tasks:", {task_id: task.status for task_id, task in orchestrator.tasks.items()})
