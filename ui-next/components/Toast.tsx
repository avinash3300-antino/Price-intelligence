"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { CheckCircle2, XCircle, X } from "lucide-react";

type ToastKind = "success" | "error";
interface ToastItem {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastContextValue {
  success: (message: string) => void;
  error: (message: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const AUTO_DISMISS_MS = 4000;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setItems((xs) => xs.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (kind: ToastKind, message: string) => {
      const id = nextId.current++;
      setItems((xs) => [...xs, { id, kind, message }]);
      // Auto-dismiss. Multi-toast stacks each keep their own timer.
      window.setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
    },
    [dismiss],
  );

  const value: ToastContextValue = {
    success: (m) => push("success", m),
    error: (m) => push("error", m),
  };

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="fixed top-5 right-5 z-[100] flex flex-col gap-2 pointer-events-none">
        {items.map((t) => (
          <ToastCard key={t.id} item={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastCard({
  item,
  onDismiss,
}: {
  item: ToastItem;
  onDismiss: () => void;
}) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    // trigger enter animation next tick
    const t = window.setTimeout(() => setVisible(true), 10);
    return () => window.clearTimeout(t);
  }, []);

  const isSuccess = item.kind === "success";
  const Icon = isSuccess ? CheckCircle2 : XCircle;
  const styles = isSuccess
    ? {
        bg: "bg-[#FFF4ED]",
        border: "border-[#FED7AA]",
        icon: "text-[#C2410C]",
        text: "text-[#9A3412]",
      }
    : {
        bg: "bg-[#FBEAE8]",
        border: "border-[#F1C7C2]",
        icon: "text-[#B5342C]",
        text: "text-[#7A2119]",
      };

  return (
    <div
      role={isSuccess ? "status" : "alert"}
      className={`pointer-events-auto flex items-start gap-2.5  border shadow-[0_6px_20px_rgba(20,25,35,0.12)] pl-3 pr-2 py-2.5 min-w-[260px] max-w-[420px] ${styles.bg} ${styles.border} ${styles.text} transition-all duration-200 ${visible ? "opacity-100 translate-x-0" : "opacity-0 translate-x-3"}`}
    >
      <Icon className={`w-4 h-4 mt-0.5 shrink-0 ${styles.icon}`} strokeWidth={2.5} />
      <div className="text-[13px] leading-snug font-medium flex-1">
        {item.message}
      </div>
      <button
        type="button"
        onClick={onDismiss}
        className="text-current opacity-50 hover:opacity-100 p-0.5 -mr-1"
        aria-label="Dismiss"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be called inside <ToastProvider>");
  }
  return ctx;
}
