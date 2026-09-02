import { Button } from "@/ui/button";
import { formatDueAt } from "@/lib/format";
import type { PostActionsApi } from "@/hooks/use-post-actions";
import type { GroupedPost } from "@/types";

/** Confirm panels and the bottom button cluster of the post modal. */
export function PostActions({
  actions,
  group,
  posted,
  dueStale,
  dirty,
  overLimit,
}: {
  actions: PostActionsApi;
  group: GroupedPost;
  posted: boolean;
  dueStale: boolean;
  dirty: boolean;
  overLimit: boolean;
}) {
  const {
    busy,
    pending,
    confirm,
    setConfirm,
    busyLabel,
    editing,
    setEditing,
    save,
    accept,
    remove,
    cancelEdit,
    discardChanges,
  } = actions;
  const due = group.posts[0].due_at;

  return (
    <>
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
            {busy !== null && (
              <span className="text-fg-muted text-sm">{busyLabel[busy]}</span>
            )}
            {!posted && confirm === null && !pending && (
              <Button variant="danger" onPress={() => setConfirm("delete")}>
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
                  onPress={discardChanges}
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
                  {dueStale ? "Reschedule & publish" : "Yes, schedule it"}
                </Button>
              </>
            ) : null}
          </div>
        </div>
      )}
    </>
  );
}
