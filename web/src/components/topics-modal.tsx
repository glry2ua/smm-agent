import { IconArrowBackUp, IconPlus, IconSearch, IconX } from "@tabler/icons-react"

import { TopicRow } from "@/components/topic-row"
import { useToast } from "@/components/toast"
import { Button } from "@/ui/button"
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog"
import { Modal } from "@/ui/modal"
import { Skeleton } from "@/ui/skeleton"
import { Input, InputGroup, InputGroupAddon } from "@/ui/input"
import { cn } from "@/lib/utils"
import { useTopics } from "@/hooks/use-topics"

/**
 * Manage the D1 topics table: add new topics and free up used ones so the
 * weekly job can pick them again. Opened from the board header.
 */
export function TopicsModal({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const notify = useToast()
  const topics = useTopics(open, notify)
  const {
    topics: rows,
    error,
    loading,
    newTopic,
    setNewTopic,
    adding,
    filter,
    setFilter,
    query,
    setQuery,
    searched,
    busyId,
    resettingAll,
    confirmDeleteId,
    setConfirmDeleteId,
    add,
    resetOne,
    resetAll,
    remove,
    used,
    visible,
    counts,
    pending,
  } = topics

  const emptyLabel = searched
    ? `No topics match “${query.trim()}”.`
    : filter === "unused"
      ? "No available topics — give a used one another run, or add new ones."
      : filter === "used"
        ? "No topics have been used yet."
        : "No topics yet. Add your first one above."

  return (
    <Dialog isOpen={open} onOpenChange={onOpenChange}>
      <Modal className="sm:max-w-3xl">
        <DialogContent showCloseButton className="gap-5 p-6">
          <DialogHeader>
            <DialogTitle>Topics</DialogTitle>
            <DialogDescription>
              Topics the weekly job picks posts from. Add new ones, or give used
              topics another run.
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="gap-4">
            <InputGroup>
              <Input
                placeholder="New topic, e.g. “Willow Glen market update”"
                value={newTopic}
                onChange={(event) => setNewTopic(event.target.value)}
                disabled={adding}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && newTopic.trim() && !adding) void add()
                }}
                aria-label="New topic"
              />
              <InputGroupAddon>
                <Button
                  variant="primary"
                  onPress={() => void add()}
                  isDisabled={adding || !newTopic.trim()}
                  isPending={adding}
                >
                  <IconPlus />
                  Add
                </Button>
              </InputGroupAddon>
            </InputGroup>

            <div className="flex items-center justify-between gap-2">
              <div className="flex gap-1.5">
                {(["unused", "used", "all"] as const).map((key) => (
                  <Button
                    key={key}
                    variant={filter === key ? "primary" : "quiet"}
                    size="xs"
                    onPress={() => setFilter(key)}
                    aria-pressed={filter === key}
                  >
                    {key === "unused" ? "Available" : key === "used" ? "Used" : "All"} (
                    {counts[key]})
                  </Button>
                ))}
              </div>
              {/* Only meaningful on the Used tab, but kept in the layout on the
                  other tabs — removing it would shift the pills row. */}
              <Button
                variant="secondary"
                size="xs"
                className={cn(filter !== "used" && "invisible")}
                onPress={() => void resetAll()}
                isDisabled={pending || used.length === 0}
                isPending={resettingAll}
              >
                <IconArrowBackUp />
                Use all again
              </Button>
            </div>

            {/* Always rendered at a fixed height: the modal keeps one stable
                size whether or not a search is active. */}
            <InputGroup>
              <InputGroupAddon>
                <IconSearch />
              </InputGroupAddon>
              <Input
                placeholder="Search topics"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                aria-label="Search topics"
              />
              {query !== "" && (
                <InputGroupAddon>
                  <Button
                    variant="quiet"
                    size="sm"
                    isIconOnly
                    onPress={() => setQuery("")}
                    aria-label="Clear search"
                  >
                    <IconX className="size-4" />
                  </Button>
                </InputGroupAddon>
              )}
            </InputGroup>

            {error && (
              <div className="bg-danger-muted text-fg-danger rounded-md px-3 py-2 text-sm">
                {error}
              </div>
            )}

            {/* Fixed height with its own scrollbar: the modal keeps one stable
                size across loading, empty, and filtered states. */}
            <div className="border-border bg-muted/30 h-96 overflow-y-auto rounded-lg border p-2">
              {rows === null && loading ? (
                <div className="flex h-full flex-col gap-1.5">
                  {Array.from({ length: 8 }, (_, i) => (
                    <Skeleton key={i} className="flex-1 rounded-md" />
                  ))}
                </div>
              ) : visible.length === 0 ? (
                <div className="flex h-full items-center justify-center">
                  <p className="text-fg-muted text-sm">{emptyLabel}</p>
                </div>
              ) : (
                <ul className="flex flex-col gap-1.5">
                  {visible.map((topic) => (
                    <TopicRow
                      key={topic.id}
                      topic={topic}
                      busyId={busyId}
                      pending={pending}
                      confirmingDelete={confirmDeleteId === topic.id}
                      onConfirmDelete={() => setConfirmDeleteId(topic.id)}
                      onCancelDelete={() => setConfirmDeleteId(null)}
                      onDelete={() => void remove(topic)}
                      onReset={() => void resetOne(topic)}
                    />
                  ))}
                </ul>
              )}
            </div>
          </DialogBody>
        </DialogContent>
      </Modal>
    </Dialog>
  )
}
