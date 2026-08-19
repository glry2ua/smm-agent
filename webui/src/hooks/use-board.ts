import { useEffect, useState } from "react"

import type { Board } from "@/types"

export interface BoardState {
  board: Board | null
  error: string | null
  loading: boolean
}

export function useBoard(): BoardState {
  const [board, setBoard] = useState<Board | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    fetch("/api/board")
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Board request failed with status ${response.status}`)
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
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  return { board, error, loading }
}
