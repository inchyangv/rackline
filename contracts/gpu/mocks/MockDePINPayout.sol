// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { ISourceAdapter } from "../source/ISourceAdapter.sol";
import { SourceEscrow } from "../source/SourceEscrow.sol";

/**
 * @title MockDePINPayout (TEST_ONLY, partnerRevenue = SIMULATED)
 * @notice Simulated DePIN provider that pays settlements into a `SourceEscrow` through the real token path
 *         (`approve` + `settle`), so LOCAL/NATIVE_TESTNET runs produce the same logs the wire fixture encodes.
 *         It is registered as a PAYER on the escrow; it never issues obligations (the issuer is a separate role).
 * @dev Never a production provider (R2-D12). `earningsProvenance` for anything it pays is SIMULATED.
 */
contract MockDePINPayout is ISourceAdapter {
    SourceEscrow public immutable ESCROW;
    address public operator;

    error NotOperator(address caller);

    constructor(SourceEscrow escrow, address operator_) {
        ESCROW = escrow;
        operator = operator_;
    }

    function capabilities() external pure override returns (Capabilities memory) {
        return Capabilities({
            provableObligation: true,
            provableAssignment: true,
            provablePayout: true,
            provableCheckpoint: true,
            measuredPayouts: true,
            simulatedRevenue: true
        });
    }

    function sourceContract() external view override returns (address) {
        return address(ESCROW);
    }

    /// @notice Pay `amount` of `token` held by this mock into the escrow for `accountKey` / `obligationRef`.
    function payout(bytes32 accountKey, bytes32 obligationRef, address token, uint256 amount, bytes32 settlementId)
        external
        returns (uint64 seq, uint256 measured)
    {
        if (msg.sender != operator) revert NotOperator(msg.sender);
        // approve exactly `amount` for the pull; the escrow measures what actually arrived
        (bool ok,) = token.call(abi.encodeWithSignature("approve(address,uint256)", address(ESCROW), amount));
        require(ok, "approve failed");
        return ESCROW.settle(accountKey, obligationRef, token, amount, settlementId);
    }
}
