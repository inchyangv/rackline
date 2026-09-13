import { EmptyState } from '@/components/shared/empty-state'
import { TxLink } from '@/components/shared/explorer-link'
import { Money } from '@/components/shared/money'
import { Reason } from '@/components/shared/reason'
import { Section } from '@/components/shared/section'
import { Skeleton } from '@/components/ui/skeleton'
import { useStatement } from '@/hooks/use-statement'
import { STABLECOIN_SYMBOL } from '@/lib/constants'

type Props = {
  address: string
  decimals: number
}

const headCell = 'py-2 text-left text-xs font-medium text-bone-2'
const headCellRight = 'py-2 text-right text-xs font-medium text-bone-2'

export function Statement({ address, decimals }: Props) {
  const { entries, isLoading, error } = useStatement(address)

  return (
    <Section title="Statement" description="Source: on-chain events via Blockscout.">
      {error ? (
        <Reason tone="warn">{error}</Reason>
      ) : isLoading && entries.length === 0 ? (
        <div className="space-y-2 py-2">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      ) : entries.length === 0 ? (
        <EmptyState title="No draws or repayments yet." />
      ) : (
        // `relative` keeps the sr-only column name inside the scroll port instead
        // of stretching the page; the tabIndex lets a keyboard scroll it.
        <div
          className="relative overflow-x-auto"
          tabIndex={0}
          role="region"
          aria-label="Statement entries"
        >
          <table className="w-full min-w-[32rem] border-collapse text-[13px]">
            <thead>
              <tr className="border-b border-rule">
                <th scope="col" className={headCell}>
                  Block
                </th>
                <th scope="col" className={headCell}>
                  Entry
                </th>
                <th scope="col" className={headCellRight}>
                  {`Debit (${STABLECOIN_SYMBOL})`}
                </th>
                <th scope="col" className={headCellRight}>
                  {`Credit (${STABLECOIN_SYMBOL})`}
                </th>
                <th scope="col" className={headCellRight}>
                  {`Balance (${STABLECOIN_SYMBOL})`}
                </th>
                <th scope="col" className={headCellRight}>
                  <span className="sr-only">Transaction</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {entries.map((entry) => (
                <tr key={`${entry.txHash}-${entry.logIndex}`}>
                  <td className="num py-2 text-bone-2">{entry.block}</td>
                  <td className="py-2 text-bone">{entry.kind === 'draw' ? 'Draw' : 'Repay'}</td>
                  <td className="py-2 text-right text-bone">
                    {entry.kind === 'draw' ? (
                      <Money value={entry.amount} decimals={decimals} unit={null} />
                    ) : null}
                  </td>
                  <td className="py-2 text-right text-bone">
                    {entry.kind === 'repay' ? (
                      <Money value={entry.amount} decimals={decimals} unit={null} />
                    ) : null}
                  </td>
                  <td className="py-2 text-right text-bone-2">
                    <Money value={entry.balance} decimals={decimals} unit={null} />
                  </td>
                  <td className="py-2 text-right">
                    <TxLink hash={entry.txHash} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  )
}
