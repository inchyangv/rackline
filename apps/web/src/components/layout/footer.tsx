export function Footer() {
  return (
    <footer className="mt-3.5 px-1 py-2">
      <p className="text-xs text-muted-foreground leading-relaxed">
        This UI is a "thin operations dashboard". SPV proof generation and checkpoint-registration
        automation are handled in prover/bridge API tickets (T1.7-T1.14).
      </p>
    </footer>
  )
}
