import { useCallback, useEffect, useRef, useState } from "react"
import { CircleCheck, PenLine, RefreshCw, type LucideIcon } from "lucide-react"

import { BoardColumn } from "@/components/board-column"
import { PostModal } from "@/components/post-modal"
import { Kanban, KanbanBoard } from "@/components/ui/kanban"
import { useBoard } from "@/hooks/use-board"
import { groupPosts } from "@/lib/grouping"
import { Button } from "@/ui/button"
import { Skeleton } from "@/ui/skeleton"
import { cn } from "@/lib/utils"
import type { GroupedPost } from "@/types"

/** Lucide icons are stroke-only; `fill` paints the enclosed paths solid. */
function filled(Icon: LucideIcon) {
  return function FilledIcon({ className }: { className?: string }) {
    return <Icon className={className} fill="currentColor" />
  }
}

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
    icon: filled(PenLine),
    accent: "text-orange-600",
    emptyLabel: "No drafts right now.",
  },
  {
    key: "accepted",
    title: "Accepted",
    icon: filled(CircleCheck),
    accent: "text-green-600",
    emptyLabel: "No accepted posts yet.",
  },
]

function formatFetchedAt(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

interface Toast {
  id: number
  message: string
}

export default function App() {
  const { board, error, loading, refreshing, refresh } = useBoard()
  const [columns, setColumns] = useState<Record<string, GroupedPost[]>>({
    drafts: [],
    accepted: [],
  })
  const [hydrated, setHydrated] = useState(false)
  const [openGroup, setOpenGroup] = useState<GroupedPost | null>(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextToastId = useRef(1)

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
      })
      setHydrated(true)
    }
  }, [board, hydrated])

  // Keep the open post in sync with fresh board data; close it if the post
  // disappeared (e.g. deleted in Buffer while the modal was open).
  useEffect(() => {
    if (!board || !openGroup || !modalOpen) return
    const all = [...groupPosts(board.drafts), ...groupPosts(board.accepted)]
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
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 p-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Content Board</h1>
          {board ? (
            <p className="text-fg-muted text-sm">
              Last updated {formatFetchedAt(board.fetched_at)}
            </p>
          ) : showSkeletons ? (
            <Skeleton className="mt-1.5 h-4 w-52" />
          ) : null}
        </div>
        <Button
          variant="secondary"
          size="sm"
          onPress={() => refresh()}
          isDisabled={loading}
        >
          <RefreshCw className={cn(refreshing && "animate-spin")} />
          Refresh
        </Button>
      </header>

      {!board && error ? (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <p className="text-fg-muted">Unable to load the content board.</p>
          <p className="text-fg-danger text-sm">{error}</p>
          <Button variant="secondary" size="sm" onPress={() => refresh()}>
            <RefreshCw />
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
                "grid-cols-1 md:grid-cols-2",
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