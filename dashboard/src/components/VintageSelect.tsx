// Vintage (run) selector: every export carries ALL recorded forecast vintages, so each
// exploratory page shows exactly one run at a time. Default = the default-architecture
// run referenced by the default optimizer plan.

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { VintageOption } from "@/lib/vintage";

interface VintageSelectProps {
  options: VintageOption[];
  value: string;
  onChange: (runId: string) => void;
}

export function VintageSelect({ options, value, onChange }: VintageSelectProps) {
  if (options.length <= 1) return null;
  return (
    <div className="flex items-center gap-2 text-sm text-muted-foreground">
      <span>Vintage</span>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger size="sm" className="w-64" aria-label="Forecast vintage">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.runId} value={option.runId}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
