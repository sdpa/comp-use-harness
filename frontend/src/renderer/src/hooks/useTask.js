import { useState, useRef, useCallback, useEffect } from 'react'
import { createTask, streamTask } from '../lib/api'

export function useTask() {
  const [running, setRunning] = useState(false)
  const [steps, setSteps] = useState([])
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState(null)
  const [elapsed, setElapsed] = useState(0)
  const [showThinking, setShowThinking] = useState(false)
  const [dryRun, setDryRun] = useState(false)
  const [vlmEnabled, setVlmEnabled] = useState(null)
  const [callUser, setCallUser] = useState(null)
  const [computer, setComputer] = useState(null)
  const active = useRef(null)

  const reset = useCallback(() => {
    if (active.current) return
    setRunning(false)
    setSteps([])
    setStatus('idle')
    setError(null)
    setElapsed(0)
    setShowThinking(false)
    setDryRun(false)
    setVlmEnabled(null)
    setCallUser(null)
    setComputer(null)
  }, [])

  const abort = useCallback(() => active.current?.abort(), [])

  useEffect(() => {
    const off = window.electronBridge?.onComputerStop(taskId => {
      if (active.current?.id === taskId) active.current.abort()
    })
    return () => { off?.(); active.current?.abort() }
  }, [])

  const run = useCallback((prompt, targetPid = 0) => new Promise(resolveRun => {
    if (active.current) {
      resolveRun({ status: 'idle', steps: [], elapsed_ms: 0 })
      return
    }
    reset()
    setRunning(true)
    setStatus('running')
    setShowThinking(true)
    const started = Date.now()
    const localSteps = []
    const controller = new AbortController()
    const task = { id: null, close: null, settled: false, abort: null }
    active.current = task
    const timer = setInterval(() => setElapsed(Date.now() - started), 200)

    function publish(patch) {
      setComputer(previous => ({ ...previous, ...patch, taskId: task.id }))
      if (task.id) window.electronBridge?.updateComputerPreview(task.id, patch)
    }

    function finish(nextStatus, message = '', elapsedMs = Date.now() - started) {
      if (task.settled) return
      task.settled = true
      controller.abort()
      task.close?.()
      clearInterval(timer)
      publish({ status: nextStatus, error: message })
      setRunning(false)
      setShowThinking(false)
      setStatus(nextStatus)
      setError(message || null)
      setElapsed(elapsedMs)
      active.current = null
      resolveRun({ status: nextStatus, steps: localSteps, elapsed_ms: elapsedMs })
    }

    task.abort = () => finish('cancelled')
    createTask(prompt, targetPid, controller.signal).then(async ({ id }) => {
      task.id = id
      if (task.settled) return
      publish({ title: prompt, status: 'running', frame: null, cursor: null, targetPid })
      try { await window.electronBridge?.startComputerPreview(id, prompt) } catch { /* Browser-only UI remains usable. */ }
      if (task.settled) {
        window.electronBridge?.updateComputerPreview(id, { status: 'cancelled' })
        return
      }
      task.close = streamTask(id, {
        onInfo(message) {
          if (typeof message.dry_run === 'boolean') {
            setDryRun(message.dry_run)
            publish({ dryRun: message.dry_run })
          }
          if (typeof message.vlm_enabled === 'boolean') setVlmEnabled(message.vlm_enabled)
        },
        onStep(step) {
          localSteps.push(step)
          setSteps([...localSteps])
          publish({ action: step.label })
        },
        onComputerFrame: frame => publish({ frame }),
        onComputerCursor: cursor => publish({ cursor }),
        onComputerTarget: target => publish({ targetPid: target.target_pid, targetApp: target.app, cursor: null, frame: null }),
        onCallUser(message) { setCallUser(message); setShowThinking(false) },
        onComplete: message => finish('success', '', message.elapsed_ms),
        onError: failure => finish('error', failure.message),
      })
    }).catch(failure => {
      if (!task.settled) finish('error', failure.message)
    })
  }), [reset])

  return { running, steps, status, error, elapsed, showThinking, dryRun, vlmEnabled, callUser, computer, run, abort, reset }
}
