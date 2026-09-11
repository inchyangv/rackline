"""
CLI entry point for HashCredit Relayer.

This module provides the command-line interface for running the relayer.
"""

import typer

app = typer.Typer(
    name="hashcredit-relayer",
    help="HashCredit Bitcoin Payout Relayer",
    add_completion=False,
)


@app.command()
def run(
    config_path: str = typer.Option(
        ".env",
        "--config",
        "-c",
        help="Path to configuration file",
    ),
    once: bool = typer.Option(
        False,
        "--once",
        help="Run once and exit (useful for testing)",
    ),
) -> None:
    """
    Start the relayer to watch Bitcoin payouts and submit proofs to EVM.
    """
    typer.echo(f"HashCredit Relayer starting with config: {config_path}")
    typer.echo("Implementation pending - see T0.8 ticket")

    if once:
        typer.echo("Running in single-shot mode...")
    else:
        typer.echo("Running in continuous mode...")

    # TODO: Implement in T0.8
    typer.echo("Relayer skeleton ready. Full implementation in T0.8.")


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
