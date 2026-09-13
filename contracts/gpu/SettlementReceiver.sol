// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

import { GpuTypes } from "./types/GpuTypes.sol";
import { IProtocolRoles } from "./interfaces/IProtocolRoles.sol";
import { IRepaymentRouter } from "./interfaces/IRepaymentRouter.sol";

interface ISettlementToken {
    function balanceOf(address) external view returns (uint256);
}

/// @notice Destination cash adapter. Source proofs/messages do not call debt hooks. An approved settlement rail
/// must DELIVER the configured destination loan token, then this module measures and passes it to RepaymentRouter.
/// Conversion and bridging remain properties of the separately approved rail, never implicit Writability support.
contract SettlementReceiver {
    IProtocolRoles public immutable ROLES;
    IRepaymentRouter public immutable ROUTER;
    address public immutable ASSET;
    uint256 public immutable DESTINATION_CHAIN_ID;
    bytes32 public constant ADMIN_ROLE = keccak256("ADMIN");

    struct Route {
        address adapter;
        uint64 sourceChainId;
        address sourceToken;
        uint256 maxReceipt;
        bool enabled;
    }
    mapping(bytes32 => Route) public routes;
    mapping(bytes32 => bool) public received;
    bool public wiringFinalized;
    uint256 private _lock;
    event RouteRegistered(bytes32 indexed routeId, address indexed adapter, uint64 sourceChainId, address sourceToken);
    event RouteEnabled(bytes32 indexed routeId, bool enabled);
    event SettlementArrived(
        bytes32 indexed settlementId,
        bytes32 indexed routeId,
        GpuTypes.FacilityId indexed facilityId,
        uint256 received,
        uint256 applied,
        uint256 excess
    );
    event WiringSealed();
    error NotAuthorized();
    error UnsupportedRoute();
    error InvalidQuote();
    error DuplicateSettlement();
    error TransferFailed();
    error Reentrancy();

    constructor(IProtocolRoles roles, IRepaymentRouter router, address asset) {
        if (address(roles).code.length == 0 || address(router).code.length == 0 || asset.code.length == 0) {
            revert UnsupportedRoute();
        }
        ROLES = roles;
        ROUTER = router;
        ASSET = asset;
        DESTINATION_CHAIN_ID = block.chainid;
    }

    function registerRoute(bytes32 id, address adapter, uint64 sourceChain, address sourceToken, uint256 maxReceipt)
        external
    {
        if (!ROLES.hasRole(ADMIN_ROLE, msg.sender)) revert NotAuthorized();
        if (
            wiringFinalized || id == bytes32(0) || routes[id].adapter != address(0) || adapter == address(0)
                || sourceChain == 0 || sourceToken == address(0) || maxReceipt == 0
        ) revert UnsupportedRoute();
        routes[id] = Route(adapter, sourceChain, sourceToken, maxReceipt, true);
        emit RouteRegistered(id, adapter, sourceChain, sourceToken);
    }

    function finalizeWiring() external {
        if (!ROLES.hasRole(ADMIN_ROLE, msg.sender)) revert NotAuthorized();
        wiringFinalized = true;
        emit WiringSealed();
    }

    /// @notice Admission pause controls NEW rail operations; ordinary direct repayFor stays available.
    function setRouteEnabled(bytes32 id, bool enabled) external {
        if (!ROLES.hasRole(ROLES.TREASURY(), msg.sender)) revert NotAuthorized();
        if (routes[id].adapter == address(0)) revert UnsupportedRoute();
        routes[id].enabled = enabled;
        emit RouteEnabled(id, enabled);
    }

    function receiveSettlement(
        bytes32 routeId,
        bytes32 settlementId,
        GpuTypes.FacilityId facilityId,
        uint256 destinationChainId,
        address destinationToken,
        uint256 amount,
        uint256 minReceived,
        uint64 deadline
    ) external returns (GpuTypes.RepayResult memory result) {
        if (_lock != 0) revert Reentrancy();
        _lock = 1;
        Route memory route = routes[routeId];
        if (!route.enabled || msg.sender != route.adapter) revert UnsupportedRoute();
        if (
            destinationChainId != DESTINATION_CHAIN_ID || destinationToken != ASSET || block.timestamp >= deadline
                || amount == 0 || amount > route.maxReceipt || minReceived == 0 || minReceived > amount
        ) revert InvalidQuote();
        if (settlementId == bytes32(0) || received[settlementId]) revert DuplicateSettlement();
        received[settlementId] = true;
        uint256 before_ = ISettlementToken(ASSET).balanceOf(address(this));
        _call(abi.encodeWithSignature("transferFrom(address,address,uint256)", msg.sender, address(this), amount));
        uint256 actual = ISettlementToken(ASSET).balanceOf(address(this)) - before_;
        if (actual < minReceived) revert InvalidQuote();
        _call(abi.encodeWithSignature("approve(address,uint256)", address(ROUTER), actual));
        result = ROUTER.receiveSettlement(facilityId, settlementId, actual);
        _call(abi.encodeWithSignature("approve(address,uint256)", address(ROUTER), 0));
        emit SettlementArrived(settlementId, routeId, facilityId, actual, result.applied, result.excess);
        _lock = 0;
    }

    function _call(bytes memory data) internal {
        (bool ok, bytes memory result) = ASSET.call(data);
        if (!ok || (result.length != 0 && !abi.decode(result, (bool)))) revert TransferFailed();
    }
}
