// Light/dark theme toggle: class on <html>, persisted, default from the OS preference.

import { useState } from "react";
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";

function applyTheme(dark: boolean) {
  document.documentElement.classList.toggle("dark", dark);
  localStorage.setItem("theme", dark ? "dark" : "light");
}

export function initTheme() {
  const stored = localStorage.getItem("theme");
  const dark = stored ? stored === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(dark);
}

export function ThemeToggle() {
  // Local state: applyTheme mutates the document, which alone never re-renders, so the
  // icon and the next toggle must track it here rather than re-reading at render time.
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="Toggle theme"
      aria-pressed={dark}
      onClick={() => {
        applyTheme(!dark);
        setDark(!dark);
      }}
    >
      {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </Button>
  );
}
