/* Shared inline SVG icon components */

const s   = { width: 14, height: 14, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2 }
const sm  = { ...s, strokeWidth: 2.5 }
const ssm = { ...s, width: 12, height: 12 }

// ── Navigation / UI icons ─────────────────────────────────────

export const IcoMonitor = () => (
  <svg {...{ ...s, width: 36, height: 36, strokeWidth: 1.4 }}>
    <rect x="2" y="3" width="20" height="14" rx="2"/>
    <line x1="8" y1="21" x2="16" y2="21"/>
    <line x1="12" y1="17" x2="12" y2="21"/>
  </svg>
)

export const IcoPlus = () => (
  <svg {...s}>
    <line x1="12" y1="5" x2="12" y2="19"/>
    <line x1="5" y1="12" x2="19" y2="12"/>
  </svg>
)

export const IcoGear = () => (
  <svg {...{ ...s, width: 15, height: 15 }}>
    <circle cx="12" cy="12" r="3"/>
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
  </svg>
)

export const IcoClose = () => (
  <svg {...{ ...s, width: 15, height: 15, strokeWidth: 2.2 }}>
    <line x1="18" y1="6" x2="6" y2="18"/>
    <line x1="6" y1="6" x2="18" y2="18"/>
  </svg>
)

export const IcoClock = () => (
  <svg {...ssm}>
    <circle cx="12" cy="12" r="10"/>
    <path d="M12 6v6l4 2"/>
  </svg>
)

export const IcoChevronDown = () => (
  <svg {...{ ...s, width: 10, height: 10, strokeWidth: 2.5 }}>
    <polyline points="6 9 12 15 18 9"/>
  </svg>
)

export const IcoChevronLeft = () => (
  <svg {...{ ...s, width: 14, height: 14, strokeWidth: 2.2 }}>
    <polyline points="15 18 9 12 15 6"/>
  </svg>
)

export const IcoCheck = () => (
  <svg {...{ ...sm, width: 14, height: 14 }}>
    <polyline points="20 6 9 17 4 12"/>
  </svg>
)

export const IcoSearch = () => (
  <svg {...ssm}>
    <circle cx="11" cy="11" r="8"/>
    <path d="m21 21-4.35-4.35"/>
  </svg>
)

export const IcoShare = () => (
  <svg {...ssm}>
    <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/>
    <polyline points="16 6 12 2 8 6"/>
    <line x1="12" y1="2" x2="12" y2="15"/>
  </svg>
)

export const IcoFolder = () => (
  <svg {...ssm}>
    <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
  </svg>
)

export const IcoMic = () => (
  <svg {...ssm}>
    <path d="M12 2a3 3 0 0 1 3 3v7a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3z"/>
    <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
    <line x1="12" y1="19" x2="12" y2="23"/>
    <line x1="8" y1="23" x2="16" y2="23"/>
  </svg>
)

export const IcoStop = () => (
  <svg {...ssm}>
    <rect x="3" y="3" width="18" height="18" rx="2"/>
  </svg>
)

export const IcoColumns = () => (
  <svg {...ssm}>
    <rect x="3" y="3" width="7" height="18"/>
    <rect x="14" y="3" width="7" height="18"/>
  </svg>
)

export const IcoMoreHoriz = () => (
  <svg {...ssm}>
    <circle cx="5" cy="12" r="1.5" fill="currentColor" stroke="none"/>
    <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/>
    <circle cx="19" cy="12" r="1.5" fill="currentColor" stroke="none"/>
  </svg>
)

export const IcoWifi = () => (
  <svg {...ssm}>
    <path d="M5 12.55a11 11 0 0 1 14.08 0"/>
    <path d="M1.42 9a16 16 0 0 1 21.16 0"/>
    <path d="M8.53 16.11a6 6 0 0 1 6.95 0"/>
    <circle cx="12" cy="20" r="1" fill="currentColor" stroke="none"/>
  </svg>
)

// ── Step type icons ───────────────────────────────────────────

export const IcoScreenshot = () => (
  <svg {...ssm}>
    <rect x="2" y="3" width="20" height="14" rx="2"/>
    <line x1="8" y1="21" x2="16" y2="21"/>
    <line x1="12" y1="17" x2="12" y2="21"/>
  </svg>
)

export const IcoAnalyze = () => (
  <svg {...ssm}>
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
    <circle cx="12" cy="12" r="3"/>
  </svg>
)

export const IcoMouse = () => (
  <svg {...ssm}>
    <path d="M5 3a7 7 0 0 1 14 0v8a7 7 0 0 1-14 0V3z"/>
    <line x1="12" y1="3" x2="12" y2="9"/>
  </svg>
)

export const IcoKeyboard = () => (
  <svg {...ssm}>
    <rect x="2" y="6" width="20" height="12" rx="2"/>
    <path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M8 14h8"/>
  </svg>
)

export const IcoVerify = () => (
  <svg {...{ ...sm, width: 12, height: 12 }}>
    <polyline points="20 6 9 17 4 12"/>
  </svg>
)

export const IcoComplete = IcoVerify

export const IcoError = () => (
  <svg {...ssm}>
    <circle cx="12" cy="12" r="10"/>
    <line x1="12" y1="8" x2="12" y2="12"/>
    <line x1="12" y1="16" x2="12.01" y2="16"/>
  </svg>
)

export const IcoThinking = IcoClock

// ── Subtask-type icons ────────────────────────────────────────

export const IcoRocket = () => (
  <svg {...ssm}>
    <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/>
    <path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/>
    <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/>
    <path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>
  </svg>
)

export const IcoNavigation = () => (
  <svg {...ssm}>
    <polygon points="3 11 22 2 13 21 11 13 3 11"/>
  </svg>
)

export const IcoClipboard = () => (
  <svg {...ssm}>
    <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>
    <rect x="8" y="2" width="8" height="4" rx="1" ry="1"/>
  </svg>
)

export const IcoTarget = () => (
  <svg {...ssm}>
    <circle cx="12" cy="12" r="10"/>
    <circle cx="12" cy="12" r="6"/>
    <circle cx="12" cy="12" r="2"/>
  </svg>
)

export const IcoRefresh = () => (
  <svg {...ssm}>
    <polyline points="23 4 23 10 17 10"/>
    <polyline points="1 20 1 14 7 14"/>
    <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
  </svg>
)

export const IcoBolt = () => (
  <svg {...ssm}>
    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
  </svg>
)

/* Map type → icon component */
export const stepIcon = {
  screenshot: IcoScreenshot,
  analyze:    IcoAnalyze,
  mouse:      IcoMouse,
  keyboard:   IcoKeyboard,
  verify:     IcoVerify,
  complete:   IcoComplete,
  error:      IcoError,
  thinking:   IcoThinking,
}

/* Map subtask_type → icon component */
export const subtaskIcon = {
  app_launcher:   IcoRocket,
  ui_navigator:   IcoNavigation,
  form_filler:    IcoClipboard,
  verifier:       IcoTarget,
  search_locator: IcoSearch,
}
