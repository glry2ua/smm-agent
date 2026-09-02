import { useCallback, useEffect, useState } from "react"

import {
  IconArrowBackUp,
  IconPlus,
  IconSearch,
  IconTrash,
  IconX,
} from "@tabler/icons-react"

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
import { topicsApi, friendlyError } from "@/lib/api"
import { cn } from "@/lib/utils"
import type { Topic } from "@/types"

type Filter = "unused" | "used" | "all"

function formatUsedAt(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "used"
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  })
}

/**
 * Manage the D1 topics table: add new topics and free up used ones so the
 * weekly job can pick them again. Opened from the board header.
 */
export function TopicsModal({
  open,
  onOpenChange,
  notify,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  notify: (message: string) => void
}) {
  const [topics, setTopics] = useState<Topic[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [newTopic, setNewTopic] = useState("")
  const [adding, setAdding] = useState(false)
  const [filter, setFilter] = useState<Filter>("unused")
  const [query, setQuery] = useState("")
  const [busyId, setBusyId] = useState<number | null>(null)
  const [resettingAll, setResettingAll] = useState(false)
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await topicsApi.listTopics()
      setTopics(data.topics)
    } catch (err) {
      setError(friendlyError(err))
    } finally {
      setLoading(false)
    }
  }, [])

  // Fresh list and a cleared search on every open: topics change from the
  // weekly job too, and a stale search would hide them.
  useEffect(() => {
    if (open) {
      setQuery("")
      void load()
    }
  }, [open, load])

  const add = async () => {
    const topic = newTopic.trim()
    if (!topic || adding) return
    setAdding(true)
    setError(null)
    try {
      await topicsApi.addTopic(topic)
      setNewTopic("")
      await load()
      notify("Topic added")
    } catch (err) {
      setError(friendlyError(err))
    } finally {
      setAdding(false)
    }
  }

  const resetOne = async (topic: Topic) => {
    if (busyId !== null || resettingAll) return
    setBusyId(topic.id)
    setError(null)
    try {
      await topicsApi.resetTopics([topic.id])
      await load()
      notify("Topic is available to use again")
    } catch (err) {
      setError(friendlyError(err))
    } finally {
      setBusyId(null)
    }
  }

  const resetAll = async () => {
    if (busyId !== null || resettingAll) return
    setResettingAll(true)
    setError(null)
    try {
      const result = await topicsApi.resetTopics([])
      await load()
      notify(
        result.reset === 1
          ? "Topic is available to use again"
          : `${result.reset} topics are available to use again`,
      )
    } catch (err) {
      setError(friendlyError(err))
    } finally {
      setResettingAll(false)
    }
  }

  const remove = async (topic: Topic) => {
    if (pending) return
    setBusyId(topic.id)
    setError(null)
    try {
      await topicsApi.deleteTopic(topic.id)
      await load()
      notify("Topic deleted")
    } catch (err) {
      setError(friendlyError(err))
    } finally {
      setBusyId(null)
      setConfirmDeleteId(null)
    }
  }

  const unused = topics?.filter((t) => t.used_at === null) ?? []
  const used = topics?.filter((t) => t.used_at !== null) ?? []
  const searched = query.trim().toLowerCase()
  const matchesQuery = (topic: Topic) => topic.topic.toLowerCase().includes(searched)
  const byFilter =
    topics === null ? [] : filter === "all" ? topics : filter === "unused" ? unused : used
  const visible = byFilter.filter(matchesQuery)

  const counts: Record<Filter, number> = {
    unused: unused.length,
    used: used.length,
    all: topics?.length ?? 0,
  }
  const pending = adding || busyId !== null || resettingAll

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
              {topics === null && loading ? (
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
                    <li
                      key={topic.id}
                      className="border-border bg-bg flex items-center gap-3 rounded-md border px-3 py-2"
                    >
                      <span
                        className={cn(
                          "min-w-0 flex-1 text-sm break-words",
                          topic.used_at && "text-fg-muted",
                        )}
                      >
                        {topic.topic}
                      </span>
                      {confirmDeleteId === topic.id ? (
                        <>
                          <span className="text-fg-danger text-xs font-medium whitespace-nowrap">
                            Delete this topic?
                          </span>
                          <Button
                            variant="secondary"
                            size="xs"
                            onPress={() => setConfirmDeleteId(null)}
                            isDisabled={busyId !== null}
                          >
                            Keep
                          </Button>
                          <Button
                            variant="danger"
                            size="xs"
                            onPress={() => void remove(topic)}
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
                                onPress={() => void resetOne(topic)}
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
                            onPress={() => setConfirmDeleteId(topic.id)}
                            isDisabled={busyId !== null}
                            aria-label="Delete this topic"
                          >
                            <IconTrash className="size-4" />
                          </Button>
                        </>
                      )}
                    </li>
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