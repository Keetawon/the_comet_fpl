import { Coffee, X } from "lucide-react";
import { Popover } from "radix-ui";
import { Button } from "@/components/ui/button";

/** No payment URL or third-party widget until the owner has a verified account. */
export function SupportButton() {
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <Button
          type="button"
          variant="outline"
          aria-label="Buy Me a Coffee"
          title="Buy Me a Coffee — coming soon"
          className="h-10 w-full gap-2 border-amber-300 bg-amber-50 text-amber-950 hover:bg-amber-100 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100 dark:hover:bg-amber-900 max-md:px-0"
        >
          <Coffee className="size-4" aria-hidden />
          <span className="max-md:hidden">Buy Me a Coffee</span>
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side="right"
          align="end"
          sideOffset={8}
          collisionPadding={12}
          aria-label="Support THE COMET"
          className="z-50 w-72 max-w-[calc(100vw-5rem)] rounded-xl border bg-popover p-4 text-popover-foreground shadow-lg outline-none"
        >
          <div className="flex items-center justify-between gap-2">
            <p className="text-sm font-semibold">Thanks for supporting THE COMET</p>
            <Popover.Close asChild>
              <Button variant="ghost" size="icon-sm" aria-label="Close support message">
                <X aria-hidden />
              </Button>
            </Popover.Close>
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            Our support page is coming soon. Payments are not available yet.
          </p>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
