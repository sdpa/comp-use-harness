/* ── Seed task history ────────────────────────────────────────── */

export const SEED_TASKS = [
  { id: 1, title: 'Play music in iTunes', status: 'success' },
  { id: 2, title: "Open Safari and search for today's weather in San Francisco", status: 'success' },
  { id: 3, title: 'Take a screenshot of the desktop and save it', status: 'success' },
]

export const SEED_SESSIONS = {
  1: {
    title: 'Play music in iTunes',
    status: 'success',
    steps: [
      { type: 'screenshot', label: 'Captured screen',           detail: '2560×1600 · 1.2 MB',                                  time: '0.3s' },
      { type: 'analyze',    label: 'Analysed screenshot',       detail: 'Identifying open apps and Dock items…',                time: '1.1s' },
      { type: 'mouse',      label: 'Clicked iTunes in Dock',    detail: 'click(x=423, y=1145)',                                 time: '2.0s' },
      { type: 'screenshot', label: 'Captured screen',           detail: 'iTunes window is now in the foreground',              time: '2.5s' },
      { type: 'mouse',      label: 'Clicked ▶ Play',            detail: 'click(x=514, y=188)',                                  time: '3.1s' },
      { type: 'verify',     label: 'Verified playback active',  detail: 'Progress bar advancing · volume 72%',                 time: '4.0s' },
      { type: 'complete',   label: 'Task complete',             detail: 'Music is now playing in iTunes',                      time: '4.1s' },
    ],
  },
  2: {
    title: "Open Safari and search for today's weather in San Francisco",
    status: 'success',
    steps: [
      { type: 'screenshot', label: 'Captured screen',           detail: '2560×1600',                                           time: '0.3s' },
      { type: 'analyze',    label: 'Analysed screenshot',       detail: 'Desktop with Finder in background',                  time: '1.0s' },
      { type: 'keyboard',   label: 'Pressed ⌘+Space',           detail: 'key(cmd+space) · Opening Spotlight',                 time: '1.6s' },
      { type: 'keyboard',   label: 'Typed "Safari"',            detail: 'type("Safari")',                                      time: '2.1s' },
      { type: 'keyboard',   label: 'Pressed Return',            detail: 'key(return) · Launching Safari',                     time: '2.4s' },
      { type: 'screenshot', label: 'Captured screen',           detail: 'Safari opened · address bar focused',                time: '3.0s' },
      { type: 'keyboard',   label: 'Typed search query',        detail: 'type("weather San Francisco today") + return',       time: '3.7s' },
      { type: 'screenshot', label: 'Captured screen',           detail: 'Results loaded',                                      time: '5.1s' },
      { type: 'verify',     label: 'Verified result',           detail: 'Weather widget visible · 68°F Partly Cloudy',        time: '5.3s' },
      { type: 'complete',   label: 'Task complete',             detail: 'Safari showing weather search results',              time: '5.3s' },
    ],
  },
  3: {
    title: 'Take a screenshot of the desktop and save it',
    status: 'success',
    steps: [
      { type: 'screenshot', label: 'Captured screenshot', detail: `~/Desktop/screenshot_2026-09-07.png · 2560×1600`, time: '0.3s' },
      { type: 'verify',     label: 'Verified file saved', detail: 'File size: 4.1 MB',                              time: '0.5s' },
      { type: 'complete',   label: 'Task complete',       detail: 'Screenshot saved to Desktop',                    time: '0.5s' },
    ],
  },
}
