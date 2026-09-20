// Light/dark theme toggle: class on <html>, persisted, default from the OS preference.

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";

function applyTheme(dark: boolean) {
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
}

function preferredDarkTheme(): boolean {
  try {
    const stored = localStorage.getItem("theme");
    if (stored === "dark" || stored === "light") return stored === "dark";
  } catch {
    // Restricted browser storage must not prevent changing the current page theme.
  }
  return typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function initTheme() {
  applyTheme(preferredDarkTheme());
}

export function ThemeToggle() {
  // App initializes the document in an effect, after this child's first render. Read
  // the same preference here so a saved dark theme does not make the first click a no-op.
  const [dark, setDark] = useState(preferredDarkTheme);
  useEffect(() => applyTheme(dark), [dark]);
  const label = dark ? "Switch to light theme" : "Switch to dark theme";
  return (
    <Button
      variant="ghost"
      size="icon"
      className="size-11 rounded-full"
      aria-label={label}
      title={label}
      aria-pressed={dark}
      onClick={() => {
        const next = !dark;
        setDark(next);
        try {
          localStorage.setItem("theme", next ? "dark" : "light");
        } catch {
          // The choice still works for this page when persistence is unavailable.
        }
      }}
    >
      {dark ? <Sun className="size-5" /> : <Moon className="size-5" />}
    </Button>
  );
}
