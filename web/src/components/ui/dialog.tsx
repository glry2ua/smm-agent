import * as React from "react"

import { cn } from "@/lib/utils"

function Dialog({
  open,
  onOpenChange,
  className,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  className?: string
  children: React.ReactNode
}) {
  React.useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onOpenChange(false)
    }
    document.addEventListener("keydown", onKey)
    document.body.style.overflow = "hidden"
    return () => {
      document.removeEventListener("keydown", onKey)
      document.body.style.overflow = ""
    }
  }, [open, onOpenChange])

  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
    >
      <div
        className="absolute inset-0 bg-black/50"
        onClick={() => onOpenChange(false)}
      />
      <div
        className={cn(
          "relative z-10 max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border bg-card text-card-foreground shadow-lg",
          className,
        )}
      >
        {children}
      </div>
    </div>
  )
}

export { Dialog }