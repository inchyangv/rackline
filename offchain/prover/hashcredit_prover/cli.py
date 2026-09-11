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
from .evm import EVMClient, EVMConfig

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


@app.command()
def set_checkpoint(
    height: int = typer.Argument(..., help="Bitcoin block height to checkpoint"),
    checkpoint_manager: Optional[str] = typer.Option(
        None,
        "--checkpoint-manager",
        "-c",
        envvar="CHECKPOINT_MANAGER",
        help="CheckpointManager contract address",
    ),
    rpc_url: Optional[str] = typer.Option(
        None, "--rpc-url", "-r", envvar="BITCOIN_RPC_URL", help="Bitcoin RPC URL"
    ),
    rpc_user: Optional[str] = typer.Option(
        None, "--rpc-user", "-u", envvar="BITCOIN_RPC_USER", help="Bitcoin RPC user"
    ),
    rpc_password: Optional[str] = typer.Option(
        None, "--rpc-password", "-p", envvar="BITCOIN_RPC_PASSWORD", help="Bitcoin RPC password"
    ),
    evm_rpc_url: Optional[str] = typer.Option(
        None, "--evm-rpc-url", envvar="EVM_RPC_URL", help="EVM RPC URL"
    ),
    chain_id: int = typer.Option(102031, "--chain-id", envvar="CHAIN_ID", help="EVM chain ID"),
    private_key: Optional[str] = typer.Option(
        None, "--private-key", envvar="PRIVATE_KEY", help="Private key for signing"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print data without sending transaction"),
) -> None:
    """
    Register a Bitcoin block checkpoint on CheckpointManager.

    Fetches block header info from Bitcoin RPC and submits to EVM contract.

    Example:
        hashcredit-prover set-checkpoint 800000 \\
            --checkpoint-manager 0x1234...
    """

    async def _set_checkpoint() -> None:
        from .bitcoin import sha256d

        # Validate required params
        if not checkpoint_manager:
            typer.echo("Error: --checkpoint-manager or CHECKPOINT_MANAGER env var required", err=True)
            raise typer.Exit(1)
        if not private_key and not dry_run:
            typer.echo("Error: --private-key or PRIVATE_KEY env var required", err=True)
            raise typer.Exit(1)

        # Setup Bitcoin RPC
        btc_config = BitcoinRPCConfig(
            url=rpc_url or os.getenv("BITCOIN_RPC_URL", "http://localhost:18332"),
            user=rpc_user or os.getenv("BITCOIN_RPC_USER", ""),
            password=rpc_password or os.getenv("BITCOIN_RPC_PASSWORD", ""),
        )
        btc_rpc = BitcoinRPC(btc_config)

        typer.echo(f"Fetching block info for height {height}...")

        try:
            # Get block hash and header info
            block_hash_hex = await btc_rpc.get_block_hash(height)
            header_info = await btc_rpc.get_block_header(block_hash_hex, verbose=True)
            header_hex = await btc_rpc.get_block_header_hex(block_hash_hex)

            # Parse header to get internal block hash
            header_bytes = bytes.fromhex(header_hex)
            internal_block_hash = sha256d(header_bytes)

            # Extract fields
            timestamp = header_info["time"]
            chain_work_hex = header_info.get("chainwork", "0")
            chain_work = int(chain_work_hex, 16)

            typer.echo(f"\nBlock Info:")
            typer.echo(f"  Height:     {height}")
            typer.echo(f"  Hash (RPC): {block_hash_hex}")
            typer.echo(f"  Hash (int): 0x{internal_block_hash.hex()}")
            typer.echo(f"  Timestamp:  {timestamp}")
            typer.echo(f"  ChainWork:  {chain_work_hex}")

            if dry_run:
                typer.echo("\n[Dry run - not sending transaction]")
                typer.echo(f"\nContract call:")
                typer.echo(f"  setCheckpoint(")
                typer.echo(f"    height: {height},")
                typer.echo(f"    blockHash: 0x{internal_block_hash.hex()},")
                typer.echo(f"    chainWork: {chain_work},")
                typer.echo(f"    timestamp: {timestamp}")
                typer.echo(f"  )")
                return

            # Setup EVM client
            evm_config = EVMConfig(
                rpc_url=evm_rpc_url or os.getenv("EVM_RPC_URL", "http://localhost:8545"),
                chain_id=chain_id,
                private_key=private_key or "",
            )
            evm_client = EVMClient(evm_config)

            typer.echo(f"\nSending transaction from {evm_client.address}...")

            # Send transaction
            receipt = await evm_client.set_checkpoint(
                contract_address=checkpoint_manager,
                height=height,
                block_hash=internal_block_hash,
                chain_work=chain_work,
                timestamp=timestamp,
            )

            typer.echo(f"\nTransaction successful!")
            typer.echo(f"  TX Hash: {receipt['transactionHash'].hex()}")
            typer.echo(f"  Block:   {receipt['blockNumber']}")
            typer.echo(f"  Gas:     {receipt['gasUsed']}")

            # Verify
            new_height = await evm_client.get_latest_checkpoint_height(checkpoint_manager)
            typer.echo(f"\nVerification:")
            typer.echo(f"  latestCheckpointHeight() = {new_height}")

        except Exception as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

    asyncio.run(_set_checkpoint())


@app.command()
def set_borrower_pubkey_hash(
    borrower: str = typer.Argument(..., help="Borrower EVM address (0x...)"),
    btc_address: str = typer.Argument(..., help="Borrower's Bitcoin address (tb1.../m.../n... for testnet)"),
    spv_verifier: Optional[str] = typer.Option(
        None,
        "--spv-verifier",
        "-v",
        envvar="BTC_SPV_VERIFIER",
        help="BtcSpvVerifier contract address",
    ),
    evm_rpc_url: Optional[str] = typer.Option(
        None, "--evm-rpc-url", envvar="EVM_RPC_URL", help="EVM RPC URL"
    ),
    chain_id: int = typer.Option(102031, "--chain-id", envvar="CHAIN_ID", help="EVM chain ID"),
    private_key: Optional[str] = typer.Option(
        None, "--private-key", envvar="PRIVATE_KEY", help="Private key for signing"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print data without sending transaction"),
) -> None:
    """
    Register a borrower's Bitcoin pubkey hash on BtcSpvVerifier.

    Decodes the Bitcoin address to extract the 20-byte pubkey hash and
    registers it on-chain for SPV proof verification.

    Supports:
    - P2WPKH (bech32): tb1q... (testnet), bc1q... (mainnet)
    - P2PKH (base58check): m.../n... (testnet), 1... (mainnet)

    Example:
        hashcredit-prover set-borrower-pubkey-hash \\
            0x1234...borrower \\
            tb1qw508d6qejxtdg4y5r3zarvary0c5xw7kxpjzsx \\
            --spv-verifier 0xABC123...
    """

    async def _set_pubkey_hash() -> None:
        from .address import decode_btc_address

        # Validate required params
        if not spv_verifier:
            typer.echo("Error: --spv-verifier or BTC_SPV_VERIFIER env var required", err=True)
            raise typer.Exit(1)
        if not private_key and not dry_run:
            typer.echo("Error: --private-key or PRIVATE_KEY env var required", err=True)
            raise typer.Exit(1)

        # Decode Bitcoin address
        typer.echo(f"Decoding Bitcoin address: {btc_address}")

        result = decode_btc_address(btc_address)
        if result is None:
            typer.echo("Error: Invalid or unsupported Bitcoin address format", err=True)
            typer.echo("Supported: P2WPKH (tb1q.../bc1q...) and P2PKH (1.../m.../n...)", err=True)
            raise typer.Exit(1)

        pubkey_hash, addr_type = result

        typer.echo(f"\nAddress Info:")
        typer.echo(f"  Type:        {addr_type.upper()}")
        typer.echo(f"  PubkeyHash:  0x{pubkey_hash.hex()}")
        typer.echo(f"  Borrower:    {borrower}")

        if dry_run:
            typer.echo("\n[Dry run - not sending transaction]")
            typer.echo(f"\nContract call:")
            typer.echo(f"  setBorrowerPubkeyHash(")
            typer.echo(f"    borrower: {borrower},")
            typer.echo(f"    pubkeyHash: 0x{pubkey_hash.hex()}")
            typer.echo(f"  )")
            return

        # Setup EVM client
        evm_config = EVMConfig(
            rpc_url=evm_rpc_url or os.getenv("EVM_RPC_URL", "http://localhost:8545"),
            chain_id=chain_id,
            private_key=private_key or "",
        )
        evm_client = EVMClient(evm_config)

        typer.echo(f"\nSending transaction from {evm_client.address}...")

        try:
            # Send transaction
            receipt = await evm_client.set_borrower_pubkey_hash(
                contract_address=spv_verifier,
                borrower=borrower,
                pubkey_hash=pubkey_hash,
            )

            typer.echo(f"\nTransaction successful!")
            typer.echo(f"  TX Hash: {receipt['transactionHash'].hex()}")
            typer.echo(f"  Block:   {receipt['blockNumber']}")
            typer.echo(f"  Gas:     {receipt['gasUsed']}")

            # Verify
            registered_hash = await evm_client.get_borrower_pubkey_hash(spv_verifier, borrower)
            typer.echo(f"\nVerification:")
            typer.echo(f"  getBorrowerPubkeyHash({borrower}) = 0x{registered_hash.hex()}")

        except Exception as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

    asyncio.run(_set_pubkey_hash())


@app.command()
def submit_proof(
    txid: str = typer.Argument(..., help="Bitcoin transaction ID (display format)"),
    output_index: int = typer.Argument(..., help="Output index (vout)"),
    borrower: str = typer.Argument(..., help="Borrower EVM address (0x...)"),
    checkpoint_height: Optional[int] = typer.Option(
        None, "--checkpoint", "-c", help="Checkpoint height (auto-select if not specified)"
    ),
    target_height: Optional[int] = typer.Option(
        None, "--target", "-t", help="Target block height (auto-detect if not specified)"
    ),
    hash_credit_manager: Optional[str] = typer.Option(
        None,
        "--manager",
        "-m",
        envvar="HASH_CREDIT_MANAGER",
        help="HashCreditManager contract address",
    ),
    checkpoint_manager: Optional[str] = typer.Option(
        None,
        "--checkpoint-manager",
        envvar="CHECKPOINT_MANAGER",
        help="CheckpointManager contract (for auto checkpoint selection)",
    ),
    rpc_url: Optional[str] = typer.Option(
        None, "--rpc-url", "-r", envvar="BITCOIN_RPC_URL", help="Bitcoin RPC URL"
    ),
    rpc_user: Optional[str] = typer.Option(
        None, "--rpc-user", "-u", envvar="BITCOIN_RPC_USER", help="Bitcoin RPC user"
    ),
    rpc_password: Optional[str] = typer.Option(
        None, "--rpc-password", "-p", envvar="BITCOIN_RPC_PASSWORD", help="Bitcoin RPC password"
    ),
    evm_rpc_url: Optional[str] = typer.Option(
        None, "--evm-rpc-url", envvar="EVM_RPC_URL", help="EVM RPC URL"
    ),
    chain_id: int = typer.Option(102031, "--chain-id", envvar="CHAIN_ID", help="EVM chain ID"),
    private_key: Optional[str] = typer.Option(
        None, "--private-key", envvar="PRIVATE_KEY", help="Private key for signing"
    ),
    output_file: Optional[str] = typer.Option(
        None, "--output", "-o", help="Save proof JSON to file"
    ),
    hex_only: bool = typer.Option(
        False, "--hex-only", help="Only output hex-encoded proof (no submission)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Build proof but don't submit"),
) -> None:
    """
    Build an SPV proof and submit it to HashCreditManager.

    Builds a Merkle inclusion proof for a Bitcoin transaction and submits
    it to the HashCreditManager contract via submitPayout().

    Example:
        hashcredit-prover submit-proof \\
            abc123...txid... 0 0x1234...borrower \\
            --checkpoint 2500000 \\
            --target 2500006 \\
            --manager 0xABC123...
    """

    async def _submit_proof() -> None:
        # Validate required params
        if not hash_credit_manager and not hex_only and not dry_run:
            typer.echo("Error: --manager or HASH_CREDIT_MANAGER env var required", err=True)
            raise typer.Exit(1)
        if not private_key and not hex_only and not dry_run:
            typer.echo("Error: --private-key or PRIVATE_KEY env var required", err=True)
            raise typer.Exit(1)
        if checkpoint_height is None:
            typer.echo("Error: --checkpoint is required (auto-selection not yet implemented)", err=True)
            raise typer.Exit(1)
        if target_height is None:
            typer.echo("Error: --target is required (auto-detection not yet implemented)", err=True)
            raise typer.Exit(1)

        # Setup Bitcoin RPC
        btc_config = BitcoinRPCConfig(
            url=rpc_url or os.getenv("BITCOIN_RPC_URL", "http://localhost:18332"),
            user=rpc_user or os.getenv("BITCOIN_RPC_USER", ""),
            password=rpc_password or os.getenv("BITCOIN_RPC_PASSWORD", ""),
        )
        btc_rpc = BitcoinRPC(btc_config)

        typer.echo(f"Building SPV proof for transaction {txid}...")
        typer.echo(f"  Output index:      {output_index}")
        typer.echo(f"  Checkpoint height: {checkpoint_height}")
        typer.echo(f"  Target height:     {target_height}")
        typer.echo(f"  Borrower:          {borrower}")

        try:
            # Build proof
            builder = ProofBuilder(btc_rpc)
            result = await builder.build_proof(
                txid=txid,
                output_index=output_index,
                checkpoint_height=checkpoint_height,
                target_height=target_height,
                borrower=borrower,
            )

            typer.echo(f"\nProof built successfully!")
            typer.echo(f"  Amount:            {result.amount_sats} sats")
            typer.echo(f"  Script type:       {result.script_type}")
            typer.echo(f"  PubkeyHash:        0x{result.pubkey_hash.hex()}")
            typer.echo(f"  Header chain:      {len(result.proof.headers)} blocks")
            typer.echo(f"  Merkle depth:      {len(result.proof.merkle_proof)}")

            # Encode proof
            encoded_proof = result.proof.encode_for_contract()
            typer.echo(f"  Encoded size:      {len(encoded_proof)} bytes")

            # Save to file if requested
            if output_file:
                import json
                with open(output_file, "w") as f:
                    json.dump(result.proof.to_dict(), f, indent=2)
                typer.echo(f"\nProof saved to {output_file}")

            # Hex-only mode
            if hex_only:
                typer.echo(f"\nABI-encoded proof:")
                typer.echo(f"0x{encoded_proof.hex()}")
                return

            # Dry run
            if dry_run:
                typer.echo("\n[Dry run - not sending transaction]")
                typer.echo(f"\nContract call:")
                typer.echo(f"  HashCreditManager({hash_credit_manager}).submitPayout(")
                typer.echo(f"    proof: 0x{encoded_proof.hex()[:64]}...")
                typer.echo(f"  )")
                return

            # Setup EVM client
            evm_config = EVMConfig(
                rpc_url=evm_rpc_url or os.getenv("EVM_RPC_URL", "http://localhost:8545"),
                chain_id=chain_id,
                private_key=private_key or "",
            )
            evm_client = EVMClient(evm_config)

            typer.echo(f"\nSubmitting proof from {evm_client.address}...")

            # Submit proof
            receipt = await evm_client.submit_payout(
                contract_address=hash_credit_manager,
                proof=encoded_proof,
            )

            typer.echo(f"\nTransaction successful!")
            typer.echo(f"  TX Hash: {receipt['transactionHash'].hex()}")
            typer.echo(f"  Block:   {receipt['blockNumber']}")
            typer.echo(f"  Gas:     {receipt['gasUsed']}")
            typer.echo(f"  Status:  {'Success' if receipt['status'] == 1 else 'Failed'}")

        except Exception as e:
            typer.echo(f"Error: {e}", err=True)
            raise typer.Exit(1)

    asyncio.run(_submit_proof())


if __name__ == "__main__":
    main()
