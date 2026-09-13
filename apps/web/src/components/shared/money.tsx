import { Figure } from '@/components/shared/figure'
import { STABLECOIN_SYMBOL } from '@/lib/constants'
import { exactAmount, formatAmount } from '@/lib/format'
import { cn } from '@/lib/utils'

type Props = {
  value: bigint | null | undefined
  decimals: number
  /** Unit rendered after the figure in sans, bone-2. Pass `null` to omit. */
  unit?: string | null
  fractionDigits?: number
  className?: string
}

/**
 * A money figure: truncated, grouped, mono, kerned separators, unit after in
 * sans — with the exact value one hover away. Renders "—" for null.
 */
export function Money({ value, decimals, unit = STABLECOIN_SYMBOL, fractionDigits = 2, className }: Props) {
  const text = formatAmount(value, decimals, { fractionDigits })
  return (
    <span className={cn('whitespace-nowrap', className)} title={value == null ? undefined : `${exactAmount(value, decimals)}${unit ? ` ${unit}` : ''}`}>
      <span className="num">
        <Figure>{text}</Figure>
      </span>
      {unit ? <span className="font-sans text-bone-2"> {unit}</span> : null}
    </span>
  )
}
