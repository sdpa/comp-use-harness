/**
 * useTask — runs a computer-use task against the single agent-loop backend.
 *
 * All steps (thought, action, reflection, verify) arrive as flat `step` events.
 * No plan/subtask state needed — the loop manages its own reasoning internally.
 */
import { useState, useRef, useCallback } from 'react'
import { createTask, streamTask } from '../lib/api'

const log = {
  info:  (...a) => console.log( '[useTask]', ...a),
  warn:  (...a) => console.warn('[useTask]', ...a),
  error: (...a) => console.error('[useTask]', ...a),
}

export function useTask() {
  const [running,      setRunning]      = useState(false)
  const [steps,        setSteps]        = useState([])   // flat list of all loop steps
  const [status,       setStatus]       = useState('idle')
  const [error,        setError]        = useState(null)
  const [elapsed,      setElapsed]      = useState(0)
  const [showThinking, setShowThinking] = useState(false)
  const [dryRun,       setDryRun]       = useState(false)
  const [vlmEnabled,   setVlmEnabled]   = useState(null) // null=unknown, true/false
  const [callUser,     setCallUser]     = useState(null) // { question } when agent needs input

  const abortRef = useRef(null)
  const timerRef = useRef(null)

  const reset = useCallback(() => {
    setRunning(false)
    setSteps([])
    setStatus('idle')
    setError(null)
    setElapsed(0)
    setShowThinking(false)
    setDryRun(false)
    setVlmEnabled(null)
    setCallUser(null)
  }, [])

  /**
   * Run a prompt. Returns { status, steps, elapsed_ms } when done.
   */
  const run = useCallback((prompt) => new Promise((resolveRun) => {
    if (running) {
      log.warn('run() called while already running — ignored')
      resolveRun({ status: 'idle', steps: [], elapsed_ms: 0 })
      return
    }
    reset()

    log.info(`starting task: "${prompt.slice(0, 60)}${prompt.length > 60 ? '…' : ''}"`)
    setRunning(true)
    setStatus('running')
    setShowThinking(true)

    const t0         = Date.now()
    const localSteps = []   // mutable ref to avoid stale closure

    timerRef.current = setInterval(() => setElapsed(Date.now() - t0), 200)

    createTask(prompt).then(({ id: taskId }) => {
      log.info(`task created  id=${taskId}`)

      const close = streamTask(taskId, {

        // ── Info ─────────────────────────────────────────────
        onInfo(msg) {
          if (msg.dry_run)                          setDryRun(true)
          if (typeof msg.vlm_enabled === 'boolean') setVlmEnabled(msg.vlm_enabled)
          if (msg.run_id) log.info(`run_id=${msg.run_id}`)
        },

        // ── Step (thought / action / reflection / verify) ────
        onStep(step) {
          localSteps.push(step)
          log.info(`step  [${step.type}] "${step.label}"  reflect=${step.is_reflection ?? false}`)
          setShowThinking(false)
          setSteps([...localSteps])
          setShowThinking(true)
        },

        // ── Agent needs human input ───────────────────────────
        onCallUser(msg) {
          log.info(`call_user  question="${msg.question}"`)
          setCallUser(msg)
          setShowThinking(false)
        },

        // ── Complete ─────────────────────────────────────────
        onComplete(msg) {
          const elapsed_ms = msg.elapsed_ms ?? Date.now() - t0
          clearInterval(timerRef.current)
          log.info(`complete  steps=${localSteps.length}  elapsed=${elapsed_ms}ms`)
          setShowThinking(false)
          setStatus('success')
          setElapsed(elapsed_ms)
          setRunning(false)
          abortRef.current = null
          resolveRun({ status: 'success', steps: localSteps, elapsed_ms })
        },

        // ── Error / task_failed ───────────────────────────────
        onError(err) {
          const elapsed_ms = Date.now() - t0
          clearInterval(timerRef.current)
          log.error(`error: ${err.message}`)
          setShowThinking(false)
          setStatus('error')
          setError(err.message)
          setRunning(false)
          abortRef.current = null
          resolveRun({ status: 'error', steps: localSteps, elapsed_ms })
        },
      })

      abortRef.current = () => {
        const elapsed_ms = Date.now() - t0
        log.info(`aborted  steps=${localSteps.length}`)
        close()
        clearInterval(timerRef.current)
        setShowThinking(false)
        setStatus('cancelled')
        setRunning(false)
        abortRef.current = null
        resolveRun({ status: 'cancelled', steps: localSteps, elapsed_ms })
      }
    }).catch((err) => {
      const elapsed_ms = Date.now() - t0
      clearInterval(timerRef.current)
      log.error(`createTask failed: ${err.message}`)
      setShowThinking(false)
      setStatus('error')
      setError(err.message)
      setRunning(false)
      abortRef.current = null
      resolveRun({ status: 'error', steps: [], elapsed_ms })
    })
  }), [running, reset])

  const abort = useCallback(() => {
    abortRef.current?.()
    clearInterval(timerRef.current)
  }, [])

  return {
    running, steps, status, error, elapsed,
    showThinking, dryRun, vlmEnabled, callUser,
    run, abort, reset,
  }
}
