import { useEffect, useState } from "react";

import {
  boardApi,
  friendlyError,
  type MutationResponse,
  type PostRef,
} from "@/lib/api";
import { channelFor, firstImage } from "@/lib/channels";
import { formatDueAt } from "@/lib/format";
import { useToast } from "@/components/toast";
import type { BoardChannel, BoardPost, GroupedPost } from "@/types";

export type Busy = "save" | "upload" | "accept" | "delete" | null;
export type ConfirmAction = "accept" | "delete" | "discard" | null;

function failuresIn(result: MutationResponse | undefined): string[] {
  if (!result) return [];
  return result.results
    .filter((item) => !item.ok && item.error)
    .map((item) => friendlyError(item.error));
}

export interface PostActionsApi {
  text: string;
  setText: (text: string) => void;
  imageUrl: string | null;
  editing: boolean;
  setEditing: (editing: boolean) => void;
  busy: Busy;
  /** True while any mutation is in flight. */
  pending: boolean;
  dirty: boolean;
  confirm: ConfirmAction;
  setConfirm: (confirm: ConfirmAction) => void;
  busyLabel: Record<Exclude<Busy, null>, string>;
  save: () => void;
  uploadImage: (file: File) => void;
  accept: () => void;
  remove: () => void;
  cancelEdit: () => void;
  discardChanges: () => void;
  /** Intercept closing while there are unsaved edits. */
  requestClose: (next: boolean) => void;
}

/**
 * All mutating behavior behind the post modal: text edits, image swaps,
 * accepting and deleting. Owns the modal's edit state so post-modal.tsx
 * stays a layout-only view.
 */
export function usePostActions({
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
}): PostActionsApi {
  const notify = useToast();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [savedText, setSavedText] = useState("");
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [confirm, setConfirm] = useState<ConfirmAction>(null);

  useEffect(() => {
    if (!open || !group) return;
    const first = group.posts[0];
    setText(first.text);
    setSavedText(first.text);
    setImageUrl(firstImage(first));
    setEditing(false);
    setBusy(null);
    setConfirm(null);
  }, [open, group]);

  const dirty = text !== savedText;
  const pending = busy !== null;

  const toRef = (post: BoardPost): PostRef => ({
    id: post.id,
    service: channelFor(post, channels)?.service ?? "",
    metadata: post.metadata,
  });

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
  const persistText = async (refs: PostRef[]): Promise<boolean> => {
    if (!dirty) return true;
    const result = await boardApi.updateText(refs, text);
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
      if (!group) return;
      const ok = await persistText(group.posts.map(toRef));
      if (ok) {
        setEditing(false);
        notify("Changes saved");
        onChanged();
      }
    });

  const uploadImage = (file: File) =>
    run("upload", async () => {
      if (!group) return;
      const result = await boardApi.replaceImage(group.posts.map(toRef), file);
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
      if (!group) return;
      // The current text always rides along with the schedule edit: Buffer
      // rejects update inputs that change neither text nor media ("Post must
      // have either text or media"), so a text-less schedule edit can fail.
      const result = await boardApi.acceptPosts(
        group.posts.map(toRef),
        group.posts[0].due_at,
        text,
      );
      const failures = failuresIn(result);
      if (failures.length > 0) {
        notify(failures[0], "error");
        return;
      }
      setSavedText(text);
      setEditing(false);
      const when = result.scheduled_at ?? group.posts[0].due_at;
      notify(`Scheduled for ${formatDueAt(when) || "the next slot"}`);
      onOpenChange(false);
      onAccepted();
    });

  const remove = () =>
    run("delete", async () => {
      if (!group) return;
      const result = await boardApi.deletePosts(group.posts.map(toRef));
      const failures = failuresIn(result);
      if (failures.length > 0) {
        notify(failures[0], "error");
        return;
      }
      notify("Post deleted");
      onOpenChange(false);
      onChanged();
    });

  const requestClose = (next: boolean) => {
    if (!next && dirty && !pending && confirm === null) {
      setConfirm("discard");
      return;
    }
    setConfirm(null);
    onOpenChange(next);
  };

  const cancelEdit = () => {
    setText(savedText);
    setEditing(false);
  };

  const discardChanges = () => {
    setText(savedText);
    setConfirm(null);
    requestClose(false);
  };

  const busyLabel: Record<Exclude<Busy, null>, string> = {
    save: "Saving…",
    upload: "Uploading image…",
    accept: "Scheduling…",
    delete: "Deleting…",
  };

  return {
    text,
    setText,
    imageUrl,
    editing,
    setEditing,
    busy,
    pending,
    dirty,
    confirm,
    setConfirm,
    busyLabel,
    save,
    uploadImage,
    accept,
    remove,
    cancelEdit,
    discardChanges,
    requestClose,
  };
}
