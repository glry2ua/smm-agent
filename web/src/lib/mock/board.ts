import type { Board, BoardChannel, BoardPost } from "@/types"
import type { MutationResponse, PostRef } from "@/lib/api"

/**
 * In-memory mock of the board backend (Buffer/D1/assets) for UI development.
 * Enabled by `npm run web-mock` (vite --mode mock): no worker, no API keys,
 * no Buffer quota. Mutations mutate the store in place so the board evolves
 * like the real thing during a session; a page reload resets it.
 */

/** Simulated network latency so skeleton and busy states stay visible. */
function latency(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 350 + Math.random() * 450))
}

/** Self-contained SVG placeholder: no network, deterministic per seed. */
function svgUri(seed: number): string {
  const hue = (seed * 67) % 360
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="640">` +
    `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">` +
    `<stop offset="0" stop-color="hsl(${hue},60%,55%)"/>` +
    `<stop offset="1" stop-color="hsl(${(hue + 60) % 360},60%,35%)"/>` +
    `</linearGradient></defs>` +
    `<rect width="640" height="640" fill="url(#g)"/>` +
    `<text x="320" y="335" font-family="sans-serif" font-size="40" ` +
    `fill="rgba(255,255,255,.85)" text-anchor="middle">mock asset ${seed}</text>` +
    `</svg>`
  return `data:image/svg+xml,${encodeURIComponent(svg)}`
}

const CHANNELS: BoardChannel[] = [
  { id: "chan_twitter", name: "twitter", display_name: "Acme on X", service: "twitter" },
  { id: "chan_instagram", name: "instagram", display_name: "Acme Studio", service: "instagram" },
  { id: "chan_linkedin", name: "linkedin", display_name: "Acme Inc.", service: "linkedin" },
]

const minutesFromNow = (minutes: number) =>
  new Date(Date.now() + minutes * 60_000).toISOString()

let nextId = 1
function post(partial: Omit<BoardPost, "id">): BoardPost {
  return { id: `mock_post_${nextId++}`, ...partial }
}

// Deliberately varied so each UI state has something to chew on: a
// cross-channel group (shared text normalizes to one card), an image draft,
// a text-only draft, an upcoming scheduled post, and an overdue one.
const INITIAL_POSTS: BoardPost[] = [
  post({
    text: "Launch week is finally here! Version 2.0 ships today with a rebuilt pipeline, 3x faster exports, and a brand-new dashboard.\n\nKeywords: launch, release",
    channel_id: "chan_twitter",
    status: "draft",
    created_at: minutesFromNow(-60 * 20),
    due_at: null,
    sent_at: null,
    assets: [],
    metadata: null,
  }),
  post({
    text: "Launch week is finally here! Version 2.0 ships today with a rebuilt pipeline, 3x faster exports, and a brand-new dashboard.\n\nKeywords: launch, release",
    channel_id: "chan_linkedin",
    status: "draft",
    created_at: minutesFromNow(-60 * 20),
    due_at: null,
    sent_at: null,
    assets: [],
    metadata: null,
  }),
  post({
    text: "Behind the scenes of the 2.0 build — swipe for the before/after of the dashboard redesign.\n\nKeywords: design, bts",
    channel_id: "chan_instagram",
    status: "draft",
    created_at: minutesFromNow(-60 * 30),
    due_at: null,
    sent_at: null,
    assets: [
      {
        id: "mock_asset_1",
        type: "image",
        mime_type: "image/svg+xml",
        source: svgUri(1),
        thumbnail: svgUri(1),
      },
    ],
    metadata: null,
  }),
  post({
    text: "Hot take: most status meetings could be a screenshot.",
    channel_id: "chan_twitter",
    status: "draft",
    created_at: minutesFromNow(-60 * 8),
    due_at: null,
    sent_at: null,
    assets: [],
    metadata: null,
  }),
  post({
    text: "Join us Thursday for a live walkthrough of 2.0 and an extended Q&A with the team.",
    channel_id: "chan_linkedin",
    status: "scheduled",
    created_at: minutesFromNow(-60 * 72),
    due_at: minutesFromNow(60 * 40),
    sent_at: null,
    assets: [],
    metadata: null,
  }),
  post({
    text: "This one should have gone out Monday — good example of the overdue styling.",
    channel_id: "chan_twitter",
    status: "scheduled",
    created_at: minutesFromNow(-60 * 96),
    due_at: minutesFromNow(-60 * 10),
    sent_at: null,
    assets: [],
    metadata: null,
  }),
  post({
    text: "Recap: our 1.9 release notes, and what the community built with the plugin API last month.",
    channel_id: "chan_twitter",
    status: "sent",
    created_at: minutesFromNow(-60 * 24 * 9),
    due_at: minutesFromNow(-60 * 24 * 8),
    sent_at: minutesFromNow(-60 * 24 * 8),
    assets: [],
    metadata: null,
  }),
  post({
    text: "Recap: our 1.9 release notes, and what the community built with the plugin API last month.",
    channel_id: "chan_linkedin",
    status: "sent",
    created_at: minutesFromNow(-60 * 24 * 9),
    due_at: minutesFromNow(-60 * 24 * 8),
    sent_at: minutesFromNow(-60 * 24 * 8),
    assets: [],
    metadata: null,
  }),
  post({
    text: "Team offsite photos — thanks for a great quarter, everyone!",
    channel_id: "chan_instagram",
    status: "sent",
    created_at: minutesFromNow(-60 * 24 * 20),
    due_at: minutesFromNow(-60 * 24 * 19),
    sent_at: minutesFromNow(-60 * 24 * 19),
    assets: [
      {
        id: "mock_asset_2",
        type: "image",
        mime_type: "image/svg+xml",
        source: svgUri(2),
        thumbnail: svgUri(2),
      },
    ],
    metadata: null,
  }),
]

