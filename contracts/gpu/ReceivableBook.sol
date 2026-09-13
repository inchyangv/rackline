// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "./types/GpuTypes.sol";
import { IReceivableBook } from "./interfaces/IReceivableBook.sol";
import { IEvidenceBook } from "./interfaces/IEvidenceBook.sol";
import { IProviderRegistry } from "./interfaces/IProviderRegistry.sol";
import { IAccountRegistry } from "./interfaces/IAccountRegistry.sol";
import { IProtocolRoles } from "./interfaces/IProtocolRoles.sol";

/**
 * @title ReceivableBook
 * @notice Proof-driven receivable ledger (GPU-035.a). The only way a balance changes is `ingest`, which consumes
 *         verified logs through the EvidenceBook (GPU-031 → GPU-078 → official BlockProver) and re-hashes every
 *         claimed field against the record's `dataHash` before applying it. No signature, admin or API path exists.
 * @dev  Economic event ids are derived on-chain from proven fields
 *       (`keccak256(abi.encode("rackline/receivable-event/v1", providerId, accountKey, kind, ref, seqOrRevision))`)
 *       so that a revision, a settlement and a checkpoint each form a distinct economic event while a second proof
 *       of the same log (or of the same economic fact through another log) is rejected by the EvidenceBook. The
 *       off-chain string form (domain-model §2) must map 1:1 onto this key — GPU-081 owns that table.
 *       Revisions are applied strictly in order; a gap or stale revision reverts and consumes nothing.
 *       Registration (facility, dispute flag) is configuration by roles; it never creates base by itself.
 */
