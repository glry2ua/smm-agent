import type { Board, BoardChannel, BoardPost } from "@/types";
import type { MutationResponse, PostRef } from "@/lib/api";

/**
 * In-memory mock of the board backend (Buffer/D1/assets) for UI development.
 * Enabled by `npm run web-mock` (vite --mode mock): no worker, no API keys,
 * no Buffer quota. Mutations mutate the store in place so the board evolves
 * like the real thing during a session; a page reload resets it.
 *
 * Payloads mirror what `src/web_api.py` + `src/buffer/client.py` actually
 * ship: Buffer GraphQL node ids, service-keyed per-network metadata, PNG
 * asset cards under origin-relative R2 paths, and the weekly job's
 * "{description}\n\nKeywords: …" text shape for a San Jose real-estate agent.
 */

/** Simulated network latency so skeleton and busy states stay visible. */
function latency(): Promise<void> {
  return new Promise((resolve) =>
    setTimeout(resolve, 350 + Math.random() * 450),
  );
}

/**
 * Self-contained SVG placeholder: no network, deterministic per seed. Real
 * assets are PNGs under `/assets/generated_graphics/…` served by the worker;
 * the data URI exists only so mock mode renders images with zero backend.
 */
function svgUri(seed: number): string {
  const hue = (seed * 67) % 360;
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="640">` +
    `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">` +
    `<stop offset="0" stop-color="hsl(${hue},60%,55%)"/>` +
    `<stop offset="1" stop-color="hsl(${(hue + 60) % 360},60%,35%)"/>` +
    `</linearGradient></defs>` +
    `<rect width="640" height="640" fill="url(#g)"/>` +
    `<text x="320" y="335" font-family="sans-serif" font-size="40" ` +
    `fill="rgba(255,255,255,.85)" text-anchor="middle">mock asset ${seed}</text>` +
    `</svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

/** Opaque Buffer-style node id (base62, fixed literals keep ids stable). */
const ids = {
  channels: {
    instagram: "01HXQ4T7VB3MKE8ZRCF2WNYAD",
    facebook: "01HXQ4T8CX5NPF2AWE4G3RZQHM",
    linkedin: "01HXQ4T8K7Q9TB6XVD2N4P8JFS",
  },
  posts: {
    launchIg: "01JAZ3M7QK2XV8R5N9WYB4TFDC",
    launchLi: "01JAZ3M7QK2XV8R5N9WYB4TFDD",
    story: "01JAZ3M8H4P6QW2ZK9XYC5NGBE",
    bridge: "01JAZ3M8T1YD7S3FB6HJ2VQKF",
    walkthrough: "01JAZ3M95XQ8NB4WV2CK7YTDG",
    overdue: "01JAZ3M9ZM4TK8Q3F7XB5WJCH",
    recapIg: "01JAZ3MA6FV2QD9NJ4XR8TBKJ",
    recapFb: "01JAZ3MA6FV2QD9NJ4XR8TBKK",
    staging: "01JAZ3MB2HK5YQ7WD3ZN6VCLM",
  },
  assets: {
    listing: "01JAZ3M7RE9XBK4WQ6YT2NVHP",
    recap: "01JAZ3MA8QC3NX7VJ5TD9WBKP",
  },
};

const CHANNELS: BoardChannel[] = [
  {
    id: ids.channels.instagram,
    // Buffer `name` is the channel's handle / page slug.
    name: "andrewmiller.sanjose",
    // `display_name` is the user-assigned label shown in Buffer.
    display_name: "Andrew Miller — San Jose",
    service: "instagram",
  },
  {
    id: ids.channels.facebook,
    name: "MillerRealtyGroup",
    display_name: "Miller Realty Group",
    service: "facebook",
  },
  {
    id: ids.channels.linkedin,
    name: "andrew-miller-san-jose",
    display_name: "Andrew Miller",
    service: "linkedin",
  },
];

const minutesFromNow = (minutes: number) =>
  new Date(Date.now() + minutes * 60_000).toISOString();

/**
 * 8:30 AM local on `daysFromNow` from today — the weekly job schedules onto
 * the Mon/Wed/Fri 8:30 slot the UI copy talks about.
 */
function slotAt(daysFromNow: number): string {
  const slot = new Date();
  slot.setDate(slot.getDate() + daysFromNow);
  slot.setHours(8, 30, 0, 0);
  return slot.toISOString();
}

/** The exact text shape `SocialPostDraft.buffer_text()` produces. */
function bufferText(description: string, keywords: string[]): string {
  return `${description}\n\nKeywords: ${keywords.join(", ")}`;
}

/** Running counter for generated asset ids (replaced images). */
let nextId = 1;

/** Fixed-literal ids keep the store stable; see `ids` above. */
function mkPost(partial: Omit<BoardPost, "id"> & { id: string }): BoardPost {
  return partial;
}

// Deliberately varied so each UI state has something to chew on: a
// cross-channel group (shared text normalizes to one card), a story draft
// with an image, a text-only draft, an upcoming scheduled post, an overdue
// one, and sent posts — some with generated graphics attached.
const INITIAL_POSTS: BoardPost[] = [
  mkPost({
    id: ids.posts.launchIg,
    text: bufferText(
      "Open house this Saturday in Willow Glen! Tour the remodeled 4-bed at 1423 Malone Rd from 1–4 PM, and I'll walk you through what sold on the block last month.",
      ["Willow Glen", "open house", "San Jose real estate", "home tour"],
    ),
    channel_id: ids.channels.instagram,
    status: "draft",
    created_at: minutesFromNow(-60 * 20),
    due_at: null,
    sent_at: null,
    assets: [],
    // Instagram posts always carry Buffer-validated metadata.
    metadata: { instagram: { type: "post", shouldShareToFeed: true } },
  }),
  mkPost({
    id: ids.posts.launchLi,
    text: bufferText(
      "Open house this Saturday in Willow Glen! Tour the remodeled 4-bed at 1423 Malone Rd from 1–4 PM, and I'll walk you through what sold on the block last month.",
      ["Willow Glen", "open house", "San Jose real estate", "home tour"],
    ),
    channel_id: ids.channels.linkedin,
    status: "draft",
    created_at: minutesFromNow(-60 * 20),
    due_at: null,
    sent_at: null,
    assets: [],
    // LinkedIn needs no per-network metadata.
    metadata: null,
  }),
  mkPost({
    id: ids.posts.story,
    text: bufferText(
      "Just listed in Almaden Valley: a 5-bed on a cul-de-sac backing to the trails, listed at $2,395,000. DM me for the private tour link before it hits Zillow.",
      ["Almaden Valley", "just listed", "luxury homes", "San Jose"],
    ),
    channel_id: ids.channels.instagram,
    status: "draft",
    created_at: minutesFromNow(-60 * 30),
    due_at: null,
    sent_at: null,
    assets: [
      {
        id: ids.assets.listing,
        type: "image",
        mime_type: "image/png",
        source: svgUri(1),
        // Real thumbnails are a distinct Buffer-generated variant, never
        // the same URL as the source.
        thumbnail: svgUri(11),
      },
    ],
    // Stories: not shared to feed, and Buffer downgrades them on edits
    // unless the metadata round-trips (why PostRef carries it).
    metadata: { instagram: { type: "story", shouldShareToFeed: false } },
  }),
  mkPost({
    id: ids.posts.bridge,
    text: bufferText(
      "Thinking about a bridge loan so you can buy before you sell? Here's how three of this year's San Jose buyers pulled it off without carrying two mortgages.",
      ["bridge loan", "financing", "move-up buyers", "San Jose real estate"],
    ),
    channel_id: ids.channels.facebook,
    status: "draft",
    created_at: minutesFromNow(-60 * 8),
    due_at: null,
    sent_at: null,
    assets: [],
    metadata: { facebook: { type: "post" } },
  }),
  mkPost({
    id: ids.posts.walkthrough,
    text: bufferText(
      "Join me Thursday evening for a live walkthrough of the San Jose market — inventory, days on market, and what the Fed's latest move means for buyers.",
      ["market update", "San Jose housing", "interest rates", "buyer tips"],
    ),
    channel_id: ids.channels.linkedin,
    status: "scheduled",
    created_at: minutesFromNow(-60 * 72),
    due_at: slotAt(2),
    sent_at: null,
    assets: [],
    metadata: null,
  }),
  mkPost({
    id: ids.posts.overdue,
    text: bufferText(
      "August's San Jose market in one chart: inventory up 12%, days-on-market down to 11, and rates finally stabilizing. Full breakdown in the comments.",
      ["market update", "San Jose housing", "inventory", "interest rates"],
    ),
    channel_id: ids.channels.instagram,
    status: "scheduled",
    created_at: minutesFromNow(-60 * 96),
    due_at: minutesFromNow(-60 * 10),
    sent_at: null,
    assets: [],
    metadata: { instagram: { type: "post", shouldShareToFeed: true } },
  }),
  mkPost({
    id: ids.posts.recapIg,
    text: bufferText(
      "Recap: three offers in six days on the Blossom Valley remodel, and what the buyers who lost out should watch for next month.",
      [
        "Blossom Valley",
        "seller tips",
        "multiple offers",
        "San Jose real estate",
      ],
    ),
    channel_id: ids.channels.instagram,
    status: "sent",
    created_at: minutesFromNow(-60 * 24 * 9),
    due_at: slotAt(-8),
    // Actual send time trails the scheduled slot by a few minutes.
    sent_at: minutesFromNow(-60 * 24 * 8 - 214),
    assets: [],
    metadata: { instagram: { type: "post", shouldShareToFeed: true } },
  }),
  mkPost({
    id: ids.posts.recapFb,
    text: bufferText(
      "Recap: three offers in six days on the Blossom Valley remodel, and what the buyers who lost out should watch for next month.",
      [
        "Blossom Valley",
        "seller tips",
        "multiple offers",
        "San Jose real estate",
      ],
    ),
    channel_id: ids.channels.facebook,
    status: "sent",
    created_at: minutesFromNow(-60 * 24 * 9),
    due_at: slotAt(-8),
    sent_at: minutesFromNow(-60 * 24 * 8 - 214),
    assets: [],
    metadata: { facebook: { type: "post" } },
  }),
  mkPost({
    id: ids.posts.staging,
    text: bufferText(
      "Behind the scenes from yesterday's shoot — staging this Blossom Valley living room took the listing photos from dated to flagship.",
      ["behind the scenes", "home staging", "Blossom Valley", "listing photos"],
    ),
    channel_id: ids.channels.facebook,
    status: "sent",
    created_at: minutesFromNow(-60 * 24 * 20),
    due_at: slotAt(-19),
    sent_at: minutesFromNow(-60 * 24 * 19 - 97),
    assets: [
      {
        id: ids.assets.recap,
        type: "image",
        mime_type: "image/png",
        source: svgUri(2),
        thumbnail: svgUri(22),
      },
    ],
    metadata: { facebook: { type: "post" } },
  }),
];

const posts: BoardPost[] = structuredClone(INITIAL_POSTS);

function board(): Board {
  // Mirror Buffer's sort (dueAt desc, then createdAt desc) per status list.
  const byDueThenCreated = (a: BoardPost, b: BoardPost) => {
    const due = (b.due_at ?? "").localeCompare(a.due_at ?? "");
    if (due !== 0) return due;
    return b.created_at.localeCompare(a.created_at);
  };
  return {
    // worker.py: "{contact.first_name}'s Agent" from R2 contact.json.
    title: "Andrew's Agent",
    // web_api.py serializes fetched_at without milliseconds.
    fetched_at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    channels: CHANNELS,
    drafts: posts.filter((p) => p.status === "draft").sort(byDueThenCreated),
    accepted: posts
      .filter((p) => p.status === "scheduled")
      .sort(byDueThenCreated),
    posted: posts.filter((p) => p.status === "sent").sort(byDueThenCreated),
  };
}

function resultsFor(refs: PostRef[], transform: (post: BoardPost) => void) {
  const results = refs.map((ref) => {
    const post = posts.find((p) => p.id === ref.id);
    if (!post) {
      return { id: ref.id, ok: false, error: "Mock post not found" };
    }
    transform(post);
    return { id: ref.id, ok: true };
  });
  return { ok: results.every((r) => r.ok), results } satisfies MutationResponse;
}

export const mockBoardApi = {
  async updateText(refs: PostRef[], text: string): Promise<MutationResponse> {
    await latency();
    return resultsFor(refs, (post) => {
      post.text = text;
    });
  },

  async acceptPosts(
    refs: PostRef[],
    dueAt: string | null,
    text?: string,
  ): Promise<MutationResponse> {
    await latency();
    return resultsFor(refs, (post) => {
      if (text !== undefined) post.text = text;
      post.status = "scheduled";
      // Keep a stable fake next-slot time instead of a moving "now".
      post.due_at = dueAt ?? slotAt(2);
      post.sent_at = null;
    });
  },

  async deletePosts(refs: PostRef[]): Promise<MutationResponse> {
    await latency();
    return resultsFor(refs, (post) => {
      const index = posts.indexOf(post);
      if (index >= 0) posts.splice(index, 1);
    });
  },

  async replaceImage(refs: PostRef[], file: File): Promise<MutationResponse> {
    await latency();
    const url = URL.createObjectURL(file);
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
        ];
      }),
      image_url: url,
    };
  },
};

/** Snapshot for `useBoard` in mock mode. */
export async function fetchMockBoard(): Promise<Board> {
  await latency();
  return board();
}