const posts: BoardPost[] = structuredClone(INITIAL_POSTS)

function board(): Board {
  return {
    title: "Minh's Agent",
    fetched_at: new Date().toISOString(),
    channels: CHANNELS,
    drafts: posts.filter((p) => p.status === "draft"),
    accepted: posts.filter((p) => p.status === "scheduled"),
    posted: posts.filter((p) => p.status === "sent"),
  }
}

function resultsFor(refs: PostRef[], transform: (post: BoardPost) => void) {
  const results = refs.map((ref) => {
    const post = posts.find((p) => p.id === ref.id)
    if (!post) {
      return { id: ref.id, ok: false, error: "Mock post not found" }
    }
    transform(post)
    return { id: ref.id, ok: true }
  })
  return { ok: results.every((r) => r.ok), results } satisfies MutationResponse
}

export const mockBoardApi = {
  async updateText(refs: PostRef[], text: string): Promise<MutationResponse> {
    await latency()
    return resultsFor(refs, (post) => {
      post.text = text
    })
  },

  async acceptPosts(
    refs: PostRef[],
    dueAt: string | null,
    text?: string,
  ): Promise<MutationResponse> {
    await latency()
    return resultsFor(refs, (post) => {
      if (text !== undefined) post.text = text
      post.status = "scheduled"
      // Keep a stable fake next-slot time instead of a moving "now".
      post.due_at = dueAt ?? minutesFromNow(60 * 26)
      post.sent_at = null
    })
  },

  async deletePosts(refs: PostRef[]): Promise<MutationResponse> {
    await latency()
    return resultsFor(refs, (post) => {
      const index = posts.indexOf(post)
      if (index >= 0) posts.splice(index, 1)
    })
  },

  async replaceImage(refs: PostRef[], file: File): Promise<MutationResponse> {
    await latency()
    const url = URL.createObjectURL(file)
    return {
      ...resultsFor(refs, (post) => {
        post.assets = [
          {
            id: `mock_asset_${nextId++}`,
            type: "image",
            mime_type: file.type,
            source: url,
            thumbnail: url,
          },
        ]
      }),
      image_url: url,
    }
  },

  async aiEditImage(
    refs: PostRef[],
    url: string,
    _instruction: string,
  ): Promise<MutationResponse> {
    await latency()
    // Same URL back: enough to exercise the busy state and the swap.
    return {
      ...resultsFor(refs, () => {}),
      image_url: url,
    }
  },

  async rewriteText(
    postId: string,
    text: string,
    instruction: string,
  ): Promise<{ text: string }> {
    await latency()
    if (!posts.some((p) => p.id === postId)) {
      throw new Error("Mock post not found")
    }
    return { text: `${text}\n\n[mock rewrite: ${instruction}]` }
  },
}

/** Snapshot for `useBoard` in mock mode. */
export async function fetchMockBoard(): Promise<Board> {
  await latency()
  return board()
}