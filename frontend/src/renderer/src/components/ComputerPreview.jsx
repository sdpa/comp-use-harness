import { useEffect, useState } from 'react'
import './ComputerPreview.css'

const actionLabels = {
  click: 'Clicking', left_double: 'Double-clicking', right_single: 'Right-clicking',
  drag: 'Dragging', move_mouse: 'Moving pointer', scroll: 'Scrolling',
}

export function ComputerScreen({ frame, cursor }) {
  const width = frame?.width > 0 ? frame.width : 1280
  const height = frame?.height > 0 ? frame.height : 800
  const pointerVisible = cursor && Number.isFinite(cursor.x) && Number.isFinite(cursor.y)
    && cursor.x >= 0 && cursor.y >= 0 && cursor.x < width && cursor.y < height
  return (
    <div className="computer-screen">
      {frame?.image_b64 ? (
        <svg className="computer-screen-svg" viewBox={`0 0 ${width} ${height}`} aria-label="Latest desktop observation" role="img">
          <image href={`data:image/png;base64,${frame.image_b64}`} width={width} height={height} />
          {pointerVisible && <AgentPointer cursor={cursor} scale={width / 700} />}
        </svg>
      ) : (
        <>
          <div className="computer-placeholder">
            <span className="computer-monitor-icon" aria-hidden="true">▣</span>
            <strong>{frame?.dry_run ? 'Simulated desktop' : frame?.error ? 'Screen unavailable' : 'Waiting for the first observation'}</strong>
            <span>{frame?.dry_run ? 'Dry run · no desktop input' : frame?.error || 'The agent’s screen will appear here.'}</span>
          </div>
          {pointerVisible && <svg className="computer-screen-svg pointer-only" viewBox={`0 0 ${width} ${height}`} aria-label="Agent pointer">
            <AgentPointer cursor={cursor} scale={width / 700} />
          </svg>}
        </>
      )}
    </div>
  )
}

export function AgentPointer({ cursor, scale }) {
  return (
    <g transform={`translate(${cursor.x} ${cursor.y})`} className={`agent-pointer ${cursor.phase === 'failed' ? 'failed' : ''}`}>
      <g transform={`scale(${scale})`}>
        {['click', 'left_double', 'right_single'].includes(cursor.action) && cursor.phase === 'acting' && (
          <circle key={cursor.sequence} className="agent-click-ring" r="18" fill="none" stroke="currentColor" strokeWidth="2" />
        )}
        <path d="M0 0 L0 25 L7 19 L13 31 L19 28 L13 16 L23 16 Z" fill="currentColor" stroke="white" strokeWidth="1.5" strokeLinejoin="round" />
        <rect x="22" y="23" width="55" height="22" rx="7" fill="currentColor" />
        <text x="49.5" y="38" textAnchor="middle" fontSize="12" fontWeight="650" fill="white">Agent</text>
      </g>
    </g>
  )
}

export function ComputerCard({ computer, running, onStop }) {
  return (
    <section className="computer-card" aria-label="Agent computer preview">
      <button className="computer-card-open" onClick={() => window.electronBridge?.openComputerPreview()} title="Open the agent computer window">
        <ComputerScreen frame={computer.frame} cursor={computer.cursor} />
        <div className="computer-card-caption"><span className={`computer-dot ${running ? 'active' : ''}`} />Agent computer<span className="computer-expand">↗</span></div>
      </button>
      <div className="computer-card-footer"><span>{running ? 'Working in the selected app' : 'Last observation'} · View only</span>{running && <button onClick={onStop}>Stop</button>}</div>
    </section>
  )
}

export default function ComputerPreview() {
  const [state, setState] = useState(null)
  useEffect(() => {
    let disposed = false
    let received = false
    const off = window.electronBridge?.onComputerPreview(value => {
      received = true
      if (!disposed) setState(value)
    })
    window.electronBridge?.getComputerPreview().then(value => {
      if (!disposed && !received) setState(value)
    }).catch(() => {})
    return () => { disposed = true; off?.() }
  }, [])

  const active = state?.status === 'running'
  const stopping = state?.status === 'stopping'
  const status = { running: 'Working', stopping: 'Stopping…', success: 'Completed', cancelled: 'Stopped', error: 'Needs attention' }[state?.status] || 'Connecting'
  const expand = () => window.electronBridge?.expandComputerPreview(!state?.expanded)
  return (
    <div className={`computer-window ${state?.expanded ? 'expanded' : 'compact'}`}>
      <header className="computer-window-bar">
        <span className={`computer-dot ${active ? 'active' : ''}`} />
        <span>Agent computer</span>
        <button onClick={expand} aria-label={state?.expanded ? 'Minimize preview' : 'Expand preview'}>{state?.expanded ? '↙' : '↗'}</button>
      </header>
      <div className="computer-window-title"><strong title={state?.title}>{state?.title || 'Computer use'}</strong><span>{status}</span></div>
      {state?.expanded ? <div className="computer-view"><ComputerScreen frame={state?.frame} cursor={state?.cursor} /></div> : (
        <button className="computer-view expandable" onClick={expand} aria-label="Expand computer view">
          <ComputerScreen frame={state?.frame} cursor={state?.cursor} />
          <span className="expand-hint">Click to expand</span>
        </button>
      )}
      <footer className="computer-window-footer">
        <div><strong>{state?.error || (active ? actionLabels[state?.cursor?.action] || state?.action || 'Observing…' : status)}</strong><span>{state?.dryRun ? 'Dry run · simulated actions' : 'Target app · view only · updates at each action'}</span></div>
        {(active || stopping) && <button className="computer-stop" disabled={stopping} onClick={() => window.electronBridge?.stopComputerPreview()}>{stopping ? 'Stopping…' : '■ Stop'}</button>}
      </footer>
    </div>
  )
}

export function AgentCursorOverlay() {
  const [cursor, setCursor] = useState(null)
  useEffect(() => {
    let active = true
    const off = window.electronBridge?.onComputerPreview(state => { if (active) setCursor(state?.cursor) })
    window.electronBridge?.getComputerPreview().then(state => { if (active) setCursor(state?.cursor) }).catch(() => {})
    return () => { active = false; off?.() }
  }, [])
  return <div className="agent-cursor-overlay" aria-hidden="true"><svg width="110" height="80">
    {cursor && <AgentPointer cursor={{ ...cursor, x: 10, y: 10 }} scale={1} />}
  </svg></div>
}
