import { IcoMonitor } from './Icons'

const SUGGESTIONS = [
  "Open Safari and search for today's weather",
  'Take a screenshot of the desktop and save it',
  'Open Calculator and compute 128 × 37',
  'Create a new note in Notes titled "Ideas"',
  'Open Finder and go to the Downloads folder',
  'Arrange all open windows side by side',
]

export default function Welcome({ onRun, backendOnline }) {
  return (
    <div className="welcome">
      <div className="welcome-icon">
        <IcoMonitor />
      </div>

      <h1>What should I do on your computer?</h1>
      <p>
        I can control your mouse and keyboard, read the screen, and complete
        tasks step by step.
      </p>

      {backendOnline === false && (
        <div className="backend-warning">
          ⚠ Backend offline — start the Python server to run real tasks.
        </div>
      )}

      <div className="suggestions">
        {SUGGESTIONS.map((prompt) => (
          <button
            key={prompt}
            className="suggestion"
            onClick={() => onRun(prompt)}
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  )
}
