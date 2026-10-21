import { cva, type VariantProps } from "class-variance-authority";
import {
  DropdownMenu as DropdownPrimitive,
  Progress as ProgressPrimitive,
  Tabs as TabsPrimitive,
  Tooltip as TooltipPrimitive,
} from "radix-ui";
import type * as React from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-2xl border border-rule bg-panel shadow-card", className)} {...props} />;
}

export function SectionTitle({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="text-[15px] font-semibold">{children}</h2>
      {action}
    </div>
  );
}

const badgeVariants = cva("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px] font-medium", {
  variants: {
    tone: {
      neutral: "bg-panel-2 text-ink-2",
      green: "bg-green-soft text-green",
      red: "bg-red-soft text-red",
      amber: "bg-amber-soft text-amber",
      blue: "bg-blue-soft text-blue",
      ink: "bg-accent text-accent-ink",
    },
  },
  defaultVariants: { tone: "neutral" },
});

export function Badge({
  className,
  tone,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

export function Progress({ value, className }: { value: number | null; className?: string }) {
  return (
    <ProgressPrimitive.Root
      className={cn("relative h-1.5 w-full overflow-hidden rounded-full bg-panel-3", className)}
      value={value ?? undefined}
    >
      <ProgressPrimitive.Indicator
        className={cn(
          "h-full rounded-full bg-accent transition-[width] duration-300",
          value === null && "w-1/3 animate-pulse",
        )}
        style={value === null ? undefined : { width: `${Math.max(2, Math.min(100, value))}%` }}
      />
    </ProgressPrimitive.Root>
  );
}

export function Tooltip({ content, children }: { content: React.ReactNode; children: React.ReactNode }) {
  return (
    <TooltipPrimitive.Root delayDuration={300}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          sideOffset={6}
          className="z-50 max-w-xs rounded-lg bg-accent px-2.5 py-1.5 text-xs text-accent-ink shadow-pop"
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

export const TooltipProvider = TooltipPrimitive.Provider;

export function Tabs({
  value,
  onValueChange,
  tabs,
  className,
}: {
  value: string;
  onValueChange: (value: string) => void;
  tabs: { value: string; label: React.ReactNode }[];
  className?: string;
}) {
  return (
    <TabsPrimitive.Root value={value} onValueChange={onValueChange}>
      <TabsPrimitive.List className={cn("inline-flex gap-1 rounded-full bg-panel-2 p-1", className)}>
        {tabs.map((tab) => (
          <TabsPrimitive.Trigger
            key={tab.value}
            value={tab.value}
            className="rounded-full px-3 py-1 text-[13px] font-medium text-ink-2 transition-colors data-[state=active]:bg-panel data-[state=active]:text-ink data-[state=active]:shadow-card"
          >
            {tab.label}
          </TabsPrimitive.Trigger>
        ))}
      </TabsPrimitive.List>
    </TabsPrimitive.Root>
  );
}

export const DropdownMenu = DropdownPrimitive.Root;
export const DropdownTrigger = DropdownPrimitive.Trigger;

export function DropdownContent({ children, align = "end" }: { children: React.ReactNode; align?: "start" | "end" }) {
  return (
    <DropdownPrimitive.Portal>
      <DropdownPrimitive.Content
        align={align}
        sideOffset={6}
        className="z-50 min-w-48 rounded-xl border border-rule bg-panel p-1 shadow-pop"
      >
        {children}
      </DropdownPrimitive.Content>
    </DropdownPrimitive.Portal>
  );
}

export function DropdownItem({
  children,
  onSelect,
  danger,
  disabled,
}: {
  children: React.ReactNode;
  onSelect: () => void;
  danger?: boolean;
  disabled?: boolean;
}) {
  return (
    <DropdownPrimitive.Item
      onSelect={onSelect}
      disabled={disabled}
      className={cn(
        "flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-sm outline-none data-[disabled]:cursor-not-allowed data-[highlighted]:bg-panel-2 data-[disabled]:opacity-45 [&_svg]:size-4",
        danger ? "text-red" : "text-ink",
      )}
    >
      {children}
    </DropdownPrimitive.Item>
  );
}

export function DropdownLabel({ children }: { children: React.ReactNode }) {
  return <DropdownPrimitive.Label className="px-2.5 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-ink-3">{children}</DropdownPrimitive.Label>;
}

export function DropdownSeparator() {
  return <DropdownPrimitive.Separator className="my-1 h-px bg-rule" />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-lg bg-panel-2", className)} />;
}

export function EmptyState({
  icon,
  title,
  children,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-rule-strong px-6 py-14 text-center">
      {icon && <div className="text-ink-3 [&_svg]:size-7">{icon}</div>}
      <div>
        <p className="font-medium">{title}</p>
        {children && <p className="mx-auto mt-1 max-w-md text-[13px] text-ink-2">{children}</p>}
      </div>
      {action}
    </div>
  );
}

export function Callout({
  tone = "neutral",
  icon,
  children,
  className,
}: {
  tone?: "neutral" | "amber" | "red" | "green" | "blue";
  icon?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  const tones = {
    neutral: "bg-panel-2 text-ink-2",
    amber: "bg-amber-soft text-amber",
    red: "bg-red-soft text-red",
    green: "bg-green-soft text-green",
    blue: "bg-blue-soft text-blue",
  };
  return (
    <div className={cn("flex items-start gap-2.5 rounded-xl px-3.5 py-2.5 text-[13px]", tones[tone], className)}>
      {icon && <span className="mt-0.5 [&_svg]:size-4">{icon}</span>}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
