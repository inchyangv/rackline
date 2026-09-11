"""
CLI for HashCredit Prover.
"""

import asyncio
import json
import os
from typing import Optional

import typer
from dotenv import load_dotenv

from .rpc import BitcoinRPC, BitcoinRPCConfig
from .proof_builder import ProofBuilder

app = typer.Typer(
    name="hashcredit-prover",
    help="HashCredit Bitcoin SPV Proof Builder",
)


def main() -> None:
    """Entry point."""
    load_dotenv()
    app()


@app.command()
def build_proof(
    txid: str = typer.Argument(..., help="Transaction ID (display format)"),
    output_index: int = typer.Argument(..., help="Output index (vout)"),
    checkpoint_height: int = typer.Argument(..., help="Checkpoint block height"),
    target_height: int = typer.Argument(..., help="Target block height"),
    borrower: str = typer.Argument(..., help="Borrower EVM address"),
    rpc_url: Optional[str] = typer.Option(
        None, "--rpc-url", "-r", envvar="BITCOIN_RPC_URL", help="Bitcoin RPC URL"
    ),
    rpc_user: Optional[str] = typer.Option(
        None, "--rpc-user", "-u", envvar="BITCOIN_RPC_USER", help="Bitcoin RPC user"
    ),
    rpc_password: Optional[str] = typer.Option(
        None, "--rpc-password", "-p", envvar="BITCOIN_RPC_PASSWORD", help="Bitcoin RPC password"
    ),
    output_file: Optional[str] = typer.Option(
        None, "--output", "-o", help="Output file for proof JSON"
    ),
    hex_output: bool = typer.Option(False, "--hex", help="Output ABI-encoded hex for contract"),
) -> None:
    """
    Build an SPV proof for a Bitcoin transaction.

    Example:
        hashcredit-prover build-proof \\
            abc123...txid... 0 800000 800006 0x1234...borrower
    """

    async def _build() -> None:
        config = BitcoinRPCConfig(
            url=rpc_url or os.getenv("BITCOIN_RPC_URL", "http://localhost:8332"),
            user=rpc_user or os.getenv("BITCOIN_RPC_USER", ""),
            password=rpc_password or os.getenv("BITCOIN_RPC_PASSWORD", ""),
        )

        rpc = BitcoinRPC(config)
        builder = ProofBuilder(rpc)

        typer.echo(f"Building proof for transaction {txid}...")
        typer.echo(f"  Output index: {output_index}")
        typer.echo(f"  Checkpoint: {checkpoint_height}")
        typer.echo(f"  Target block: {target_height}")
        typer.echo(f"  Borrower: {borrower}")

        try:
            result = await builder.build_proof(
                txid=txid,
                output_index=output_index,
                checkpoint_height=checkpoint_height,
                target_height=target_height,
                borrower=borrower,
            )

            typer.echo("\nProof built successfully!")
            typer.echo(f"  Amount: {result.amount_sats} sats")
            typer.echo(f"  Script type: {result.script_type}")
            typer.echo(f"  Block height: {result.block_height}")
            typer.echo(f"  Block timestamp: {result.block_timestamp}")
            typer.echo(f"  Header chain length: {len(result.proof.headers)}")
            typer.echo(f"  Merkle proof depth: {len(result.proof.merkle_proof)}")

            if hex_output:
                encoded = result.proof.encode_for_contract()
                typer.echo(f"\nABI-encoded proof (for verifyPayout):")
                typer.echo(f"0x{encoded.hex()}")
            else:
                proof_dict = result.proof.to_dict()
                proof_json = json.dumps(proof_dict, indent=2)

                if output_file:
                    with open(output_file, "w") as f:
                        f.write(proof_json)
                    typer.echo(f"\nProof saved to {output_file}")
                else:
                    typer.echo(f"\nProof JSON:")
                    typer.echo(proof_json)

        except Exception as e:
            typer.echo(f"Error building proof: {e}", err=True)
            raise typer.Exit(1)

    asyncio.run(_build())


@app.command()
def verify_local(
    proof_file: str = typer.Argument(..., help="Path to proof JSON file"),
) -> None:
    """
    Verify a proof locally (without submitting to chain).
    """

    async def _verify() -> None:
        from .bitcoin import sha256d, verify_merkle_proof, BlockHeader, parse_tx_outputs

        with open(proof_file) as f:
            proof_dict = json.load(f)

        headers = [bytes.fromhex(h) for h in proof_dict["headers"]]
        raw_tx = bytes.fromhex(proof_dict["rawTx"])
        merkle_proof = [bytes.fromhex(p) for p in proof_dict["merkleProof"]]
        tx_index = proof_dict["txIndex"]

        typer.echo("Verifying proof...")

        # Verify header chain
        prev_hash = None
        for i, header_bytes in enumerate(headers):
            header = BlockHeader.from_bytes(header_bytes)
            if i > 0 and header.prev_block_hash != prev_hash:
                typer.echo(f"FAIL: Header chain broken at index {i}", err=True)
                raise typer.Exit(1)
            prev_hash = header.block_hash()
            typer.echo(f"  Header {i}: {header.block_hash_hex()}")

        # Verify Merkle proof
        target_header = BlockHeader.from_bytes(headers[-1])
        txid = sha256d(raw_tx)

        if not verify_merkle_proof(txid, target_header.merkle_root, merkle_proof, tx_index):
            typer.echo("FAIL: Merkle proof verification failed", err=True)
            raise typer.Exit(1)

        typer.echo(f"  TXID: {txid[::-1].hex()}")
        typer.echo(f"  Merkle root: {target_header.merkle_root[::-1].hex()}")

        # Parse outputs
        outputs = parse_tx_outputs(raw_tx)
        output_index = proof_dict["outputIndex"]
        if output_index < len(outputs):
            output = outputs[output_index]
            typer.echo(f"  Output {output_index}: {output.value} sats")

        typer.echo("\nProof verified successfully!")

    asyncio.run(_verify())


if __name__ == "__main__":
    main()
