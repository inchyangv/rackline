import fs from 'node:fs';
import path from 'node:path';

// Generated contract ABI snapshots; no key, network, or broadcast access.
const names = [
  'ProtocolRoles', 'ProviderRegistry', 'AuthorizationVerifier', 'AccountRegistry', 'DebtLedger',
  'LendingVaultV2', 'ControlRegistry', 'EvidenceBook', 'AttestcoinRevenueVerifier', 'ReceivableBook',
  'GpuRiskPolicy', 'ExposureController', 'CreditFacilityManager', 'RepaymentRouter', 'RecoveryManager',
  'SettlementReceiver', 'GovernanceTimelock', 'GpuTestToken', 'RevenueEscrow', 'SourceEscrow',
  'IProtocolRoles', 'IProviderRegistry', 'IAuthorizationVerifier', 'IAccountRegistry', 'IDebtLedger',
  'ILendingVaultV2', 'IControlRegistry', 'IEvidenceBook', 'IRevenueVerifier', 'IReceivableBook',
  'IRiskPolicy', 'IExposureController', 'ICreditFacilityManager', 'IRepaymentRouter', 'IRevenueEscrow',
];
const check = process.argv.includes('--check');
for (const name of names) {
  const artifact = JSON.parse(fs.readFileSync(path.join('out', `${name}.sol`, `${name}.json`), 'utf8'));
  if (!Array.isArray(artifact.abi) || artifact.abi.length === 0) throw new Error(`Missing ABI: ${name}`);
  const target = path.join('test/fixtures/gpu/abi', `${name}.json`);
  const content = `${JSON.stringify(artifact.abi, null, 2)}\n`;
  if (check) {
    if (!fs.existsSync(target) || fs.readFileSync(target, 'utf8') !== content) throw new Error(`ABI drift: ${target}`);
  } else fs.writeFileSync(target, content);
}
console.log(`${check ? 'Checked' : 'Exported'} ${names.length} GPU ABI snapshots`);
