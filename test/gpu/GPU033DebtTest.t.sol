// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { Test } from "forge-std/Test.sol";
import { GpuTypes } from "../../contracts/gpu/types/GpuTypes.sol";
import { ProtocolRoles } from "../../contracts/gpu/ProtocolRoles.sol";
import { DebtLedger } from "../../contracts/gpu/DebtLedger.sol";
import { IDebtLedger } from "../../contracts/gpu/interfaces/IDebtLedger.sol";
import { InterestMath } from "../../contracts/gpu/libraries/InterestMath.sol";

/**
 * @title GPU033DebtTest
 * @notice Single facility ledger: exact interest accumulator, forward-only rate segments, waterfall allocation,
 *         no capitalization by default (docs/gpu/accounting.md, AC-01..AC-06, AR-01..AR-04 corrected).
 */
contract GPU033DebtTest is Test {
    ProtocolRoles roles;
    DebtLedger ledger;

    address admin = address(0xAD);
    address manager = address(0x3A); // ledger writer (manager / router)
    address mallory = address(0xBAD);

    uint64 constant T0 = 1_800_000_000;
    uint64 constant YEAR = 365 days;
    uint256 constant USDC = 1e6;
    GpuTypes.FacilityId F1 = GpuTypes.FacilityId.wrap(keccak256("f1"));
    GpuTypes.FacilityId F2 = GpuTypes.FacilityId.wrap(keccak256("f2"));

    string vectors;

    function setUp() public {
        vm.warp(T0);
        roles = new ProtocolRoles(admin);
        ledger = new DebtLedger(roles);
        vm.prank(admin);
        ledger.setWriter(manager, true);
        vectors = vm.readFile("test/fixtures/gpu/accounting.json");
    }

    // ------------------------------------------------------------------ helpers

    function _terms(uint32 rateBps, bool capitalize) internal pure returns (IDebtLedger.Terms memory) {
        return IDebtLedger.Terms({
            loanAsset: GpuTypes.AssetRef({ chainId: 102_031, token: address(0x05DC), decimals: 6 }),
            rateBps: rateBps,
            maturityAt: 0,
            termsVersionId: keccak256("terms-v1"),
            policyVersionId: keccak256("policy-v1"),
            executionProfile: GpuTypes.ExecutionProfile.LOCAL_MOCK,
            capitalizeUnpaidInterest: capitalize
        });
    }

    function _open(GpuTypes.FacilityId id, uint32 rateBps) internal {
        vm.prank(manager);
        ledger.open(id, _terms(rateBps, false));
    }

    function _draw(GpuTypes.FacilityId id, uint256 amount) internal {
        vm.prank(manager);
        ledger.recordDraw(id, amount);
    }

    function _allocate(GpuTypes.FacilityId id, uint256 amount) internal returns (GpuTypes.RepayResult memory) {
        vm.prank(manager);
        return ledger.allocate(id, amount);
    }

    function _accrue(GpuTypes.FacilityId id) internal {
        vm.prank(manager);
        ledger.accrue(id);
    }

    function _expect(string memory vectorPath, string memory key) internal view returns (uint256) {
        return vm.parseJsonUint(vectors, string.concat(vectorPath, ".expect['", key, "']"));
    }

    // ------------------------------------------------------------------ AC-01 / AR-01

    function test_ac01_partialInterestPaymentPreservesUnpaidInterest() public {
        _open(F1, 1000);
        _draw(F1, 5000 * USDC);
        vm.warp(T0 + YEAR);
        assertEq(ledger.unpaidInterestAt(F1, T0 + YEAR), 500 * USDC, "interest before payment");
        GpuTypes.RepayResult memory r = _allocate(F1, 250 * USDC);
        assertEq(r.interestPaid, 250 * USDC);
        assertEq(r.principalPaid, 0);
        assertEq(r.feePaid, 0);
        assertEq(r.excess, 0);
        assertEq(r.applied, 250 * USDC);
        assertEq(r.newDebt, 5250 * USDC, "$5,250 = principal 5,000 + unpaid interest 250");
        GpuTypes.FacilityLedgerView memory v = ledger.view_(F1);
        assertEq(v.principal, 5000 * USDC);
        assertEq(v.unpaidInterest, 250 * USDC);
        assertEq(ledger.legalDebtAt(F1, T0 + YEAR), 5250 * USDC);
        // matches the GPU-012 vector expectations
        assertEq(v.principal, _expect(".vectors[0]", "f1.principal"));
        assertEq(v.unpaidInterest, _expect(".vectors[0]", "f1.unpaid_interest"));
        assertEq(r.newDebt, _expect(".vectors[0]", "f1.legal_debt"));
    }

    function test_ac01_paymentDoesNotResetAccrualClock_interestKeepsAccruing() public {
        _open(F1, 1000);
        _draw(F1, 5000 * USDC);
        vm.warp(T0 + YEAR);
        _allocate(F1, 250 * USDC);
        vm.warp(T0 + 2 * YEAR);
        // second year accrues another 500 on the untouched principal; the 250 unpaid interest is still owed
        assertEq(ledger.unpaidInterestAt(F1, T0 + 2 * YEAR), 750 * USDC);
        assertEq(ledger.legalDebtAt(F1, T0 + 2 * YEAR), 5750 * USDC);
    }

    // ------------------------------------------------------------------ AC-02 / AR-04 rate segments

    function test_ac02_rateChangeAtExactHalfYearIsForwardOnly() public {
        _open(F1, 1000);
        _draw(F1, 10_000 * USDC);
        vm.warp(T0 + YEAR / 2); // 15,768,000 s
        vm.prank(manager);
        ledger.setRate(F1, 2000);
        // the elapsed half year was settled at 10% (500), not re-priced at 20%
        assertEq(ledger.unpaidInterestAt(F1, T0 + YEAR / 2), 500 * USDC);
        vm.warp(T0 + YEAR);
        _accrue(F1);
        assertEq(ledger.unpaidInterestAt(F1, T0 + YEAR), 1500 * USDC, "500 @10% + 1000 @20%");
        assertEq(ledger.legalDebtAt(F1, T0 + YEAR), 11_500 * USDC);
        assertEq(ledger.unpaidInterestAt(F1, T0 + YEAR), _expect(".vectors[1]", "f1.unpaid_interest"));
        assertEq(ledger.legalDebtAt(F1, T0 + YEAR), _expect(".vectors[1]", "f1.legal_debt"));
        DebtLedger.RateSegment[] memory segs = ledger.rateSegments(F1);
        assertEq(segs.length, 2);
        assertEq(segs[0].start, T0);
        assertEq(segs[0].rateBps, 1000);
        assertEq(segs[1].start, T0 + YEAR / 2);
        assertEq(segs[1].rateBps, 2000);
    }

    function test_ac02_rateChangeNeverRetroactive_ar04() public {
        // AR-04: $5,000 at 10% for a year, then the rate is set to 20% -> elapsed year is still $500
        _open(F1, 1000);
        _draw(F1, 5000 * USDC);
        vm.warp(T0 + YEAR);
        vm.prank(manager);
        ledger.setRate(F1, 2000);
        assertEq(ledger.unpaidInterestAt(F1, T0 + YEAR), 500 * USDC);
        vm.warp(T0 + YEAR + 1 days);
        // forward: one day at 20% on 5,000 = 5000e6 * 2000 * 86400 / (10000 * 31536000) = 2,739,726 (floor)
        assertEq(ledger.unpaidInterestAt(F1, T0 + YEAR + 1 days), 500 * USDC + 2_739_726);
    }

    function test_rateChangeTwiceInSameSecondReplacesSegment() public {
        _open(F1, 1000);
        _draw(F1, 1000 * USDC);
        vm.warp(T0 + 10 days);
        vm.startPrank(manager);
        ledger.setRate(F1, 1500);
        ledger.setRate(F1, 2500);
        vm.stopPrank();
        DebtLedger.RateSegment[] memory segs = ledger.rateSegments(F1);
        assertEq(segs.length, 2);
        assertEq(segs[1].rateBps, 2500);
        assertEq(ledger.view_(F1).rateBps, 2500);
    }

    // ------------------------------------------------------------------ AC-03 accrual frequency

    function test_ac03_dailyAccrualEqualsOneShotAccrual_exactCarry() public {
        _open(F1, 1000);
        _open(F2, 1000);
        _draw(F1, 10_000 * USDC);
        _draw(F2, 10_000 * USDC);
        for (uint256 d = 1; d <= 365; d++) {
            vm.warp(T0 + d * 1 days);
            _accrue(F1);
        }
        _accrue(F2);
        assertEq(ledger.unpaidInterestAt(F1, T0 + YEAR), 1000 * USDC);
        assertEq(ledger.unpaidInterestAt(F2, T0 + YEAR), 1000 * USDC);
        // the accumulators are identical, not merely the floored units
        assertEq(ledger.interestAccumulator(F1), ledger.interestAccumulator(F2));
        assertEq(ledger.interestAccumulator(F1), 10_000 * USDC * 1000 * uint256(YEAR));
        assertEq(ledger.unpaidInterestAt(F1, T0 + YEAR), _expect(".vectors[2]", "f1.unpaid_interest"));
    }

    function test_ac03_oddPeriodsCarryFractionalRemainderAcrossAccruals() public {
        // 1,234.567891 at 7.37% accrued in 97 irregular steps must equal a single accrual (floor of exact sum)
        _open(F1, 737);
        _open(F2, 737);
        _draw(F1, 1_234_567_891);
        _draw(F2, 1_234_567_891);
        uint64 t = T0;
        for (uint256 i = 1; i <= 97; i++) {
            t += uint64(3600 * i + 17 * (i % 7));
            vm.warp(t);
            _accrue(F1);
        }
        _accrue(F2);
        uint256 exact = uint256(1_234_567_891) * 737 * uint256(t - T0) / InterestMath.DENOM;
        assertEq(ledger.unpaidInterestAt(F1, t), exact);
        assertEq(ledger.unpaidInterestAt(F2, t), exact);
        assertEq(ledger.interestAccumulator(F1), ledger.interestAccumulator(F2));
    }

    function test_zeroElapsedAccrualIsNoOp() public {
        _open(F1, 1000);
        _draw(F1, 5000 * USDC);
        vm.warp(T0 + 100 days);
        _accrue(F1);
        uint256 acc = ledger.interestAccumulator(F1);
        _accrue(F1); // same block/second
        assertEq(ledger.interestAccumulator(F1), acc);
        assertEq(ledger.view_(F1).lastAccrualAt, T0 + 100 days);
    }

    function test_tinyRepaymentDoesNotResetAccrualOrLoseFraction() public {
        _open(F1, 1000);
        _draw(F1, 5000 * USDC);
        vm.warp(T0 + 1 days + 12 hours); // 1.5 days: 5000e6 * 1000 * 129600 / DENOM = 2,054,794.5...
        uint256 accBefore = uint256(5000 * USDC) * 1000 * 129_600;
        GpuTypes.RepayResult memory r = _allocate(F1, 1);
        assertEq(r.interestPaid, 1);
        assertEq(ledger.interestAccumulator(F1), accBefore - InterestMath.DENOM, "exactly one unit removed");
        assertEq(ledger.unpaidInterestAt(F1, T0 + 1 days + 12 hours), 2_054_793);
        // the fractional 0.2 unit is still in the numerator and completes later
        vm.warp(T0 + YEAR);
        assertEq(ledger.unpaidInterestAt(F1, T0 + YEAR), 500 * USDC - 1);
    }

    // ------------------------------------------------------------------ AC-04 / AR-03 capitalization

    function test_ac04_redrawDoesNotCapitalizeInterest() public {
        _open(F1, 1000);
        _draw(F1, 5000 * USDC);
        vm.warp(T0 + YEAR);
        _draw(F1, 1000 * USDC);
        GpuTypes.FacilityLedgerView memory v = ledger.view_(F1);
        assertEq(v.principal, 6000 * USDC);
        assertEq(v.unpaidInterest, 500 * USDC);
        assertEq(ledger.legalDebtAt(F1, T0 + YEAR), 6500 * USDC);
        assertEq(v.principal, _expect(".vectors[3]", "f1.principal"));
        assertEq(ledger.legalDebtAt(F1, T0 + YEAR), _expect(".vectors[3]", "f1.legal_debt"));
        vm.expectRevert(IDebtLedger.CapitalizationDisabled.selector);
        vm.prank(manager);
        ledger.capitalize(F1);
    }

    function test_capitalizationOnlyWhenTermsAllow() public {
        vm.prank(manager);
        ledger.open(F1, _terms(1000, true));
        _draw(F1, 5000 * USDC);
        vm.warp(T0 + YEAR);
        vm.prank(manager);
        ledger.capitalize(F1);
        GpuTypes.FacilityLedgerView memory v = ledger.view_(F1);
        assertEq(v.principal, 5500 * USDC);
        assertEq(v.unpaidInterest, 0);
        assertEq(ledger.interestAccumulator(F1), 0);
    }

    // ------------------------------------------------------------------ AC-05 multiple borrowers

    function test_ac05_twoBorrowersAreIndependent_totalIncludesUnrecordedInterest() public {
        _open(F1, 1000);
        _open(F2, 1200);
        _draw(F1, 5000 * USDC);
        _draw(F2, 3000 * USDC);
        vm.warp(T0 + YEAR);
        _allocate(F1, 250 * USDC);
        // F2 was never accrued explicitly: the views still include its year of interest
        assertEq(ledger.view_(F1).unpaidInterest, 250 * USDC);
        assertEq(ledger.view_(F2).unpaidInterest, 360 * USDC);
        assertEq(ledger.view_(F2).lastAccrualAt, T0, "no accrual write happened on F2");
        assertEq(ledger.totalLegalDebtAt(T0 + YEAR), 8610 * USDC);
        assertEq(ledger.totalLegalDebtAt(T0 + YEAR), _expect(".vectors[4]", "vault.total_legal_debt"));
        assertEq(ledger.view_(F2).unpaidInterest, _expect(".vectors[4]", "b.unpaid_interest"));
        assertEq(ledger.facilityCount(), 2);
    }

    function test_longInactiveFacilityInterestIsVisibleWithoutAccrual() public {
        _open(F1, 1000);
        _draw(F1, 5000 * USDC);
        vm.warp(T0 + 3 * YEAR);
        assertEq(ledger.unpaidInterestAt(F1, T0 + 3 * YEAR), 1500 * USDC);
        assertEq(ledger.legalDebtAt(F1, T0 + 3 * YEAR), 6500 * USDC);
        assertEq(ledger.totalLegalDebtAt(T0 + 3 * YEAR), 6500 * USDC);
        // a view at a time before the last accrual returns the recorded value (never un-accrues)
        _accrue(F1);
        assertEq(ledger.unpaidInterestAt(F1, T0), 1500 * USDC);
    }

    // ------------------------------------------------------------------ AC-06 waterfall / excess

    function test_ac06_waterfall_feesInterestPrincipalExcess() public {
        _open(F1, 1000);
        _draw(F1, 1000 * USDC);
        vm.prank(manager);
        ledger.recordFee(F1, 10 * USDC, "origination");
        vm.warp(T0 + YEAR / 2); // interest 50
        GpuTypes.RepayResult memory r = _allocate(F1, 1200 * USDC);
        assertEq(r.feePaid, 10 * USDC);
        assertEq(r.interestPaid, 50 * USDC);
        assertEq(r.principalPaid, 1000 * USDC);
        assertEq(r.excess, 140 * USDC);
        assertEq(r.applied, 1060 * USDC);
        assertEq(r.newDebt, 0);
        GpuTypes.FacilityLedgerView memory v = ledger.view_(F1);
        assertEq(v.principal, 0);
        assertEq(v.unpaidInterest, 0);
        assertEq(v.fees, 0);
    }

    function test_ac06_overpaymentExcessMatchesVector_andOtherFacilityUntouched() public {
        _open(F1, 1000);
        _open(F2, 1000);
        _draw(F1, 1000 * USDC);
        _draw(F2, 1000 * USDC);
        vm.warp(T0 + YEAR / 2);
        GpuTypes.RepayResult memory r = _allocate(F1, 1200 * USDC);
        assertEq(r.excess, _expect(".vectors[5]", "vault.borrower_refundable.a"));
        assertEq(ledger.legalDebtAt(F1, T0 + YEAR / 2), 0);
        assertEq(ledger.view_(F2).principal, 1000 * USDC);
        assertEq(ledger.view_(F2).unpaidInterest, 50 * USDC);
    }

    function test_partialPaymentBelowFeesTouchesFeesOnly() public {
        _open(F1, 1000);
        _draw(F1, 1000 * USDC);
        vm.prank(manager);
        ledger.recordFee(F1, 30 * USDC, "late");
        vm.warp(T0 + YEAR);
        GpuTypes.RepayResult memory r = _allocate(F1, 20 * USDC);
        assertEq(r.feePaid, 20 * USDC);
        assertEq(r.interestPaid, 0);
        assertEq(r.principalPaid, 0);
        assertEq(ledger.view_(F1).fees, 10 * USDC);
        assertEq(ledger.view_(F1).unpaidInterest, 100 * USDC);
    }

    // ------------------------------------------------------------------ freeze / non-accrual

    function test_freezeStopsInterestButNotDebt() public {
        _open(F1, 1000);
        _draw(F1, 5000 * USDC);
        vm.warp(T0 + YEAR);
        vm.prank(manager);
        ledger.freezeAccrual(F1);
        assertTrue(ledger.isFrozen(F1));
        vm.warp(T0 + 5 * YEAR);
        assertEq(ledger.unpaidInterestAt(F1, T0 + 5 * YEAR), 500 * USDC);
        assertEq(ledger.legalDebtAt(F1, T0 + 5 * YEAR), 5500 * USDC, "write-off is not forgiveness");
        // allocation on a frozen facility still applies (recovery)
        GpuTypes.RepayResult memory r = _allocate(F1, 400 * USDC);
        assertEq(r.interestPaid, 400 * USDC);
        assertEq(r.newDebt, 5100 * USDC);
        vm.expectRevert(abi.encodeWithSelector(IDebtLedger.AccrualFrozenError.selector, F1));
        _draw(F1, 1);
    }

    // ------------------------------------------------------------------ authorization / guards

    function test_unauthorizedWriterRejected() public {
        vm.expectRevert(abi.encodeWithSelector(IDebtLedger.NotLedgerWriter.selector, mallory));
        vm.prank(mallory);
        ledger.open(F1, _terms(1000, false));
        _open(F1, 1000);
        vm.startPrank(mallory);
        vm.expectRevert(abi.encodeWithSelector(IDebtLedger.NotLedgerWriter.selector, mallory));
        ledger.recordDraw(F1, 1);
        vm.expectRevert(abi.encodeWithSelector(IDebtLedger.NotLedgerWriter.selector, mallory));
        ledger.allocate(F1, 1);
        vm.expectRevert(abi.encodeWithSelector(IDebtLedger.NotLedgerWriter.selector, mallory));
        ledger.setRate(F1, 1);
        vm.expectRevert(abi.encodeWithSelector(IDebtLedger.NotLedgerWriter.selector, mallory));
        ledger.freezeAccrual(F1);
        vm.expectRevert(abi.encodeWithSelector(DebtLedger.NotAdmin.selector, mallory));
        ledger.setWriter(mallory, true);
        vm.stopPrank();
    }

    function test_guards_zeroAmount_unknownFacility_duplicateOpen_badTerms() public {
        vm.startPrank(manager);
        vm.expectRevert(abi.encodeWithSelector(IDebtLedger.FacilityUnknown.selector, F1));
        ledger.recordDraw(F1, 1);
        ledger.open(F1, _terms(1000, false));
        vm.expectRevert(abi.encodeWithSelector(IDebtLedger.FacilityExists.selector, F1));
        ledger.open(F1, _terms(1000, false));
        vm.expectRevert(IDebtLedger.ZeroAmount.selector);
        ledger.recordDraw(F1, 0);
        vm.expectRevert(IDebtLedger.ZeroAmount.selector);
        ledger.allocate(F1, 0);
        vm.expectRevert(IDebtLedger.ZeroAmount.selector);
        ledger.recordFee(F1, 0, "x");
        IDebtLedger.Terms memory bad = _terms(1000, false);
        bad.termsVersionId = bytes32(0);
        vm.expectRevert(abi.encodeWithSelector(DebtLedger.InvalidTerms.selector, "version ids"));
        ledger.open(F2, bad);
        bad = _terms(1000, false);
        bad.maturityAt = T0;
        vm.expectRevert(abi.encodeWithSelector(DebtLedger.InvalidTerms.selector, "maturity"));
        ledger.open(F2, bad);
        vm.stopPrank();
    }

    function test_accrualBackwardsRejected() public {
        _open(F1, 1000);
        _draw(F1, 5000 * USDC);
        vm.warp(T0 + 10 days);
        _accrue(F1);
        vm.warp(T0 + 5 days);
        vm.expectRevert(abi.encodeWithSelector(IDebtLedger.AccrualBackwards.selector, T0 + 10 days, T0 + 5 days));
        _accrue(F1);
    }

    function test_extremeValues_principalCapRevertsCleanly_andMaxSafeDoesNotOverflow() public {
        _open(F1, type(uint32).max);
        vm.prank(manager);
        vm.expectRevert(abi.encodeWithSelector(InterestMath.PrincipalTooLarge.selector, uint256(type(uint128).max) + 1));
        ledger.recordDraw(F1, uint256(type(uint128).max) + 1);
        _draw(F1, type(uint128).max);
        vm.warp(T0 + 100 * YEAR);
        // no overflow at the documented caps: 2^128 * 2^32 * 2^64 < 2^256
        uint256 expected =
            uint256(type(uint128).max) * uint256(type(uint32).max) * uint256(100 * YEAR) / InterestMath.DENOM;
        assertEq(ledger.unpaidInterestAt(F1, T0 + 100 * YEAR), expected);
        _accrue(F1);
        assertEq(ledger.view_(F1).unpaidInterest, expected);
    }

    function test_viewFieldsAndDefaults() public {
        _open(F1, 1000);
        GpuTypes.FacilityLedgerView memory v = ledger.view_(F1);
        assertEq(uint8(v.state), uint8(GpuTypes.FacilityState.ACTIVE));
        assertEq(v.loanAsset.chainId, 102_031);
        assertEq(v.reservedDraws, 0, "reservations are GPU-035's, not the ledger's");
        assertEq(v.rateBps, 1000);
        assertEq(v.termsVersionId, keccak256("terms-v1"));
        assertEq(uint8(v.executionProfile), uint8(GpuTypes.ExecutionProfile.LOCAL_MOCK));
        assertEq(GpuTypes.FacilityId.unwrap(ledger.facilityAt(0)), GpuTypes.FacilityId.unwrap(F1));
        vm.prank(manager);
        ledger.setState(F1, GpuTypes.FacilityState.DELINQUENT);
        assertEq(uint8(ledger.view_(F1).state), uint8(GpuTypes.FacilityState.DELINQUENT));
        IDebtLedger.Terms memory t = ledger.terms(F1);
        assertFalse(t.capitalizeUnpaidInterest);
    }
}
