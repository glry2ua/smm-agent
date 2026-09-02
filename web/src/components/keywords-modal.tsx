import { useCallback, useEffect, useState } from "react"

import {
  IconArrowBackUp,
  IconPlus,
} from "@tabler/icons-react"

import { Button } from "@/ui/button"
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/ui/dialog"
import { Modal } from "@/ui/modal"
import { Skeleton } from "@/ui/skeleton"
import { keywordsApi, friendlyError } from "@/lib/api"
import { cn } from "@/lib/utils"
import type { Keyword } from "@/types"

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
 * Manage the D1 keywords table: add new topics and free up used ones so the
 * weekly job can pick them again. Opened from the board header.
 */
export function KeywordsModal({
  open,
  onOpenChange,
  notify,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  notify: (message: string) => void
}) {
  const [keywords, setKeywords] = useState<Keyword[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [newTopic, setNewTopic] = useState("")
  const [adding, setAdding] = useState(false)
  const [filter, setFilter] = useState<Filter>("unused")
  const [busyId, setBusyId] = useState<number | null>(null)
  const [resettingAll, setResettingAll] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await keywordsApi.listKeywords()
      setKeywords(data.keywords)
    } catch (err) {
      setError(friendlyError(err))
    } finally {
      setLoading(false)
    }
  }, [])

  // Fresh list on every open: keywords change from the weekly job too.
  useEffect(() => {
    if (open) void load()
  }, [open, load])

  const add = async () => {
    const topic = newTopic.trim()
    if (!topic || adding) return
    setAdding(true)
    setError(null)
    try {
      await keywordsApi.addKeyword(topic)
      setNewTopic("")
      await load()
      notify("Keyword added")
    } catch (err) {
      setError(friendlyError(err))
    } finally {
      setAdding(false)
    }
  }

  const resetOne = async (keyword: Keyword) => {
    if (busyId !== null || resettingAll) return
    setBusyId(keyword.id)
    setError(null)
    try {
      await keywordsApi.resetKeywords([keyword.id])
      await load()
      notify("Keyword is available to use again")
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
      const result = await keywordsApi.resetKeywords([])
      await load()
      notify(
        result.reset === 1
          ? "Keyword is available to use again"
          : `${result.reset} keywords are available to use again`,
      )
    } catch (err) {
      setError(friendlyError(err))
    } finally {
      setResettingAll(false)
    }
  }

  const unused = keywords?.filter((k) => k.used_at === null) ?? []
  const used = keywords?.filter((k) => k.used_at !== null) ?? []
  const visible =
    keywords === null ? [] : filter === "all" ? keywords : filter === "unused" ? unused : used

  const counts: Record<Filter, number> = {
    unused: unused.length,
    used: used.length,
    all: keywords?.length ?? 0,
  }
  const pending = adding || busyId !== null || resettingAll

  const emptyLabel =
    filter === "unused"
      ? "No available keywords — give a used one another run, or add new ones."
      : filter === "used"
        ? "No keywords have been used yet."
        : "No keywords yet. Add your first one above."

  return (
    <Dialog isOpen={open} onOpenChange={onOpenChange}>
      <Modal className="sm:max-w-3xl">
        <DialogContent className="gap-5 p-6">
          <DialogHeader>
            <DialogTitle>Keywords</DialogTitle>
            <DialogDescription>
              Topics the weekly job picks posts from. Add new ones, or give used
              topics another run.
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="gap-4">
            <div className="flex items-center gap-2">
              <input
                className="border-border-control bg-bg h-9 min-w-0 flex-1 rounded-md border px-3 text-sm focus:outline-none"
                placeholder="New keyword or topic, e.g. “Willow Glen market update”"
                value={newTopic}
                onChange={(event) => setNewTopic(event.target.value)}
                disabled={adding}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && newTopic.trim() && !adding) void add()
                }}
              />
              <Button
                className="h-9 px-4"
                onPress={() => void add()}
                isDisabled={adding || !newTopic.trim()}
                isPending={adding}
              >
                <IconPlus />
                Add
              </Button>
            </div>

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
                  others — removing it would shift the pills row. */}
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

            {error && (
              <div className="bg-danger-muted text-fg-danger rounded-md px-3 py-2 text-sm">
                {error}
              </div>
            )}

            {/* Fixed height with its own scrollbar: the modal keeps one stable
                size across loading, empty, and filtered states. */}
            <div className="border-border bg-muted/30 h-96 overflow-y-auto rounded-lg border p-2">
              {keywords === null && loading ? (
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
                  {visible.map((keyword) => (
                    <li
                      key={keyword.id}
                      className="border-border bg-bg flex items-center gap-3 rounded-md border px-3 py-2"
                    >
                      <span
                        className={cn(
                          "min-w-0 flex-1 text-sm break-words",
                          keyword.used_at && "text-fg-muted",
                        )}
                      >
                        {keyword.topic}
                      </span>
                      {keyword.used_at ? (
                        <>
                          <span className="text-fg-muted whitespace-nowrap text-xs">
                            Used {formatUsedAt(keyword.used_at)}
                          </span>
                          <Button
                            variant="secondary"
                            size="xs"
                            onPress={() => void resetOne(keyword)}
                            isDisabled={pending && busyId !== keyword.id}
                            isPending={busyId === keyword.id}
                            aria-label="Use this keyword again in the weekly job"
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
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </DialogBody>
          <DialogFooter>
            <Button className="px-4" onPress={() => onOpenChange(false)}>
              Done
            </Button>
          </DialogFooter>
        </DialogContent>
      </Modal>
    </Dialog>
  )
}
