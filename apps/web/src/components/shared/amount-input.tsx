import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** Token scale used when a call site does not pass one. */
const DEFAULT_DECIMALS = 6

/**
 * Digits and at most one decimal point; commas are read as decimal points.
 * The fraction is truncated to the token's scale as the reader types, so a
 * pasted 18-dp value cannot turn into "Enter a valid amount."
 */
function sanitize(raw: string, decimals: number): string {
  let out = ''
  let dot = false
  let frac = 0
  for (const ch of raw.replace(/,/g, '.')) {
    if (ch >= '0' && ch <= '9') {
      if (dot) {
        if (frac >= decimals) continue
        frac += 1
      }
      out += ch
    } else if (ch === '.' && !dot && decimals > 0) {
      out += ch
      dot = true
    }
  }
  return out
}

type Props = {
  id?: string
  value: string
  onChange: (v: string) => void
  /** Token scale; fraction digits beyond it are dropped while typing. */
  decimals?: number
  unit?: string
  max?: { label: string; onClick: () => void; disabled?: boolean }
  disabled?: boolean
  invalid?: boolean
  placeholder?: string
  'aria-label'?: string
}

export function AmountInput({
  id,
  value,
  onChange,
  decimals = DEFAULT_DECIMALS,
  unit,
  max,
  disabled,
  invalid,
  placeholder = '0.00',
  'aria-label': ariaLabel,
}: Props) {
  return (
    <div
      className={cn(
        'flex items-center rounded-md border bg-ink-1',
        'focus-within:outline-2 focus-within:outline-offset-0 focus-within:outline-signal',
        invalid ? 'border-err' : 'border-rule-strong',
        disabled && 'opacity-60',
      )}
    >
      <input
        id={id}
        type="text"
        inputMode="decimal"
        pattern="[0-9]*[.,]?[0-9]*"
        autoComplete="off"
        spellCheck={false}
        disabled={disabled}
        aria-invalid={invalid || undefined}
        aria-label={ariaLabel}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(sanitize(e.target.value, decimals))}
        className="num h-11 min-w-0 flex-1 bg-transparent px-3 text-base font-medium text-bone outline-none placeholder:text-bone-3"
      />
      {unit ? <span className="pr-3 text-[13px] text-bone-2">{unit}</span> : null}
      {max ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="mr-1.5 shrink-0"
          disabled={disabled || max.disabled}
          onClick={max.onClick}
        >
          {max.label}
        </Button>
      ) : null}
    </div>
  )
}
