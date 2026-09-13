// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { Test } from "forge-std/Test.sol";
import { GpuTypes } from "../../contracts/gpu/types/GpuTypes.sol";
import { INativeQueryVerifier } from "@gluwa/asc-contracts/contracts/write-ability/common/INativeQueryVerifier.sol";
import { IRevenueVerifier } from "../../contracts/gpu/interfaces/IRevenueVerifier.sol";
import { IEvidenceBook } from "../../contracts/gpu/interfaces/IEvidenceBook.sol";
import { IAuthorizationVerifier } from "../../contracts/gpu/interfaces/IAuthorizationVerifier.sol";
import { ICreditFacilityManager } from "../../contracts/gpu/interfaces/ICreditFacilityManager.sol";
import { IDebtLedger } from "../../contracts/gpu/interfaces/IDebtLedger.sol";
import { ILendingVaultV2 } from "../../contracts/gpu/interfaces/ILendingVaultV2.sol";
import { IRepaymentRouter } from "../../contracts/gpu/interfaces/IRepaymentRouter.sol";
import { IRiskPolicy } from "../../contracts/gpu/interfaces/IRiskPolicy.sol";
import { IControlRegistry } from "../../contracts/gpu/interfaces/IControlRegistry.sol";
import { IProviderRegistry } from "../../contracts/gpu/interfaces/IProviderRegistry.sol";
import { IAccountRegistry } from "../../contracts/gpu/interfaces/IAccountRegistry.sol";
import { IProtocolRoles } from "../../contracts/gpu/interfaces/IProtocolRoles.sol";
import { IRevenueEscrow } from "../../contracts/gpu/interfaces/IRevenueEscrow.sol";
import { MockBlockProver } from "../../contracts/gpu/mocks/MockBlockProver.sol";

/**
 * @title GPU029InterfacesTest
 * @notice Compile-level and parity checks for the shared GPU types/interfaces (GPU-029).
 */
