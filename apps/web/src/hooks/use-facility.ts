import { useMemo } from 'react'
import { ethers } from 'ethers'
import { BorrowerStatus, useBorrowerInfo } from './use-borrower-info'
import { useManagerReads } from './use-manager-reads'
import { useVaultInfo } from './use-vault-info'
import { useConfigStore } from '@/stores/config-store'

export type FacilityState =
  | 'no-address'
  | 'not-registered'
  | 'limit-not-set'
  | 'undrawn'
  | 'drawn'
  | 'frozen'
  | 'closed'

export type Facility = {
  address: string
  state: FacilityState
  tag: { label: string; tone: 'neutral' | 'ok' | 'warn' | 'err' | 'signal' } | null
  paused: boolean | null
  isBtcLinked: boolean
  /** Outstanding principal (info.currentDebt), interest excluded. */
  principal: bigint | null
  accruedInterest: bigint | null
  /** Principal + accrued interest as of the last block. */
  totalOwed: bigint | null
  creditLimit: bigint | null
  /** Credit limit less total owed, floored at zero (getAvailableCredit). */
  undrawnLimit: bigint | null
  poolLiquidity: bigint | null
  /** min(undrawnLimit, poolLiquidity) — what can actually be drawn right now. */
  drawableNow: bigint | null
  borrowAprBps: bigint | null
  walletBalance: bigint | null
  decimals: number
  /** principal / creditLimit, 0…1. Null when either is unknown or the limit is 0. */
  gauge: number | null
  isLoading: boolean
  error: string | null
}

const TAGS: Record<Exclude<FacilityState, 'no-address'>, NonNullable<Facility['tag']>> = {
  'not-registered': { label: 'Not registered', tone: 'neutral' },
  'limit-not-set': { label: 'Registered · limit not set', tone: 'warn' },
  undrawn: { label: 'Limit granted · undrawn', tone: 'ok' },
  drawn: { label: 'Drawn', tone: 'signal' },
  frozen: { label: 'Frozen', tone: 'warn' },
  closed: { label: 'Closed', tone: 'err' },
}

function minBigint(a: bigint | null, b: bigint | null): bigint | null {
  if (a === null || b === null) return null
  return a < b ? a : b
}

function ratio(part: bigint | null, whole: bigint | null): number | null {
  if (part === null || whole === null || whole <= 0n) return null
  const scaled = Number((part * 10_000n) / whole) / 10_000
  if (!Number.isFinite(scaled)) return null
  return Math.min(1, Math.max(0, scaled))
}

/**
 * Everything the Borrow page needs about one facility, read from chain.
 * Unknown values stay `null` — callers must not substitute zeros.
 */
export function useFacility(address: string): Facility {
  const configStablecoin = useConfigStore((s) => s.stablecoinAddress)
  const { stablecoin, paused } = useManagerReads()
  const borrower = useBorrowerInfo(address, stablecoin || configStablecoin)
  const vault = useVaultInfo()

  const {
    borrowerInfo: info,
    availableCredit,
    currentDebt,
    accruedInterest,
    stablecoinBalance,
    stablecoinDecimals,
    isBtcLinked,
  } = borrower

  return useMemo(() => {
    const hasAddress = ethers.isAddress(address)
    const principal = info ? info.currentDebt : null
    const creditLimit = info ? info.creditLimit : null

    let state: FacilityState
    if (!hasAddress) state = 'no-address'
    else if (!info || info.status === BorrowerStatus.None) state = 'not-registered'
    else if (info.status === BorrowerStatus.Frozen) state = 'frozen'
    else if (info.status === BorrowerStatus.Closed) state = 'closed'
    else if (creditLimit === 0n) state = 'limit-not-set'
    else if (principal === 0n) state = 'undrawn'
    else state = 'drawn'

    // An unregistered address still returns a zeroed struct, so a missing
    // struct means "not read yet / read failed" — show no tag rather than a
    // status we cannot vouch for.
    const tag = state === 'no-address' || !info ? null : TAGS[state]

    const poolLiquidity = vault.availableLiquidity
    const undrawnLimit = hasAddress ? availableCredit : null

    return {
      address,
      state,
      tag,
      paused,
      isBtcLinked,
      principal,
      accruedInterest: hasAddress ? accruedInterest : null,
      totalOwed: hasAddress ? currentDebt : null,
      creditLimit,
      undrawnLimit,
      poolLiquidity,
      drawableNow: minBigint(undrawnLimit, poolLiquidity),
      borrowAprBps: vault.borrowAPR,
      walletBalance: hasAddress ? stablecoinBalance : null,
      decimals: stablecoinDecimals,
      gauge: ratio(principal, creditLimit),
      isLoading: borrower.isLoading || vault.isLoading,
      error: borrower.error ?? vault.error ?? null,
    }
  }, [
    address,
    info,
    paused,
    isBtcLinked,
    availableCredit,
    currentDebt,
    accruedInterest,
    stablecoinBalance,
    stablecoinDecimals,
    borrower.isLoading,
    borrower.error,
    vault.availableLiquidity,
    vault.borrowAPR,
    vault.isLoading,
    vault.error,
  ])
}
