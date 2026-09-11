import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { cn } from '@/lib/utils'

type Props = {
  title: string
  description?: string
  full?: boolean
  children: React.ReactNode
  className?: string
}

export function SectionCard({ title, description, full, children, className }: Props) {
  return (
    <Card
      className={cn(
        'border-border/40 bg-gradient-to-br from-[rgba(12,19,41,0.82)] to-[rgba(14,28,52,0.68)]',
        'shadow-[0_14px_32px_rgba(3,9,22,0.38),inset_0_1px_0_rgba(182,209,255,0.05)]',
        'transition-all duration-200 hover:border-primary/30 hover:-translate-y-0.5',
        full && 'col-span-full',
        className,
      )}
    >
      <CardHeader className="pb-3">
        <CardTitle className="text-sm tracking-wide text-foreground/90">{title}</CardTitle>
        {description && (
          <CardDescription className="text-xs text-muted-foreground">{description}</CardDescription>
        )}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}
