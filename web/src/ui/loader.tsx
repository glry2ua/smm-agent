"use client";

import * as ProgressBarPrimitives from "react-aria-components/ProgressBar";

import { IconLoader2 } from "@tabler/icons-react";
import { cn } from "@/lib/utils";

interface LoaderProps extends ProgressBarPrimitives.ProgressBarProps {}

function Loader({ className, ...props }: LoaderProps) {
  return (
    <ProgressBarPrimitives.ProgressBar
      data-loader=""
      className={cn(
        "inline-flex shrink-0 items-center justify-center",
        className,
      )}
      aria-label="loading..."
      {...props}
      isIndeterminate
    >
      <IconLoader2
        role="status"
        aria-label="Loading"
        className={cn("size-4 animate-spin")}
      />
    </ProgressBarPrimitives.ProgressBar>
  );
}

export type { LoaderProps };
export { Loader };
