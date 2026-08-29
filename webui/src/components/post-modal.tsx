import { useEffect, useRef, useState } from "react"
import { Loader2 } from "lucide-react"

import { SkeletonImage } from "@/components/skeleton-image"
import { Skeleton } from "@/components/ui/skeleton"
import { Button } from "@/components/ui/button"
import { Dialog } from "@/components/ui/dialog"
import { PlatformIcon } from "@/components/ui/platform-icon"
import { boardApi, friendlyError, type MutationResponse } from "@/lib/api"
import { cn } from "@/lib/utils"
import type { BoardChannel, GroupedPost } from "@/types"

type Busy = "save" | "rewrite" | "upload" | "ai-image" | "accept" | "delete" | null
type ConfirmAction = "accept" | "delete" | "discard" | null

function channelFor(
  post: { channel_id: string },
  channels: BoardChannel[],
): BoardChannel | undefined {
  return channels.find((channel) => channel.id === post.channel_id)
}

function formatDueAt(dueAt: string | null): string {
  if (!dueAt) return ""
  const date = new Date(dueAt)
  if (Number.isNaN(date.getTime())) return ""
  return date.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })
}

function failuresIn(result: MutationResponse | undefined): string[] {
  if (!result) return []
  return result.results
    .filter((item) => !item.ok && item.error)
    .map((item) => friendlyError(item.error))
}

const MAX_CHARS = 5000

