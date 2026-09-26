/**
 * useBackend — polls the Python backend health endpoint.
 * Returns { online, checking }.
 */
import { useState, useEffect, useCallback } from 'react'
import { checkHealth } from '../lib/api'

const log = {
  info: (...a) => console.log('[useBackend]', ...a),
  warn: (...a) => console.warn('[useBackend]', ...a),
}

export function useBackend(pollIntervalMs = 8000) {
  const [online,   setOnline]   = useState(null)   // null = unknown
  const [checking, setChecking] = useState(false)

  const ping = useCallback(async () => {
    setChecking(true)
    const ok = await checkHealth()
    if (ok !== null) {
      log.info(ok ? 'backend online ✓' : 'backend offline ✗')
    }
    setOnline(ok)
    setChecking(false)
  }, [])

  useEffect(() => {
    ping()
    const id = setInterval(ping, pollIntervalMs)
    return () => clearInterval(id)
  }, [ping, pollIntervalMs])

  return { online, checking, ping }
}
