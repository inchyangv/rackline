import * as React from "react"

import { cn } from "@/lib/utils"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-9 w-full min-w-0 rounded-md border border-rule-strong bg-ink-1 px-3 text-sm text-bone transition-colors",
        "placeholder:text-bone-3 selection:bg-bone selection:text-ink-0",
        "file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-bone",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "aria-invalid:border-err",
        className
      )}
      {...props}
    />
  )
}

export { Input }
