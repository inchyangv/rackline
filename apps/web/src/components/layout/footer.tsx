export function Footer() {
  return (
    <footer className="mt-3.5 px-1 py-2 flex flex-wrap items-center justify-between gap-x-6 gap-y-1">
      <p className="text-xs text-muted-foreground leading-relaxed">
        &copy; {new Date().getFullYear()} HashCredit. Built on HashKey Chain.
      </p>
      <p className="text-xs text-muted-foreground leading-relaxed">
        <span className="font-medium text-foreground/60">mUSDT</span> = Mock USDT (testnet
        stablecoin, no real value)
      </p>
    </footer>
  )
}
