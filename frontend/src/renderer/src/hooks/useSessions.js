/**
 * useSessions — manages in-app session history.
 * Sessions are kept in React state (and optionally localStorage).
 */
import { useState, useCallback, useEffect } from 'react'

const log = {
  info: (...a) => console.log('[useSessions]', ...a),
}

const STORAGE_KEY = 'cu-harness:sessions'

function loadFromStorage() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return { tasks: [], sessions: {} }
    return JSON.parse(raw)
  } catch {
    return { tasks: [], sessions: {} }
  }
}

function saveToStorage(data) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
  } catch {
    // ignore quota errors
  }
}

export function useSessions() {
  const [tasks,    setTasks]    = useState(() => loadFromStorage().tasks)
  const [sessions, setSessions] = useState(() => loadFromStorage().sessions)

  // Persist whenever tasks or sessions change
  useEffect(() => {
    saveToStorage({ tasks, sessions })
  }, [tasks, sessions])

  /**
   * Begin tracking a new task in the sidebar.
   * Returns the task id.
   */
  const startTask = useCallback((id, title) => {
    log.info(`startTask  id=${id}  title="${title}"`)
    setTasks((prev) => [{ id, title, status: 'running' }, ...prev])
    return id
  }, [])

  /**
   * Finalise a task once it completes (or fails).
   */
  const finishTask = useCallback((id, status, steps) => {
    log.info(`finishTask  id=${id}  status=${status}  steps=${steps.length}`)
    setTasks((prev) =>
      prev.map((t) => (t.id === id ? { ...t, status } : t))
    )
    setSessions((prev) => ({
      ...prev,
      [id]: { id, title: steps[0]?.label ?? 'Task', status, steps, finishedAt: Date.now() },
    }))
  }, [])

  /**
   * Store a complete session (used when loading from backend history).
   */
  const upsertSession = useCallback((id, data) => {
    setSessions((prev) => ({ ...prev, [id]: data }))
    setTasks((prev) => {
      if (prev.find((t) => t.id === id)) return prev
      return [{ id, title: data.title ?? data.prompt ?? id, status: data.status }, ...prev]
    })
  }, [])

  const removeTask = useCallback((id) => {
    setTasks((prev) => prev.filter((t) => t.id !== id))
    setSessions((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
  }, [])

  return { tasks, sessions, startTask, finishTask, upsertSession, removeTask }
}
