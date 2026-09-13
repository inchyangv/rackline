import { ExternalLink } from 'lucide-react'
import { getTxExplorerUrl } from '@/lib/explorer'
import { shortHash } from '@/lib/format'
import { cn } from '@/lib/utils'

const linkClass =
  'num inline-flex items-center gap-1 text-bone-2 underline decoration-rule-strong underline-offset-2 hover:text-bone hover:decoration-bone'

/** Creditcoin (EVM) transaction. */
export function TxLink({ hash, className }: { hash: string; className?: string }) {
  const url = getTxExplorerUrl(hash)

  if (!url) return <span className={cn('num break-all', className)}>{shortHash(hash)}</span>

  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      title={hash}
      className={cn(linkClass, className)}
    >
      {shortHash(hash)}
      <ExternalLink aria-hidden="true" className="size-3" strokeWidth={1.5} />
    </a>
  )
}
