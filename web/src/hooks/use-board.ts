import { useCallback, useEffect, useState } from "react"

import type { Board } from "@/types"

export interface BoardState {
  board: Board | null
  error: string | null
  /** First fetch and nothing on screen yet: show skeletons. */
  loading: boolean
  /** Refetching in the background: keep the current board visible. */
  refreshing: boolean
  refresh: () => void
}

export function useBoard(): BoardState {
  const [board, setBoard] = useState<Board | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [reloadToken, setReloadToken] = useState(0)

  const refresh = useCallback(() => setReloadToken((token) => token + 1), [])

  useEffect(() => {
    let cancelled = false
    setRefreshing(true)
    fetch("/api/board")
      .then(async (response) => {
        if (!response.ok) {
          // Prefer the server's error message over a bare status code.
          let message = `Board request failed with status ${response.status}`
          try {
            const body = (await response.json()) as { error?: unknown }
            if (body && typeof body.error === "string" && body.error.trim()) {
              message = body.error
            }
          } catch {
            // non-JSON error body: keep the status-code message
          }
          throw new Error(message)
        }
        return response.json() as Promise<Board>
      })
      .then((data) => {
        if (!cancelled) {
          setBoard(data)
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load board")
        }
      })
      .finally(() => {
        if (!cancelled) {
          setRefreshing(false)
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [reloadToken])

  return { board, error, loading, refreshing, refresh }
}
