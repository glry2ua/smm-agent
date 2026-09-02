import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { cn } from "@/lib/utils";

interface Toast {
  id: number;
  message: string;
  tone?: "info" | "error";
}

export type Notify = (message: string, tone?: "info" | "error") => void;

const ToastContext = createContext<Notify>(() => {});

export function useToast(): Notify {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextToastId = useRef(1);

  const notify = useCallback<Notify>((message, tone = "info") => {
    const id = nextToastId.current++;
    setToasts((prev) => [...prev, { id, message, tone }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 5000);
  }, []);

  return (
    <ToastContext.Provider value={notify}>
      {children}
      <div className="pointer-events-none fixed bottom-6 left-1/2 z-[60] flex -translate-x-1/2 flex-col items-center gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={cn(
              "rounded-full px-4 py-2 text-sm font-medium shadow-lg",
              toast.tone === "error"
                ? "bg-danger text-fg-on-danger"
                : "bg-primary text-fg-on-primary",
            )}
          >
            {toast.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
