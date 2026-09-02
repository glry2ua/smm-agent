import type { BoardPost, GroupedPost } from "@/types"

/**
 * Normalize post text for cross-platform matching: collapse whitespace and
 * ignore trailing keyword/blank-line differences the agent may add per channel.
 */
function normalizeText(text: string): string {
  return text
    .replace(/\s+/g, " ")
    .replace(/\s+Keywords:.*$/i, "")
    .trim()
    .toLowerCase()
}

export function groupPosts(posts: BoardPost[]): GroupedPost[] {
  const groups = new Map<string, BoardPost[]>()
  for (const post of posts) {
    const key = normalizeText(post.text)
    const bucket = groups.get(key)
    if (bucket) {
      bucket.push(post)
    } else {
      groups.set(key, [post])
    }
  }
  return Array.from(groups, ([key, posts]) => ({ key, posts }))
}