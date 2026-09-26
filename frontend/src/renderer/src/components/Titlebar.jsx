import { IcoGear, IcoShare, IcoColumns, IcoChevronLeft, IcoMoreHoriz } from './Icons'

export default function Titlebar({ title, onSettings, onNew, showBack }) {
  return (
    <div className="titlebar">
      {/* Left: back + breadcrumb */}
      <div className="titlebar-left">
        {showBack && (
          <button className="icon-btn tb-back" onClick={onNew} title="New chat">
            <IcoChevronLeft />
          </button>
        )}
        <span className="titlebar-title">{title || 'Computer-Use Harness'}</span>
        {title && (
          <button className="icon-btn tb-more" title="More options">
            <IcoMoreHoriz />
          </button>
        )}
      </div>

      {/* Right: actions */}
      <div className="titlebar-controls">
        {title && (
          <button className="tb-share-btn" title="Share">
            <IcoShare />
            Share
          </button>
        )}
        <button className="icon-btn" onClick={onSettings} title="Settings (⌘,)">
          <IcoGear />
        </button>
        <button className="icon-btn" title="Toggle layout">
          <IcoColumns />
        </button>
      </div>
    </div>
  )
}