contract ReceivableBook is IReceivableBook {
    bytes32 public constant ECONOMIC_KEY_DOMAIN = keccak256("rackline/receivable-event/v1");

    bytes32 public constant TOPIC_OBLIGATION_RECOGNIZED =
        keccak256("ObligationRecognized(bytes32,bytes32,address,address,address,uint256,uint64,uint32)");
    bytes32 public constant TOPIC_OBLIGATION_ASSIGNED = keccak256("ObligationAssigned(bytes32,bytes32,bytes32,uint32)");
    bytes32 public constant TOPIC_OBLIGATION_CORRECTED =
        keccak256("ObligationCorrected(bytes32,bytes32,int256,uint32,uint8)");
    bytes32 public constant TOPIC_PAYOUT_RECEIVED =
        keccak256("PayoutReceived(bytes32,bytes32,address,address,uint256,uint64)");
    bytes32 public constant TOPIC_PAYOUT_CANCELLED = keccak256("PayoutCancelled(bytes32,bytes32,uint64,uint256)");
    bytes32 public constant TOPIC_SOURCE_CHECKPOINT =
        keccak256("SourceCheckpoint(bytes32,uint64,uint32,uint256,uint256)");
    uint8 public constant CORRECTION_REASON_CANCEL = 3; // ISourceEscrow.CorrectionReason.CANCEL

    IProtocolRoles public immutable ROLES;
    IEvidenceBook public immutable EVIDENCE;
    IProviderRegistry public immutable PROVIDERS;
    IAccountRegistry public immutable ACCOUNTS;

    enum Kind {
        NONE,
        RECOGNIZED,
        ASSIGNED,
        CORRECTED,
        PAYOUT,
        PAYOUT_CANCELLED,
        CHECKPOINT
    }

    struct Settlement {
        bytes32 receivableId; // 0 for unattributed
        uint256 amount;
        bool exists;
        bool cancelled;
    }

    mapping(GpuTypes.FacilityId => Facility) private _facilities;
    mapping(bytes32 facilityKey => GpuTypes.FacilityId) private _facilityByKey;
    mapping(GpuTypes.FacilityId => bytes32[]) private _facilityReceivables;
    mapping(bytes32 => Receivable) private _receivables;
    mapping(bytes32 accountId => AccountStats) private _stats; // accountId = keccak(providerId, accountKey)
    mapping(bytes32 accountId => Checkpoint) private _checkpoints;
    mapping(GpuTypes.ProviderId => mapping(uint64 => Settlement)) private _settlements;

    error NotRole(bytes32 role, address caller);
    error ZeroAddress();

    constructor(IProtocolRoles roles, IEvidenceBook evidence, IProviderRegistry providers, IAccountRegistry accounts) {
        if (
            address(roles) == address(0) || address(evidence) == address(0) || address(providers) == address(0)
                || address(accounts) == address(0)
        ) revert ZeroAddress();
        ROLES = roles;
        EVIDENCE = evidence;
        PROVIDERS = providers;
        ACCOUNTS = accounts;
    }

    modifier onlyRole(bytes32 role) {
        if (!ROLES.hasRole(role, msg.sender)) revert NotRole(role, msg.sender);
        _;
    }

    // ------------------------------------------------------------------ configuration (roles)

    /// @notice Bind a facility to its borrower, provider and admitted source asset (UNDERWRITER). Configuration only.
    function registerFacility(
        GpuTypes.FacilityId facilityId,
        bytes32 borrowerId,
        GpuTypes.ProviderId providerId,
        GpuTypes.AssetRef calldata sourceAsset
    ) external onlyRole(ROLES.UNDERWRITER()) {
        if (_facilities[facilityId].exists) revert FacilityExists(facilityId);
        if (borrowerId == bytes32(0)) revert ZeroAddress();
        if (!PROVIDERS.isTokenAdmitted(providerId, sourceAsset.chainId, sourceAsset.token)) {
            revert IProviderRegistry.TokenNotAdmitted(providerId, sourceAsset.chainId, sourceAsset.token);
        }
        _facilities[facilityId] =
            Facility({ borrowerId: borrowerId, providerId: providerId, sourceAsset: sourceAsset, exists: true });
        _facilityByKey[facilityKey(facilityId)] = facilityId;
        emit FacilityRegistered(facilityId, borrowerId, providerId);
    }

    /// @notice Mark a receivable disputed (excluded from base) or clear the flag. UNDERWRITER or GUARDIAN.
    function setDisputed(bytes32 id, bool disputed, string calldata reason) external {
        if (!ROLES.hasRole(ROLES.UNDERWRITER(), msg.sender) && !ROLES.hasRole(ROLES.GUARDIAN(), msg.sender)) {
            revert NotRole(ROLES.UNDERWRITER(), msg.sender);
        }
        if (_receivables[id].state == ReceivableState.NONE) revert ReceivableUnknown(id);
        _receivables[id].disputed = disputed;
        emit ReceivableDisputed(id, disputed, reason);
    }

    // ------------------------------------------------------------------ views

    function facility(GpuTypes.FacilityId facilityId) external view override returns (Facility memory) {
        return _facilities[facilityId];
    }

    function facilityKey(GpuTypes.FacilityId facilityId) public pure override returns (bytes32) {
        return keccak256(abi.encodePacked(GpuTypes.FacilityId.unwrap(facilityId)));
    }

    function receivableId(GpuTypes.ProviderId providerId, GpuTypes.AccountKey accountKey, bytes32 obligationRef)
        public
        pure
        override
        returns (bytes32)
    {
        return keccak256(abi.encode(providerId, accountKey, obligationRef));
    }

    function receivable(bytes32 id) external view override returns (Receivable memory) {
        return _receivables[id];
    }

    function checkpoint(GpuTypes.ProviderId providerId, GpuTypes.AccountKey accountKey)
        external
        view
        override
        returns (Checkpoint memory)
    {
        return _checkpoints[_accountId(providerId, accountKey)];
    }

    function accountStats(GpuTypes.ProviderId providerId, GpuTypes.AccountKey accountKey)
        external
        view
        override
        returns (AccountStats memory)
    {
        return _stats[_accountId(providerId, accountKey)];
    }

    function facilityReceivables(GpuTypes.FacilityId facilityId) external view returns (bytes32[] memory) {
        return _facilityReceivables[facilityId];
    }

    function settlement(GpuTypes.ProviderId providerId, uint64 settlementSeq)
        external
        view
        returns (Settlement memory)
    {
        return _settlements[providerId][settlementSeq];
    }

    function eligibleUnpaid(
        GpuTypes.FacilityId facilityId,
        uint64 checkpointMaxAge,
        uint32 checkpointToleranceBps,
        uint32 overdueHaircutBps,
        uint64 at
    ) external view override returns (uint256 eligible, uint64 evidenceValidUntil, uint64 checkpointAge) {
        Facility storage f = _facilities[facilityId];
        if (!f.exists) revert FacilityUnknown(facilityId);
        bytes32[] storage ids = _facilityReceivables[facilityId];
        evidenceValidUntil = type(uint64).max;
        for (uint256 i = 0; i < ids.length; i++) {
            Receivable storage r = _receivables[ids[i]];
            if (r.state != ReceivableState.ASSIGNED || r.disputed) continue;
            if (GpuTypes.FacilityId.unwrap(r.facilityId) != GpuTypes.FacilityId.unwrap(facilityId)) continue;
            if (r.evidenceValidUntil <= at) continue;
            if (r.token != address(0) && r.token != f.sourceAsset.token) continue;
            (bool fresh, uint64 age) =
                _checkpointOk(_accountId(f.providerId, r.accountKey), checkpointMaxAge, checkpointToleranceBps, at);
            if (!fresh) continue;
            uint256 unpaid = r.net - r.paid;
            if (r.dueAt != 0 && r.dueAt < at) unpaid = unpaid * (10_000 - overdueHaircutBps) / 10_000;
            eligible += unpaid;
            if (r.evidenceValidUntil < evidenceValidUntil) evidenceValidUntil = r.evidenceValidUntil;
            if (age > checkpointAge) checkpointAge = age;
        }
        if (eligible == 0) evidenceValidUntil = 0;
    }

    /// @dev R2-D06 freshness gate: a checkpoint exists, is young enough, its revision counter equals what we consumed
    ///      (gap or lag ⇒ false) and its open amount reconciles with ours within tolerance.
    function _checkpointOk(bytes32 accountId, uint64 maxAge, uint32 toleranceBps, uint64 at)
        internal
        view
        returns (bool ok, uint64 age)
    {
        Checkpoint storage c = _checkpoints[accountId];
        if (!c.exists || at < c.provenAt) return (false, 0);
        age = at - c.provenAt;
        if (age > maxAge) return (false, age);
        AccountStats storage s = _stats[accountId];
        if (c.latestRevision != s.eventsConsumed) return (false, age);
        uint256 hi = c.openAmount > s.openAmount ? c.openAmount : s.openAmount;
        uint256 lo = c.openAmount > s.openAmount ? s.openAmount : c.openAmount;
        if (hi - lo > s.openAmount * toleranceBps / 10_000) return (false, age);
        ok = true;
    }

    // ------------------------------------------------------------------ ingestion (proof submitters)

    function ingest(
        GpuTypes.ProviderId providerId,
        GpuTypes.NativeProofEnvelope calldata envelope,
        address expectedEmitter,
        bytes32[] calldata topic0s,
        ReceivableClaim[] calldata claims
    ) external override {
        if (!ROLES.hasRole(ROLES.RELAYER(), msg.sender) && !ROLES.hasRole(ROLES.SERVICER(), msg.sender)) {
            revert NotRole(ROLES.RELAYER(), msg.sender);
        }
        // Instructions are derived from the claims; a wrong claim makes the dataHash check below revert the whole tx.
        IEvidenceBook.ConsumeInstruction[] memory ins = new IEvidenceBook.ConsumeInstruction[](claims.length);
        for (uint256 i = 0; i < claims.length; i++) {
            ins[i] = IEvidenceBook.ConsumeInstruction({
                logOrdinal: claims[i].logOrdinal,
                economicEventId: _economicKey(providerId, claims[i], _kindOfClaim(claims[i], topic0s)),
                accountKey: claims[i].accountKey,
                validUntil: claims[i].validUntil
            });
        }
        IEvidenceBook.EvidenceRecord[] memory recs =
            EVIDENCE.consume(providerId, envelope, expectedEmitter, topic0s, ins);
        for (uint256 i = 0; i < recs.length; i++) {
            _apply(providerId, recs[i], claims[i]);
        }
    }

    // ------------------------------------------------------------------ internals

    function _accountId(GpuTypes.ProviderId providerId, GpuTypes.AccountKey accountKey)
        internal
        pure
        returns (bytes32)
    {
        return keccak256(abi.encode(providerId, accountKey));
    }

    function _kindOf(bytes32 topic0) internal pure returns (Kind) {
        if (topic0 == TOPIC_OBLIGATION_RECOGNIZED) return Kind.RECOGNIZED;
        if (topic0 == TOPIC_OBLIGATION_ASSIGNED) return Kind.ASSIGNED;
        if (topic0 == TOPIC_OBLIGATION_CORRECTED) return Kind.CORRECTED;
        if (topic0 == TOPIC_PAYOUT_RECEIVED) return Kind.PAYOUT;
        if (topic0 == TOPIC_PAYOUT_CANCELLED) return Kind.PAYOUT_CANCELLED;
        if (topic0 == TOPIC_SOURCE_CHECKPOINT) return Kind.CHECKPOINT;
        revert UnknownTopic(topic0);
    }

    /// @dev Before verification the kind is only known when the submitter asked for a single topic; with several
    ///      topics the claim's shape (topic count) is ambiguous, so we require one topic per ingest call.
    function _kindOfClaim(ReceivableClaim calldata, bytes32[] calldata topic0s) internal pure returns (Kind) {
        if (topic0s.length != 1) revert UnknownTopic(bytes32(0));
        return _kindOf(topic0s[0]);
    }

    function _expectedMeaning(Kind k) internal pure returns (GpuTypes.EvidenceMeaning) {
        if (k == Kind.RECOGNIZED) return GpuTypes.EvidenceMeaning.OBLIGATION_RECOGNIZED;
        if (k == Kind.ASSIGNED) return GpuTypes.EvidenceMeaning.ASSIGNMENT_RECOGNIZED;
        if (k == Kind.CORRECTED) return GpuTypes.EvidenceMeaning.CORRECTION;
        if (k == Kind.PAYOUT) return GpuTypes.EvidenceMeaning.PAYOUT;
        return GpuTypes.EvidenceMeaning.PAYMENT_CANCELLED;
    }

    /// @dev Distinct key per proven economic fact: revision-bearing events include the revision, payouts the
    ///      settlement sequence, checkpoints the checkpoint sequence.
    function _economicKey(GpuTypes.ProviderId providerId, ReceivableClaim calldata c, Kind k)
        internal
        pure
        returns (GpuTypes.EconomicEventId)
    {
        uint256 seqOrRev;
        if (k == Kind.RECOGNIZED) {
            (,,,, uint32 rev) = abi.decode(c.data, (address, address, uint256, uint64, uint32));
            seqOrRev = rev;
        } else if (k == Kind.ASSIGNED) {
            seqOrRev = abi.decode(c.data, (uint32));
        } else if (k == Kind.CORRECTED) {
            (, uint32 rev,) = abi.decode(c.data, (int256, uint32, uint8));
            seqOrRev = rev;
        } else if (k == Kind.PAYOUT) {
            (,, uint64 seq) = abi.decode(c.data, (address, uint256, uint64));
            seqOrRev = seq;
        } else if (k == Kind.PAYOUT_CANCELLED) {
            (uint64 seq,) = abi.decode(c.data, (uint64, uint256));
            seqOrRev = seq;
        } else {
            (uint64 seq,,,) = abi.decode(c.data, (uint64, uint32, uint256, uint256));
            seqOrRev = seq;
        }
        return GpuTypes.EconomicEventId
            .wrap(keccak256(abi.encode(ECONOMIC_KEY_DOMAIN, providerId, c.accountKey, uint8(k), c.topic2, seqOrRev)));
    }

    function _topicsFor(Kind k, bytes32 topic0, ReceivableClaim calldata c) internal pure returns (bytes32[] memory t) {
        uint256 n = (k == Kind.CHECKPOINT) ? 2 : (k == Kind.CORRECTED || k == Kind.PAYOUT_CANCELLED) ? 3 : 4;
        t = new bytes32[](n);
        t[0] = topic0;
        t[1] = GpuTypes.AccountKey.unwrap(c.accountKey);
        if (n > 2) t[2] = c.topic2;
        if (n > 3) t[3] = c.topic3;
    }

    function _apply(
        GpuTypes.ProviderId providerId,
        IEvidenceBook.EvidenceRecord memory rec,
        ReceivableClaim calldata c
    ) internal {
        Kind k = _kindOf(rec.topic0);
        if (k != Kind.CHECKPOINT && rec.meaning != _expectedMeaning(k)) {
            revert MeaningMismatch(_expectedMeaning(k), rec.meaning);
        }
        bytes32 claimed = keccak256(abi.encode(_topicsFor(k, rec.topic0, c), c.data));
        if (claimed != rec.dataHash) revert ClaimMismatch(rec.dataHash, claimed);

        if (k == Kind.RECOGNIZED) _recognize(providerId, rec, c);
        else if (k == Kind.ASSIGNED) _assign(providerId, rec, c);
        else if (k == Kind.CORRECTED) _correct(providerId, rec, c);
        else if (k == Kind.PAYOUT) _payout(providerId, c);
        else if (k == Kind.PAYOUT_CANCELLED) _cancelPayout(providerId, c);
        else _checkpoint(providerId, rec, c);
    }

    function _recognize(
        GpuTypes.ProviderId providerId,
        IEvidenceBook.EvidenceRecord memory rec,
        ReceivableClaim calldata c
    ) internal {
        (address payer, address payee, uint256 amount, uint64 dueAt, uint32 rev) =
            abi.decode(c.data, (address, address, uint256, uint64, uint32));
        bytes32 id = receivableId(providerId, c.accountKey, c.topic2);
        Receivable storage r = _receivables[id];
        if (r.state != ReceivableState.NONE) revert ReceivableExists(id);
        if (rev != 1) revert RevisionGap(id, 1, rev);
        if (payee != rec.emitter) {
            revert ClaimMismatch(bytes32(uint256(uint160(rec.emitter))), bytes32(uint256(uint160(payee))));
        }
        r.providerId = providerId;
        r.accountKey = c.accountKey;
        r.obligationRef = c.topic2;
        r.payer = payer;
        r.net = amount;
        r.revision = 1;
        r.dueAt = dueAt;
        r.evidenceValidUntil = rec.validUntil;
        r.state = ReceivableState.OPEN;
        AccountStats storage s = _stats[_accountId(providerId, c.accountKey)];
        s.eventsConsumed += 1;
        s.openAmount += amount;
        emit ReceivableRecognized(id, c.accountKey, c.topic2, amount);
    }

    function _assign(
        GpuTypes.ProviderId providerId,
        IEvidenceBook.EvidenceRecord memory rec,
        ReceivableClaim calldata c
    ) internal {
        uint32 rev = abi.decode(c.data, (uint32));
        bytes32 id = receivableId(providerId, c.accountKey, c.topic2);
        Receivable storage r = _receivables[id];
        _requireOpen(id, r);
        _bumpRevision(id, r, rev);
        GpuTypes.FacilityId fid = _facilityByKey[c.topic3];
        Facility storage f = _facilities[fid];
        if (!f.exists) revert FacilityKeyMismatch(c.topic3);
        if (GpuTypes.ProviderId.unwrap(f.providerId) != GpuTypes.ProviderId.unwrap(providerId)) {
            revert FacilityKeyMismatch(c.topic3);
        }
        if (ACCOUNTS.borrowerOfAccount(c.accountKey) != f.borrowerId) {
            revert AccountNotOfBorrower(c.accountKey, f.borrowerId);
        }
        bytes32 current = GpuTypes.FacilityId.unwrap(r.facilityId);
        if (current != bytes32(0) && current != GpuTypes.FacilityId.unwrap(fid)) {
            revert AlreadyAssigned(id, r.facilityId);
        }
        if (current == bytes32(0)) {
            r.facilityId = fid;
            _facilityReceivables[fid].push(id);
        }
        r.state = ReceivableState.ASSIGNED;
        r.evidenceValidUntil = rec.validUntil;
        _stats[_accountId(providerId, c.accountKey)].eventsConsumed += 1;
        emit ReceivableAssigned(id, fid, rev);
    }

    function _correct(
        GpuTypes.ProviderId providerId,
        IEvidenceBook.EvidenceRecord memory rec,
        ReceivableClaim calldata c
    ) internal {
        (int256 delta, uint32 rev, uint8 reason) = abi.decode(c.data, (int256, uint32, uint8));
        bytes32 id = receivableId(providerId, c.accountKey, c.topic2);
        Receivable storage r = _receivables[id];
        _requireOpen(id, r);
        _bumpRevision(id, r, rev);
        uint256 newNet;
        if (delta < 0) {
            uint256 dec = uint256(-delta);
            if (dec > r.net || r.net - dec < r.paid) revert CorrectionBelowPaid(id, r.paid, delta);
            newNet = r.net - dec;
        } else {
            newNet = r.net + uint256(delta);
        }
        uint256 openBefore = r.net - r.paid;
        uint256 openAfter = newNet - r.paid;
        if (reason == CORRECTION_REASON_CANCEL) {
            if (openAfter != 0) revert CancelMustZeroOpen(id, openAfter);
            r.state = ReceivableState.CANCELLED;
        }
        r.net = newNet;
        r.evidenceValidUntil = rec.validUntil;
        AccountStats storage s = _stats[_accountId(providerId, c.accountKey)];
        s.openAmount = s.openAmount - openBefore + openAfter;
        s.eventsConsumed += 1;
        emit ReceivableCorrected(id, delta, rev, reason);
    }

    function _payout(GpuTypes.ProviderId providerId, ReceivableClaim calldata c) internal {
        (, uint256 amount, uint64 seq) = abi.decode(c.data, (address, uint256, uint64));
        address token = address(uint160(uint256(c.topic3)));
        Settlement storage st = _settlements[providerId][seq];
        if (st.exists) revert SettlementSeen(seq);
        AccountStats storage s = _stats[_accountId(providerId, c.accountKey)];
        if (c.topic2 == bytes32(0)) {
            _settlements[providerId][seq] =
                Settlement({ receivableId: 0, amount: amount, exists: true, cancelled: false });
            s.paidCumulative += amount;
            emit UnattributedPayoutRecorded(c.accountKey, amount, seq);
            return;
        }
        bytes32 id = receivableId(providerId, c.accountKey, c.topic2);
        Receivable storage r = _receivables[id];
        _requireOpen(id, r);
        if (r.token == address(0)) r.token = token;
        else if (r.token != token) revert TokenMismatch(r.token, token);
        if (GpuTypes.FacilityId.unwrap(r.facilityId) != bytes32(0)) {
            address expected = _facilities[r.facilityId].sourceAsset.token;
            if (token != expected) revert TokenMismatch(expected, token);
        }
        uint256 remaining = r.net - r.paid;
        if (amount > remaining) revert Overpayment(id, remaining, amount);
        r.paid += amount;
        r.revision += 1; // the escrow bumps the obligation revision on an attributed payout (no revision in the log)
        if (r.paid == r.net) r.state = ReceivableState.PAID;
        _settlements[providerId][seq] = Settlement({ receivableId: id, amount: amount, exists: true, cancelled: false });
        s.openAmount -= amount;
        s.paidCumulative += amount;
        s.eventsConsumed += 1;
        emit ReceivablePaid(id, amount, seq, r.net - r.paid);
    }

    function _cancelPayout(GpuTypes.ProviderId providerId, ReceivableClaim calldata c) internal {
        (uint64 seq, uint256 amount) = abi.decode(c.data, (uint64, uint256));
        Settlement storage st = _settlements[providerId][seq];
        if (!st.exists) revert SettlementUnknown(seq);
        if (st.cancelled) revert SettlementSeen(seq);
        if (st.amount != amount) revert ClaimMismatch(bytes32(st.amount), bytes32(amount));
        st.cancelled = true;
        AccountStats storage s = _stats[_accountId(providerId, c.accountKey)];
        s.paidCumulative -= amount;
        if (st.receivableId == bytes32(0)) return;
        Receivable storage r = _receivables[st.receivableId];
        r.paid -= amount;
        r.revision += 1;
        if (r.state == ReceivableState.PAID) {
            r.state = GpuTypes.FacilityId.unwrap(r.facilityId) != bytes32(0)
                ? ReceivableState.ASSIGNED
                : ReceivableState.OPEN;
        }
        s.openAmount += amount;
        s.eventsConsumed += 1;
        emit ReceivablePayoutCancelled(st.receivableId, amount, seq);
    }

    function _checkpoint(
        GpuTypes.ProviderId providerId,
        IEvidenceBook.EvidenceRecord memory rec,
        ReceivableClaim calldata c
    ) internal {
        (uint64 seq, uint32 latestRevision, uint256 openAmount, uint256 paidCumulative) =
            abi.decode(c.data, (uint64, uint32, uint256, uint256));
        bytes32 accountId = _accountId(providerId, c.accountKey);
        Checkpoint storage cp = _checkpoints[accountId];
        if (cp.exists && seq <= cp.checkpointSeq) revert CheckpointNotNewer(cp.checkpointSeq, seq);
        _checkpoints[accountId] = Checkpoint({
            checkpointSeq: seq,
            latestRevision: latestRevision,
            openAmount: openAmount,
            paidCumulative: paidCumulative,
            provenAt: rec.provenAt,
            exists: true
        });
        emit CheckpointRecorded(c.accountKey, seq, latestRevision);
    }

    function _requireOpen(bytes32 id, Receivable storage r) internal view {
        if (r.state != ReceivableState.OPEN && r.state != ReceivableState.ASSIGNED) {
            revert ReceivableNotOpen(id, r.state);
        }
    }

    function _bumpRevision(bytes32 id, Receivable storage r, uint32 rev) internal {
        if (rev <= r.revision) revert RevisionStale(id, r.revision, rev);
        if (rev != r.revision + 1) revert RevisionGap(id, r.revision + 1, rev);
        r.revision = rev;
    }
}
