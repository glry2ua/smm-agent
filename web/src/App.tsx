import { useCallback, useEffect, useRef, useState } from "react"
import {
  IconCheck,
  IconCircleCheckFilled,
  IconClockFilled,
  IconPencilFilled,
  IconRefresh,
  IconTags,
} from "@tabler/icons-react"

import { BoardColumn } from "@/components/board-column"
import { KeywordsModal } from "@/components/keywords-modal"
import { PostModal } from "@/components/post-modal"
import { MOCK } from "@/lib/api"
import { Kanban, KanbanBoard } from "@/components/ui/kanban"
import { useBoard } from "@/hooks/use-board"
import { groupPosts } from "@/lib/grouping"
import { Button } from "@/ui/button"
import { cn } from "@/lib/utils"
import type { GroupedPost } from "@/types"

const COLUMNS: {
  key: string
  title: string
  icon: React.ComponentType<{ className?: string }>
  accent: string
  emptyLabel: string
}[] = [
  {
    key: "drafts",
    title: "Drafts",
    icon: IconPencilFilled,
    accent: "text-orange-600",
    emptyLabel: "No drafts right now.",
  },
  {
    key: "accepted",
    title: "Scheduled",
    icon: IconClockFilled,
    accent: "text-green-600",
    emptyLabel: "Nothing scheduled yet.",
  },
  {
    key: "posted",
    title: "Posted",
    icon: IconCircleCheckFilled,
    accent: "text-blue-600",
    emptyLabel: "Nothing posted yet.",
  },
]

interface Toast {
  id: number
  message: string
}

export default function App() {
  const { board, error, loading, refreshing, refresh } = useBoard()
  const [columns, setColumns] = useState<Record<string, GroupedPost[]>>({
    drafts: [],
    accepted: [],
    posted: [],
  })
  const [hydrated, setHydrated] = useState(false)
  const [openGroup, setOpenGroup] = useState<GroupedPost | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [keywordsOpen, setKeywordsOpen] = useState(false)
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextToastId = useRef(1)

  // After a user-triggered refresh succeeds, briefly swap the refresh icon
  // for a checkmark. `requestedRef` excludes the initial page load.
  const [justRefreshed, setJustRefreshed] = useState(false)
  const requestedRefresh = useRef(false)
  const awaitingRefreshResult = useRef(false)

  useEffect(() => {
    if (refreshing) {
      setJustRefreshed(false)
      if (requestedRefresh.current) awaitingRefreshResult.current = true
      return
    }
    requestedRefresh.current = false
    if (!awaitingRefreshResult.current) return
    awaitingRefreshResult.current = false
    if (error !== null) return
    setJustRefreshed(true)
    const timer = window.setTimeout(() => setJustRefreshed(false), 1600)
    return () => window.clearTimeout(timer)
  }, [refreshing, error])

  const notify = useCallback((message: string) => {
    const id = nextToastId.current++
    setToasts((prev) => [...prev, { id, message }])
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id))
    }, 5000)
  }, [])

  useEffect(() => {
    if (board && !hydrated) {
      setColumns({
        drafts: groupPosts(board.drafts),
        accepted: groupPosts(board.accepted),
        posted: groupPosts(board.posted),
      })
      setHydrated(true)
    }
  }, [board, hydrated])

  // Keep the open post in sync with fresh board data; close it if the post
  // disappeared (e.g. deleted in Buffer while the modal was open).
  useEffect(() => {
    if (!board || !openGroup || !modalOpen) return
    const all = [
      ...groupPosts(board.drafts),
      ...groupPosts(board.accepted),
      ...groupPosts(board.posted),
    ]
    const fresh = all.find((g) => g.key === openGroup.key)
    if (fresh) {
      setOpenGroup(fresh)
    } else {
      setOpenGroup(null)
      setModalOpen(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [board])

  const handleOpen = (group: GroupedPost) => {
    setOpenGroup(group)
    setModalOpen(true)
  }

  const handleAccepted = () => {
    setHydrated(false)
    setModalOpen(false)
    setOpenGroup(null)
    refresh()
  }

  const handleChange = () => {
    setHydrated(false)
    refresh()
  }

  // Nothing on screen yet: the first fetch is in flight, so every column shows
  // cards taking shape. Background refreshes keep the real cards and dim them.
  const showSkeletons = board === null && error === null

  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col gap-10 p-6 py-16">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            {board?.title ?? "Content Board"}
            {MOCK && (
              <span
                className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-semibold text-amber-600"
                title="In-memory mock data — run `npm run dev` for the real backend"
              >
                mock data
              </span>
            )}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            onPress={() => setKeywordsOpen(true)}
          >
            <IconTags />
            Keywords
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onPress={() => {
              requestedRefresh.current = true
              refresh()
            }}
            isDisabled={loading}
          >
            Refresh
            <span className="relative flex size-4 items-center justify-center">
              <IconRefresh
                className={cn(
                  "absolute transition-all duration-300",
                  !justRefreshed && "opacity-100",
                  refreshing && "animate-spin",
                  justRefreshed && "scale-50 opacity-0",
                )}
              />
              <IconCheck
                className={cn(
                  "absolute scale-50 opacity-0 transition-all duration-300",
                  justRefreshed && "scale-100 opacity-100",
                )}
              />
            </span>
          </Button>
        </div>
      </header>

      {!board && error ? (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <p className="text-fg-muted">Unable to load the content board.</p>
          <p className="text-fg-danger text-sm">{error}</p>
          <Button variant="secondary" size="sm" onPress={() => refresh()}>
            <IconRefresh />
            Retry
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {/* A failed background refresh keeps the stale board on screen. */}
          {board && error && (
            <p className="text-fg-danger text-sm">Couldn’t refresh: {error}</p>
          )}
          <Kanban
            value={columns}
            onValueChange={setColumns}
            getItemValue={(group) => group.key}
            disabled
          >
            <KanbanBoard
              className={cn(
                "grid-cols-1 md:grid-cols-3",
                refreshing &&
                  !showSkeletons &&
                  "opacity-70 transition-opacity duration-200",
              )}
            >
              {COLUMNS.map((col) => (
                <BoardColumn
                  key={col.key}
                  title={col.title}
                  icon={col.icon}
                  accent={col.accent}
                  columnValue={col.key}
                  groups={columns[col.key] ?? []}
                  channels={board?.channels ?? []}
                  emptyLabel={col.emptyLabel}
                  onOpen={handleOpen}
                  loading={showSkeletons}
                />
              ))}
            </KanbanBoard>
          </Kanban>
        </div>
      )}

      <PostModal
        group={openGroup}
        channels={board?.channels ?? []}
        open={modalOpen}
        onOpenChange={setModalOpen}
        onAccepted={handleAccepted}
        onChanged={handleChange}
        notify={notify}
      />

      <KeywordsModal open={keywordsOpen} onOpenChange={setKeywordsOpen} notify={notify} />

      <div className="pointer-events-none fixed bottom-6 left-1/2 z-[60] flex -translate-x-1/2 flex-col items-center gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-fg-on-primary shadow-lg"
          >
            {toast.message}
          </div>
        ))}
      </div>
    </main>
  )
}