export function PostModal({
  group,
  channels,
  open,
  onOpenChange,
  onAccepted,
  onChanged,
  notify,
}: {
  group: GroupedPost | null
  channels: BoardChannel[]
  open: boolean
  onOpenChange: (open: boolean) => void
  onAccepted: () => void
  onChanged: () => void
  notify: (message: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState("")
  const [savedText, setSavedText] = useState("")
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [instruction, setInstruction] = useState("")
  const [imageInstruction, setImageInstruction] = useState("")
  const [busy, setBusy] = useState<Busy>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<ConfirmAction>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!open || !group) return
    const first = group.posts[0]
    setText(first.text)
    setSavedText(first.text)
    const asset = first.assets.find((a) => a.thumbnail || a.source)
    setImageUrl(asset?.thumbnail || asset?.source || null)
    setEditing(false)
    setInstruction("")
    setImageInstruction("")
    setError(null)
    setBusy(null)
    setConfirm(null)
  }, [open, group])

  if (!group) return null
  const postRefs = group.posts.map((post) => ({
    id: post.id,
    service: channelFor(post, channels)?.service ?? "",
    metadata: post.metadata,
  }))
  const ids = postRefs.map((ref) => ref.id)
  const due = group.posts[0].due_at
  const dueStale = due !== null && new Date(due).getTime() < Date.now()
  const dirty = text !== savedText
  const charCount = text.length
  const overLimit = charCount > MAX_CHARS
  const pending = busy !== null

  const run = async (kind: Exclude<Busy, null>, action: () => Promise<void>) => {
    setBusy(kind)
    setError(null)
    setConfirm(null)
    try {
      await action()
      return true
    } catch (err) {
      setError(friendlyError(err))
      return false
    } finally {
      setBusy(null)
    }
  }

  /** Save text edits. Returns true when Buffer is in sync with `text`. */
  const persistText = async (): Promise<boolean> => {
    if (!dirty) return true
    const result = await boardApi.updateText(postRefs, text)
    const failures = failuresIn(result)
    if (failures.length > 0) {
      setError(failures[0])
      return false
    }
    setSavedText(text)
    return true
  }

  const save = () =>
    run("save", async () => {
      const ok = await persistText()
      if (ok) {
        setEditing(false)
        notify("Changes saved")
        onChanged()
      }
    })

  const rewrite = () =>
    run("rewrite", async () => {
      const result = await boardApi.rewriteText(ids[0], text, instruction)
      setText(result.text)
      setInstruction("")
    })

  const uploadImage = (file: File) =>
    run("upload", async () => {
      const result = await boardApi.replaceImage(postRefs, file)
      const failures = failuresIn(result)
      if (failures.length > 0) {
        setError(failures[0])
        return
      }
      if (result.image_url) setImageUrl(result.image_url)
      notify("Image updated")
      onChanged()
    })

  const aiEditImage = () =>
    run("ai-image", async () => {
      if (!imageUrl) return
      const result = await boardApi.aiEditImage(postRefs, imageUrl, imageInstruction)
      const failures = failuresIn(result)
      if (failures.length > 0) {
        setError(failures[0])
        return
      }
      if (result.image_url) setImageUrl(result.image_url)
      setImageInstruction("")
      notify("Image edited with AI")
      onChanged()
    })

  const accept = () =>
    run("accept", async () => {
      // The current text always rides along with the schedule edit: Buffer
      // rejects update inputs that change neither text nor media ("Post must
      // have either text or media"), so a text-less schedule edit can fail.
      const result = await boardApi.acceptPosts(postRefs, due, text)
      const failures = failuresIn(result)
      if (failures.length > 0) {
        setError(failures[0])
        return
      }
      setSavedText(text)
      setEditing(false)
      const when = result.scheduled_at ?? due
      notify(`Scheduled for ${formatDueAt(when) || "the next slot"}`)
      onOpenChange(false)
      onAccepted()
    })

  const remove = () =>
    run("delete", async () => {
      const result = await boardApi.deletePosts(postRefs)
      const failures = failuresIn(result)
      if (failures.length > 0) {
        setError(failures[0])
        return
      }
      notify("Post deleted")
      onOpenChange(false)
      onChanged()
    })

  /** Intercept closing while there are unsaved edits. */
  const handleOpenChange = (next: boolean) => {
    if (!next && dirty && !pending && confirm === null) {
      setConfirm("discard")
      return
    }
    setConfirm(null)
    onOpenChange(next)
  }

  const cancelEdit = () => {
    setText(savedText)
    setInstruction("")
    setEditing(false)
    setError(null)
  }

  const busyLabel: Record<Exclude<Busy, null>, string> = {
    save: "Saving…",
    rewrite: "Asking AI to edit…",
    upload: "Uploading image…",
    "ai-image": "Editing image with AI…",
    accept: "Scheduling…",
    delete: "Deleting…",
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange} className="max-w-3xl">
      <div className="flex">
        <div className="bg-muted/40 shrink-0 border-r">
          {/* `h-full` all the way down keeps the pane (and therefore the
              skeleton box) at real size while the image is still decoding. */}
          <div className="relative h-full">
            {imageUrl ? (
              <SkeletonImage
                src={imageUrl}
                alt=""
                className="h-full"
                imgClassName="h-full max-h-[60vh] w-72 object-contain"
              />
            ) : (
              <div className="flex h-64 w-72 items-center justify-center">
                <p className="text-muted-foreground text-sm">No image</p>
              </div>
            )}
            {/* Cover the previous render while the replacement is in flight. */}
            {busy === "upload" && (
              <Skeleton className="absolute inset-0 rounded-none" />
            )}
          </div>
          {editing && (
            <div className="border-t space-y-2 p-3">
              <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="hidden"
                disabled={pending}
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  event.target.value = ""
                  if (file) uploadImage(file)
                }}
              />
              <Button
                variant="outline"
                size="sm"
                className="w-full"
                disabled={pending}
                onClick={() => fileInputRef.current?.click()}
              >
                {busy === "upload" ? <Loader2 className="animate-spin" /> : null}
                {imageUrl ? "Replace image…" : "Add image…"}
              </Button>
              {imageUrl && (
                <div className="flex gap-2">
                  <input
                    className="border-input bg-background min-w-0 flex-1 rounded-md border px-2 py-1.5 text-xs focus:outline-none"
                    placeholder='Edit the image with AI, e.g. "make the sky golden hour"'
                    value={imageInstruction}
                    onChange={(event) => setImageInstruction(event.target.value)}
                    disabled={pending}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && imageInstruction.trim() && !pending)
                        aiEditImage()
                    }}
                  />
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={pending || !imageInstruction.trim()}
                    title="AI will edit the current image using this instruction"
                    onClick={aiEditImage}
                  >
                    {busy === "ai-image" ? <Loader2 className="animate-spin" /> : null}
                    Apply
                  </Button>
                </div>
              )}
            </div>
          )}
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-4 p-5">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              {Array.from(
                new Set(
                  group.posts
                    .map((p) => channelFor(p, channels)?.service)
                    .filter((s): s is string => Boolean(s)),
                ),
              ).map((service) => (
                <PlatformIcon key={service} service={service} className="size-5" />
              ))}
              <span className="text-muted-foreground text-xs">
                {group.posts.length} {group.posts.length === 1 ? "post" : "posts"}
              </span>
            </div>
            {due && (
              <time
                className={`text-sm font-semibold tabular-nums ${
                  dueStale ? "text-destructive" : ""
                }`}
                title={dueStale ? "This time has already passed" : undefined}
              >
                {formatDueAt(due)}
                {dueStale ? " (missed)" : ""}
              </time>
            )}
          </div>

          {editing ? (
            <div className="flex min-w-0 flex-1 flex-col gap-3">
              <div className="relative min-h-40 flex-1">
                <textarea
                  className={cn(
                    "border-input bg-background h-full w-full resize-y rounded-md border p-3 text-sm leading-relaxed focus:outline-none",
                    busy === "rewrite" && "text-transparent caret-transparent",
                  )}
                  value={text}
                  onChange={(event) => setText(event.target.value)}
                  disabled={pending}
                />
                {/* The AI rewrite blanks the draft until the new copy lands. */}
                {busy === "rewrite" && (
                  <div className="absolute inset-0 flex flex-col gap-2 p-3">
                    <Skeleton className="h-3.5 w-full" />
                    <Skeleton className="h-3.5 w-11/12" />
                    <Skeleton className="h-3.5 w-9/12" />
                    <Skeleton className="h-3.5 w-full" />
                    <Skeleton className="h-3.5 w-7/12" />
                  </div>
                )}
              </div>
              <p
                className={`text-right text-xs tabular-nums ${
                  overLimit ? "text-destructive" : "text-muted-foreground"
                }`}
              >
                {charCount}/{MAX_CHARS}
              </p>
              <div className="flex gap-2">
                <input
                  className="border-input bg-background min-w-0 flex-1 rounded-md border px-3 py-2 text-sm focus:outline-none"
                  placeholder='Ask for changes, e.g. "make it shorter and friendlier"'
                  value={instruction}
                  onChange={(event) => setInstruction(event.target.value)}
                  disabled={pending}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && instruction.trim() && !pending) rewrite()
                  }}
                />
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={rewrite}
                  disabled={pending || !instruction.trim() || overLimit}
                  title="AI will rewrite the text above using this instruction"
                >
                  {busy === "rewrite" ? <Loader2 className="animate-spin" /> : null}
                  Apply
                </Button>
              </div>
            </div>
          ) : (
            <p className="text-sm whitespace-pre-line leading-relaxed">{text}</p>
          )}

          {error && (
            <div className="bg-destructive/10 text-destructive rounded-md px-3 py-2 text-sm">
              {error}
            </div>
          )}

          {confirm === "accept" && (
            <div className="bg-accent/40 rounded-md px-3 py-2.5 text-sm">
              <p className="font-medium">
                Publish {group.posts.length > 1 ? `to ${group.posts.length} channels` : "this post"}
                {dirty ? " with your edited text" : ""}?
              </p>
              <p className="text-muted-foreground mt-1">
                {dueStale
                  ? "The original time has passed, so it will publish at the next Mon/Wed/Fri 8:30 AM slot."
                  : `It is scheduled for ${formatDueAt(due)}.`}
              </p>
            </div>
          )}
          {confirm === "delete" && (
            <div className="bg-destructive/10 rounded-md px-3 py-2.5 text-sm">
              <p className="text-destructive font-medium">
                Delete this post from Buffer? This can't be undone.
              </p>
            </div>
          )}
          {confirm === "discard" && (
            <div className="bg-accent/40 rounded-md px-3 py-2.5 text-sm">
              <p className="font-medium">Discard your unsaved changes?</p>
            </div>
          )}

          <div className="mt-auto flex items-center gap-2 pt-2">
            {pending && <span className="text-muted-foreground text-sm">{busyLabel[busy]}</span>}
            <div className="ml-auto flex items-center gap-2">
              {confirm === null && !pending && (
                <Button variant="outline" size="sm" onClick={() => setConfirm("delete")}>
                  Delete
                </Button>
              )}
              {confirm === "delete" && (
                <Button variant="outline" size="sm" onClick={() => setConfirm(null)} disabled={pending}>
                  Keep post
                </Button>
              )}
              {confirm === "delete" && (
                <Button variant="destructive" size="sm" onClick={remove} disabled={pending}>
                  {busy === "delete" ? <Loader2 className="animate-spin" /> : null}
                  Delete forever
                </Button>
              )}
              {editing ? (
                <>
                  <Button variant="outline" size="sm" onClick={cancelEdit} disabled={pending}>
                    Cancel
                  </Button>
                  <Button size="sm" onClick={save} disabled={pending || overLimit}>
                    {busy === "save" ? <Loader2 className="animate-spin" /> : null}
                    Save
                  </Button>
                </>
              ) : confirm === null ? (
                <>
                  <Button variant="outline" size="sm" onClick={() => setEditing(true)} disabled={pending}>
                    Edit
                  </Button>
                  <Button size="sm" onClick={() => setConfirm("accept")} disabled={pending}>
                    Accept &amp; schedule
                  </Button>
                </>
              ) : confirm === "accept" ? (
                <>
                  <Button variant="outline" size="sm" onClick={() => setConfirm(null)} disabled={pending}>
                    Not yet
                  </Button>
                  <Button size="sm" onClick={accept} disabled={pending || overLimit}>
                    {busy === "accept" ? <Loader2 className="animate-spin" /> : null}
                    {dueStale ? "Reschedule & publish" : "Yes, schedule it"}
                  </Button>
                </>
              ) : (
                <>
                  <Button variant="outline" size="sm" onClick={() => setConfirm(null)} disabled={pending}>
                    Keep editing
                  </Button>
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => {
                      setText(savedText)
                      setConfirm(null)
                      handleOpenChange(false)
                    }}
                    disabled={pending}
                  >
                    Discard changes
                  </Button>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </Dialog>
  )
}