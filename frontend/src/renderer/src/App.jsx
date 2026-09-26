import { useCallback } from 'react'

const log = {
  info:  (...a) => console.log( '[App]', ...a),
  warn:  (...a) => console.warn('[App]', ...a),
  error: (...a) => console.error('[App]', ...a),
}
import Titlebar  from './components/Titlebar'
import Sidebar   from './components/Sidebar'
import Welcome   from './components/Welcome'
import Stream    from './components/Stream'
import PromptBar from './components/PromptBar'
import Settings  from './components/Settings'
import TargetApp from './components/TargetApp'
import { ComputerCard } from './components/ComputerPreview'

import { useTask }     from './hooks/useTask'
import { useSessions } from './hooks/useSessions'
import { useBackend }  from './hooks/useBackend'
import { useState }    from 'react'

export default function App() {
  /* ── Backend health ──────────────────────────────────────── */
  const { online: backendOnline } = useBackend()

  /* ── Session history ─────────────────────────────────────── */
  const { tasks, sessions, startTask, finishTask, upsertSession } = useSessions()

  /* ── Active task (real backend) ──────────────────────────── */
  const { running, steps, status, elapsed, showThinking, dryRun, vlmEnabled, callUser, computer, run, abort, reset } = useTask()

  /* ── Navigation ──────────────────────────────────────────── */
  const [targetPid, setTargetPid] = useState(0)
  const [currentId,    setCurrentId]    = useState(null)
  const [view,         setView]         = useState('welcome') // 'welcome' | 'stream'
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [model,        setModel]        = useState('Qwen2.5-VL')
  const [historyMode,  setHistoryMode]  = useState(false)
  const [liveTitle,   setLiveTitle]   = useState('')
  const [liveSteps,   setLiveSteps]   = useState([])
  const [liveElapsed, setLiveElapsed] = useState(0)
  const [liveStatus,  setLiveStatus]  = useState('idle')

  /* ── Load a past session ─────────────────────────────────── */
  const loadSession = useCallback((id) => {
    if (running) { log.warn('loadSession: task running, ignoring'); return }
    const session = sessions[id]
    if (!session) { log.warn(`loadSession: session ${id} not found`); return }
    log.info(`loadSession  id=${id}  status=${session.status}  steps=${session.steps?.length ?? 0}`)
    setCurrentId(id)
    setView('stream')
    setHistoryMode(true)
    setLiveTitle(session.title ?? session.prompt ?? 'Session')
    setLiveSteps(session.steps ?? [])
    setLiveElapsed(session.elapsed_ms ?? 0)
    setLiveStatus(session.status === 'success' ? 'success' : 'idle')
  }, [running, sessions])

  /* ── New task ────────────────────────────────────────────── */
  const newTask = useCallback(() => {
    if (running) { log.warn('newTask: task running, ignoring'); return }
    log.info('newTask → navigating to welcome')
    reset()
    setCurrentId(null)
    setView('welcome')
    setHistoryMode(false)
    setLiveTitle('')
    setLiveSteps([])
    setLiveElapsed(0)
    setLiveStatus('idle')
  }, [running, reset])

  /* ── Run a task ──────────────────────────────────────────── */
  const runTask = useCallback(async (prompt) => {
    if (running || !prompt.trim()) {
      log.warn('runTask: already running or empty prompt — ignored')
      return
    }
    log.info(`runTask: "${prompt.slice(0, 60)}${prompt.length > 60 ? '…' : ''}"`)

    const id    = Date.now()
    const title = prompt.trim()

    setCurrentId(id)
    setView('stream')
    setHistoryMode(false)
    setLiveTitle(title)
    setLiveSteps([])
    setLiveElapsed(0)
    setLiveStatus('running')

    startTask(id, title)

    const result = await run(prompt, targetPid)
    log.info(`runTask done  status=${result.status}  steps=${result.steps.length}  elapsed=${result.elapsed_ms}ms`)

    // Sync final state from the resolved result
    setLiveStatus(result.status)
    setLiveSteps(result.steps)
    setLiveElapsed(result.elapsed_ms)

    finishTask(id, result.status, result.steps)
    upsertSession(id, {
      id,
      title,
      prompt,
      status:     result.status,
      steps:      result.steps,
      elapsed_ms: result.elapsed_ms,
    })
  }, [running, run, targetPid, status, steps, elapsed, startTask, finishTask, upsertSession])

  /* ── Expose to Electron menu ─────────────────────────────── */
  if (typeof window !== 'undefined') {
    window.__cuNewTask = newTask
  }

  /* ── Derive display state ────────────────────────────────── */
  // In live mode use hook state (updates reactively); in history mode use stored data
  const displaySteps   = historyMode ? liveSteps   : steps
  const displayElapsed = historyMode ? liveElapsed : elapsed
  const displayStatus  = historyMode ? liveStatus  : (running ? 'running' : status)

  const statusLabel = displayStatus === 'running'  ? 'Running'
    : displayStatus === 'success'  ? 'Completed'
    : displayStatus === 'error'    ? 'Error'
    : displayStatus === 'cancelled' ? 'Cancelled'
    : 'Ready'

  const statusCls = displayStatus === 'running'  ? 'running'
    : displayStatus === 'success'  ? 'success'
    : displayStatus === 'error'    ? 'error'
    : ''

  /* ── Render ──────────────────────────────────────────────── */
  return (
    <div className="app-root">
      <Titlebar
        title={view === 'stream' ? liveTitle : ''}
        showBack={view === 'stream'}
        onSettings={() => setSettingsOpen(true)}
        onNew={newTask}
      />

      <div className="app-shell">
        <Sidebar
          tasks={tasks}
          currentId={currentId}
          running={running}
          onSelect={loadSession}
          onNew={newTask}
        />

        <div className="main">
          {!historyMode && computer && <ComputerCard computer={computer} running={running} onStop={abort} />}
          {view === 'welcome' ? (
            <Welcome onRun={runTask} backendOnline={backendOnline} />
          ) : (
            <Stream
              title={liveTitle}
              steps={displaySteps}
              showThinking={showThinking && !historyMode}
              showComplete={displayStatus === 'success'}
              statusLabel={statusLabel}
              statusCls={statusCls}
              historyMode={historyMode}
              model={model}
              elapsed={displayElapsed}
              dryRun={!historyMode && dryRun}
              vlmEnabled={!historyMode ? vlmEnabled : null}
              callUser={!historyMode ? callUser : null}
            />
          )}

          <TargetApp value={targetPid} onChange={setTargetPid} running={running} />
          <PromptBar
            running={running}
            model={model}
            onRun={runTask}
            onStop={abort}
            onModelClick={() => setSettingsOpen(true)}
          />
        </div>
      </div>

      {settingsOpen && (
        <Settings
          model={model}
          version={window.appInfo?.version ?? '0.1.0'}
          onSave={(m) => { setModel(m); setSettingsOpen(false) }}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div>
  )
}
