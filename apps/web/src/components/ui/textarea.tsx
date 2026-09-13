import * as React from "react"

import { cn } from "@/lib/utils"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "field-sizing-content flex min-h-20 w-full rounded-md border border-rule-strong bg-ink-1 px-3 py-2 text-sm text-bone transition-colors",
        "placeholder:text-bone-3 selection:bg-bone selection:text-ink-0",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "aria-invalid:border-err",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
