import { IconArrowBackUp, IconTrash } from "@tabler/icons-react"

import { Button } from "@/ui/button"
import { formatUsedAt } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { Topic } from "@/types"

/** One row of the topics list: used/available state and the delete confirm. */
export function TopicRow({
  topic,
  busyId,
  pending,
  confirmingDelete,
  onConfirmDelete,
  onCancelDelete,
  onDelete,
  onReset,
}: {
  topic: Topic
  busyId: number | null
  pending: boolean
  confirmingDelete: boolean
  onConfirmDelete: () => void
  onCancelDelete: () => void
  onDelete: () => void
  onReset: () => void
}) {
  return (
    <li className="border-border bg-bg flex items-center gap-3 rounded-md border px-3 py-2">
      <span
        className={cn(
          "min-w-0 flex-1 text-sm break-words",
          topic.used_at && "text-fg-muted",
        )}
      >
        {topic.topic}
      </span>
      {confirmingDelete ? (
        <>
          <span className="text-fg-danger text-xs font-medium whitespace-nowrap">
            Delete this topic?
          </span>
          <Button
            variant="secondary"
            size="xs"
            onPress={onCancelDelete}
            isDisabled={busyId !== null}
          >
            Keep
          </Button>
          <Button
            variant="danger"
            size="xs"
            onPress={onDelete}
            isDisabled={busyId !== null}
            isPending={busyId === topic.id}
          >
            Delete
          </Button>
        </>
      ) : (
        <>
          {topic.used_at ? (
            <>
              <span className="text-fg-muted whitespace-nowrap text-xs">
                Used {formatUsedAt(topic.used_at)}
              </span>
              <Button
                variant="secondary"
                size="xs"
                onPress={onReset}
                isDisabled={pending && busyId !== topic.id}
                isPending={busyId === topic.id}
                aria-label="Use this topic again in the weekly job"
              >
                <IconArrowBackUp />
                Use again
              </Button>
            </>
          ) : (
            <span className="rounded-full bg-green-600/15 px-2 py-0.5 text-xs font-semibold whitespace-nowrap text-green-600">
              Available
            </span>
          )}
          <Button
            variant="quiet"
            size="sm"
            isIconOnly
            className="text-fg-muted hover:bg-transparent hover:text-fg-danger pressed:bg-transparent"
            onPress={onConfirmDelete}
            isDisabled={busyId !== null}
            aria-label="Delete this topic"
          >
            <IconTrash className="size-4" />
          </Button>
        </>
      )}
    </li>
  )
}
