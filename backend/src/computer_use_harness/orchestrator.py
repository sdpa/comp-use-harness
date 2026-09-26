"""
Orchestrator — DAG scheduler for GUI-automation subtasks.

Core features:
  • topological-sort execution order
  • status tracking: pending → running → success | failed | stuck
  • async parallel execution (independent subtasks run concurrently)
  • replanning: adjust a subtask's goal and retry it
  • plan_from_instruction: heuristic task decomposition
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Iterable

log = logging.getLogger("harness.orchestrator")

# Type alias
Emitter = Callable[[dict], Awaitable[None]]


@dataclass
class Subtask:
    id:           str
    goal:         str
    subtask_type: str = "ui_navigator"
    depends_on:   list[str] = field(default_factory=list)
    status:       str = "pending"   # pending | running | success | failed | stuck
    notes:        str = ""
    evidence:     str = ""

    def __post_init__(self) -> None:
        self.depends_on = list(dict.fromkeys(self.depends_on))


class Orchestrator:
    """Dependency-aware scheduler for GUI-automation subtasks."""

    def __init__(self, tasks: Iterable[Subtask] | None = None):
        self.tasks: dict[str, Subtask] = {}
        if tasks:
            for t in tasks:
                self.tasks[t.id] = t

    # ── Task management ───────────────────────────────────────────────────────

    def add_task(self, task: Subtask) -> None:
        self.tasks[task.id] = task

    def complete_subtask(
        self, task_id: str, *, evidence: str = "", notes: str = ""
    ) -> Subtask:
        t = self.tasks[task_id]
        t.status   = "success"
        t.evidence = evidence
        t.notes    = notes
        return t

    def fail_subtask(
        self, task_id: str, *, evidence: str = "", notes: str = ""
    ) -> Subtask:
        t = self.tasks[task_id]
        t.status   = "failed"
        t.evidence = evidence
        t.notes    = notes
        return t

    def replan_subtask(self, task_id: str, new_goal: str) -> Subtask:
        """Replace a failed/stuck subtask's goal and reset it to pending."""
        t = self.tasks[task_id]
        log.info(f"replanning {task_id!r}: {t.goal!r} → {new_goal!r}")
        t.goal   = new_goal
        t.status = "pending"
        t.notes  = ""
        return t

    # ── Execution order (topological sort) ───────────────────────────────────

    def execution_order(self) -> list[str]:
        """Return a valid serial execution order (respecting dependencies)."""
        adjacency: dict[str, set[str]] = {tid: set() for tid in self.tasks}
        indegree:  dict[str, int]      = {tid: 0     for tid in self.tasks}

        for task in self.tasks.values():
            for dep in task.depends_on:
                if dep not in self.tasks:
                    raise ValueError(f"Unknown dependency '{dep}' in task '{task.id}'")
                if task.id not in adjacency[dep]:
                    adjacency[dep].add(task.id)
                    indegree[task.id] += 1

        ready  = deque(sorted(tid for tid, deg in indegree.items() if deg == 0))
        order: list[str] = []

        while ready:
            curr = ready.popleft()
            order.append(curr)
            for nxt in sorted(adjacency[curr]):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    ready.append(nxt)

        if len(order) != len(self.tasks):
            raise ValueError("Task graph contains a cycle")
        return order

    # ── Async parallel execution ──────────────────────────────────────────────

    async def run_parallel(
        self,
        ctrl:       Any,
        vlm_client: Any,
        t0:         float,
        emit:       Emitter,
        store:      Any | None = None,
        session_id: str | None = None,
        *,
        replan_on_failure: bool = True,
        max_replan:        int  = 1,
    ) -> bool:
        """
        Execute the DAG in parallel: whenever a task's dependencies are all
        satisfied, launch it immediately alongside any other ready tasks.

        Emits plan → subtask_start → subtask_step → subtask_complete events.
        Returns True if all subtasks succeed, False otherwise.
        """
        from computer_use_harness.sub_agent import SubAgent

        # Emit the plan first
        await emit({
            "type":     "plan",
            "subtasks": [
                {
                    "id":           t.id,
                    "goal":         t.goal,
                    "subtask_type": t.subtask_type,
                    "depends_on":   t.depends_on,
                    "status":       t.status,
                }
                for t in self.tasks.values()
            ],
        })

        # Store subtasks in the session store
        if store and session_id:
            for t in self.tasks.values():
                await store.upsert_subtask(
                    session_id, t.id, t.goal, t.subtask_type, t.depends_on
                )

        replan_counts: dict[str, int] = {tid: 0 for tid in self.tasks}
        completed_ids: set[str]       = set()
        failed_ids:    set[str]       = set()
        any_stuck                     = False

        while True:
            # Identify tasks ready to run
            ready = [
                tid for tid, task in self.tasks.items()
                if task.status == "pending"
                and all(d in completed_ids for d in task.depends_on)
            ]

            if not ready:
                # Are we deadlocked? (pending tasks with all deps failed)
                still_pending = [
                    tid for tid, t in self.tasks.items()
                    if t.status == "pending"
                ]
                if still_pending:
                    log.warning(f"Deadlock — these tasks can't run: {still_pending}")
                    for tid in still_pending:
                        self.fail_subtask(tid, notes="Dependency failed")
                        failed_ids.add(tid)
                        await emit({
                            "type":       "subtask_complete",
                            "subtask_id": tid,
                            "status":     "failed",
                            "notes":      "Dependency failed",
                        })
                break

            # Mark ready tasks as running
            for tid in ready:
                self.tasks[tid].status = "running"

            log.info(f"Running in parallel: {ready}")

            # Run all ready tasks concurrently
            async def run_one(tid: str) -> None:
                nonlocal any_stuck

                async def subtask_emit(event: dict) -> None:
                    # Persist steps to session store
                    if (
                        store and session_id
                        and event.get("type") == "subtask_step"
                    ):
                        await store.log_step(session_id, tid, event["step"])
                    await emit(event)

                task    = self.tasks[tid]
                agent   = SubAgent(task, ctrl, vlm_client, t0, subtask_emit)
                success = await agent.run()

                if success:
                    self.complete_subtask(tid, notes="Completed by sub-agent")
                    completed_ids.add(tid)
                    if store and session_id:
                        await store.update_subtask_status(session_id, tid, "success", notes=task.notes)
                else:
                    outcome = self.tasks[tid].status  # could be 'stuck' or 'failed' already

                    # Replanning
                    if (
                        replan_on_failure
                        and replan_counts[tid] < max_replan
                        and outcome != "stuck"
                    ):
                        replan_counts[tid] += 1
                        new_goal = (
                            f"{task.goal} (alternative approach — previous attempt failed)"
                        )
                        log.info(f"Replanning {tid!r}  attempt={replan_counts[tid]}")
                        self.replan_subtask(tid, new_goal)
                        await emit({
                            "type":         "subtask_replanning",
                            "subtask_id":   tid,
                            "attempt":      replan_counts[tid],
                            "new_goal":     new_goal,
                        })
                        # Don't add to failed_ids — it will get picked up next iteration
                    else:
                        self.fail_subtask(tid, notes=task.notes)
                        failed_ids.add(tid)
                        if outcome == "stuck":
                            any_stuck = True
                        if store and session_id:
                            await store.update_subtask_status(
                                session_id, tid, outcome, notes=task.notes
                            )

            await asyncio.gather(*[run_one(tid) for tid in ready])

        all_success = len(failed_ids) == 0 and len(completed_ids) == len(self.tasks)
        log.info(
            f"Orchestration done  completed={len(completed_ids)}  failed={len(failed_ids)}"
            f"  total={len(self.tasks)}"
        )
        return all_success

    # ── Heuristic task decomposition ──────────────────────────────────────────

    def plan_from_instruction(self, instruction: str) -> list[Subtask]:
        """
        Decompose a natural-language instruction into an ordered list of subtasks.
        This is a simple keyword-based heuristic; replace with an LLM call for
        production use.
        """
        low = instruction.lower()

        # ── iTunes / Music ────────────────────────────────────────────────────
        if any(w in low for w in ("itunes", "music", "play music", "start music")):
            return [
                Subtask(id="t1", goal="Ensure iTunes / Music app is open and in the foreground",
                        subtask_type="app_launcher"),
                Subtask(id="t2", goal="Start music playback in the Music / iTunes app",
                        subtask_type="ui_navigator", depends_on=["t1"]),
                Subtask(id="t3", goal="Confirm that audio playback has started",
                        subtask_type="verifier", depends_on=["t2"]),
            ]

        # ── Search ────────────────────────────────────────────────────────────
        if any(w in low for w in ("search", "google", "look up", "find")):
            return [
                Subtask(id="t1", goal=f"Open the web browser for: {instruction}",
                        subtask_type="app_launcher"),
                Subtask(id="t2", goal=f"Navigate to the search bar and type the search query for: {instruction}",
                        subtask_type="ui_navigator", depends_on=["t1"]),
                Subtask(id="t3", goal=f"Verify the search results are visible for: {instruction}",
                        subtask_type="verifier", depends_on=["t2"]),
            ]

        # ── Screenshot ────────────────────────────────────────────────────────
        if any(w in low for w in ("screenshot", "capture screen", "screen shot")):
            return [
                Subtask(id="t1", goal="Take a screenshot of the current desktop",
                        subtask_type="ui_navigator"),
                Subtask(id="t2", goal="Verify the screenshot was saved",
                        subtask_type="verifier", depends_on=["t1"]),
            ]

        # ── Open + do something ───────────────────────────────────────────────
        import re
        open_m = re.search(
            r"\b(?:open|launch|start)\s+([a-z0-9 ]+?)(?:\s+and|\s+then|\s+to|$)", low
        )
        if open_m:
            app_name = open_m.group(1).strip().title()
            action   = re.sub(r"open\s+\S+\s*(and|then)?\s*", "", low, count=1).strip()
            subtasks = [
                Subtask(id="t1", goal=f"Open {app_name}",
                        subtask_type="app_launcher"),
            ]
            if action:
                subtasks += [
                    Subtask(id="t2", goal=f"In {app_name}: {action}",
                            subtask_type="ui_navigator", depends_on=["t1"]),
                    Subtask(id="t3", goal=f"Verify the result of: {action}",
                            subtask_type="verifier", depends_on=["t2"]),
                ]
            else:
                subtasks.append(
                    Subtask(id="t2", goal=f"Verify {app_name} is open and ready",
                            subtask_type="verifier", depends_on=["t1"]),
                )
            return subtasks

        # ── Generic fallback ──────────────────────────────────────────────────
        return [
            Subtask(id="t1", goal=f"Open the application needed to accomplish: {instruction}",
                    subtask_type="app_launcher"),
            Subtask(id="t2", goal=f"Complete the requested action: {instruction}",
                    subtask_type="ui_navigator", depends_on=["t1"]),
            Subtask(id="t3", goal=f"Verify the action succeeded: {instruction}",
                    subtask_type="verifier", depends_on=["t2"]),
        ]

    def run_plan(self, instruction: str) -> list[str]:
        """Convenience: decompose + add tasks + return execution order."""
        for t in self.plan_from_instruction(instruction):
            self.add_task(t)
        return self.execution_order()


__all__ = ["Orchestrator", "Subtask"]
