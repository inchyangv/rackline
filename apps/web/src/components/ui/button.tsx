import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Loader2 } from "lucide-react"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md text-[13px] font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 aria-disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        // A dead filled button recesses to ink-2 instead of going translucent:
        // bone at 50% is the largest bright mass on the page. `aria-disabled`
        // gets the same treatment so a page can keep the control focusable and
        // explain itself with a <Reason>.
        default:
          "bg-bone text-ink-0 hover:bg-bone-2 disabled:bg-ink-2 disabled:text-bone-3 disabled:opacity-100 aria-disabled:bg-ink-2 aria-disabled:text-bone-3 aria-disabled:opacity-100 aria-disabled:hover:bg-ink-2",
        secondary:
          "border border-rule-strong bg-ink-2 text-bone hover:bg-ink-3",
        outline:
          "border border-rule-strong bg-transparent text-bone hover:bg-ink-2",
        ghost: "bg-transparent text-bone-2 hover:bg-ink-2 hover:text-bone",
        destructive:
          "border border-err/40 bg-transparent text-err hover:bg-err/10",
        link: "bg-transparent text-bone-2 underline underline-offset-4 hover:text-bone",
      },
      size: {
        default: "h-9 px-4 has-[>svg]:px-3",
        sm: "h-8 gap-1.5 px-3 has-[>svg]:px-2.5",
        lg: "h-10 px-6 has-[>svg]:px-4",
        icon: "size-9",
        "icon-sm": "size-8",
        "icon-lg": "size-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  loading = false,
  disabled,
  children,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
    loading?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      data-loading={loading || undefined}
      aria-busy={loading || undefined}
      disabled={disabled || loading}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    >
      {loading && !asChild ? (
        <>
          <Loader2 className="animate-spin" strokeWidth={1.5} aria-hidden />
          {children}
        </>
      ) : (
        children
      )}
    </Comp>
  )
}

export { Button }
