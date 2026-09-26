import { subtaskIcon, IcoCheck, IcoError, IcoRefresh } from './Icons'

const TYPE_LABELS = {
  app_launcher:   'App launcher',
  ui_navigator:   'UI navigator',
  form_filler:    'Form filler',
  verifier:       'Verifier',
  search_locator: 'Search locator',
}

const STATUS_LABELS = {
  pending:  'Pending',
  running:  'Running',
  success:  'Done',
  failed:   'Failed',
  stuck:    'Stuck',
}

function SubtaskRow({ subtask, steps, isLast }) {
  const { id, goal, subtask_type = 'ui_navigator', status = 'pending', depends_on = [] } = subtask
  const IconComp = subtaskIcon[subtask_type] ?? subtaskIcon.ui_navigator
  const mySteps = steps.filter((s) => s.subtask_id === id)

  return (
    <div className={`dag-subtask dag-status-${status}`}>
      {/* Connector line (skip for first item) */}
      {depends_on.length > 0 && <div className="dag-connector" />}

      {/* Header row */}
      <div className="dag-subtask-header">
        <div className={`dag-icon dag-icon-${subtask_type}`}>
          <IconComp />
        </div>

        <div className="dag-subtask-body">
          <span className="dag-subtask-type">{TYPE_LABELS[subtask_type] ?? subtask_type}</span>
          <span className="dag-subtask-goal">{goal}</span>
        </div>

        <div className="dag-status-badge-wrap">
          {status === 'running' && (
            <span className="dag-badge dag-badge-running">
              <span className="dag-dot-running" />
              Running
            </span>
          )}
          {status === 'success' && (
            <span className="dag-badge dag-badge-success">
              <IcoCheck />
              Done
            </span>
          )}
          {status === 'failed' && (
            <span className="dag-badge dag-badge-failed">
              <IcoError />
              Failed
            </span>
          )}
          {status === 'stuck' && (
            <span className="dag-badge dag-badge-failed">
              <IcoRefresh />
              Stuck
            </span>
          )}
          {status === 'pending' && (
            <span className="dag-badge dag-badge-pending">
              Waiting
            </span>
          )}
        </div>
      </div>

      {/* Per-subtask steps (when running or completed) */}
      {mySteps.length > 0 && (
        <div className="dag-steps">
          {mySteps.map((step, i) => (
            <div key={i} className={`dag-step dag-step-${step.type}`}>
              <span className="dag-step-dot" />
              <span className="dag-step-label">{step.label}</span>
              {step.detail && <span className="dag-step-detail">{step.detail}</span>}
              {step.time && <span className="dag-step-time">{step.time}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function PlanDAG({ subtasks = [], steps = [] }) {
  if (!subtasks.length) return null

  return (
    <div className="plan-dag">
      <div className="dag-header">
        <span className="dag-label">Subtask plan</span>
        <span className="dag-count">{subtasks.length} subtask{subtasks.length !== 1 ? 's' : ''}</span>
      </div>
      <div className="dag-list">
        {subtasks.map((st, i) => (
          <SubtaskRow
            key={st.id}
            subtask={st}
            steps={steps}
            isLast={i === subtasks.length - 1}
          />
        ))}
      </div>
    </div>
  )
}
