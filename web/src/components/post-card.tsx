import { SkeletonImage } from "@/components/skeleton-image"
import { KanbanItem } from "@/components/ui/kanban"
import { PlatformIcon } from "@/components/ui/platform-icon"
import { firstImage, groupServices } from "@/lib/channels"
import { formatDueDay } from "@/lib/format"
import type { BoardChannel, GroupedPost } from "@/types"

export function PostCard({
  group,
  channels,
  onOpen,
}: {
  group: GroupedPost
  channels: BoardChannel[]
  onOpen: (group: GroupedPost) => void
}) {
  const first = group.posts[0]
  const imageUrl = firstImage(first)
  const due = formatDueDay(first.due_at)
  const services = groupServices(group, channels)

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
            className="h-42 w-32 m-0.5 shrink-0 rounded-md overflow-hidden"
            imgClassName="h-full w-full object-cover"
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
