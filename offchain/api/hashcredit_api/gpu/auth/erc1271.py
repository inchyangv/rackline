"""ERC-1271 checker protocol. Production binds an RPC-backed checker; tests inject a fake (no live RPC)."""

from __future__ import annotations

from typing import Protocol


class Erc1271Checker(Protocol):
    async def is_valid_signature(self, wallet: str, digest: bytes, signature: bytes) -> bool:
        """True iff `wallet` (a contract) returns the ERC-1271 magic value for (digest, signature)."""


class RejectAllErc1271Checker:
    """Default when no RPC checker is configured: contract wallets cannot log in (fail closed)."""

    async def is_valid_signature(self, wallet: str, digest: bytes, signature: bytes) -> bool:
        return False


class RpcErc1271Checker:
    """Only the deployed contract wallet on this API's chain can authorize its login digest."""

    def __init__(self, web3, chain_id):
        self.web3, self.chain_id = web3, chain_id

    async def is_valid_signature(self, wallet: str, digest: bytes, signature: bytes) -> bool:
        from starlette.concurrency import run_in_threadpool
        from eth_abi import encode
        from web3 import Web3

        def check():
            try:
                if self.web3.eth.chain_id != self.chain_id:
                    return False
                address = Web3.to_checksum_address(wallet)
                block = self.web3.eth.get_block("latest")
                if not self.web3.eth.get_code(address, block_identifier=block.number):
                    return False
                calldata = bytes.fromhex("1626ba7e") + encode(["bytes32", "bytes"], [digest, signature])
                result = self.web3.eth.call({"to": address, "data": calldata, "gas": 100000}, block_identifier=block.number)
                return len(result) >= 32 and result[:4] == bytes.fromhex("1626ba7e")
            except Exception:
                return False
        return await run_in_threadpool(check)


class FakeErc1271Checker:
    """TEST_ONLY: accepts exactly the (wallet, digest, signature) triples registered in advance."""

    def __init__(self) -> None:
        self._accepted: set[tuple[str, bytes, bytes]] = set()
        self.calls = 0

    def accept(self, wallet: str, digest: bytes, signature: bytes) -> None:
        self._accepted.add((wallet.lower(), digest, signature))

    async def is_valid_signature(self, wallet: str, digest: bytes, signature: bytes) -> bool:
        self.calls += 1
        return (wallet.lower(), digest, signature) in self._accepted
