import { SkeletonImage } from "@/components/skeleton-image"
import { Skeleton } from "@/ui/skeleton"
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
    day: "numeric"
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
      className="overflow-hidden p-0 flex flex-col justify-between items-stretch"
      onClick={() => onOpen(group)}
    >
      <div className="flex min-h-40">
        {imageUrl && (
          <SkeletonImage
            src={imageUrl}
            alt=""
            className="h-40 m-0.5 shrink-0 rounded-md overflow-hidden"
            imgClassName="h-full w-full object-contain"
            loading="lazy"
          />
        )}
        <div className="flex min-w-0 flex-1 flex-col gap-1 py-2 px-2">
          <p className="line-clamp-7 text-xs font-medium whitespace-pre-line">
            {first.text}
          </p>
          <div className="mt-auto flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              {services.map((service) => (
                <PlatformIcon key={service} service={service} className="size-4" />
              ))}
            </div>
            {due && (
              <time className="text-xs font-medium text-fg-muted tabular-nums">
                {due}
              </time>
            )}
          </div>
        </div>
      </div>
    </KanbanItem>
  )
}


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
  icon,
  accent,
  groups,
  channels,
  emptyLabel,
  onOpen,
  loading = false,
  skeletonCards = 2,
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
  skeletonCards?: number
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
            {Array.from({ length: skeletonCards }, (_, i) => (
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
