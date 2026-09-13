import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Tabs as TabsPrimitive } from "radix-ui"

import { cn } from "@/lib/utils"

function Tabs({
  className,
  orientation = "horizontal",
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      data-orientation={orientation}
      orientation={orientation}
      className={cn(
        "group/tabs flex gap-2 data-[orientation=horizontal]:flex-col",
        className
      )}
      {...props}
    />
  )
}

// The list inherits its host surface so "active is one step lighter" holds
// on the ink-0 page ground and inside the ink-1 action block alike.
const SEGMENTED =
  "inline-grid grid-flow-col auto-cols-fr w-full h-9 p-0 rounded-md border border-rule-strong bg-transparent overflow-hidden"

const tabsListVariants = cva("group/tabs-list items-center justify-center", {
  variants: {
    variant: {
      default: SEGMENTED,
      segmented: SEGMENTED,
      line: "inline-flex w-fit gap-4 rounded-none bg-transparent group-data-[orientation=vertical]/tabs:h-fit group-data-[orientation=vertical]/tabs:flex-col group-data-[orientation=vertical]/tabs:items-start",
    },
  },
  defaultVariants: {
    variant: "default",
  },
})

function TabsList({
  className,
  variant = "default",
  ...props
}: React.ComponentProps<typeof TabsPrimitive.List> &
  VariantProps<typeof tabsListVariants>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      data-variant={variant === "line" ? "line" : "segmented"}
      className={cn(tabsListVariants({ variant }), className)}
      {...props}
    />
  )
}

function TabsTrigger({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        "relative inline-flex items-center justify-center gap-1.5 rounded-none text-[13px] font-medium whitespace-nowrap text-bone-2 transition-colors hover:text-bone disabled:pointer-events-none disabled:opacity-50 data-[state=active]:text-bone [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        // segmented (also the default): flush cells divided by a hairline
        "group-data-[variant=segmented]/tabs-list:h-full group-data-[variant=segmented]/tabs-list:border-rule group-data-[variant=segmented]/tabs-list:px-3 group-data-[variant=segmented]/tabs-list:data-[state=active]:bg-ink-2 group-data-[variant=segmented]/tabs-list:[&+&]:border-l",
        // line: plain text, no surface, 2px signal rule under the active item
        "group-data-[variant=line]/tabs-list:py-2",
        "after:absolute after:bg-signal after:opacity-0 group-data-[orientation=horizontal]/tabs:after:inset-x-0 group-data-[orientation=horizontal]/tabs:after:bottom-0 group-data-[orientation=horizontal]/tabs:after:h-0.5 group-data-[orientation=vertical]/tabs:after:inset-y-0 group-data-[orientation=vertical]/tabs:after:-right-1 group-data-[orientation=vertical]/tabs:after:w-0.5 group-data-[variant=line]/tabs-list:data-[state=active]:after:opacity-100",
        className
      )}
      {...props}
    />
  )
}

function TabsContent({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      data-slot="tabs-content"
      className={cn("flex-1", className)}
      {...props}
    />
  )
}

export { Tabs, TabsList, TabsTrigger, TabsContent }
