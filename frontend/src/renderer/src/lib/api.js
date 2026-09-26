/**
 * Computer-Use Harness — API client
 *
 * Communicates with the Python FastAPI backend at BACKEND_URL.
 */

const log = {
  info:  (...a) => console.log( '[api]', ...a),
  warn:  (...a) => console.warn('[api]', ...a),
  error: (...a) => console.error('[api]', ...a),
}

let BACKEND_URL = 'http://127.0.0.1:7123'
if (window.electronBridge?.getBackendUrl) {
  window.electronBridge.getBackendUrl()
    .then((url) => { BACKEND_URL = url })
    .catch(() => {})
}

const getWsUrl = () => BACKEND_URL.replace(/^http/, 'ws')

// ── Health ────────────────────────────────────────────────────────────────────

export async function checkHealth() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/health`, {
      signal: AbortSignal.timeout(2000),
    })
    const ok = res.ok
    log.info(`health → ${ok ? 'online ✓' : `HTTP ${res.status}`}`)
    return ok
  } catch (err) {
    log.warn(`health failed: ${err.message}`)
    return false
  }
}

// ── Config ────────────────────────────────────────────────────────────────────

export async function fetchConfig() {
  const res = await fetch(`${BACKEND_URL}/api/config`)
  if (!res.ok) throw new Error(`fetchConfig: HTTP ${res.status}`)
  return res.json()
}

export async function saveConfig(cfg) {
  const res = await fetch(`${BACKEND_URL}/api/config`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify(cfg),
  })
  if (!res.ok) throw new Error(`saveConfig: HTTP ${res.status}`)
  return res.json()
}

// ── Sessions ──────────────────────────────────────────────────────────────────

export async function fetchSessions() {
  const res = await fetch(`${BACKEND_URL}/api/sessions`)
  if (!res.ok) throw new Error(`fetchSessions: HTTP ${res.status}`)
  return res.json()
}

export async function fetchSession(sessionId) {
  const res = await fetch(`${BACKEND_URL}/api/sessions/${sessionId}`)
  if (!res.ok) throw new Error(`fetchSession: HTTP ${res.status}`)
  return res.json()
}

// ── Tasks ─────────────────────────────────────────────────────────────────────

export async function fetchTasks() {
  const res = await fetch(`${BACKEND_URL}/api/tasks`)
  if (!res.ok) throw new Error(`fetchTasks: HTTP ${res.status}`)
  return res.json()
}

export async function createTask(prompt) {
  log.info(`POST /api/tasks  prompt="${prompt.slice(0, 60)}${prompt.length > 60 ? '…' : ''}"`)
  const res = await fetch(`${BACKEND_URL}/api/tasks`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ prompt }),
  })
  if (!res.ok) throw new Error(`createTask: HTTP ${res.status}`)
  const data = await res.json()
  log.info(`task created  id=${data.id}`)
  return data
}

// ── WebSocket stream ──────────────────────────────────────────────────────────

/**
 * Stream task events over WebSocket (single agent-loop architecture).
 *
 * Callbacks:
 *   onInfo(msg)          — backend info (vlm_enabled, run_id, …)
 *   onStep(step)         — every loop step: thought, action, reflection, verify
 *   onCallUser(msg)      — agent needs human input; msg = { question }
 *   onComplete(msg)      — task finished successfully; msg = { elapsed_ms }
 *   onError(err)         — server error or task_failed
 *
 * Returns a close() function to abort streaming.
 */
export function streamTask(taskId, callbacks = {}) {
  const { onInfo, onStep, onCallUser, onComplete, onError } = callbacks

  const url = `${getWsUrl()}/api/tasks/${taskId}/stream`
  log.info(`WS open  ${url}`)
  const ws      = new WebSocket(url)
  let closed    = false
  let stepCount = 0

  ws.onopen = () => log.info(`WS connected → task ${taskId}`)

  ws.onmessage = (evt) => {
    let msg
    try {
      msg = JSON.parse(evt.data)
    } catch (err) {
      log.error(`WS parse error: ${err.message}`)
      onError?.(err)
      return
    }

    switch (msg.type) {
      case 'info':
        log.info(`WS info: ${msg.message}  run_id=${msg.run_id ?? '—'}`)
        onInfo?.(msg)
        break

      case 'step':
        stepCount++
        log.info(`WS step #${stepCount}  [${msg.step?.type}] ${msg.step?.label}`)
        onStep?.(msg.step)
        break

      case 'call_user':
        log.info(`WS call_user  question="${msg.question}"`)
        onCallUser?.(msg)
        break

      case 'task_failed':
        log.warn(`WS task_failed  detail=${msg.detail}`)
        onError?.(new Error(msg.detail || 'Task failed'))
        ws.close()
        break

      case 'complete':
        log.info(`WS complete  elapsed=${msg.elapsed_ms}ms`)
        onComplete?.(msg)
        ws.close()
        break

      case 'error':
        log.error(`WS server error: ${msg.message}`)
        onError?.(new Error(msg.message))
        ws.close()
        break

      default:
        log.warn(`WS unknown message type: ${msg.type}`)
    }
  }

  ws.onerror = () => {
    log.error(`WS error on task ${taskId}`)
    if (!closed) onError?.(new Error('WebSocket connection failed'))
  }

  ws.onclose = (evt) => {
    closed = true
    log.info(`WS closed  code=${evt.code}  reason="${evt.reason || 'none'}"`)
  }

  return () => {
    log.info('WS close requested (abort)')
    closed = true
    ws.close()
  }
}
