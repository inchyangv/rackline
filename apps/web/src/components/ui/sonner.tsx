import type { CSSProperties } from "react"
import {
  CircleCheckIcon,
  InfoIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon,
} from "lucide-react"
import { Toaster as Sonner, type ToasterProps } from "sonner"

const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      theme="dark"
      className="toaster group"
      icons={{
        success: <CircleCheckIcon className="size-4" strokeWidth={1.5} />,
        info: <InfoIcon className="size-4" strokeWidth={1.5} />,
        warning: <TriangleAlertIcon className="size-4" strokeWidth={1.5} />,
        error: <OctagonXIcon className="size-4" strokeWidth={1.5} />,
        loading: (
          <Loader2Icon className="size-4 animate-spin" strokeWidth={1.5} />
        ),
      }}
      style={
        {
          "--normal-bg": "var(--ink-1)",
          "--normal-text": "var(--bone)",
          "--normal-border": "var(--rule-strong)",
          "--border-radius": "4px",
          "--font-family": "var(--font-sans)",
        } as CSSProperties
      }
      toastOptions={{
        classNames: {
          toast: "shadow-none text-sm",
          description: "text-bone-3",
          success: "[&_[data-icon]]:text-ok",
          error: "[&_[data-icon]]:text-err",
          warning: "[&_[data-icon]]:text-warn",
          loading: "[&_[data-icon]]:text-signal",
        },
      }}
      {...props}
    />
  )
}

export { Toaster }
