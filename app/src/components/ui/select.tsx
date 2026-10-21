import { Check, ChevronDown } from "lucide-react";
import { Select as SelectPrimitive } from "radix-ui";
import type * as React from "react";
import { cn } from "@/lib/utils";

export interface Option {
  value: string;
  label: React.ReactNode;
  description?: React.ReactNode;
  disabled?: boolean;
}

/** A single-value dropdown in the studio style. */
export function Select({
  value,
  onValueChange,
  options,
  placeholder = "Select…",
  className,
  disabled,
  id,
  size = "md",
}: {
  value: string | undefined;
  onValueChange: (value: string) => void;
  options: Option[];
  placeholder?: string;
  className?: string;
  disabled?: boolean;
  id?: string;
  size?: "sm" | "md";
}) {
  return (
    <SelectPrimitive.Root value={value ?? ""} onValueChange={onValueChange} disabled={disabled}>
      <SelectPrimitive.Trigger
        id={id}
        className={cn(
          "inline-flex w-full items-center justify-between gap-2 rounded-[10px] border border-rule-strong bg-panel px-3.5 text-left text-[14.5px] text-ink shadow-control outline-none transition-[background-color,border-color,box-shadow] hover:bg-panel-2 focus:border-ink-3 focus:ring-4 focus:ring-panel-3 disabled:opacity-50 data-[placeholder]:text-ink-3",
          size === "sm" ? "h-8 rounded-lg px-3 text-[13px]" : "h-11",
          className,
        )}
      >
        <span className="truncate">
          <SelectPrimitive.Value placeholder={placeholder} />
        </span>
        <SelectPrimitive.Icon>
          <ChevronDown className="size-4 text-ink-3" />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          position="popper"
          sideOffset={6}
          className="z-50 max-h-80 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-xl border border-rule bg-panel shadow-pop"
        >
          <SelectPrimitive.Viewport className="p-1">
            {options.map((option) => (
              <SelectPrimitive.Item
                key={option.value}
                value={option.value}
                disabled={option.disabled}
                className="relative flex cursor-pointer select-none flex-col rounded-lg py-2 pl-3 pr-8 text-[14px] text-ink outline-none data-[disabled]:cursor-not-allowed data-[highlighted]:bg-panel-2 data-[disabled]:opacity-45"
              >
                <SelectPrimitive.ItemText>{option.label}</SelectPrimitive.ItemText>
                {option.description && <span className="text-xs text-ink-3">{option.description}</span>}
                <SelectPrimitive.ItemIndicator className="absolute right-2 top-2">
                  <Check className="size-4" />
                </SelectPrimitive.ItemIndicator>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}
