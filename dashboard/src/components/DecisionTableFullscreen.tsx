import { Maximize2, Minimize2 } from "lucide-react";
import {
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type FullscreenMode = "inline" | "native" | "fallback";

export interface DecisionTableFullscreenState {
  isFullscreen: boolean;
}

interface DecisionTableFullscreenProps {
  label: string;
  children:
    | ReactNode
    | ((state: DecisionTableFullscreenState) => ReactNode);
  className?: string;
  contentClassName?: string;
}

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

function focusableElements(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) => !element.hidden && element.getAttribute("aria-hidden") !== "true",
  );
}

function inertOutside(root: HTMLElement): () => void {
  const previous = new Map<HTMLElement, boolean>();
  let current: HTMLElement = root;
  while (current.parentElement) {
    const parent = current.parentElement;
    for (const sibling of Array.from(parent.children)) {
      if (sibling === current || !(sibling instanceof HTMLElement)) continue;
      if (!previous.has(sibling)) previous.set(sibling, Boolean(sibling.inert));
      sibling.inert = true;
    }
    current = parent;
  }
  return () => {
    for (const [element, wasInert] of previous) element.inert = wasInert;
  };
}

export function DecisionTableFullscreen({
  label,
  children,
  className,
  contentClassName,
}: DecisionTableFullscreenProps) {
  const [mode, setMode] = useState<FullscreenMode>("inline");
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const priorFocusRef = useRef<HTMLElement | null>(null);
  const modeRef = useRef(mode);
  const isFullscreen = mode !== "inline";
  modeRef.current = mode;

  useEffect(() => {
    const handleFullscreenChange = () => {
      const ownsFullscreen = document.fullscreenElement === rootRef.current;
      if (ownsFullscreen) setMode("native");
      else if (modeRef.current === "native") setMode("inline");
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  useEffect(() => {
    if (!isFullscreen) return;
    triggerRef.current?.focus();
  }, [isFullscreen]);

  useEffect(() => {
    if (mode === "inline" || !rootRef.current) return;
    const root = rootRef.current;
    const priorBodyOverflow = document.body.style.overflow;
    const restoreInert = inertOutside(root);
    const isFallback = mode === "fallback";
    if (isFallback) document.body.style.overflow = "hidden";

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && isFallback) {
        event.preventDefault();
        setMode("inline");
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = focusableElements(root);
      if (focusable.length === 0) {
        event.preventDefault();
        root.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      if (isFallback) document.body.style.overflow = priorBodyOverflow;
      restoreInert();
    };
  }, [mode]);

  useEffect(() => {
    if (isFullscreen) return;
    const priorFocus = priorFocusRef.current;
    if (priorFocus?.isConnected) priorFocus.focus();
    priorFocusRef.current = null;
  }, [isFullscreen]);

  useEffect(() => {
    const root = rootRef.current;
    return () => {
      if (document.fullscreenElement === root && document.exitFullscreen) {
        void document.exitFullscreen().catch(() => undefined);
      }
    };
  }, []);

  const enterFullscreen = async () => {
    const root = rootRef.current;
    if (!root) return;
    priorFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (typeof root.requestFullscreen !== "function") {
      setMode("fallback");
      return;
    }
    try {
      await root.requestFullscreen();
      if (document.fullscreenElement === root) setMode("native");
    } catch {
      setMode("fallback");
    }
  };

  const exitFullscreen = async () => {
    if (mode === "fallback") {
      setMode("inline");
      return;
    }
    if (document.fullscreenElement !== rootRef.current) {
      setMode("inline");
      return;
    }
    try {
      await document.exitFullscreen?.();
    } catch {
      // The browser remains authoritative. A later fullscreenchange will reconcile state.
    }
  };

  const handleRootKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape" && mode === "fallback") {
      event.preventDefault();
      setMode("inline");
    }
  };

  return (
    <div
      ref={rootRef}
      role={isFullscreen ? "dialog" : undefined}
      aria-modal={isFullscreen ? true : undefined}
      aria-label={isFullscreen ? `${label} fullscreen` : undefined}
      tabIndex={isFullscreen ? -1 : undefined}
      data-fullscreen-mode={mode}
      onKeyDown={handleRootKeyDown}
      className={cn(
        "relative flex min-w-0 flex-col overflow-hidden rounded-md border bg-background",
        isFullscreen &&
          "fixed inset-0 z-[100] h-[100dvh] w-[100dvw] overflow-hidden rounded-none border-0 p-[max(0.5rem,env(safe-area-inset-top))_max(0.5rem,env(safe-area-inset-right))_max(0.5rem,env(safe-area-inset-bottom))_max(0.5rem,env(safe-area-inset-left))]",
        className,
      )}
    >
      <div className="flex shrink-0 items-center justify-end border-b bg-background/95 p-1.5">
        <Button
          ref={triggerRef}
          type="button"
          variant="ghost"
          size="icon"
          className="size-10 touch-manipulation motion-reduce:transition-none motion-reduce:active:translate-y-0"
          aria-label={`${isFullscreen ? "Exit" : "Enter"} ${label} fullscreen`}
          title={`${isFullscreen ? "Exit" : "Open"} ${label} fullscreen`}
          onClick={() => void (isFullscreen ? exitFullscreen() : enterFullscreen())}
        >
          {isFullscreen ? (
            <Minimize2 className="size-4" aria-hidden="true" />
          ) : (
            <Maximize2 className="size-4" aria-hidden="true" />
          )}
        </Button>
      </div>
      <div
        className={cn(
          "min-h-0 min-w-0",
          isFullscreen && "flex flex-1 flex-col overflow-hidden",
          contentClassName,
        )}
      >
        {typeof children === "function" ? children({ isFullscreen }) : children}
      </div>
    </div>
  );
}
