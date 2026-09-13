import { Check, Copy, ExternalLink } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { copyToClipboard } from '@/lib/clipboard'
import { getAddressExplorerUrl } from '@/lib/explorer'
import { shortAddr } from '@/lib/format'
import { cn } from '@/lib/utils'

type Props = {
  address: string
  short?: boolean
  mono?: boolean
  explorer?: boolean
  /** What the address is, for accessible names: "Copy Vault address". */
  label?: string
  className?: string
}

export function AddressDisplay({
  address,
  short = true,
  mono = true,
  explorer = false,
  label,
  className,
}: Props) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    await copyToClipboard(address)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  if (!address) return <span className="text-bone-3">—</span>

  const explorerUrl = explorer ? getAddressExplorerUrl(address) : ''

  return (
    <span className={cn('inline-flex items-center gap-1.5', className)}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span tabIndex={0} className={cn('text-[13px] break-all', mono && 'num')}>
            {short ? shortAddr(address) : address}
          </span>
        </TooltipTrigger>
        <TooltipContent>
          <span className="num break-all">{address}</span>
        </TooltipContent>
      </Tooltip>
      <Button
        type="button"
        variant="ghost"
        size="icon-sm"
        className="shrink-0"
        aria-label={label ? `Copy ${label} address` : 'Copy address'}
        onClick={handleCopy}
      >
        {copied ? (
          <Check aria-hidden="true" className="size-3.5 text-ok" strokeWidth={1.5} />
        ) : (
          <Copy aria-hidden="true" className="size-3.5" strokeWidth={1.5} />
        )}
      </Button>
      <span role="status" className="sr-only">
        {copied ? 'Address copied' : ''}
      </span>
      {explorerUrl ? (
        <a
          href={explorerUrl}
          target="_blank"
          rel="noreferrer"
          aria-label={label ? `View ${label} address on explorer` : 'View address on explorer'}
          className="inline-flex size-8 shrink-0 items-center justify-center rounded-md text-bone-2 hover:bg-ink-2 hover:text-bone"
        >
          <ExternalLink aria-hidden="true" className="size-3.5" strokeWidth={1.5} />
        </a>
      ) : null}
    </span>
  )
}
