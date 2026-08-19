import { useEffect, useState } from "react"
import { RefreshCw } from "lucide-react"

import { BoardColumn } from "@/components/board-column"
import { PostModal } from "@/components/post-modal"
import { Button } from "@/components/ui/button"
import { Kanban, KanbanBoard } from "@/components/ui/kanban"
import { Skeleton } from "@/components/ui/skeleton"
import { useBoard } from "@/hooks/use-board"
import { groupPosts } from "@/lib/grouping"
import type { GroupedPost } from "@/types"

const COLUMNS: { key: string; title: string; emptyLabel: string }[] = [
  { key: "drafts", title: "Drafts", emptyLabel: "No drafts right now." },
  { key: "accepted", title: "Accepted", emptyLabel: "No accepted posts yet." },
]

function formatFetchedAt(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function BoardSkeleton() {
  return (
    <div className="grid auto-rows-fr grid-cols-1 gap-4 md:grid-cols-2">
      {COLUMNS.map((col) => (
        <div key={col.key} className="flex flex-col gap-2.5">
          <Skeleton className="h-5 w-32" />
          {[0, 1].map((i) => (
            <Skeleton key={i} className="h-44 w-full" />
          ))}
        </div>
      ))}
    </div>
  )
}

export default function App() {
  const { board, error, loading } = useBoard()
  const [columns, setColumns] = useState<Record<string, GroupedPost[]>>({
    drafts: [],
    accepted: [],
  })
  const [hydrated, setHydrated] = useState(false)
  const [openGroup, setOpenGroup] = useState<GroupedPost | null>(null)
  const [modalOpen, setModalOpen] = useState(false)

  useEffect(() => {
    if (board && !hydrated) {
      setColumns({
        drafts: groupPosts(board.drafts),
        accepted: groupPosts(board.accepted),
      })
      setHydrated(true)
    }
  }, [board, hydrated])

  const handleOpen = (group: GroupedPost) => {
    setOpenGroup(group)
    setModalOpen(true)
  }

  const removeGroupFromColumns = (group: GroupedPost) => {
    setColumns((prev) => {
      const next: Record<string, GroupedPost[]> = {}
      for (const [col, groups] of Object.entries(prev)) {
        next[col] = groups.filter((g) => g.key !== group.key)
      }
      return next
    })
  }

  const handleAccept = (_group: GroupedPost) => {
    // UI-only for now; wiring to Buffer comes later.
    setModalOpen(false)
  }
  const handleEdit = (_group: GroupedPost) => {
    // UI-only for now; wiring to Buffer comes later.
    setModalOpen(false)
  }
  const handleDelete = (group: GroupedPost) => {
    removeGroupFromColumns(group)
    setModalOpen(false)
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-6xl flex-col gap-6 p-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Content Board</h1>
          {board && (
            <p className="text-muted-foreground text-sm">
              Last updated {formatFetchedAt(board.fetched_at)}
            </p>
          )}
        </div>
        <Button variant="outline" size="sm" onClick={() => window.location.reload()}>
          <RefreshCw />
          Refresh
        </Button>
      </header>

      {loading && <BoardSkeleton />}

      {!loading && error && (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <p className="text-muted-foreground">Unable to load the content board.</p>
          <p className="text-destructive text-sm">{error}</p>
          <Button variant="outline" size="sm" onClick={() => window.location.reload()}>
            <RefreshCw />
            Retry
          </Button>
        </div>
      )}

      {!loading && !error && board && (
        <Kanban
          value={columns}
          onValueChange={setColumns}
          getItemValue={(group) => group.key}
        >
          <KanbanBoard className="grid-cols-1 md:grid-cols-2">
            {COLUMNS.map((col) => (
              <BoardColumn
                key={col.key}
                title={col.title}
                columnValue={col.key}
                groups={columns[col.key] ?? []}
                channels={board.channels}
                emptyLabel={col.emptyLabel}
                onOpen={handleOpen}
              />
            ))}
          </KanbanBoard>
        </Kanban>
      )}

      <PostModal
        group={openGroup}
        channels={board?.channels ?? []}
        open={modalOpen}
        onOpenChange={setModalOpen}
        onAccept={handleAccept}
        onEdit={handleEdit}
        onDelete={handleDelete}
      />
    </main>
  )
}