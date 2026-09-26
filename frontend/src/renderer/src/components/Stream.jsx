import { useEffect, useRef } from 'react'
import StepEntry from './StepEntry'
import { IcoCheck } from './Icons'

function formatElapsed(ms) {
  if (!ms) return ''
  const s = Math.round(ms / 1000)
  const m = Math.floor(s / 60)
  const sec = s % 60
  if (m === 0) return `${sec}s`
  return `${m}m ${sec}s`
}

export default function Stream({
  steps,
  showThinking,
  showComplete,
  statusLabel,
  statusCls,
  historyMode,
  model,
  elapsed,
  dryRun,
  vlmEnabled,
  callUser,      // { question } — agent paused for human input
}) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: historyMode ? 'instant' : 'smooth' })
  }, [steps, showThinking, showComplete, historyMode])

  return (
    <div className="stream">
      <div className="stream-body">

        {/* Dry-run notice */}
        {dryRun && (
          <div className="dryrun-banner">
            🧪 <strong>Dry-run mode</strong> — no real mouse or keyboard actions are being performed.
          </div>
        )}

        {/* VLM mode banner */}
        {!historyMode && vlmEnabled === false && (
          <div className="heuristic-banner">
            🔧 <strong>Heuristic mode</strong> — running built-in action patterns.
            Configure a VLM endpoint in Settings for AI-driven control.
          </div>
        )}
        {!historyMode && vlmEnabled === true && (
          <div className="vlm-banner">
            🤖 <strong>VLM active</strong> — AI vision model is controlling the computer.
          </div>
        )}

        {/* Flat step feed — thoughts, actions, reflections all in one list */}
        {steps.map((step, i) => (
          <StepEntry key={i} {...step} instant={historyMode} />
        ))}

        {/* Agent paused — needs human input */}
        {callUser && (
          <div className="call-user-banner">
            <span className="call-user-icon">💬</span>
            <div className="call-user-body">
              <span className="call-user-label">Agent needs your input</span>
              <span className="call-user-question">{callUser.question}</span>
            </div>
          </div>
        )}

        {/* Thinking indicator */}
        {showThinking && (
          <div className="step animated step-thinking">
            <div className="step-avatar step-avatar-thinking">
              <ThinkingDots />
            </div>
            <div className="step-body">
              <span className="step-label thinking-label">Thinking…</span>
            </div>
          </div>
        )}

        {/* Timing badge */}
        {showComplete && elapsed > 0 && (
          <div className="worked-badge">
            Worked for {formatElapsed(elapsed)}
          </div>
        )}

        {/* Completion banner */}
        {showComplete && (
          <div className={`complete-banner${historyMode ? ' instant' : ''}`}>
            <IcoCheck />
            Task completed successfully
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Status bar */}
      {statusLabel && (
        <div className="stream-status">
          <span className={`status-dot ${statusCls}`} />
          <span className="status-label">{statusLabel}</span>
          {model && <span className="model-badge">{model}</span>}
        </div>
      )}
    </div>
  )
}

function ThinkingDots() {
  return (
    <span className="thinking-dots">
      <span>·</span><span>·</span><span>·</span>
    </span>
  )
}
