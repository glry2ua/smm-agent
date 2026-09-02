import type { Topic } from "@/types"

/**
 * In-memory mock of the topics API (D1 `topics` table) for UI development
 * (`npm run web-mock`). Mutations evolve the store in place; a page reload
 * resets it. Mirrors the worker: unused topics first, used ones after.
 */

function latency(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 250 + Math.random() * 350))
}

const daysAgo = (days: number) =>
  new Date(Date.now() - days * 24 * 60 * 60_000).toISOString()

let nextId = 1
const mk = (topic: string, usedDaysAgo: number | null): Topic => ({
  id: nextId++,
  topic,
  used_at: usedDaysAgo === null ? null : daysAgo(usedDaysAgo),
})

const topics: Topic[] = [
  mk("Almaden Valley homes $2–3M", null),
  mk("Willow Glen vs Almaden Valley", null),
  mk("Move-up buyer financing options", null),
  mk("Best San Jose school districts", null),
  mk("Bridge loans for San Jose buyers", null),
  mk("San Jose market update Q3", 21),
  mk("Downsizing in Silicon Valley", 35),
  mk("Preparing a $2M home for sale", 49),
]

export const mockTopicsApi = {
  async listTopics(): Promise<{ topics: Topic[] }> {
    await latency()
    const unused = topics.filter((t) => t.used_at === null)
    const used = topics
      .filter((t) => t.used_at !== null)
      .sort((a, b) => (a.used_at! < b.used_at! ? 1 : -1))
    return { topics: [...unused, ...used] }
  },

  async addTopic(topic: string): Promise<{ ok: boolean }> {
    await latency()
    const cleaned = topic.trim()
    if (!cleaned) throw new Error("ValueError: topic must not be empty")
    if (topics.some((t) => t.topic.toLowerCase() === cleaned.toLowerCase())) {
      throw new Error("ValueError: That topic already exists")
    }
    topics.unshift(mk(cleaned, null))
    return { ok: true }
  },

  async resetTopics(ids: number[]): Promise<{ ok: boolean; reset: number }> {
    await latency()
    const targets = ids.length
      ? topics.filter((t) => ids.includes(t.id))
      : topics.filter((t) => t.used_at !== null)
    let reset = 0
    for (const t of targets) {
      if (t.used_at !== null) {
        t.used_at = null
        reset++
      }
    }
    return { ok: true, reset }
  },

  async deleteTopic(id: number): Promise<{ ok: boolean }> {
    await latency()
    const index = topics.findIndex((t) => t.id === id)
    if (index < 0) throw new Error("ValueError: Topic not found")
    topics.splice(index, 1)
    return { ok: true }
  },
}
