import { stepIcon, IcoThinking } from './Icons'

/**
 * A single step row in the agent loop feed.
 *
 * step.type can be:
 *   thought      — VLM chain-of-thought (shown in a distinct style)
 *   mouse        — click / drag / scroll
 *   keyboard     — type / key_press / open_app
 *   screenshot   — screen capture
 *   analyze      — wait / reflection notice
 *   verify       — task complete check
 *   error        — failed action
 *
 * step.is_reflection=true tints the row amber to signal error-recovery.
 */
export default function StepEntry({ type, label, detail, time, instant, is_reflection }) {
  const IconComp  = stepIcon[type] ?? IcoThinking
  const reflectCls = is_reflection ? ' step-reflection' : ''

  // Thought steps get a distinct collapsed layout
  if (type === 'thought') {
    return (
      <div className={`step ${instant ? 'instant' : 'animated'} step-thought${reflectCls}`}>
        <div className="step-avatar step-avatar-thought">
          <span className="thought-icon">{is_reflection ? '🔄' : '💭'}</span>
        </div>
        <div className="step-body">
          <span className="step-label">{label}</span>
          {detail && <span className="step-detail step-detail-thought">{detail}</span>}
        </div>
        {time && <span className="step-time">{time}</span>}
      </div>
    )
  }

  return (
    <div className={`step ${instant ? 'instant' : 'animated'} step-${type}${reflectCls}`}>
      <div className={`step-avatar step-avatar-${type}`}>
        <IconComp />
      </div>
      <div className="step-body">
        <span className="step-label">{label}</span>
        {detail && <span className="step-detail">{detail}</span>}
      </div>
      {time && <span className="step-time">{time}</span>}
    </div>
  )
}
