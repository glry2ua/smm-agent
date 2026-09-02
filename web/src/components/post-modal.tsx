import { useEffect, useRef, useState } from "react";

import { IconPhoto } from "@tabler/icons-react";
import { SkeletonImage } from "@/components/skeleton-image";
import { Skeleton } from "@/ui/skeleton";
import { Button } from "@/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/ui/dialog";
import { Modal } from "@/ui/modal";
import { PlatformIcon } from "@/components/ui/platform-icon";
import { boardApi, friendlyError, type MutationResponse } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { BoardChannel, GroupedPost } from "@/types";

type Busy = "save" | "upload" | "accept" | "delete" | null;
type ConfirmAction = "accept" | "delete" | "discard" | null;

function channelFor(
  post: { channel_id: string },
  channels: BoardChannel[],
): BoardChannel | undefined {
  return channels.find((channel) => channel.id === post.channel_id);
}

function formatDueAt(dueAt: string | null): string {
  if (!dueAt) return "";
  const date = new Date(dueAt);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatDay(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatTime(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

function failuresIn(result: MutationResponse | undefined): string[] {
  if (!result) return [];
  return result.results
    .filter((item) => !item.ok && item.error)
    .map((item) => friendlyError(item.error));
}

const MAX_CHARS = 5000;

/** Status pill styling, mirrored from the board column accents. */
const STATUS_BADGE: Record<string, { label: string; className: string }> = {
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
  notify,
}: {
  group: GroupedPost | null;
  channels: BoardChannel[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAccepted: () => void;
  onChanged: () => void;
  notify: (message: string, tone?: "info" | "error") => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [savedText, setSavedText] = useState("");
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [confirm, setConfirm] = useState<ConfirmAction>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open || !group) return;
    const first = group.posts[0];
    setText(first.text);
    setSavedText(first.text);
    const asset = first.assets.find((a) => a.thumbnail || a.source);
    setImageUrl(asset?.thumbnail || asset?.source || null);
    setEditing(false);
    setBusy(null);
    setConfirm(null);
  }, [open, group]);

  if (!group) return null;
  const postRefs = group.posts.map((post) => ({
    id: post.id,
    service: channelFor(post, channels)?.service ?? "",
    metadata: post.metadata,
  }));
  const due = group.posts[0].due_at;
  const sentAt = group.posts[0].sent_at;
  // Sent posts are immutable in Buffer: show them read-only.
  const posted = group.posts[0].status === "sent";
  const badge = STATUS_BADGE[group.posts[0].status];
  const stamp = posted ? sentAt : due;
  const dueStale = due !== null && new Date(due).getTime() < Date.now();
  const dirty = text !== savedText;
  const charCount = text.length;
  const overLimit = charCount > MAX_CHARS;
  const pending = busy !== null;

  const run = async (
    kind: Exclude<Busy, null>,
    action: () => Promise<void>,
  ) => {
    setBusy(kind);
    setConfirm(null);
    try {
      await action();
      return true;
    } catch (err) {
      notify(friendlyError(err), "error");
      return false;
    } finally {
      setBusy(null);
    }
  };

  /** Save text edits. Returns true when Buffer is in sync with `text`. */
  const persistText = async (): Promise<boolean> => {
    if (!dirty) return true;
    const result = await boardApi.updateText(postRefs, text);
    const failures = failuresIn(result);
    if (failures.length > 0) {
      notify(failures[0], "error");
      return false;
    }
    setSavedText(text);
    return true;
  };

  const save = () =>
    run("save", async () => {
      const ok = await persistText();
      if (ok) {
        setEditing(false);
        notify("Changes saved");
        onChanged();
      }
    });

  const uploadImage = (file: File) =>
    run("upload", async () => {
      const result = await boardApi.replaceImage(postRefs, file);
      const failures = failuresIn(result);
      if (failures.length > 0) {
        notify(failures[0], "error");
        return;
      }
      if (result.image_url) setImageUrl(result.image_url);
      notify("Image updated");
      onChanged();
    });

  const accept = () =>
    run("accept", async () => {
      // The current text always rides along with the schedule edit: Buffer
      // rejects update inputs that change neither text nor media ("Post must
      // have either text or media"), so a text-less schedule edit can fail.
      const result = await boardApi.acceptPosts(postRefs, due, text);
      const failures = failuresIn(result);
      if (failures.length > 0) {
        notify(failures[0], "error");
        return;
      }
      setSavedText(text);
      setEditing(false);
      const when = result.scheduled_at ?? due;
      notify(`Scheduled for ${formatDueAt(when) || "the next slot"}`);
      onOpenChange(false);
      onAccepted();
    });

  const remove = () =>
    run("delete", async () => {
      const result = await boardApi.deletePosts(postRefs);
      const failures = failuresIn(result);
      if (failures.length > 0) {
        notify(failures[0], "error");
        return;
      }
      notify("Post deleted");
      onOpenChange(false);
      onChanged();
    });

  /** Intercept closing while there are unsaved edits. */
  const handleOpenChange = (next: boolean) => {
    if (!next && dirty && !pending && confirm === null) {
      setConfirm("discard");
      return;
    }
    setConfirm(null);
    onOpenChange(next);
  };

  const cancelEdit = () => {
    setText(savedText);
    setInstruction("");
    setEditing(false);
    setError(null);
  };

  const busyLabel: Record<Exclude<Busy, null>, string> = {
    save: "Saving…",
    upload: "Uploading image…",
    accept: "Scheduling…",
    delete: "Deleting…",
  };

  return (
    <Dialog isOpen={open} onOpenChange={handleOpenChange}>
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
                        if (file) uploadImage(file);
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
                  {badge && (
                    <span
                      className={cn(
                        "rounded-full px-2 py-0.5 text-xs font-semibold",
                        badge.className,
                      )}
                    >
                      {badge.label}
                    </span>
                  )}
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
                  {Array.from(
                    new Set(
                      group.posts
                        .map((p) => channelFor(p, channels)?.service)
                        .filter((s): s is string => Boolean(s)),
                    ),
                  ).map((service) => (
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
                  value={text}
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

              {confirm === "accept" && (
                <div className="border-border/20 bg-muted/30 rounded-lg border px-3 py-2.5 text-sm">
                  <p className="font-medium">
                    Publish{" "}
                    {group.posts.length > 1
                      ? `to ${group.posts.length} channels`
                      : "this post"}
                    {dirty ? " with your edited text" : ""}?
                  </p>
                  <p className="text-fg-muted mt-1">
                    {dueStale
                      ? "The original time has passed, so it will publish at the next Mon/Wed/Fri 8:30 AM slot."
                      : `It is scheduled for ${formatDueAt(due)}.`}
                  </p>
                </div>
              )}
              {confirm === "delete" && (
                <div className="bg-danger-muted rounded-lg px-3 py-2.5 text-sm">
                  <p className="text-fg-danger font-medium">
                    Delete this post from Buffer? This can't be undone.
                  </p>
                </div>
              )}
              {confirm === "discard" && (
                <div className="border-border/20 bg-muted/30 rounded-lg border px-3 py-2.5 text-sm">
                  <p className="font-medium">Discard your unsaved changes?</p>
                </div>
              )}

              {!posted && (
                <div className="flex items-center gap-2">
                  <div className="flex items-center gap-2">
                    {pending && (
                      <span className="text-fg-muted text-sm">
                        {busyLabel[busy]}
                      </span>
                    )}
                    {!posted && confirm === null && !pending && (
                      <Button
                        variant="danger"
                        onPress={() => setConfirm("delete")}
                      >
                        Delete
                      </Button>
                    )}
                    {confirm === "delete" && (
                      <Button
                        variant="secondary"
                        onPress={() => setConfirm(null)}
                        isDisabled={pending}
                      >
                        Keep post
                      </Button>
                    )}
                    {confirm === "delete" && (
                      <Button
                        variant="danger"
                        onPress={remove}
                        isDisabled={pending}
                        isPending={busy === "delete"}
                      >
                        Delete forever
                      </Button>
                    )}
                    {confirm === "discard" && (
                      <>
                        <Button
                          variant="secondary"
                          onPress={() => setConfirm(null)}
                          isDisabled={pending}
                        >
                          Keep editing
                        </Button>
                        <Button
                          variant="danger"
                          onPress={() => {
                            setText(savedText);
                            setConfirm(null);
                            handleOpenChange(false);
                          }}
                          isDisabled={pending}
                        >
                          Discard changes
                        </Button>
                      </>
                    )}
                  </div>
                  <div className="ml-auto flex items-center gap-2">
                    {editing ? (
                      <>
                        <Button
                          variant="secondary"
                          onPress={cancelEdit}
                          isDisabled={pending}
                        >
                          Cancel
                        </Button>
                        <Button
                          variant="primary"
                          onPress={save}
                          isDisabled={pending || overLimit}
                          isPending={busy === "save"}
                        >
                          Save
                        </Button>
                      </>
                    ) : posted ? null : confirm === null ? (
                      <>
                        <Button
                          variant="secondary"
                          onPress={() => setEditing(true)}
                          isDisabled={pending}
                        >
                          Edit
                        </Button>
                        <Button
                          variant="primary"
                          onPress={() => setConfirm("accept")}
                          isDisabled={pending}
                        >
                          Accept &amp; schedule
                        </Button>
                      </>
                    ) : confirm === "accept" ? (
                      <>
                        <Button
                          variant="secondary"
                          onPress={() => setConfirm(null)}
                          isDisabled={pending}
                        >
                          Not yet
                        </Button>
                        <Button
                          variant="primary"
                          onPress={accept}
                          isDisabled={pending || overLimit}
                          isPending={busy === "accept"}
                        >
                          {dueStale
                            ? "Reschedule & publish"
                            : "Yes, schedule it"}
                        </Button>
                      </>
                    ) : null}
                  </div>
                </div>
              )}
            </div>
          </div>
        </DialogContent>
      </Modal>
    </Dialog>
  );
}
