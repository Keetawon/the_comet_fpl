import { useId, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Search } from "lucide-react";
import { Popover } from "radix-ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface MultiSelectOption<T extends string | number> {
  value: T;
  label: string;
  /** Extra case-insensitive terms accepted by the optional search field. */
  searchText?: string;
}

interface MultiSelectFilterProps<T extends string | number> {
  label: string;
  ariaLabel: string;
  allLabel: string;
  options: readonly MultiSelectOption<T>[];
  selected: readonly T[];
  onChange: (selected: T[]) => void;
  searchable?: boolean;
  searchLabel?: string;
  emptyLabel?: string;
  className?: string;
}

function normaliseSearch(value: string): string {
  return value.trim().toLocaleLowerCase();
}

/**
 * Compact checkbox popover used for OR-within / AND-across table filtering. An empty
 * selection deliberately means "all" so clearing a dimension never creates an empty table.
 */
export function MultiSelectFilter<T extends string | number>({
  label,
  ariaLabel,
  allLabel,
  options,
  selected,
  onChange,
  searchable = false,
  searchLabel = `Search ${label.toLocaleLowerCase()}`,
  emptyLabel = "No matching options",
  className,
}: MultiSelectFilterProps<T>) {
  const id = useId();
  const searchRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const selectedOptions = options.filter((option) => selectedSet.has(option.value));
  const normalisedQuery = normaliseSearch(query);
  const visibleOptions = normalisedQuery
    ? options.filter((option) =>
        normaliseSearch(`${option.label} ${option.searchText ?? ""}`).includes(normalisedQuery),
      )
    : options;
  const triggerText =
    selectedOptions.length === 0
      ? allLabel
      : selectedOptions.length === 1
        ? selectedOptions[0].label
        : `${selectedOptions.length} selected`;

  const toggle = (value: T, checked: boolean) => {
    const next = new Set(selected);
    if (checked) next.add(value);
    else next.delete(value);
    // Preserve the authoritative option order instead of click order.
    onChange(options.filter((option) => next.has(option.value)).map((option) => option.value));
  };

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span>{label}</span>
      <Popover.Root
        open={open}
        onOpenChange={(nextOpen) => {
          setOpen(nextOpen);
          if (!nextOpen) setQuery("");
        }}
      >
        <Popover.Trigger asChild>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="min-w-28 max-w-44 justify-between font-normal"
            aria-label={`${ariaLabel}: ${triggerText}`}
          >
            <span className="truncate" title={triggerText}>{triggerText}</span>
            <ChevronDown className="size-3.5 opacity-60" aria-hidden />
          </Button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content
            align="start"
            sideOffset={4}
            role="dialog"
            aria-label={`${label} choices`}
            onOpenAutoFocus={(event) => {
              if (!searchable) return;
              event.preventDefault();
              searchRef.current?.focus();
            }}
            className="z-50 w-72 rounded-lg border bg-popover p-2 text-popover-foreground shadow-md outline-none"
          >
            <div className="flex items-center justify-between gap-2 px-1 pb-2">
              <p className="text-xs font-medium">
                {selectedOptions.length === 0 ? allLabel : `${selectedOptions.length} selected`}
              </p>
              <Button
                type="button"
                variant="ghost"
                size="xs"
                disabled={selectedOptions.length === 0}
                onClick={() => onChange([])}
              >
                Clear
              </Button>
            </div>
            {searchable && (
              <div className="relative mb-2">
                <Search
                  className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground"
                  aria-hidden
                />
                <Input
                  ref={searchRef}
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  aria-label={searchLabel}
                  placeholder={searchLabel}
                  autoComplete="off"
                  className="pl-8"
                />
              </div>
            )}
            <div
              className="max-h-64 overflow-y-auto overscroll-contain"
              role="group"
              aria-label={`${label} options`}
            >
              {visibleOptions.length === 0 ? (
                <p role="status" className="px-2 py-4 text-center text-xs text-muted-foreground">
                  {emptyLabel}
                </p>
              ) : (
                visibleOptions.map((option) => {
                  const optionId = `${id}-${String(option.value)}`;
                  const checked = selectedSet.has(option.value);
                  return (
                    <label
                      key={String(option.value)}
                      htmlFor={optionId}
                      className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent hover:text-accent-foreground"
                    >
                      <span className="relative grid size-4 shrink-0 place-items-center">
                        <input
                          id={optionId}
                          type="checkbox"
                          checked={checked}
                          onChange={(event) => toggle(option.value, event.target.checked)}
                          className="peer size-4 appearance-none rounded border border-input bg-background outline-none focus-visible:ring-2 focus-visible:ring-ring/50 checked:border-primary checked:bg-primary"
                        />
                        <Check
                          className="pointer-events-none absolute size-3 text-primary-foreground opacity-0 peer-checked:opacity-100"
                          aria-hidden
                        />
                      </span>
                      <span className="min-w-0 truncate" title={option.label}>
                        {option.label}
                      </span>
                    </label>
                  );
                })
              )}
            </div>
            <Popover.Arrow className="fill-border" aria-hidden />
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  );
}
