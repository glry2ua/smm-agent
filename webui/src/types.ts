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
}

export interface Board {
  fetched_at: string
  channels: BoardChannel[]
  drafts: BoardPost[]
  accepted: BoardPost[]
}

export interface GroupedPost {
  key: string
  posts: BoardPost[]
}