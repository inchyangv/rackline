export const HashCreditManagerAbi = [
  {
    inputs: [],
    name: 'owner',
    outputs: [{ internalType: 'address', name: '', type: 'address' }],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [],
    name: 'verifier',
    outputs: [{ internalType: 'address', name: '', type: 'address' }],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [],
    name: 'stablecoin',
    outputs: [{ internalType: 'address', name: '', type: 'address' }],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [],
    name: 'vault',
    outputs: [{ internalType: 'address', name: '', type: 'address' }],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [{ internalType: 'address', name: 'borrower', type: 'address' }],
    name: 'getAvailableCredit',
    outputs: [{ internalType: 'uint256', name: '', type: 'uint256' }],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [{ internalType: 'address', name: 'borrower', type: 'address' }],
    name: 'getBorrowerInfo',
    outputs: [
      {
        components: [
          { internalType: 'uint8', name: 'status', type: 'uint8' },
          { internalType: 'bytes32', name: 'btcPayoutKeyHash', type: 'bytes32' },
          { internalType: 'uint128', name: 'totalRevenueSats', type: 'uint128' },
          { internalType: 'uint128', name: 'trailingRevenueSats', type: 'uint128' },
          { internalType: 'uint128', name: 'creditLimit', type: 'uint128' },
          { internalType: 'uint128', name: 'currentDebt', type: 'uint128' },
          { internalType: 'uint64', name: 'lastPayoutTimestamp', type: 'uint64' },
          { internalType: 'uint64', name: 'registeredAt', type: 'uint64' },
          { internalType: 'uint32', name: 'payoutCount', type: 'uint32' },
        ],
        internalType: 'struct IHashCreditManager.BorrowerInfo',
        name: 'info',
        type: 'tuple',
      },
    ],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [
      { internalType: 'address', name: 'borrower', type: 'address' },
      { internalType: 'bytes32', name: 'btcPayoutKeyHash', type: 'bytes32' },
    ],
    name: 'registerBorrower',
    outputs: [],
    stateMutability: 'nonpayable',
    type: 'function',
  },
  {
    inputs: [{ internalType: 'address', name: 'newVerifier', type: 'address' }],
    name: 'setVerifier',
    outputs: [],
    stateMutability: 'nonpayable',
    type: 'function',
  },
  {
    inputs: [{ internalType: 'bytes', name: 'proof', type: 'bytes' }],
    name: 'submitPayout',
    outputs: [],
    stateMutability: 'nonpayable',
    type: 'function',
  },
  {
    inputs: [{ internalType: 'uint256', name: 'amount', type: 'uint256' }],
    name: 'borrow',
    outputs: [],
    stateMutability: 'nonpayable',
    type: 'function',
  },
  {
    inputs: [{ internalType: 'uint256', name: 'amount', type: 'uint256' }],
    name: 'repay',
    outputs: [],
    stateMutability: 'nonpayable',
    type: 'function',
  },
] as const;

export const BtcSpvVerifierAbi = [
  {
    inputs: [],
    name: 'owner',
    outputs: [{ internalType: 'address', name: '', type: 'address' }],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [],
    name: 'checkpointManager',
    outputs: [{ internalType: 'address', name: '', type: 'address' }],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [{ internalType: 'address', name: 'borrower', type: 'address' }],
    name: 'getBorrowerPubkeyHash',
    outputs: [{ internalType: 'bytes20', name: '', type: 'bytes20' }],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [
      { internalType: 'address', name: 'borrower', type: 'address' },
      { internalType: 'bytes20', name: 'pubkeyHash', type: 'bytes20' },
    ],
    name: 'setBorrowerPubkeyHash',
    outputs: [],
    stateMutability: 'nonpayable',
    type: 'function',
  },
] as const;

export const CheckpointManagerAbi = [
  {
    inputs: [],
    name: 'latestCheckpointHeight',
    outputs: [{ internalType: 'uint32', name: '', type: 'uint32' }],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [{ internalType: 'uint32', name: 'height', type: 'uint32' }],
    name: 'getCheckpoint',
    outputs: [
      {
        components: [
          { internalType: 'bytes32', name: 'blockHash', type: 'bytes32' },
          { internalType: 'uint32', name: 'height', type: 'uint32' },
          { internalType: 'uint256', name: 'chainWork', type: 'uint256' },
          { internalType: 'uint32', name: 'timestamp', type: 'uint32' },
        ],
        internalType: 'struct ICheckpointManager.Checkpoint',
        name: 'checkpoint',
        type: 'tuple',
      },
    ],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [],
    name: 'latestCheckpoint',
    outputs: [
      {
        components: [
          { internalType: 'bytes32', name: 'blockHash', type: 'bytes32' },
          { internalType: 'uint32', name: 'height', type: 'uint32' },
          { internalType: 'uint256', name: 'chainWork', type: 'uint256' },
          { internalType: 'uint32', name: 'timestamp', type: 'uint32' },
        ],
        internalType: 'struct ICheckpointManager.Checkpoint',
        name: '',
        type: 'tuple',
      },
    ],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [
      { internalType: 'uint32', name: 'height', type: 'uint32' },
      { internalType: 'bytes32', name: 'blockHash', type: 'bytes32' },
      { internalType: 'uint256', name: 'chainWork', type: 'uint256' },
      { internalType: 'uint32', name: 'timestamp', type: 'uint32' },
    ],
    name: 'setCheckpoint',
    outputs: [],
    stateMutability: 'nonpayable',
    type: 'function',
  },
] as const;

export const Erc20Abi = [
  {
    inputs: [{ internalType: 'address', name: 'account', type: 'address' }],
    name: 'balanceOf',
    outputs: [{ internalType: 'uint256', name: '', type: 'uint256' }],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [],
    name: 'decimals',
    outputs: [{ internalType: 'uint8', name: '', type: 'uint8' }],
    stateMutability: 'view',
    type: 'function',
  },
  {
    inputs: [
      { internalType: 'address', name: 'spender', type: 'address' },
      { internalType: 'uint256', name: 'amount', type: 'uint256' },
    ],
    name: 'approve',
    outputs: [{ internalType: 'bool', name: '', type: 'bool' }],
    stateMutability: 'nonpayable',
    type: 'function',
  },
] as const;

