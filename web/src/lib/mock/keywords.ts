import type { Keyword } from "@/types"

/**
 * In-memory mock of the keywords API (D1 `keywords` table) for UI development
 * (`npm run web-mock`). Mutations evolve the store in place; a page reload
 * resets it. Mirrors the worker: unused keywords first, used ones after.
 */

function latency(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 250 + Math.random() * 350))
}

const daysAgo = (days: number) =>
  new Date(Date.now() - days * 24 * 60 * 60_000).toISOString()

let nextId = 1
const mk = (topic: string, usedDaysAgo: number | null): Keyword => ({
  id: nextId++,
  topic,
  used_at: usedDaysAgo === null ? null : daysAgo(usedDaysAgo),
})

const keywords: Keyword[] = [
  mk("Almaden Valley homes $2–3M", null),
  mk("Willow Glen vs Almaden Valley", null),
  mk("Move-up buyer financing options", null),
  mk("Best San Jose school districts", null),
  mk("Bridge loans for San Jose buyers", null),
  mk("San Jose market update Q3", 21),
  mk("Downsizing in Silicon Valley", 35),
  mk("Preparing a $2M home for sale", 49),
]

export const mockKeywordsApi = {
  async listKeywords(): Promise<{ keywords: Keyword[] }> {
    await latency()
    const unused = keywords.filter((k) => k.used_at === null)
    const used = keywords
      .filter((k) => k.used_at !== null)
      .sort((a, b) => (a.used_at! < b.used_at! ? 1 : -1))
    return { keywords: [...unused, ...used] }
  },

  async addKeyword(topic: string): Promise<{ ok: boolean }> {
    await latency()
    const cleaned = topic.trim()
    if (!cleaned) throw new Error("ValueError: topic must not be empty")
    if (keywords.some((k) => k.topic.toLowerCase() === cleaned.toLowerCase())) {
      throw new Error("ValueError: That keyword already exists")
    }
    keywords.unshift(mk(cleaned, null))
    return { ok: true }
  },

  async resetKeywords(ids: number[]): Promise<{ ok: boolean; reset: number }> {
    await latency()
    const targets = ids.length
      ? keywords.filter((k) => ids.includes(k.id))
      : keywords.filter((k) => k.used_at !== null)
    let reset = 0
    for (const k of targets) {
      if (k.used_at !== null) {
        k.used_at = null
        reset++
      }
    }
    return { ok: true, reset }
  },
}
