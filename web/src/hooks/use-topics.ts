import { useCallback, useEffect, useState } from "react"

import { topicsApi, friendlyError } from "@/lib/api"
import type { Topic } from "@/types"

export type TopicFilter = "unused" | "used" | "all"

/**
 * All state and mutations behind the topics modal: the topic list, the
 * add/reset/delete flows, and the filter/search-derived visible rows.
 */
export function useTopics(open: boolean, notify: (message: string) => void) {
  const [topics, setTopics] = useState<Topic[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [newTopic, setNewTopic] = useState("")
  const [adding, setAdding] = useState(false)
  const [filter, setFilter] = useState<TopicFilter>("unused")
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

  const pending = adding || busyId !== null || resettingAll

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
  const byFilter =
    topics === null ? [] : filter === "all" ? topics : filter === "unused" ? unused : used
  const visible = byFilter.filter((topic) =>
    topic.topic.toLowerCase().includes(searched),
  )

  const counts: Record<TopicFilter, number> = {
    unused: unused.length,
    used: used.length,
    all: topics?.length ?? 0,
  }

  return {
    topics,
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
    unused,
    used,
    visible,
    counts,
    pending,
  }
}
