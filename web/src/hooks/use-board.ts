import { useCallback, useEffect, useState } from "react"

import { MOCK } from "@/lib/api"
import { fetchMockBoard } from "@/lib/mock/board"
import type { Board } from "@/types"

interface BoardState {
  board: Board | null
  error: string | null
  /** First fetch and nothing on screen yet: show skeletons. */
  loading: boolean
  /** Refetching in the background: keep the current board visible. */
  refreshing: boolean
  refresh: () => void
}

// Module scope, not component state: it survives Vite HMR remounts and
// StrictMode double-mounts, so re-rendering the page never re-hits
// /api/board. Buffer's quota (250 calls/24h) makes every call count.
let cache: { board: Board } | null = null
let inFlight: Promise<Board> | null = null

export function useBoard(): BoardState {
  // MOCK is a build-time constant (vite --mode mock); the branch never flips
  // within a session, so the hook-order difference it implies is safe.
  return MOCK ? useMockBoard() : useRealBoard()
}

/** Board state against the in-memory mock store (`npm run web-mock`). */
function useMockBoard(): BoardState {
  const [board, setBoard] = useState<Board | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [reloadToken, setReloadToken] = useState(0)

  const refresh = useCallback(() => setReloadToken((token) => token + 1), [])

  useEffect(() => {
    let cancelled = false
    setRefreshing(true)
    fetchMockBoard()
      .then((data) => {
        if (!cancelled) setBoard(data)
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

  return { board, error: null, loading, refreshing, refresh }
}

function useRealBoard(): BoardState {
  const [board, setBoard] = useState<Board | null>(cache?.board ?? null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(cache === null)
  const [refreshing, setRefreshing] = useState(false)
  const [reloadToken, setReloadToken] = useState(0)

  const refresh = useCallback(() => setReloadToken((token) => token + 1), [])

  useEffect(() => {
    // Warm cache and no explicit refresh requested: render from memory only.
    if (cache && reloadToken === 0) {
      setBoard(cache.board)
      setError(null)
      setLoading(false)
      setRefreshing(false)
      return
    }

    let cancelled = false
    setRefreshing(true)

    // Returns the board instead of setting state: state writes live in the
    // effect below so each run reacts with its own `cancelled` flag, even when
    // it reuses a promise started by a run whose cleanup already fired.
    const load = async (): Promise<Board> => {
      // `fresh=1` bypasses the server's board TTL for explicit user reloads.
      const url = reloadToken > 0 ? "/api/board?fresh=1" : "/api/board"
      const response = await fetch(url)
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
      const data = (await response.json()) as Board
      cache = { board: data }
      return data
    }

    // Dedupe concurrent loads (e.g. StrictMode's double effect run) into one
    // request; both mounts get the same result.
    const promise =
      inFlight ??
      (inFlight = load().finally(() => {
        inFlight = null
      }))

    promise.then(
      (data) => {
        if (!cancelled) {
          setBoard(data)
          setError(null)
        }
      },
      (err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load board")
        }
      },
    ).finally(() => {
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