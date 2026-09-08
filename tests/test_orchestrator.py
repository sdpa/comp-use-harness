from computer_use_harness.orchestrator import Orchestrator, Subtask


def test_execution_order_is_topological():
    orchestrator = Orchestrator(
        [
            Subtask(id="t1", goal="Open app", subtask_type="app_launcher"),
            Subtask(id="t2", goal="Click play", subtask_type="ui_navigator", depends_on=["t1"]),
            Subtask(id="t3", goal="Verify playback", subtask_type="verifier", depends_on=["t2"]),
        ]
    )

    assert orchestrator.execution_order() == ["t1", "t2", "t3"]


def test_completed_subtasks_are_marked_success():
    orchestrator = Orchestrator([
        Subtask(id="t1", goal="Open app", subtask_type="app_launcher"),
    ])

    orchestrator.complete_subtask("t1")

    assert orchestrator.tasks["t1"].status == "success"
