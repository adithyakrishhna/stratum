import { useEffect, useRef, useCallback } from 'react'

/**
 * Connects to the Django Channels WebSocket for a specific repo's pipeline.
 * Auto-reconnects on disconnect (3 s backoff).
 *
 * @param {string|null} repoId  UUID of the repository
 * @param {Function}    onMessage  called with parsed JSON payload on each message
 */
export function useWebSocket(repoId, onMessage) {
  const wsRef = useRef(null)
  const timerRef = useRef(null)
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage   // keep ref stable so connect() doesn't re-run

  const connect = useCallback(() => {
    if (!repoId) return
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${proto}//${window.location.host}/ws/pipeline/${repoId}/`
    const ws = new WebSocket(url)

    ws.onmessage = (e) => onMessageRef.current(JSON.parse(e.data))
    ws.onclose   = () => { timerRef.current = setTimeout(connect, 3000) }
    ws.onerror   = () => ws.close()

    wsRef.current = ws
  }, [repoId])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(timerRef.current)
      wsRef.current?.close()
    }
  }, [connect])
}