contract GPU029InterfacesTest is Test {
    string constant ENUMS = "test/fixtures/gpu/enums-v1.json";
    // From @gluwa/usc-sdk 0.18.0 block_prover.json (keccak of the canonical signatures).
    bytes4 constant SEL_VERIFY_SINGLE = 0x7cc4e258;
    bytes4 constant SEL_VERIFY_AND_EMIT_SINGLE = 0x02f4d167;
    bytes4 constant SEL_VERIFY_BATCH = 0x1b5f6f88;
    bytes4 constant SEL_VERIFY_AND_EMIT_BATCH = 0x4da3b895;
    bytes4 constant SEL_CALCULATE_TX_INDEX = 0x44f85f1c;

    function _enum(string memory name) internal view returns (string[] memory) {
        string memory json = vm.readFile(ENUMS);
        return vm.parseJsonStringArray(json, string.concat(".enums.", name));
    }

    // -------------------------------------------------------------- enum ordinal parity with domain-v1

    function test_enumOrdinals_matchDomainSchema() public view {
        assertEq(_enum("ExecutionProfile").length, uint256(type(GpuTypes.ExecutionProfile).max) + 1);
        assertEq(_enum("VerificationMethod").length, uint256(type(GpuTypes.VerificationMethod).max) + 1);
        assertEq(_enum("NativeStatus").length, uint256(type(GpuTypes.NativeStatus).max) + 1);
        assertEq(_enum("EarningsProvenance").length, uint256(type(GpuTypes.EarningsProvenance).max) + 1);
        assertEq(_enum("ControlGrade").length, uint256(type(GpuTypes.ControlGrade).max) + 1);
        assertEq(_enum("CashState").length, uint256(type(GpuTypes.CashState).max) + 1);
        assertEq(_enum("FacilityState").length, uint256(type(GpuTypes.FacilityState).max) + 1);
        assertEq(_enum("Trust").length, uint256(type(GpuTypes.Trust).max) + 1);
        assertEq(_enum("EvidenceMeaning").length, uint256(type(GpuTypes.EvidenceMeaning).max) + 1);
        assertEq(_enum("AssertionPurpose").length, uint256(type(GpuTypes.AssertionPurpose).max) + 1);

        // spot-check ordinals that policy logic depends on
        string[] memory ns = _enum("NativeStatus");
        assertEq(ns[uint256(GpuTypes.NativeStatus.NATIVE_ACCEPTED)], "NATIVE_ACCEPTED");
        assertEq(ns[uint256(GpuTypes.NativeStatus.CONSUMED)], "CONSUMED");
        string[] memory fs = _enum("FacilityState");
        assertEq(fs[uint256(GpuTypes.FacilityState.ACTIVE)], "ACTIVE");
        assertEq(fs[uint256(GpuTypes.FacilityState.CLOSED_WITH_LOSS)], "CLOSED_WITH_LOSS");
        string[] memory cg = _enum("ControlGrade");
        assertEq(cg[uint256(GpuTypes.ControlGrade.E2)], "E2");
        string[] memory vm_ = _enum("VerificationMethod");
        assertEq(vm_[uint256(GpuTypes.VerificationMethod.ATTESTCOIN_NATIVE)], "ATTESTCOIN_NATIVE");
        assertEq(vm_[uint256(GpuTypes.VerificationMethod.OFFCHAIN_ASSERTION)], "OFFCHAIN_ASSERTION");
    }

    // -------------------------------------------------------------- official ABI selectors (pinned by GPU-075)

    function test_officialBlockProverSelectors_matchSdkAbi() public {
        // MockBlockProver compiles only if it implements every overload of the vendored official interface exactly.
        MockBlockProver mock = new MockBlockProver();
        INativeQueryVerifier v = INativeQueryVerifier(address(mock));
        INativeQueryVerifier.MerkleProofEntry[] memory sib = new INativeQueryVerifier.MerkleProofEntry[](2);
        sib[0] = INativeQueryVerifier.MerkleProofEntry({ hash: bytes32(0), isLeft: true });
        sib[1] = INativeQueryVerifier.MerkleProofEntry({ hash: bytes32(0), isLeft: false });
        INativeQueryVerifier.MerkleProof memory mp =
            INativeQueryVerifier.MerkleProof({ root: bytes32(0), siblings: sib });
        INativeQueryVerifier.ContinuityProof memory cp =
            INativeQueryVerifier.ContinuityProof({ lowerEndpointDigest: bytes32(0), roots: new bytes32[](0) });

        assertTrue(v.verifyAndEmit(1, 2, hex"00", mp, cp));
        assertEq(mock.lastSelector(), SEL_VERIFY_AND_EMIT_SINGLE, "verifyAndEmit single");
        uint64[] memory hs = new uint64[](1);
        bytes[] memory txs = new bytes[](1);
        INativeQueryVerifier.MerkleProof[] memory mps = new INativeQueryVerifier.MerkleProof[](1);
        mps[0] = mp;
        assertTrue(v.verifyAndEmit(1, hs, txs, mps, cp));
        assertEq(mock.lastSelector(), SEL_VERIFY_AND_EMIT_BATCH, "verifyAndEmit batch");
        // view overloads: selectors from the pinned ABI signatures
        assertEq(
            bytes4(keccak256("verify(uint64,uint64,bytes,(bytes32,(bytes32,bool)[]),(bytes32,bytes32[]))")),
            SEL_VERIFY_SINGLE
        );
        assertEq(
            bytes4(keccak256("verify(uint64,uint64[],bytes[],(bytes32,(bytes32,bool)[])[],(bytes32,bytes32[]))")),
            SEL_VERIFY_BATCH
        );
        assertTrue(v.verify(1, 2, hex"00", mp, cp));
        assertTrue(v.verify(1, hs, txs, mps, cp));
        assertEq(v.calculateTxIndex.selector, SEL_CALCULATE_TX_INDEX, "calculateTxIndex");
        // documented semantics observed live on CC3 testnet (GPU-075 probe): [L,R] -> 1
        assertEq(v.calculateTxIndex(mp), 1);
        // fail-closed shape: the real precompile reverts on invalid proofs; the double reproduces it
        mock.setRevert(true);
        vm.expectRevert(bytes("Merkle proof validation failed"));
        v.verifyAndEmit(1, 2, hex"00", mp, cp);
    }

    // -------------------------------------------------------------- struct encode/decode round trips

    function test_nativeProofEnvelope_roundTrip() public pure {
        INativeQueryVerifier.MerkleProofEntry[] memory sib = new INativeQueryVerifier.MerkleProofEntry[](2);
        sib[0] = INativeQueryVerifier.MerkleProofEntry({ hash: bytes32(uint256(1)), isLeft: true });
        sib[1] = INativeQueryVerifier.MerkleProofEntry({ hash: bytes32(uint256(2)), isLeft: false });
        bytes32[] memory roots = new bytes32[](1);
        roots[0] = bytes32(uint256(9));
        GpuTypes.NativeProofEnvelope memory env = GpuTypes.NativeProofEnvelope({
            chainKey: 1,
            height: 9_100_000,
            encodedTransaction: hex"deadbeef",
            merkleRoot: bytes32(uint256(7)),
            siblings: sib,
            lowerEndpointDigest: bytes32(uint256(8)),
            continuityRoots: roots
        });
        GpuTypes.NativeProofEnvelope memory back = abi.decode(abi.encode(env), (GpuTypes.NativeProofEnvelope));
        assertEq(back.chainKey, 1);
        assertEq(back.height, 9_100_000);
        assertEq(back.siblings.length, 2);
        assertTrue(back.siblings[0].isLeft);
        assertEq(back.continuityRoots[0], bytes32(uint256(9)));
    }

    function test_sourceEventId_matchesCanonicalVectors() public pure {
        // canonical-id-vectors-v1.json #0: cc3-testnet, chainKey 1, height 9100000, txIndex 17, logOrdinal 0
        bytes32 id =
            keccak256(abi.encode(keccak256(bytes("cc3-testnet")), uint64(1), uint64(9_100_000), uint64(17), uint32(0)));
        assertEq(id, 0xc000764953a9f8b015dde6fd467ee579ce76089c53936bfffa1e5d84264a56ad);
        // a different environment with the same locator is a different event
        bytes32 idMain =
            keccak256(abi.encode(keccak256(bytes("cc3-mainnet")), uint64(1), uint64(9_100_000), uint64(17), uint32(0)));
        assertTrue(id != idMain);
    }

    function test_repayResult_fieldsAreDistinct() public pure {
        GpuTypes.RepayResult memory r = GpuTypes.RepayResult({
            requested: 1200,
            received: 1194,
            applied: 1050,
            feePaid: 20,
            interestPaid: 30,
            principalPaid: 1000,
            excess: 144,
            newDebt: 0
        });
        assertEq(r.feePaid + r.interestPaid + r.principalPaid, r.applied);
        assertEq(r.applied + r.excess, r.received);
        assertTrue(r.received <= r.requested);
    }

    // -------------------------------------------------------------- interface ids are stable / distinct

    function test_interfaceIds_distinct() public pure {
        bytes4[13] memory ids = [
            type(IRevenueVerifier).interfaceId,
            type(IEvidenceBook).interfaceId,
            type(IAuthorizationVerifier).interfaceId,
            type(ICreditFacilityManager).interfaceId,
            type(IDebtLedger).interfaceId,
            type(ILendingVaultV2).interfaceId,
            type(IRepaymentRouter).interfaceId,
            type(IRiskPolicy).interfaceId,
            type(IControlRegistry).interfaceId,
            type(IProviderRegistry).interfaceId,
            type(IAccountRegistry).interfaceId,
            type(IProtocolRoles).interfaceId,
            type(IRevenueEscrow).interfaceId
        ];
        for (uint256 i = 0; i < ids.length; i++) {
            assertTrue(ids[i] != bytes4(0));
            for (uint256 j = i + 1; j < ids.length; j++) {
                assertTrue(ids[i] != ids[j]);
            }
        }
    }

    // -------------------------------------------------------------- R2 type separation

    function test_nativeAndAuxiliaryTypes_areSeparate() public pure {
        // A SupplementaryAssertion cannot be mistaken for a VerifiedSourceEvent: different shapes, no shared fields.
        GpuTypes.SupplementaryAssertion memory a = GpuTypes.SupplementaryAssertion({
            purpose: GpuTypes.AssertionPurpose.CREDIT_APPROVAL,
            subject: bytes32(uint256(1)),
            signer: address(0xA11CE),
            keyEpoch: 1,
            nonce: 1,
            issuedAt: 1,
            expiresAt: 2,
            signature: hex""
        });
        assertEq(uint256(a.purpose), uint256(GpuTypes.AssertionPurpose.CREDIT_APPROVAL));
        assertTrue(
            keccak256(abi.encode(a))
                != keccak256(
                    abi.encode(
                        GpuTypes.VerifiedSourceEvent({
                            id: GpuTypes.SourceEventId.wrap(bytes32(uint256(1))),
                            locator: GpuTypes.SourceEventLocator({ chainKey: 1, height: 1, txIndex: 1, logOrdinal: 0 }),
                            emitter: address(0xA11CE),
                            topic0: bytes32(uint256(1)),
                            topics: new bytes32[](0),
                            data: hex"",
                            manifestHash: bytes32(0),
                            verifier: address(0)
                        })
                    )
                )
        );
    }
}
