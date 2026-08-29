import { cn } from "@/lib/utils"

/**
 * Tinted with `foreground` rather than `accent`/`muted`: those tokens are the
 * same lightness as the page background, so blocks on them were invisible.
 */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      aria-hidden
      data-slot="skeleton"
      className={cn(
        "bg-foreground/10 motion-reduce:animate-none animate-pulse rounded-md",
        className,
      )}
      {...props}
    />
  )
}

export { Skeleton }
