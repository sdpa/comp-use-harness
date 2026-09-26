import { useState, useRef, useEffect, useCallback } from 'react'
import { IcoChevronDown, IcoMic, IcoStop, IcoPlus } from './Icons'

export default function PromptBar({ running, model, onRun, onStop, onModelClick }) {
  const [value, setValue] = useState('')
  const textareaRef = useRef(null)

  /* Auto-grow */
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  }, [value])

  /* Focus on mount / when running ends */
  useEffect(() => {
    if (!running) textareaRef.current?.focus()
  }, [running])

  const submit = useCallback(() => {
    if (value.trim() && !running) {
      onRun(value.trim())
      setValue('')
    }
  }, [value, running, onRun])

  const handleKeyDown = useCallback((e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault()
      submit()
    }
    if (e.key === 'Escape') textareaRef.current?.blur()
  }, [submit])

  const canRun = value.trim().length > 0 && !running

  return (
    <div className="prompt-wrap">
      <div className="prompt-box">
        <textarea
          ref={textareaRef}
          className="prompt-textarea"
          placeholder="Do anything."
          rows={1}
          spellCheck={false}
          value={value}
          disabled={running}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
        />

        <div className="prompt-actions">
          {/* Left: attachment */}
          <button className="prompt-action-btn" title="Add attachment">
            <IcoPlus />
          </button>

          {/* Centre: approval / stop */}
          {running ? (
            <button className="ask-approval-btn active" onClick={onStop} title="Stop">
              <IcoStop />
              Stop
            </button>
          ) : (
            <button className="ask-approval-btn" disabled>
              Ask for approval
            </button>
          )}

          {/* Right: model + mic + send */}
          <div className="prompt-right">
            <button
              className="model-selector"
              onClick={onModelClick}
              title="Change model"
            >
              <span>{model}</span>
              <IcoChevronDown />
            </button>

            <button className="prompt-action-btn" title="Voice input">
              <IcoMic />
            </button>

            <button
              className="run-btn"
              disabled={!canRun}
              onClick={submit}
              title="Run task (⌘↵)"
            >
              ↵
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
