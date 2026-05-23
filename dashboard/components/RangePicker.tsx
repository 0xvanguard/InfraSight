"use client";

import { RANGE_PRESETS, type RangePreset } from "../lib/types";

interface Props {
  value: RangePreset;
  onChange: (next: RangePreset) => void;
  /** Auto-refresh activo. */
  autoRefresh: boolean;
  onToggleAutoRefresh: (next: boolean) => void;
}

export function RangePicker({
  value,
  onChange,
  autoRefresh,
  onToggleAutoRefresh,
}: Props) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="inline-flex overflow-hidden rounded border border-border">
        {RANGE_PRESETS.map((preset) => {
          const active = preset.key === value;
          return (
            <button
              key={preset.key}
              type="button"
              onClick={() => onChange(preset.key)}
              className={`px-3 py-1.5 text-xs font-medium transition ${
                active
                  ? "bg-accent/20 text-accent"
                  : "bg-surface text-muted hover:text-foreground"
              }`}
            >
              {preset.label}
            </button>
          );
        })}
      </div>
      <label className="inline-flex items-center gap-2 text-xs text-muted">
        <input
          type="checkbox"
          className="accent-accent"
          checked={autoRefresh}
          onChange={(e) => onToggleAutoRefresh(e.target.checked)}
        />
        Auto-refresh (30 s)
      </label>
    </div>
  );
}
