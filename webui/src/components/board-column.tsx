import {
  KanbanColumn,
  KanbanColumnContent,
  KanbanColumnHeader,
  KanbanItem,
} from "@/components/ui/kanban"
import { PlatformIcon } from "@/components/ui/platform-icon"
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
        <div className="mx-auto w-24 overflow-hidden rounded-md p-2">
          <img
            src={imageUrl}
            alt=""
            className="aspect-square w-full object-cover"
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

export function BoardColumn({
  title,
  columnValue,
  groups,
  channels,
  emptyLabel,
  onOpen,
}: {
  title: string
  columnValue: string
  groups: GroupedPost[]
  channels: BoardChannel[]
  emptyLabel: string
  onOpen: (group: GroupedPost) => void
}) {
  return (
    <KanbanColumn value={columnValue}>
      <KanbanColumnHeader title={title} count={groups.length} />
      <KanbanColumnContent>
        {groups.length === 0 ? (
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