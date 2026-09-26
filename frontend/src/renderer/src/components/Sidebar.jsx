import { IcoFolder, IcoSearch, IcoPlus } from './Icons'

function formatRelTime(id) {
  // id is a timestamp number
  const ms = typeof id === 'number' ? id : 0
  if (!ms) return ''
  const diff = Date.now() - ms
  if (diff < 60000) return 'just now'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`
  return `${Math.floor(diff / 86400000)}d ago`
}

// Group tasks into Today / Yesterday / Older
function groupTasks(tasks) {
  const now = Date.now()
  const DAY = 86400000
  const groups = { Today: [], Yesterday: [], Older: [] }
  for (const t of tasks) {
    const ms = typeof t.id === 'number' ? t.id : 0
    const diff = now - ms
    if (diff < DAY)         groups.Today.push(t)
    else if (diff < 2 * DAY) groups.Yesterday.push(t)
    else                     groups.Older.push(t)
  }
  return groups
}

export default function Sidebar({ tasks, currentId, running, onSelect, onNew }) {
  const groups = groupTasks(tasks)

  return (
    <aside className="sidebar">
      {/* ── Header ─────────────────────────────────────── */}
      <div className="sidebar-header">
        <div className="sidebar-brand">
          <span className="brand-logo">CH</span>
          <span className="brand-name">CompUse</span>
        </div>
        <div className="sidebar-header-actions">
          <button className="icon-btn" title="Search">
            <IcoSearch />
          </button>
          <button
            className="icon-btn"
            onClick={onNew}
            disabled={running}
            title="New chat (⌘N)"
          >
            <IcoPlus />
          </button>
        </div>
      </div>

      {/* ── New chat button ─────────────────────────────── */}
      <div className="sidebar-new">
        <button
          className="new-task-btn"
          onClick={onNew}
          disabled={running}
        >
          <IcoPlus />
          New chat
        </button>
      </div>

      {/* ── Task history ────────────────────────────────── */}
      <div className="sidebar-scroll">
        {/* Project section */}
        <div className="sidebar-section">
          <div className="sidebar-section-header">
            <IcoFolder />
            <span>comp use harness</span>
          </div>

          {tasks.length === 0 ? (
            <p className="sidebar-empty">No chats yet</p>
          ) : (
            Object.entries(groups).map(([label, group]) =>
              group.length === 0 ? null : (
                <div key={label} className="sidebar-group">
                  <span className="sidebar-group-label">{label}</span>
                  <nav className="task-history">
                    {group.map((task) => (
                      <button
                        key={task.id}
                        className={`history-item${task.id === currentId ? ' active' : ''}`}
                        onClick={() => onSelect(task.id)}
                        disabled={running && task.id !== currentId}
                        title={task.title}
                      >
                        <span className={`history-dot ${task.status}`} />
                        <span className="history-title">{task.title}</span>
                      </button>
                    ))}
                  </nav>
                </div>
              )
            )
          )}
        </div>
      </div>

      {/* ── Footer ──────────────────────────────────────── */}
      <div className="sidebar-footer">
        <div className="sidebar-user">
          <div className="user-avatar">S</div>
          <span className="user-name">User</span>
        </div>
      </div>
    </aside>
  )
}
