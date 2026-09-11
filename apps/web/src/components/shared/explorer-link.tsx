import { ExternalLink } from 'lucide-react'
import { getBtcTxExplorerUrl } from '@/lib/explorer'
import { shortAddr } from '@/lib/format'

type Props = {
  txid: string
  className?: string
}

export function ExplorerLink({ txid, className }: Props) {
  const txidHex = txid.replace(/^0x/, '')
  const url = getBtcTxExplorerUrl(txidHex)

  if (!url) {
    return <span className={`font-mono text-xs ${className ?? ''}`}>{txid}</span>
  }

  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      className={`inline-flex items-center gap-1 font-mono text-xs text-primary hover:text-primary/80 underline underline-offset-2 ${className ?? ''}`}
    >
      {shortAddr(`0x${txidHex}`)}
      <ExternalLink className="h-3 w-3" />
    </a>
  )
}
