import { useEffect, useState } from 'react'
import { fetchApplications } from '../lib/api'

export default function TargetApp({ value, onChange, running }) {
  const [apps, setApps] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function refresh() {
    setLoading(true)
    try {
      const result = await fetchApplications()
      setApps(result.apps || [])
      setError('')
    } catch (failure) { setError(failure.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { refresh() }, [])

  return (
    <div className="target-app">
      <label htmlFor="target-app">Control app</label>
      <select id="target-app" value={value} disabled={running || loading} onChange={event => onChange(Number(event.target.value))}>
        <option value={0}>Open an app from my instruction</option>
        {apps.map(app => <option key={app.pid} value={app.pid}>{app.name} · {app.pid}</option>)}
      </select>
      <button onClick={refresh} disabled={running || loading} aria-label="Refresh applications">↻</button>
      {error ? <span role="alert">{error}</span> : <span>App-targeted input · Your pointer stays yours</span>}
    </div>
  )
}
