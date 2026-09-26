/* ── Step generation ─────────────────────────────────────────── */

function makeTimer() {
  let acc = 0
  return (delta = 0) => {
    acc += delta
    return acc.toFixed(1) + 's'
  }
}

function rx() { return Math.floor(Math.random() * 800 + 200) }
function ry() { return Math.floor(Math.random() * 500 + 100) }

function titleCase(s) {
  return s.replace(/\w\S*/g, (w) => w[0].toUpperCase() + w.slice(1))
}

function extractApp(prompt) {
  const known = [
    'safari', 'chrome', 'firefox', 'itunes', 'music', 'finder',
    'terminal', 'vscode', 'slack', 'calculator', 'notes', 'mail',
    'photos', 'calendar', 'maps', 'xcode', 'notion', 'zoom',
  ]
  for (const a of known) {
    if (prompt.includes(a)) return a
  }
  const m = prompt.match(/(?:open|launch|start)\s+([a-z0-9 ]+?)(?:\s+and|\s+then|\s+to|$)/i)
  return m ? m[1].trim() : null
}

function extractSearchQuery(prompt) {
  const m = prompt.match(/(?:search for|google|find|look up|search)\s+(.+?)(?:\s+in\s|\s+on\s|$)/i)
  return m ? m[1].trim() : 'your query'
}

/**
 * Generate a plausible sequence of agent steps for a given prompt.
 * @param {string} prompt
 * @returns {{ type: string, label: string, detail?: string, time: string }[]}
 */
export function generateSteps(prompt) {
  const p = prompt.toLowerCase()
  const t = makeTimer()

  const base = [
    { type: 'screenshot', label: 'Captured screen',      detail: '2560×1600',                              time: t(0.3) },
    { type: 'analyze',    label: 'Analysed screenshot',  detail: 'Identifying UI context and open apps…',   time: t(1.0) },
  ]

  let middle = []

  /* open / launch */
  if (/open|launch|start/.test(p)) {
    const appName = extractApp(p) ?? 'the application'
    middle.push(
      { type: 'keyboard',   label: 'Pressed ⌘+Space',              detail: 'key(cmd+space) · Spotlight',                        time: t(0.6) },
      { type: 'keyboard',   label: `Typed "${titleCase(appName)}"`, detail: `type("${titleCase(appName)}")`,                     time: t(0.5) },
      { type: 'keyboard',   label: 'Pressed Return',                detail: `key(return) · Launching ${titleCase(appName)}`,    time: t(0.3) },
      { type: 'screenshot', label: 'Captured screen',               detail: `${titleCase(appName)} window is open`,             time: t(1.2) },
    )
  }

  /* search */
  if (/search|google|find|look up/.test(p)) {
    const q = extractSearchQuery(p)
    middle.push(
      { type: 'mouse',      label: 'Clicked address / search bar', detail: 'click on URL field',             time: t(0.4) },
      { type: 'keyboard',   label: 'Typed search query',           detail: `type("${q}")`,                   time: t(0.8) },
      { type: 'keyboard',   label: 'Pressed Return',               detail: 'key(return) · Submitting',       time: t(0.3) },
      { type: 'screenshot', label: 'Captured screen',              detail: 'Results page loaded',             time: t(1.5) },
    )
  }

  /* screenshot / capture */
  if (/screenshot|capture|snap|screen shot/.test(p)) {
    middle = [
      {
        type:   'screenshot',
        label:  'Captured screenshot',
        detail: `~/Desktop/screenshot_${new Date().toISOString().slice(0, 10)}.png`,
        time:   t(0.2),
      },
    ]
  }

  /* type / write */
  if (/type|write|input|enter/.test(p) && !/screenshot/.test(p)) {
    middle.push(
      { type: 'mouse',    label: 'Focused input field', detail: `click(x=${rx()}, y=${ry()})`, time: t(0.4) },
      { type: 'keyboard', label: 'Typed text',          detail: 'type("…")',                    time: t(0.7) },
    )
  }

  /* click / press */
  if (/click|press|tap|button/.test(p)) {
    middle.push(
      { type: 'analyze', label: 'Located target element', detail: 'Bounding-box confirmed in screenshot', time: t(0.5) },
      { type: 'mouse',   label: 'Clicked element',        detail: `click(x=${rx()}, y=${ry()})`,          time: t(0.3) },
    )
  }

  /* media / music / volume */
  if (/music|play|pause|volume|song|track|itunes/.test(p)) {
    middle.push(
      { type: 'analyze', label: 'Located media controls', detail: 'Found playback toolbar',        time: t(0.5) },
      { type: 'mouse',   label: 'Clicked Play/Pause',     detail: `click(x=${rx()}, y=${ry()})`,  time: t(0.3) },
    )
  }

  /* calculator / compute */
  if (/calculat|comput|math|\d[\d\s×x*+\-/]+\d/.test(p)) {
    const expr = p.match(/(\d[\d\s×x*+\-/]+\d)/)?.[1]?.trim() ?? 'expression'
    middle.push(
      { type: 'screenshot', label: 'Captured screen',    detail: 'Calculator app in foreground',  time: t(0.5) },
      { type: 'keyboard',   label: 'Entered expression', detail: `type("${expr}")`,               time: t(0.8) },
      { type: 'mouse',      label: 'Clicked = button',   detail: 'click on equals',               time: t(0.3) },
      { type: 'screenshot', label: 'Captured result',    detail: 'Result visible on display',     time: t(0.5) },
    )
  }

  /* notes */
  if (/note|notes/.test(p)) {
    const tm = p.match(/titled?\s+['""]?([^'""\n]+)['""]?/i)
    const noteTitle = tm ? tm[1].trim() : 'New Note'
    middle.push(
      { type: 'screenshot', label: 'Captured screen',    detail: 'Notes app is open',          time: t(0.5) },
      { type: 'mouse',      label: 'Clicked New Note',   detail: 'click on compose button',    time: t(0.4) },
      { type: 'keyboard',   label: 'Typed note title',   detail: `type("${noteTitle}")`,       time: t(0.5) },
    )
  }

  /* fallback */
  if (middle.length === 0) {
    middle = [
      { type: 'analyze',    label: 'Planning sub-steps', detail: 'Breaking task into executable actions…', time: t(0.8) },
      { type: 'mouse',      label: 'Interacted with UI', detail: `click(x=${rx()}, y=${ry()})`,           time: t(0.6) },
      { type: 'screenshot', label: 'Captured screen',    detail: 'Verifying action result',                time: t(0.8) },
    ]
  }

  const end = [
    { type: 'verify',   label: 'Verified task outcome', detail: 'All expected changes confirmed on screen', time: t(0.6) },
    { type: 'complete', label: 'Task complete',          detail: prompt.trim(),                              time: t(0.1) },
  ]

  return [...base, ...middle, ...end]
}
