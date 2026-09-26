import { useState, useEffect, useCallback } from 'react'
import { IcoClose } from './Icons'
import { fetchConfig, saveConfig } from '../lib/api'

const VLM_MODELS = [
  { value: 'qwen3-vl:8b',             label: 'Qwen3-VL 8B (Ollama)' },
  { value: 'qwen2.5-vl:7b',           label: 'Qwen2.5-VL 7B (Ollama)' },
  { value: 'qwen2.5-vl:72b',          label: 'Qwen2.5-VL 72B (Ollama)' },
  { value: 'llava:13b',               label: 'LLaVA 13B (Ollama)' },
  { value: 'ui-tars',                 label: 'UI-TARS (vLLM)' },
  { value: 'gpt-4o',                  label: 'GPT-4o (OpenAI)' },
  { value: 'claude-3-5-sonnet-latest', label: 'Claude 3.5 Sonnet (Anthropic)' },
]

const DISPLAY_MODELS = [
  { value: 'Qwen2.5-VL',         label: 'Qwen2.5-VL (default)' },
  { value: 'Claude 3.5 Sonnet',  label: 'Claude 3.5 Sonnet' },
  { value: 'GPT-4o',             label: 'GPT-4o' },
  { value: 'Gemini 2.0 Flash',   label: 'Gemini 2.0 Flash' },
]

export default function Settings({ model, version, onSave, onClose }) {
  const [selectedModel, setSelectedModel] = useState(model)
  const [vlmBaseUrl,    setVlmBaseUrl]    = useState('')
  const [vlmModel,      setVlmModel]      = useState('qwen2.5-vl:7b')
  const [vlmApiKey,     setVlmApiKey]     = useState('')
  const [interval,      setInterval]      = useState(500)
  const [confirmActs,   setConfirmActs]   = useState(false)
  const [saveLogs,      setSaveLogs]      = useState(true)
  const [saveStatus,    setSaveStatus]    = useState(null)  // null | 'saving' | 'saved' | 'error'
  const [configLoaded,  setConfigLoaded]  = useState(false)

  /* Load config from backend on open */
  useEffect(() => {
    fetchConfig()
      .then((cfg) => {
        if (cfg.vlm_base_url) setVlmBaseUrl(cfg.vlm_base_url)
        if (cfg.vlm_model)    setVlmModel(cfg.vlm_model)
        setConfigLoaded(true)
      })
      .catch(() => setConfigLoaded(true))
  }, [])

  /* Close on Escape */
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  const handleOverlayClick = useCallback((e) => {
    if (e.target === e.currentTarget) onClose()
  }, [onClose])

  const handleSave = useCallback(async () => {
    setSaveStatus('saving')
    try {
      await saveConfig({
        vlm_base_url: vlmBaseUrl.trim(),
        vlm_model:    vlmModel,
        vlm_api_key:  vlmApiKey,
      })
      setSaveStatus('saved')
      setTimeout(() => setSaveStatus(null), 2000)
    } catch {
      setSaveStatus('error')
      setTimeout(() => setSaveStatus(null), 3000)
    }
    onSave(selectedModel)
  }, [selectedModel, vlmBaseUrl, vlmModel, vlmApiKey, onSave])

  return (
    <div className="settings-overlay" onClick={handleOverlayClick}>
      <div className="settings-panel" role="dialog" aria-modal="true" aria-label="Settings">
        {/* Header */}
        <div className="settings-header">
          <h2>Settings</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close settings">
            <IcoClose />
          </button>
        </div>

        <div className="settings-body">

          {/* ── VLM Configuration ─────────────────────────── */}
          <div className="settings-section-title">VLM / AI Model</div>

          <div className="settings-group">
            <label className="settings-label" htmlFor="vlm-base-url">
              Inference server URL
            </label>
            <input
              className="settings-field"
              id="vlm-base-url"
              type="url"
              placeholder="http://localhost:11434/v1  (Ollama)"
              value={vlmBaseUrl}
              onChange={(e) => setVlmBaseUrl(e.target.value)}
              spellCheck={false}
            />
            <p className="settings-desc">
              OpenAI-compatible endpoint. Leave blank to use built-in heuristics (no VLM needed).
              Ollama: <code>http://localhost:11434/v1</code> · vLLM: <code>http://localhost:8000/v1</code>
            </p>
          </div>

          <div className="settings-group">
            <label className="settings-label" htmlFor="vlm-model">
              Model
            </label>
            <select
              className="settings-field"
              id="vlm-model"
              value={vlmModel}
              onChange={(e) => setVlmModel(e.target.value)}
            >
              {VLM_MODELS.map((m) => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
              <option value={vlmModel}>{vlmModel}</option>
            </select>
          </div>

          <div className="settings-group">
            <label className="settings-label" htmlFor="vlm-api-key">
              API Key (optional)
            </label>
            <input
              className="settings-field"
              id="vlm-api-key"
              type="password"
              placeholder="sk-… or leave blank for Ollama"
              autoComplete="off"
              value={vlmApiKey}
              onChange={(e) => setVlmApiKey(e.target.value)}
            />
          </div>

          {/* ── Display model label ───────────────────────── */}
          <div className="settings-section-title" style={{ marginTop: '4px' }}>Display</div>

          <div className="settings-group">
            <label className="settings-label" htmlFor="model-select">Model badge label</label>
            <select
              className="settings-field"
              id="model-select"
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
            >
              {DISPLAY_MODELS.map((m) => (
                <option key={m.value} value={m.value}>{m.label}</option>
              ))}
            </select>
          </div>

          {/* ── Agent behaviour ───────────────────────────── */}
          <div className="settings-section-title">Agent behaviour</div>

          <div className="settings-group">
            <label className="settings-label" htmlFor="screenshot-interval">
              Screenshot interval (ms)
            </label>
            <input
              className="settings-field"
              id="screenshot-interval"
              type="number"
              min={100}
              max={5000}
              step={100}
              value={interval}
              onChange={(e) => setInterval(Number(e.target.value))}
            />
          </div>

          <div className="settings-group settings-row">
            <div>
              <label className="settings-label">Confirm before actions</label>
              <p className="settings-desc">Pause and ask before mouse or keyboard actions</p>
            </div>
            <label className="toggle">
              <input
                type="checkbox"
                checked={confirmActs}
                onChange={(e) => setConfirmActs(e.target.checked)}
              />
              <span className="toggle-track" />
            </label>
          </div>

          <div className="settings-group settings-row">
            <div>
              <label className="settings-label">Save session logs</label>
              <p className="settings-desc">Persist action logs to SQLite after each task</p>
            </div>
            <label className="toggle">
              <input
                type="checkbox"
                checked={saveLogs}
                onChange={(e) => setSaveLogs(e.target.checked)}
              />
              <span className="toggle-track" />
            </label>
          </div>
        </div>

        {/* Footer */}
        <div className="settings-footer">
          <span className="settings-version">v{version}</span>
          <button
            className={`settings-save-btn ${saveStatus === 'saved' ? 'saved' : ''} ${saveStatus === 'error' ? 'err' : ''}`}
            onClick={handleSave}
            disabled={saveStatus === 'saving'}
          >
            {saveStatus === 'saving' ? 'Saving…' : saveStatus === 'saved' ? '✓ Saved' : saveStatus === 'error' ? '✗ Error' : 'Save changes'}
          </button>
        </div>
      </div>
    </div>
  )
}
