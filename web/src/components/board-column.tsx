import { PostCard } from "@/components/post-card"
import { Skeleton } from "@/ui/skeleton"
import {
  KanbanColumn,
  KanbanColumnContent,
  KanbanColumnHeader,
} from "@/components/ui/kanban"
import type { BoardChannel, GroupedPost } from "@/types"

function PostCardSkeleton({ withImage = true }: { withImage?: boolean }) {
  return (
    <div className="flex flex-col overflow-hidden rounded-lg border bg-card shadow-sm/5">
      <div className="flex min-h-40">
        {withImage && (
          <Skeleton className="m-0.5 h-40 w-40 shrink-0 rounded-md" />
        )}
        <div className="flex min-w-0 flex-1 flex-col gap-1 px-2 py-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-11/12" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-9/12" />
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-4 w-1/3" />
          <div className="mt-auto flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Skeleton className="size-4 rounded-sm" />
              <Skeleton className="size-4 rounded-sm" />
            </div>
            <Skeleton className="h-4 w-12" />
          </div>
        </div>
      </div>
    </div>
  )
}

export function BoardColumn({
  title,
  columnValue,
  icon,
  accent,
  groups,
  channels,
  emptyLabel,
  onOpen,
  loading = false,
}: {
  title: string
  columnValue: string
  icon: React.ComponentType<{ className?: string }>
  accent: string
  groups: GroupedPost[]
  channels: BoardChannel[]
  emptyLabel: string
  onOpen: (group: GroupedPost) => void
  /** Render placeholder cards instead of the (empty) real ones. */
  loading?: boolean
}) {
  return (
    <KanbanColumn value={columnValue}>
      <KanbanColumnHeader
        title={title}
        icon={icon}
        accent={accent}
        count={loading ? null : groups.length}
      />
      <KanbanColumnContent aria-busy={loading || undefined}>
        {loading ? (
          <>
            <span className="sr-only">Loading {title.toLowerCase()}…</span>
            {Array.from({ length: 2 }, (_, i) => (
              <PostCardSkeleton key={i} withImage={i % 2 === 0} />
            ))}
          </>
        ) : groups.length === 0 ? (
          <p className="text-fg-muted px-2 py-3 text-sm">{emptyLabel}</p>
        ) : (
          groups.map((group) => (
            <PostCard
              key={group.key}
              group={group}
              channels={channels}
              onOpen={onOpen}
            />
          ))
        )}
      </KanbanColumnContent>
    </KanbanColumn>
  )
}
