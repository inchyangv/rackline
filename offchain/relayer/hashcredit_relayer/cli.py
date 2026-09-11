"""
CLI entry point for HashCredit Relayer.
"""

from pathlib import Path
from typing import Optional

import typer
import structlog

from .config import RelayerConfig
from .relayer import HashCreditRelayer

# Configure structlog
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)

app = typer.Typer(
    name="hashcredit-relayer",
    help="HashCredit Bitcoin Payout Relayer",
    add_completion=False,
)


@app.command()
def run(
    config_path: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to .env configuration file",
    ),
    once: bool = typer.Option(
        False,
        "--once",
        help="Run once and exit (useful for testing)",
    ),
    btc_address: Optional[str] = typer.Option(
        None,
        "--btc-address",
        help="Bitcoin address to watch",
    ),
    evm_address: Optional[str] = typer.Option(
        None,
        "--evm-address",
        help="EVM address of the borrower",
    ),
) -> None:
    """
    Start the relayer to watch Bitcoin payouts and submit proofs to EVM.
    """
    # Load config
    config = RelayerConfig.from_env(config_path)

    # Add watched borrower if provided
    if btc_address and evm_address:
        config.add_borrower(evm_address=evm_address, btc_address=btc_address)
        typer.echo(f"Watching BTC address: {btc_address} -> EVM: {evm_address}")

    if not config.watched_borrowers:
        typer.echo("Warning: No borrowers to watch. Use --btc-address and --evm-address to add one.")

    # Create relayer
    relayer = HashCreditRelayer(config)

    if once:
        typer.echo("Running in single-shot mode...")
        results = relayer.run_once()
        for result in results:
            if result.success:
                typer.echo(f"✓ Submitted: {result.tx_hash}")
            else:
                typer.echo(f"✗ Failed: {result.error}")
        typer.echo(f"Processed {len(results)} payouts")
    else:
        typer.echo("Running in continuous mode. Press Ctrl+C to stop.")
        try:
            relayer.run()
        except KeyboardInterrupt:
            typer.echo("\nStopping relayer...")
            relayer.stop()


@app.command()
def check(
    btc_address: str = typer.Argument(..., help="Bitcoin address to check"),
    api_url: str = typer.Option(
        "https://mempool.space/api",
        "--api",
        help="Bitcoin API URL",
    ),
    confirmations: int = typer.Option(
        6,
        "--confirmations",
        "-c",
        help="Minimum confirmations required",
    ),
) -> None:
    """
    Check payouts to a Bitcoin address (without submitting).
    """
    from .bitcoin import BitcoinApiClient

    client = BitcoinApiClient(api_url)

    typer.echo(f"Checking payouts to: {btc_address}")
    typer.echo(f"Minimum confirmations: {confirmations}")
    typer.echo("")

    payouts = client.find_payouts_to_address(btc_address, confirmations)

    if not payouts:
        typer.echo("No confirmed payouts found.")
        return

    typer.echo(f"Found {len(payouts)} confirmed payouts:\n")

    for tx, output in payouts:
        typer.echo(f"  TXID: {tx.txid}")
        typer.echo(f"  VOUT: {output.vout}")
        typer.echo(f"  Amount: {output.value_sats} sats ({output.value_sats / 1e8:.8f} BTC)")
        typer.echo(f"  Block: {tx.block_height}")
        typer.echo(f"  Confirmations: {tx.confirmations}")
        typer.echo("")

    client.close()


@app.command()
def version() -> None:
    """Show the relayer version."""
    from hashcredit_relayer import __version__
    typer.echo(f"hashcredit-relayer v{__version__}")


def main() -> None:
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
