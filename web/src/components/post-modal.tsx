import { useRef } from "react";

import { IconPhoto } from "@tabler/icons-react";
import { SkeletonImage } from "@/components/skeleton-image";
import { PostActions } from "@/components/post-actions";
import { Skeleton } from "@/ui/skeleton";
import { Button } from "@/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/ui/dialog";
import { Modal } from "@/ui/modal";
import { PlatformIcon } from "@/components/ui/platform-icon";
import { groupServices } from "@/lib/channels";
import { formatDay, formatTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { usePostActions } from "@/hooks/use-post-actions";
import type { BoardChannel, GroupedPost, PostStatus } from "@/types";

const MAX_CHARS = 5000;

/** Status pill styling, mirrored from the board column accents. */
const STATUS_BADGE: Record<PostStatus, { label: string; className: string }> = {
  draft: { label: "Draft", className: "bg-orange-600/15 text-orange-600" },
  scheduled: {
    label: "Scheduled",
    className: "bg-green-600/15 text-green-600",
  },
  sent: { label: "Posted", className: "bg-blue-600/15 text-blue-600" },
};

export function PostModal({
  group,
  channels,
  open,
  onOpenChange,
  onAccepted,
  onChanged,
}: {
  group: GroupedPost | null;
  channels: BoardChannel[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAccepted: () => void;
  onChanged: () => void;
}) {
  const actions = usePostActions({
    group,
    channels,
    open,
    onOpenChange,
    onAccepted,
    onChanged,
  });
  const fileInputRef = useRef<HTMLInputElement>(null);

  if (!group) return null;
  const post = group.posts[0];
  // Sent posts are immutable in Buffer: show them read-only.
  const posted = post.status === "sent";
  const badge = STATUS_BADGE[post.status];
  const stamp = posted ? post.sent_at : post.due_at;
  const dueStale = post.due_at !== null && new Date(post.due_at).getTime() < Date.now();
  const charCount = actions.text.length;
  const overLimit = charCount > MAX_CHARS;
  const { busy, pending, editing, imageUrl, setText } = actions;

  return (
    <Dialog isOpen={open} onOpenChange={actions.requestClose}>
      <Modal className="sm:max-w-5xl sm:h-[min(40rem,calc(var(--visual-viewport-height)-4rem))]">
        <DialogContent
          showCloseButton
          className="min-h-0 flex-1 gap-5 p-5 sm:p-6"
        >
          <DialogTitle className="sr-only">Post details</DialogTitle>
          <div className="flex min-h-0 flex-1 flex-col gap-5 sm:flex-row">
            <div className="flex shrink-0 flex-col gap-3 sm:w-[44%] sm:max-w-[26rem]">
              {/* The frame bleeds into the modal padding so the image sits
                  tighter to the edge than the rest of the modal's content. */}
              <div className="border-border/20 bg-muted/60 relative -ml-3 -mt-3 h-[40vh] overflow-hidden rounded-xl border sm:-ml-4 sm:-mt-4 sm:-mb-4 sm:h-auto sm:min-h-0 sm:flex-1">
                {imageUrl ? (
                  <SkeletonImage
                    src={imageUrl}
                    alt=""
                    className="h-full w-full"
                    imgClassName="h-full w-full object-cover"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center">
                    <p className="text-fg-muted text-sm">No image</p>
                  </div>
                )}
                {/* Cover the previous render while the replacement is in flight. */}
                {busy === "upload" && (
                  <Skeleton className="absolute inset-0 rounded-none" />
                )}
                {/* Upload button floats top-left while editing, fading with
                    the edit mode transition. */}
                {!posted && (
                  <div
                    className={cn(
                      "absolute top-3 left-3 transition-opacity duration-200",
                      editing ? "opacity-100" : "pointer-events-none opacity-0",
                    )}
                    aria-hidden={!editing}
                  >
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      className="hidden"
                      disabled={pending}
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        event.target.value = "";
                        if (file) actions.uploadImage(file);
                      }}
                    />
                    <Button
                      variant="secondary"
                      size="xs"
                      className="bg-bg/80 shadow-sm backdrop-blur-md"
                      isDisabled={pending}
                      isPending={busy === "upload"}
                      onPress={() => fileInputRef.current?.click()}
                    >
                      <IconPhoto />
                      Upload new
                    </Button>
                  </div>
                )}
              </div>
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-4 -mt-1">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-lg font-semibold leading-tight tabular-nums">
                    {stamp ? formatDay(stamp) : "Unscheduled"}
                  </span>
                  <span
                    className={cn(
                      "rounded-full px-2 py-0.5 text-xs font-semibold",
                      badge.className,
                    )}
                  >
                    {badge.label}
                  </span>
                  {dueStale && !posted && (
                    <span
                      className="text-fg-danger text-xs font-semibold"
                      title="This time has already passed"
                    >
                      (missed)
                    </span>
                  )}
                </div>
                <div className="text-fg-muted mt-1.5 flex items-center gap-3 text-sm tabular-nums">
                  <p>
                    {stamp ? formatTime(stamp) : "No slot yet"}
                    {" · "}
                    {group.posts.length}{" "}
                    {group.posts.length === 1 ? "post" : "posts"}
                  </p>
                  {groupServices(group, channels).map((service) => (
                    <PlatformIcon
                      key={service}
                      service={service}
                      className="size-4"
                    />
                  ))}
                </div>
              </div>

              {/* One stable text element in both modes: view mode styles it
                  like the read-only card, edit mode makes it an editable
                  textarea — same box, same padding, zero shift. The char
                  counter floats over its bottom edge. */}
              <div className="relative min-h-40 flex-1">
                <textarea
                  className={cn(
                    "text-sm leading-relaxed focus:outline-none h-full w-full resize-none p-4",
                    editing
                      ? "border-border-control bg-bg rounded-md border"
                      : "border-border/20 bg-muted/30 cursor-default rounded-xl border",
                  )}
                  value={actions.text}
                  onChange={(event) => setText(event.target.value)}
                  readOnly={!editing}
                  tabIndex={editing ? undefined : -1}
                  disabled={pending}
                />
                {!posted && editing && (
                  <div
                    className="bg-bg/70 border-border/20 text-fg-muted absolute right-3 bottom-3 rounded-full border px-2.5 py-1 text-xs text-right tabular-nums backdrop-blur-md"
                    aria-hidden
                  >
                    <span className={cn(overLimit && "text-fg-danger")}>
                      {charCount}/{MAX_CHARS}
                    </span>
                  </div>
                )}
              </div>

              <PostActions
                actions={actions}
                group={group}
                posted={posted}
                dueStale={dueStale}
                dirty={actions.dirty}
                overLimit={overLimit}
              />
            </div>
          </div>
        </DialogContent>
      </Modal>
    </Dialog>
  );
}
