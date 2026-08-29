import { useState } from "react"

import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"

type ImgProps = Omit<React.ComponentProps<"img">, "src" | "className" | "alt">

/**
 * An `<img>` that keeps a skeleton in its place until the bytes have actually
 * painted, so remote Buffer assets never flash or shove the layout around.
 */
export function SkeletonImage({
  src,
  alt = "",
  className,
  imgClassName,
  ...imgProps
}: ImgProps & {
  src: string
  alt?: string
  /** Classes for the box the image sits in (skeleton fills exactly this). */
  className?: string
  imgClassName?: string
}) {
  // Track *which* src finished, not a boolean: a new src falls back to the
  // skeleton on its own. A boolean reset from an effect could clear a load
  // that already happened (StrictMode re-runs effects; cached images only
  // fire `load` once), which pinned every thumbnail to the skeleton.
  const [loadedSrc, setLoadedSrc] = useState<string | null>(null)
  const loaded = loadedSrc === src
  const markLoaded = () => setLoadedSrc(src)

  return (
    <div className={cn("relative overflow-hidden", className)}>
      {!loaded && <Skeleton className="absolute inset-0 rounded-none" />}
      <img
        src={src}
        alt={alt}
        ref={(node) => {
          // `complete` means the request has settled — decoded (cached: no
          // load event is coming) or failed. Either way, stop pulsing.
          if (node?.complete) markLoaded()
        }}
        onLoad={markLoaded}
        onError={markLoaded}
        className={cn("relative", !loaded && "invisible", imgClassName)}
        {...imgProps}
      />
    </div>
  )
}
