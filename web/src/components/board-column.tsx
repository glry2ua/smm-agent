import { SkeletonImage } from "@/components/skeleton-image"
import { Skeleton } from "@/components/ui/skeleton"
import {
  KanbanColumn,
  KanbanColumnContent,
  KanbanColumnHeader,
  KanbanItem,
} from "@/components/ui/kanban"
import { PlatformIcon } from "@/components/ui/platform-icon"
import { cn } from "@/lib/utils"
import type { BoardChannel, GroupedPost } from "@/types"

function channelFor(
  post: { channel_id: string },
  channels: BoardChannel[],
): BoardChannel | undefined {
  return channels.find((channel) => channel.id === post.channel_id)
}

function formatDueAt(dueAt: string | null): string | null {
  if (!dueAt) return null
  const date = new Date(dueAt)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })
}

function PostCard({
  group,
  channels,
  onOpen,
}: {
  group: GroupedPost
  channels: BoardChannel[]
  onOpen: (group: GroupedPost) => void
}) {
  const first = group.posts[0]
  const asset = first.assets.find((a) => a.thumbnail || a.source)
  const imageUrl = asset?.thumbnail || asset?.source || null
  const due = formatDueAt(first.due_at)
  const services = Array.from(
    new Set(
      group.posts
        .map((p) => channelFor(p, channels)?.service)
        .filter((s): s is string => Boolean(s)),
    ),
  )

  return (
    <KanbanItem
      value={group.key}
      className="overflow-hidden p-0"
      onClick={() => onOpen(group)}
    >
      {imageUrl && (
        <div className="mx-auto w-24 p-2">
          <SkeletonImage
            src={imageUrl}
            alt=""
            imgClassName="aspect-square w-full object-cover"
            loading="lazy"
          />
        </div>
      )}
      <div className="flex flex-col gap-1 p-2">
        <p className="line-clamp-2 text-[11px] font-medium whitespace-pre-line">
          {first.text}
        </p>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1">
            {services.map((service) => (
              <PlatformIcon key={service} service={service} className="size-3" />
            ))}
          </div>
          {due && (
            <time className="text-[10px] font-semibold tabular-nums">
              {due}
            </time>
          )}
        </div>
      </div>
    </KanbanItem>
  )
}

/**
 * Placeholder that mirrors PostCard's real geometry (same card shell, same
 * 96px thumbnail box, same two clamped text lines, same footer row) so cards
 * swapping in never move the layout.
 */
export function PostCardSkeleton({ withImage = true }: { withImage?: boolean }) {
  return (
    <div className="bg-card overflow-hidden rounded-lg border">
      {withImage && (
        <div className="mx-auto w-24 p-2">
          <Skeleton className="aspect-square w-full" />
        </div>
      )}
      <div className="flex flex-col gap-1 p-2">
        <Skeleton className={cn("h-2.5", withImage ? "w-full" : "w-11/12")} />
        <Skeleton className="h-2.5 w-2/3" />
        <div className="mt-1 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1">
            <Skeleton className="size-3 rounded-full" />
          </div>
          <Skeleton className="h-2.5 w-16" />
        </div>
      </div>
    </div>
  )
}

export function BoardColumn({
  title,
  columnValue,
  groups,
  channels,
  emptyLabel,
  onOpen,
  loading = false,
  skeletonCards = 2,
}: {
  title: string
  columnValue: string
  groups: GroupedPost[]
  channels: BoardChannel[]
  emptyLabel: string
  onOpen: (group: GroupedPost) => void
  /** Render placeholder cards instead of the (empty) real ones. */
  loading?: boolean
  skeletonCards?: number
}) {
  return (
    <KanbanColumn value={columnValue}>
      <KanbanColumnHeader
        title={title}
        count={loading ? null : groups.length}
      />
      <KanbanColumnContent aria-busy={loading || undefined}>
        {loading ? (
          <>
            <span className="sr-only">Loading {title.toLowerCase()}…</span>
            {Array.from({ length: skeletonCards }, (_, i) => (
              <PostCardSkeleton key={i} withImage={i % 2 === 0} />
            ))}
          </>
        ) : groups.length === 0 ? (
          <p className="text-muted-foreground px-1 py-2 text-sm">{emptyLabel}</p>
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