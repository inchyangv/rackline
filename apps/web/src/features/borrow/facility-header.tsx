import { useEffect, useRef, useState } from 'react'
import { AddressDisplay } from '@/components/shared/address-display'
import { Reason } from '@/components/shared/reason'
import { Section } from '@/components/shared/section'
import { Tag } from '@/components/shared/tag'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { Facility } from '@/hooks/use-facility'
import { sameAddress } from '@/lib/format'

type Props = {
  viewed: string
  facility: Facility
  walletAccount: string
  onView: (address: string, following: boolean) => void
}

export function FacilityHeader({ viewed, facility, walletAccount, onView }: Props) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])

  const hasAddress = facility.state !== 'no-address'
  const canViewOwn = Boolean(walletAccount) && !sameAddress(viewed, walletAccount)
  // With nothing to look at, the address field is the primary control: keep it open.
  const showInput = editing || !hasAddress

  function toggleEditing() {
    setDraft(viewed)
    setEditing((open) => !open)
  }

  // Blur commits but leaves the field open, so the `Change` button can close it
  // without the blur that precedes the click reopening it.
  function commit(close: boolean) {
    const next = draft.trim()
    if (close) setEditing(false)
    if (!next || next === viewed) return
    onView(next, false)
  }

  return (
    <Section eyebrow="Facility">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        {hasAddress ? <AddressDisplay address={viewed} explorer label="facility" /> : null}
        {facility.tag ? <Tag tone={facility.tag.tone}>{facility.tag.label}</Tag> : null}
        {facility.paused ? <Tag tone="warn">Paused</Tag> : null}
        <span className="ml-auto flex items-center gap-1">
          {hasAddress ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-expanded={editing}
              onClick={toggleEditing}
            >
              Change
            </Button>
          ) : null}
          {canViewOwn ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => onView(walletAccount, true)}
            >
              View my facility
            </Button>
          ) : null}
        </span>
      </div>

      {showInput ? (
        <Input
          ref={inputRef}
          className="num mt-3"
          value={draft}
          placeholder="Facility address (0x…)"
          aria-label="Facility address"
          autoComplete="off"
          spellCheck={false}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => commit(false)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit(true)
          }}
        />
      ) : null}

      {hasAddress ? null : (
        <Reason className="mt-2">Connect a wallet, or enter an address, to view a facility.</Reason>
      )}
    </Section>
  )
}
