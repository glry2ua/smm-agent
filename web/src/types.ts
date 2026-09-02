export interface BoardChannel {
  id: string
  name: string
  display_name: string
  service: string
}

export interface BoardAsset {
  id: string
  type: string
  mime_type: string
  source: string
  thumbnail: string
}

export interface BoardPost {
  id: string
  text: string
  channel_id: string
  status: string
  created_at: string
  due_at: string | null
  sent_at: string | null
  assets: BoardAsset[]
  metadata: Record<string, unknown> | null
}

export interface Board {
  title: string
  fetched_at: string
  channels: BoardChannel[]
  drafts: BoardPost[]
  accepted: BoardPost[]
  posted: BoardPost[]
}

export interface GroupedPost {
  key: string
  posts: BoardPost[]
}

/** One row of the D1 `topics` table: a topic the weekly job can pick. */
export interface Topic {
  id: number
  topic: string
  used_at: string | null
}
