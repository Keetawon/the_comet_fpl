import { Coffee } from "lucide-react";
import { Button } from "@/components/ui/button";

/** Owner-provided destination; payment handling stays on Buy Me a Coffee. */
export function SupportButton() {
  return (
    <Button
      asChild
      variant="outline"
      className="h-10 w-full gap-2 border-amber-300 bg-amber-50 text-amber-950 hover:bg-amber-100 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100 dark:hover:bg-amber-900 max-md:px-0"
    >
      <a
        href="https://buymeacoffee.com/thecomet"
        target="_blank"
        rel="noopener noreferrer"
        aria-label="Buy Me a Coffee (opens in a new tab)"
        title="Buy Me a Coffee (opens in a new tab)"
      >
        <Coffee className="size-4" aria-hidden />
        <span className="max-md:hidden">Buy Me a Coffee</span>
      </a>
    </Button>
  );
}
