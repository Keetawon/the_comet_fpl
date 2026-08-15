// Light/dark theme toggle: class on <html>, persisted, default from the OS preference.

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
  const dark = document.documentElement.classList.contains("dark");
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label="Toggle theme"
      onClick={() => applyTheme(!dark)}
    >
      {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </Button>
  );
}
