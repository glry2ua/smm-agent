import { Button } from "@/components/ui/button"
import { Dialog } from "@/components/ui/dialog"
import { PlatformIcon } from "@/components/ui/platform-icon"
import type { BoardChannel, GroupedPost } from "@/types"

function channelFor(
  post: { channel_id: string },
  channels: BoardChannel[],
): BoardChannel | undefined {
  return channels.find((channel) => channel.id === post.channel_id)
}

function formatDueAt(dueAt: string | null): string {
  if (!dueAt) return ""
  const date = new Date(dueAt)
  if (Number.isNaN(date.getTime())) return ""
  return date.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })
}

export function PostModal({
  group,
  channels,
  open,
  onOpenChange,
  onAccept,
  onEdit,
  onDelete,
}: {
  group: GroupedPost | null
  channels: BoardChannel[]
  open: boolean
  onOpenChange: (open: boolean) => void
  onAccept: (group: GroupedPost) => void
  onEdit: (group: GroupedPost) => void
  onDelete: (group: GroupedPost) => void
}) {
  if (!group) return null
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
    <Dialog open={open} onOpenChange={onOpenChange} className="max-w-3xl">
      <div className="flex">
        {imageUrl && (
          <div className="bg-muted/40 shrink-0 border-r">
            <img
              src={imageUrl}
              alt=""
              className="h-full max-h-[60vh] w-72 object-contain"
            />
          </div>
        )}
        <div className="flex min-w-0 flex-1 flex-col gap-4 p-5">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              {services.map((service) => (
                <PlatformIcon key={service} service={service} className="size-5" />
              ))}
            </div>
            {due && (
              <time className="text-base font-semibold tabular-nums">{due}</time>
            )}
          </div>
          <p className="text-sm whitespace-pre-line leading-relaxed">
            {first.text}
          </p>
          <div className="mt-auto flex items-center justify-end gap-2 pt-2">
            <Button variant="outline" size="sm" onClick={() => onDelete(group)}>
              Delete
            </Button>
            <Button variant="outline" size="sm" onClick={() => onEdit(group)}>
              Edit
            </Button>
            <Button size="sm" onClick={() => onAccept(group)}>
              Accept
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  )
}