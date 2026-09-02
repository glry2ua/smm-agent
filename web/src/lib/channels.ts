import type { BoardChannel, BoardPost, GroupedPost } from "@/types";

export function channelFor(
  post: { channel_id: string },
  channels: BoardChannel[],
): BoardChannel | undefined {
  return channels.find((channel) => channel.id === post.channel_id);
}

/** Unique channel services across the group's posts, in first-seen order. */
export function groupServices(
  group: GroupedPost,
  channels: BoardChannel[],
): string[] {
  return Array.from(
    new Set(
      group.posts
        .map((p) => channelFor(p, channels)?.service)
        .filter((s): s is string => Boolean(s)),
    ),
  );
}

/** Best available image for a post, or null when it has no assets. */
export function firstImage(post: Pick<BoardPost, "assets">): string | null {
  const asset = post.assets.find((a) => a.thumbnail || a.source);
  return asset?.thumbnail || asset?.source || null;
}
