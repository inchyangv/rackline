import { Copy, Check } from 'lucide-react'
import { useState } from 'react'
import { shortAddr } from '@/lib/format'
import { copyToClipboard } from '@/lib/clipboard'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { Button } from '@/components/ui/button'

type Props = {
  address: string
  short?: boolean
  mono?: boolean
  className?: string
}

export function AddressDisplay({ address, short = true, mono = true, className }: Props) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    await copyToClipboard(address)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  if (!address) return <span className="text-muted-foreground">—</span>

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={`inline-flex items-center gap-1.5 ${className ?? ''}`}>
          <span className={mono ? 'font-mono text-xs' : 'text-xs'}>
            {short ? shortAddr(address) : address}
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="h-5 w-5 shrink-0"
            onClick={handleCopy}
          >
            {copied ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3" />}
          </Button>
        </span>
      </TooltipTrigger>
      <TooltipContent>
        <p className="font-mono text-xs break-all max-w-[320px]">{address}</p>
      </TooltipContent>
    </Tooltip>
  )
}
