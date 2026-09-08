from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class Subtask:
    id: str
    goal: str
    subtask_type: str = "ui_navigator"
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"
    notes: str = ""
    evidence: str = ""

    def __post_init__(self) -> None:
        self.depends_on = list(dict.fromkeys(self.depends_on))


class Orchestrator:
    """Simple dependency scheduler for GUI automation subtasks."""

    def __init__(self, tasks: Iterable[Subtask] | None = None):
        self.tasks: dict[str, Subtask] = {}
        if tasks:
            for task in tasks:
                self.tasks[task.id] = task

    def add_task(self, task: Subtask) -> None:
        self.tasks[task.id] = task

    def execution_order(self) -> list[str]:
        adjacency: dict[str, set[str]] = {task_id: set() for task_id in self.tasks}
        indegree: dict[str, int] = {task_id: 0 for task_id in self.tasks}

        for task in self.tasks.values():
            for dependency in task.depends_on:
                if dependency not in self.tasks:
                    raise ValueError(f"Unknown dependency: {dependency} for task {task.id}")
                if task.id not in adjacency[dependency]:
                    adjacency[dependency].add(task.id)
                    indegree[task.id] += 1

        ready = deque(sorted(task_id for task_id, degree in indegree.items() if degree == 0))
        order: list[str] = []

        while ready:
            current = ready.popleft()
            order.append(current)
            for next_task in sorted(adjacency[current]):
                indegree[next_task] -= 1
                if indegree[next_task] == 0:
                    ready.append(next_task)

        if len(order) != len(self.tasks):
            raise ValueError("Task graph contains a cycle")

        return order

    def complete_subtask(self, task_id: str, *, evidence: str = "", notes: str = "") -> Subtask:
        task = self.tasks[task_id]
        task.status = "success"
        task.evidence = evidence
        task.notes = notes
        return task

    def fail_subtask(self, task_id: str, *, evidence: str = "", notes: str = "") -> Subtask:
        task = self.tasks[task_id]
        task.status = "failed"
        task.evidence = evidence
        task.notes = notes
        return task

    def plan_from_instruction(self, instruction: str) -> list[Subtask]:
        lower = instruction.lower()
        if "itunes" in lower:
            return [
                Subtask(id="t1", goal="Ensure iTunes is open and focused", subtask_type="app_launcher"),
                Subtask(id="t2", goal="Start music playback in iTunes", subtask_type="ui_navigator", depends_on=["t1"]),
                Subtask(id="t3", goal="Confirm music is playing", subtask_type="verifier", depends_on=["t2"]),
            ]
        return [
            Subtask(id="t1", goal=f"Open the application needed for: {instruction}", subtask_type="app_launcher"),
            Subtask(id="t2", goal=f"Complete the requested action for: {instruction}", subtask_type="ui_navigator", depends_on=["t1"]),
            Subtask(id="t3", goal=f"Verify the action for: {instruction} succeeded", subtask_type="verifier", depends_on=["t2"]),
        ]

    def run_plan(self, instruction: str) -> list[str]:
        tasks = self.plan_from_instruction(instruction)
        for task in tasks:
            self.add_task(task)
        return self.execution_order()


__all__ = ["Orchestrator", "Subtask"]
