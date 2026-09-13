import { useEffect, useId, useState } from "react";
import {
  ArrowDownLeft,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronDown,
  CircleHelp,
  Cpu,
  Download,
  ExternalLink,
  Layers3,
  Menu,
  Plus,
  RotateCcw,
  ShieldCheck,
  Wallet,
  X,
} from "lucide-react";
import { toast } from "sonner";
import {
  getDemoMaxAmount,
  useDemoStore,
  type DemoTransactionKind,
} from "./demo-store";
import { TransactionDialog } from "./transaction-dialog";
import { ProviderPage } from "./provider-page";
import { OperationsPage } from "./operations-page";
import "./preview.css";

type Page =
  | "overview"
  | "earn"
  | "borrow"
  | "providers"
  | "activity"
  | "operations";
const pages: Page[] = [
  "overview",
  "earn",
  "borrow",
  "providers",
  "activity",
  "operations",
];
const money = (value: number, digits = 0) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
const compact = (value: number) =>
  new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(value);
const percent = (value: number) => `${value.toFixed(1)}%`;

function readPage(): Page {
  const value = window.location.hash.slice(1);
  return pages.includes(value as Page) ? (value as Page) : "overview";
}

function Token({ small = false }: { small?: boolean }) {
  return (
    <span
      className={`rl-token ${small ? "rl-token-small" : ""}`}
      aria-label="Demo USDC"
    >
      $
    </span>
  );
}

function RackArt() {
  return (
    <div className="rl-rack-art" aria-hidden="true">
      <div className="rl-orbit rl-orbit-one" />
      <div className="rl-orbit rl-orbit-two" />
      <div className="rl-art-grid" />
      <div className="rl-racks">
        {[0, 1, 2].map((rack) => (
          <div key={rack} className={`rl-rack rl-rack-${rack}`}>
            <div className="rl-rack-top" />
            {[0, 1, 2, 3, 4].map((row) => (
              <div key={row} className="rl-rack-slot">
                <span />
                <span />
                <i />
                <i />
                <b />
              </div>
            ))}
            <div className="rl-rack-base" />
          </div>
        ))}
      </div>
      <div className="rl-art-label rl-art-label-a">
        <span className="rl-live-dot" /> Compute at work
      </div>
      <div className="rl-art-label rl-art-label-b">
        <ShieldCheck size={14} /> Receivable-backed
      </div>
    </div>
  );
}

function Trend({
  range,
  mode = "assets",
}: {
  range: string;
  mode?: "assets" | "yield";
}) {
  const id = useId().replace(/:/g, "");
  const lines: Record<string, number[]> = {
    "1W": [114, 107, 112, 86, 89, 75, 77, 70, 73, 50, 56, 38, 40, 20],
    "1M": [
      144, 140, 148, 131, 134, 117, 120, 96, 103, 100, 84, 88, 63, 73, 54, 60,
      37, 39, 20,
    ],
    "3M": [
      161, 159, 153, 155, 137, 147, 134, 125, 128, 118, 110, 119, 93, 97, 76,
      84, 66, 61, 65, 39, 49, 20,
    ],
    ALL: [
      173, 170, 157, 163, 149, 141, 145, 121, 131, 101, 107, 94, 101, 73, 83,
      60, 65, 43, 49, 20,
    ],
  };
  const points = (lines[range] ?? lines["1M"]).map((point) =>
    mode === "yield" ? 100.4 + (point - 20) * 0.3 : point + 8,
  );
  const dates: Record<string, string[]> = {
    "1W": ["Sep 08", "Sep 10", "Sep 12", "Sep 14"],
    "1M": ["Aug 15", "Aug 25", "Sep 04", "Sep 14"],
    "3M": ["Jun 15", "Jul 15", "Aug 15", "Sep 14"],
    ALL: ["Jan 01", "Apr 01", "Jul 01", "Sep 14"],
  };
  const path = points
    .map(
      (y, index) =>
        `${index === 0 ? "M" : "L"} ${(index / (points.length - 1)) * 680} ${y}`,
    )
    .join(" ");
  return (
    <div
      className="rl-chart"
      role="img"
      aria-label={`Illustrative ${range} ${mode === "assets" ? "vault assets" : "supply APY"} trend. Synthetic historical data.`}
    >
      <div className="rl-chart-axis">
        <span>{mode === "assets" ? "$2.5M" : "9.0%"}</span>
        <span>{mode === "assets" ? "$2.0M" : "8.5%"}</span>
        <span>{mode === "assets" ? "$1.5M" : "8.0%"}</span>
      </div>
      <svg viewBox="0 0 680 200" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#2563eb" stopOpacity=".15" />
            <stop offset="100%" stopColor="#2563eb" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[25, 90, 155].map((y) => (
          <line
            key={y}
            x1="0"
            x2="680"
            y1={y}
            y2={y}
            stroke="#e9edf3"
            strokeDasharray="4 5"
          />
        ))}
        <path d={`${path} L 680 200 L 0 200 Z`} fill={`url(#${id})`} />
        <path
          d={path}
          fill="none"
          stroke="#2864ef"
          strokeWidth="2.5"
          vectorEffect="non-scaling-stroke"
          strokeLinejoin="round"
        />
        <circle cx="680" cy={points[points.length - 1]} r="4" fill="#2864ef" />
      </svg>
      <div className="rl-chart-dates">
        {(dates[range] ?? dates["1M"]).map((date) => (
          <span key={date}>{date}</span>
        ))}
      </div>
    </div>
  );
}

function RangeTabs({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="rl-range" aria-label="Chart period">
      {["1W", "1M", "3M", "ALL"].map((range) => (
        <button
          key={range}
          aria-pressed={value === range}
          onClick={() => onChange(range)}
        >
          {range}
        </button>
      ))}
    </div>
  );
}

function Metric({
  title,
  value,
  detail,
  positive,
}: {
  title: string;
  value: string;
  detail: string;
  positive?: boolean;
}) {
  return (
    <div className="rl-metric">
      <span className="rl-muted">{title}</span>
      <strong>{value}</strong>
      <span className={positive ? "rl-positive" : "rl-muted"}>
        {positive && <ArrowUpRight size={13} />} {detail}
      </span>
    </div>
  );
}

function Overview({
  navigate,
  transact,
}: {
  navigate: (page: Page) => void;
  transact: (kind: DemoTransactionKind) => void;
}) {
  const state = useDemoStore();
  const [range, setRange] = useState("1M");
  return (
    <>
      <section className="rl-hero">
        <div className="rl-hero-copy">
          <div className="rl-eyebrow">
            <span className="rl-blue-dot" /> THE NEXT LAYER OF GPU FINANCE
          </div>
          <h1>
            Real compute.
            <br />
            <span>Productive capital.</span>
          </h1>
          <p>
            Put capital to work. Unlock liquidity from earned GPU revenue, or
            supply the credit that powers it.
          </p>
          <div className="rl-hero-actions">
            <button
              className="rl-button rl-button-primary"
              onClick={() => navigate("earn")}
            >
              Explore the vault <ArrowUpRight size={16} />
            </button>
            <button
              className="rl-text-button"
              onClick={() => navigate("borrow")}
            >
              Get working capital <ArrowRight size={16} />
            </button>
          </div>
        </div>
        <RackArt />
      </section>
      <div className="rl-infrastructure">
        <span>BUILT AROUND REAL COMPUTE</span>
        <div className="rl-partner-wordmark">
          <span className="rl-aethir-mark">A</span> Aethir
        </div>
        <div className="rl-partner-wordmark">
          <Cpu size={19} /> GPU.net
        </div>
        <i />
        <div className="rl-partner-wordmark rl-infra-wordmark">
          <Layers3 size={18} /> Creditcoin
        </div>
        <div className="rl-partner-wordmark rl-infra-wordmark">
          <ShieldCheck size={18} /> Attestcoin
        </div>
        <span className="rl-fixture-label">Illustrative integrations</span>
      </div>
      <section className="rl-metrics" aria-label="Demo market statistics">
        <Metric
          title="Total supplied"
          value={money(state.vaultAssets)}
          detail="Illustrative vault NAV"
        />
        <Metric
          title="Capital at work"
          value={money(state.vaultAssets - state.vaultCash)}
          detail={`${percent((1 - state.vaultCash / state.vaultAssets) * 100)} utilization`}
        />
        <Metric
          title="Indicative supply APY"
          value="8.42%"
          detail="Variable · sample annualized rate"
          positive
        />
        <Metric
          title="Available liquidity"
          value={money(state.vaultCash)}
          detail="Excludes borrower reserves"
        />
      </section>
      <div className="rl-section-heading">
        <div>
          <h2>A market for productive capital</h2>
          <p>One clear connection between GPU operators and liquidity.</p>
        </div>
        <span className="rl-badge">
          <span className="rl-blue-dot" /> Creditcoin · Preview
        </span>
      </div>
      <div className="rl-overview-grid">
        <section className="rl-panel rl-vault-panel">
          <div className="rl-panel-header">
            <div className="rl-identity">
              <Token />
              <div>
                <h3>GPU Credit Vault</h3>
                <span className="rl-muted">
                  Diversified GPU receivables · Demo USDC
                </span>
              </div>
            </div>
            <span className="rl-badge rl-badge-blue">Earn</span>
          </div>
          <div className="rl-vault-headline">
            <div>
              <span className="rl-muted">Total supplied</span>
              <strong>{money(state.vaultAssets)}</strong>
              <span className="rl-chart-caption">
                Illustrative history · not live performance
              </span>
            </div>
            <RangeTabs value={range} onChange={setRange} />
          </div>
          <Trend range={range} />
          <div className="rl-vault-bottom">
            <div>
              <span className="rl-muted">Indicative supply APY</span>
              <strong className="rl-positive">
                8.42% <ArrowUpRight size={17} />
              </strong>
            </div>
            <div>
              <span className="rl-muted">Liquidity</span>
              <strong>{money(state.vaultCash)}</strong>
            </div>
            <button
              className="rl-button rl-button-primary"
              onClick={() => transact("supply")}
            >
              Supply <Plus size={16} />
            </button>
          </div>
        </section>
        <aside className="rl-portfolio-card">
          <div className="rl-panel-header">
            <h3>Your workspace</h3>
            <Wallet size={18} />
          </div>
          <div className="rl-portfolio-total">
            <span className="rl-muted">Your supplied balance</span>
            <strong>{money(state.supplied, 2)}</strong>
            <span className="rl-positive">
              <span className="rl-live-dot" /> Demo portfolio
            </span>
          </div>
          <div className="rl-portfolio-row">
            <span>Outstanding debt</span>
            <strong>{money(state.debt + state.interest, 2)}</strong>
          </div>
          <div className="rl-portfolio-row">
            <span>Available to borrow</span>
            <strong>{money(getDemoMaxAmount(state, "borrow"))}</strong>
          </div>
          <div className="rl-portfolio-row">
            <span>Wallet balance</span>
            <strong>{money(state.walletBalance, 2)}</strong>
          </div>
          <button
            className="rl-button rl-button-secondary rl-full"
            onClick={() => navigate("borrow")}
          >
            Manage your facility <ArrowRight size={16} />
          </button>
          <div className="rl-portfolio-note">
            <ShieldCheck size={17} />
            <p>
              Credit against receivables.
              <br />
              <span>Not your GPUs. Not future earnings.</span>
            </p>
          </div>
        </aside>
      </div>
      <div className="rl-section-heading">
        <div>
          <h2>Compute, connected.</h2>
          <p>Explore the provider routes behind your credit.</p>
        </div>
        <button
          className="rl-text-button"
          onClick={() => navigate("providers")}
        >
          View providers <ArrowRight size={16} />
        </button>
      </div>
      <div className="rl-provider-strip">
        {[
          {
            name: "Aethir",
            detail: "Distributed enterprise compute",
            amount: 98000,
            share: "70%",
            icon: "A",
          },
          {
            name: "GPU.net",
            detail: "Decentralized GPU infrastructure",
            amount: 42000,
            share: "30%",
            icon: "G",
          },
        ].map((provider) => (
          <button
            key={provider.name}
            className="rl-provider-summary"
            onClick={() => navigate("providers")}
          >
            <span
              className={`rl-provider-avatar ${provider.icon === "G" ? "rl-provider-purple" : ""}`}
            >
              {provider.icon}
            </span>
            <div>
              <strong>{provider.name}</strong>
              <span>{provider.detail}</span>
            </div>
            <div className="rl-provider-amount">
              <strong>{money(provider.amount)}</strong>
              <span>Sample unpaid receivables · {provider.share}</span>
            </div>
            <ArrowUpRight size={18} />
          </button>
        ))}
      </div>
    </>
  );
}

function EarnPage({
  transact,
}: {
  transact: (kind: DemoTransactionKind) => void;
}) {
  const state = useDemoStore();
  const [range, setRange] = useState("1M");
  const [view, setView] = useState<"performance" | "allocation">("performance");
  const [riskOpen, setRiskOpen] = useState(false);
  return (
    <>
      <div className="rl-page-heading">
        <div className="rl-eyebrow">EARN ON PRODUCTIVE CAPITAL</div>
        <h1>
          GPU Credit Vault
          <span className="rl-badge rl-badge-blue">Demo USDC</span>
        </h1>
        <p>
          Supply liquidity to a diversified portfolio of confirmed GPU
          receivables.
        </p>
      </div>
      <div className="rl-earn-grid">
        <div>
          <section className="rl-panel">
            <div className="rl-panel-header">
              <div className="rl-identity">
                <Token />
                <div>
                  <h3>Rackline GPU Credit</h3>
                  <span className="rl-muted">
                    Creditcoin · Illustrative vault
                  </span>
                </div>
              </div>
              <ShieldCheck className="rl-blue" size={24} />
            </div>
            <div className="rl-vault-stat-grid">
              <Metric
                title="Indicative supply APY"
                value="8.42%"
                detail="Variable · after 10% performance fee"
                positive
              />
              <Metric
                title="Total supplied"
                value={`$${compact(state.vaultAssets)}`}
                detail="Sample net asset value"
              />
              <Metric
                title="Available liquidity"
                value={`$${compact(state.vaultCash)}`}
                detail="Immediate withdrawals"
              />
            </div>
            <div className="rl-chart-toolbar">
              <div className="rl-subtabs">
                <button
                  aria-pressed={view === "performance"}
                  onClick={() => setView("performance")}
                >
                  Performance
                </button>
                <button
                  aria-pressed={view === "allocation"}
                  onClick={() => setView("allocation")}
                >
                  Allocation
                </button>
              </div>
              <RangeTabs value={range} onChange={setRange} />
            </div>
            {view === "performance" ? (
              <>
                <Trend range={range} mode="yield" />
                <p className="rl-fine-print">
                  Synthetic APY history. Estimates are not realized returns or a
                  promise of future yield.
                </p>
              </>
            ) : (
              <div className="rl-allocation">
                <div className="rl-allocation-bar">
                  <span />
                  <span />
                </div>
                <div>
                  <span>
                    <i className="rl-blue-dot" /> Aethir receivables
                  </span>
                  <strong>
                    70% · {money((state.vaultAssets - state.vaultCash) * 0.7)}
                  </strong>
                </div>
                <div>
                  <span>
                    <i className="rl-purple-dot" /> GPU.net receivables
                  </span>
                  <strong>
                    30% · {money((state.vaultAssets - state.vaultCash) * 0.3)}
                  </strong>
                </div>
                <p className="rl-fine-print">
                  Illustrative allocation of deployed capital. Provider
                  receivables are not added again to vault NAV.
                </p>
              </div>
            )}
          </section>
          <section className="rl-panel rl-details-panel">
            <h3>Know what your capital funds</h3>
            <div className="rl-three-principles">
              <div>
                <Layers3 size={23} />
                <h4>Earned, not projected</h4>
                <p>
                  Credit is based on confirmed unpaid receivables, not estimates
                  of future GPU revenue.
                </p>
              </div>
              <div>
                <ShieldCheck size={23} />
                <h4>Payment-path control</h4>
                <p>
                  Eligible receivables require independent rights review and E2
                  payment control.
                </p>
              </div>
              <div>
                <ArrowDownToLine size={23} />
                <h4>Cash before repayment</h4>
                <p>
                  Only allocated destination cash can repay a facility. A proof
                  alone cannot.
                </p>
              </div>
            </div>
            <button
              className="rl-disclosure-button"
              aria-expanded={riskOpen}
              onClick={() => setRiskOpen(!riskOpen)}
            >
              <span>Risk, fees & withdrawal terms</span>
              <ChevronDown size={17} className={riskOpen ? "rl-rotate" : ""} />
            </button>
            {riskOpen && (
              <div className="rl-risk-copy">
                Capital is at risk from borrower default, disputed receivables,
                payment-control failure, smart-contract issues, and settlement
                delays. The sample 8.42% APY is annualized and net of an
                illustrative 10% fee on realized interest; it is not guaranteed.
                Withdrawals depend on available vault cash and may queue. Demo
                balances are synthetic, not redeemable tokens. Production asset
                selection and risk parameters remain subject to approval.
              </div>
            )}
          </section>
        </div>
        <aside>
          <section className="rl-panel rl-position-panel">
            <div className="rl-panel-header">
              <h3>Your position</h3>
              <span className="rl-badge">Demo</span>
            </div>
            <span className="rl-muted">Supplied assets</span>
            <strong className="rl-position-value">
              {money(state.supplied, 2)}
            </strong>
            <div className="rl-position-detail">
              <span>Wallet balance</span>
              <strong>{money(state.walletBalance, 2)}</strong>
            </div>
            <div className="rl-position-detail">
              <span>Sample realized earnings¹</span>
              <strong className="rl-positive">$86.42</strong>
            </div>
            <div className="rl-action-stack">
              <button
                className="rl-button rl-button-primary"
                onClick={() => transact("supply")}
              >
                Supply <Plus size={16} />
              </button>
              <button
                className="rl-button rl-button-secondary"
                onClick={() => transact("withdraw")}
              >
                Withdraw <ArrowUpRight size={16} />
              </button>
            </div>
            <p className="rl-fine-print">
              ¹ Seeded past-period fixture, not accrued live yield. Included in
              the sample supplied balance.
            </p>
          </section>
          <section className="rl-panel rl-queue-panel">
            <h3>
              Withdrawal queue{" "}
              <span className="rl-count">{state.queue.length}</span>
            </h3>
            {state.queue.length === 0 ? (
              <div className="rl-empty-small">
                <Check size={22} />
                <strong>Nothing in the queue</strong>
                <p>
                  Requests appear here when vault liquidity is insufficient.
                </p>
                <button
                  className="rl-text-button"
                  disabled={state.vaultCash <= 5000}
                  onClick={() => {
                    const result = state.simulateLiquidityStress();
                    if (!result.ok) toast.error(result.message);
                    else toast.success(result.message);
                  }}
                >
                  {state.vaultCash <= 5000
                    ? "Limited liquidity scenario active"
                    : "Try limited liquidity"}
                </button>
                {state.vaultCash <= 5000 && (
                  <p>
                    Withdraw over the available cash to queue. Then supply or
                    repay to replenish liquidity.
                  </p>
                )}
              </div>
            ) : (
              state.queue.map((item) => (
                <div className="rl-queue-item" key={item.id}>
                  <div>
                    <strong>{money(item.amount, 2)}</strong>
                    <span className="rl-badge">{item.status}</span>
                  </div>
                  {item.status === "pending" ? (
                    <>
                      <button
                        className="rl-text-button"
                        onClick={() => {
                          const result = state.settleWithdrawal(item.id);
                          if (!result.ok) toast.error(result.message);
                          else toast.success(result.message);
                        }}
                      >
                        Simulate settlement
                      </button>
                      <button
                        className="rl-text-button"
                        onClick={() => {
                          const result = state.cancelWithdrawal(item.id);
                          if (!result.ok) toast.error(result.message);
                          else toast.success(result.message);
                        }}
                      >
                        Cancel request
                      </button>
                    </>
                  ) : (
                    <button
                      className="rl-button rl-button-secondary"
                      onClick={() => {
                        const result = state.claimWithdrawal(item.id);
                        if (!result.ok) toast.error(result.message);
                        else toast.success(result.message);
                      }}
                    >
                      Claim demo funds
                    </button>
                  )}
                </div>
              ))
            )}
          </section>
        </aside>
      </div>
    </>
  );
}

function BorrowPage({
  transact,
  navigate,
}: {
  transact: (kind: DemoTransactionKind) => void;
  navigate: (page: Page) => void;
}) {
  const state = useDemoStore();
  const blocked = state.scenario !== "healthy";
  const totalDebt = state.debt + state.interest;
  const available = getDemoMaxAmount(state, "borrow");
  return (
    <>
      <div className="rl-page-heading">
        <div className="rl-eyebrow">WORKING CAPITAL, UNLOCKED</div>
        <h1>Your compute. More possibilities.</h1>
        <p>
          Access liquidity from revenue you have already earned. Keep your GPUs
          working.
        </p>
      </div>
      <div className="rl-facility-bar">
        <div className="rl-identity">
          <span className="rl-facility-icon">
            <Cpu size={21} />
          </span>
          <div>
            <strong>Atlas Compute · Working capital</strong>
            <span className="rl-muted">
              Facility DEMO-001 · Demo USDC · Sample terms
            </span>
          </div>
        </div>
        <span
          className={`rl-badge ${blocked ? "rl-badge-amber" : "rl-badge-green"}`}
        >
          <span className="rl-live-dot" />
          {blocked
            ? "New draws paused"
            : totalDebt === 0
              ? "Debt repaid · control retained"
              : "Active · simulation"}
        </span>
      </div>
      {blocked && (
        <div className="rl-notice" role="status">
          <ShieldCheck size={19} />
          <div>
            <strong>
              {state.scenario === "proof-pending"
                ? "Waiting for source proof"
                : "Payment-control review required"}
            </strong>
            <p>
              New borrowing is unavailable in this scenario. Existing debt is
              unchanged and direct repayment remains available.
            </p>
          </div>
        </div>
      )}
      <section className="rl-metrics">
        <Metric
          title="Unpaid receivables"
          value="$140,000"
          detail={
            blocked
              ? "Eligibility pending · draw blocked"
              : "Eligible · simulated current balance"
          }
        />
        <Metric
          title="Credit limit"
          value={money(state.creditLimit)}
          detail="70% illustrative advance rate"
        />
        <Metric
          title="Outstanding debt"
          value={money(totalDebt, 2)}
          detail={`${money(state.debt)} principal + ${money(state.interest, 2)} interest`}
        />
        <Metric
          title="Borrow APR"
          value="11.50%"
          detail="Illustrative rate · not LP yield"
        />
      </section>
      <div className="rl-borrow-grid">
        <div>
          <section className="rl-panel rl-details-panel">
            <div className="rl-panel-header">
              <h3>Your borrowing power</h3>
              <span className="rl-badge">DEMO-001</span>
            </div>
            <div className="rl-borrowing-power">
              <div>
                <span className="rl-muted">Available to borrow</span>
                <strong>{money(available, 2)}</strong>
              </div>
              <span>
                {percent((totalDebt / state.creditLimit) * 100)} utilized
              </span>
            </div>
            <div className="rl-capacity-track">
              <span
                style={{
                  width: `${Math.min(100, (totalDebt / state.creditLimit) * 100)}%`,
                }}
              />
            </div>
            <div className="rl-capacity-labels">
              <span>Debt {money(totalDebt)}</span>
              <span>Limit {money(state.creditLimit)}</span>
            </div>
            <div className="rl-terms-grid">
              <div>
                <span>Next payment date</span>
                <strong>October 14, 2026</strong>
              </div>
              <div>
                <span>Facility maturity</span>
                <strong>October 14, 2026</strong>
              </div>
              <div>
                <span>Payment sweep</span>
                <strong>100% until debt repaid</strong>
              </div>
              <div>
                <span>Payment control</span>
                <strong>
                  {state.scenario === "control-expired"
                    ? "Expired · draw blocked"
                    : "E2 · simulated"}
                </strong>
              </div>
            </div>
          </section>
          <section className="rl-panel rl-details-panel">
            <div className="rl-panel-header">
              <h3>From compute to capital</h3>
              <button
                className="rl-text-button"
                onClick={() => navigate("providers")}
              >
                View evidence <ArrowUpRight size={15} />
              </button>
            </div>
            <div className="rl-proof-flow">
              {[
                {
                  title: "Source event",
                  detail: "Confirmed unpaid claim",
                  complete: true,
                },
                {
                  title: "Attestcoin proof",
                  detail:
                    state.scenario === "proof-pending"
                      ? "Awaiting proof · fixture"
                      : "Native path · simulated",
                  complete: state.scenario !== "proof-pending",
                },
                {
                  title: "Rights & E2",
                  detail:
                    state.scenario === "control-expired"
                      ? "Control expired"
                      : "Independent demo checks",
                  complete: !blocked,
                },
                {
                  title: "Credit decision",
                  detail: blocked
                    ? "Draw unavailable"
                    : "Eligible · demo policy",
                  complete: !blocked,
                },
              ].map((step, index) => (
                <div className="rl-proof-step" key={step.title}>
                  <span className={step.complete ? "rl-step-complete" : ""}>
                    {step.complete ? <Check size={14} /> : index + 1}
                  </span>
                  <strong>{step.title}</strong>
                  <small>{step.detail}</small>
                </div>
              ))}
            </div>
            <div className="rl-inline-note">
              <CircleHelp size={15} />
              <span>
                A source proof is not cash received. Debt is reduced only when a
                demo repayment is applied.
              </span>
            </div>
          </section>
          <section className="rl-panel rl-details-panel">
            <h3>Repayment & release</h3>
            <div className="rl-repayment-track">
              <div>
                <span className="rl-badge">1</span>
                <strong>Destination cash</strong>
                <p>Funds must arrive in the designated loan asset.</p>
              </div>
              <ArrowRight size={16} />
              <div>
                <span className="rl-badge">2</span>
                <strong>Facility allocation</strong>
                <p>Accrued interest first, then outstanding principal.</p>
              </div>
              <ArrowRight size={16} />
              <div>
                <span className="rl-badge">3</span>
                <strong>Separate release</strong>
                <p>Zero debt does not automatically release payment control.</p>
              </div>
            </div>
          </section>
        </div>
        <aside>
          <section className="rl-panel rl-position-panel">
            <h3>Manage your credit</h3>
            <span className="rl-muted">Available demo balance</span>
            <strong className="rl-position-value">
              {money(state.walletBalance, 2)}
            </strong>
            <div className="rl-action-stack">
              <button
                className="rl-button rl-button-primary"
                disabled={blocked || available <= 0}
                onClick={() => transact("borrow")}
              >
                Borrow <ArrowUpRight size={16} />
              </button>
              <button
                className="rl-button rl-button-secondary"
                disabled={totalDebt <= 0}
                onClick={() => transact("repay")}
              >
                Repay <ArrowDownLeft size={16} />
              </button>
            </div>
            <div className="rl-inline-note">
              <ShieldCheck size={16} />
              <span>
                Direct repayment stays available during proof or control
                interruptions.
              </span>
            </div>
          </section>
          <section className="rl-panel rl-details-panel rl-scenario-card">
            <div className="rl-eyebrow">DEMO SCENARIOS</div>
            <h3>See the safeguards in action</h3>
            <label htmlFor="demo-scenario">Facility condition</label>
            <select
              id="demo-scenario"
              value={state.scenario}
              onChange={(event) =>
                state.setScenario(event.target.value as typeof state.scenario)
              }
            >
              <option value="healthy">Healthy facility</option>
              <option value="proof-pending">Native proof pending</option>
              <option value="control-expired">Payment control expired</option>
            </select>
            <p className="rl-fine-print">
              Changes the local fixture only. Cannot verify real evidence or
              change production policy.
            </p>
          </section>
        </aside>
      </div>
    </>
  );
}

function ActivityPage() {
  const activities = useDemoStore((state) => state.activities);
  const [filter, setFilter] = useState("all");
  const filtered = activities.filter(
    (item) => filter === "all" || item.kind === filter,
  );
  function exportCsv() {
    const cell = (value: unknown) =>
      `"${String(value ?? "").replaceAll('"', '""')}"`;
    const csv = [
      "Profile,Date,Type,Description,Amount",
      ...filtered.map((item) =>
        ["LOCAL_MOCK", item.createdAt, item.kind, item.title, item.amount ?? ""]
          .map(cell)
          .join(","),
      ),
    ].join("\n");
    const url = URL.createObjectURL(
      new Blob([csv], { type: "text/csv;charset=utf-8;" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "rackline-demo-activity.csv";
    link.click();
    URL.revokeObjectURL(url);
    toast.success("Demo activity exported");
  }
  return (
    <>
      <div className="rl-page-heading rl-heading-row">
        <div>
          <div className="rl-eyebrow">YOUR CAPITAL, IN MOTION</div>
          <h1>Activity</h1>
          <p>A clear record of every action in your demo workspace.</p>
        </div>
        <button className="rl-button rl-button-secondary" onClick={exportCsv}>
          <Download size={16} /> Export CSV
        </button>
      </div>
      <section className="rl-panel">
        <div className="rl-panel-header">
          <div className="rl-subtabs rl-activity-tabs">
            {["all", "supply", "withdraw", "borrow", "repay"].map((kind) => (
              <button
                key={kind}
                aria-pressed={filter === kind}
                onClick={() => setFilter(kind)}
              >
                {kind === "all"
                  ? "All activity"
                  : kind[0].toUpperCase() + kind.slice(1)}
              </button>
            ))}
          </div>
          <span className="rl-muted">{filtered.length} records</span>
        </div>
        <div className="rl-table-scroll">
          <table className="rl-table">
            <thead>
              <tr>
                <th>Transaction</th>
                <th>Details</th>
                <th>Amount</th>
                <th>Status</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item) => (
                <tr key={item.id}>
                  <td>
                    <div className="rl-identity">
                      <span className="rl-activity-icon">
                        {item.kind === "borrow" || item.kind === "withdraw" ? (
                          <ArrowUpRight size={17} />
                        ) : (
                          <ArrowDownLeft size={17} />
                        )}
                      </span>
                      <strong>{item.title}</strong>
                    </div>
                  </td>
                  <td className="rl-muted">{item.detail}</td>
                  <td className="rl-tabular">
                    {item.amount == null ? "—" : money(item.amount, 2)}
                  </td>
                  <td>
                    <span className="rl-badge rl-badge-blue">Simulated</span>
                  </td>
                  <td className="rl-muted">
                    {new Date(item.createdAt).toLocaleString("en-US", {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {filtered.length === 0 && (
          <div className="rl-empty-small">
            <Layers3 size={28} />
            <strong>No {filter === "all" ? "" : filter} activity yet</strong>
            <p>
              Try an action in Earn or Borrow to create a local demo record.
            </p>
          </div>
        )}
        <p className="rl-table-note">
          Local simulation records only. No blockchain transactions were signed
          or broadcast.
        </p>
      </section>
    </>
  );
}

export function PreviewApp() {
  const [page, setPage] = useState<Page>(readPage);
  const [transaction, setTransaction] = useState<DemoTransactionKind | null>(
    null,
  );
  const [menuOpen, setMenuOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [workspaceVersion, setWorkspaceVersion] = useState(0);
  const state = useDemoStore();
  useEffect(() => {
    const listener = () => setPage(readPage());
    window.addEventListener("hashchange", listener);
    return () => window.removeEventListener("hashchange", listener);
  }, []);
  function navigate(next: Page) {
    window.location.hash = next;
    setPage(next);
    setMenuOpen(false);
    window.scrollTo({ top: 0, behavior: "instant" });
  }
  function openTransaction(kind: DemoTransactionKind) {
    setTransaction(kind);
  }
  return (
    <div className="rl-app">
      <a
        className="rl-skip-link"
        href="#main-content"
        onClick={(event) => {
          event.preventDefault();
          document.getElementById("main-content")?.focus();
          document.getElementById("main-content")?.scrollIntoView();
        }}
      >
        Skip to content
      </a>
      <header className="rl-header">
        <div className="rl-header-inner">
          <button
            className="rl-brand"
            onClick={() => navigate("overview")}
            aria-label="Rackline overview"
          >
            <span className="rl-brand-mark">
              <i />
              <i />
              <i />
            </span>
            rackline<span className="rl-brand-period">.</span>
          </button>
          <nav
            className={`rl-nav ${menuOpen ? "rl-nav-open" : ""}`}
            aria-label="Main navigation"
          >
            {pages.map((item) => (
              <button
                key={item}
                aria-current={page === item ? "page" : undefined}
                onClick={() => navigate(item)}
              >
                {item[0].toUpperCase() + item.slice(1)}
              </button>
            ))}
          </nav>
          <div className="rl-header-actions">
            <span className="rl-network">
              <Layers3 size={15} /> Creditcoin
            </span>
            <button
              className="rl-wallet-button"
              onClick={() => {
                if (state.connected) {
                  state.disconnect();
                  toast("Demo wallet disconnected");
                } else {
                  state.connect();
                  toast.success(
                    "Demo wallet connected. No wallet signature required.",
                  );
                }
              }}
            >
              <Wallet size={16} />
              <span>
                {state.connected ? "Demo wallet" : "Connect demo wallet"}
              </span>
              {state.connected && <span className="rl-live-dot" />}
            </button>
            <button
              className="rl-icon-button rl-mobile-toggle"
              aria-label={menuOpen ? "Close navigation" : "Open navigation"}
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen(!menuOpen)}
            >
              {menuOpen ? <X size={21} /> : <Menu size={21} />}
            </button>
          </div>
        </div>
      </header>
      <div className="rl-demo-bar">
        <div>
          <span className="rl-demo-pill">INTERACTIVE DEMO</span>
          <span>
            Synthetic balances. Simulated providers and proofs. No real funds
            move.
          </span>
          <button
            onClick={() => setHelpOpen(!helpOpen)}
            aria-expanded={helpOpen}
          >
            How it works <CircleHelp size={13} />
          </button>
        </div>
      </div>
      {helpOpen && (
        <div className="rl-demo-help">
          <strong>
            A complete product walkthrough, isolated from live infrastructure.
          </strong>
          <p>
            Explore Earn, Borrow, Providers, and Operations without a wallet.
            USDC is a demo denomination, not an approved production asset.
            Creditcoin is the intended execution chain; official Attestcoin is
            the required native proof path. This preview does not call either
            network or partner APIs. Sample checks cannot establish real GPU
            ownership, revenue, E2 control, or native verification.
          </p>
          <button className="rl-text-button" onClick={() => setHelpOpen(false)}>
            Got it <Check size={14} />
          </button>
        </div>
      )}
      <main id="main-content" className="rl-main" tabIndex={-1}>
        {page === "overview" && (
          <Overview navigate={navigate} transact={openTransaction} />
        )}
        {page === "earn" && <EarnPage transact={openTransaction} />}
        {page === "borrow" && (
          <BorrowPage transact={openTransaction} navigate={navigate} />
        )}
        <div
          hidden={page !== "providers"}
          key={`providers-${workspaceVersion}`}
        >
          <ProviderPage />
        </div>
        {page === "activity" && <ActivityPage />}
        <div
          hidden={page !== "operations"}
          key={`operations-${workspaceVersion}`}
        >
          <OperationsPage />
        </div>
      </main>
      <footer className="rl-footer">
        <div>
          <span className="rl-footer-brand">rackline.</span>
          <span>Capital for the compute economy.</span>
        </div>
        <div>
          <a
            href="https://github.com/inchyangv/rackline"
            target="_blank"
            rel="noreferrer"
          >
            GitHub <ExternalLink size={12} />
          </a>
          <button
            onClick={() => {
              if (
                window.confirm(
                  "Reset all demo balances, transactions, and facility scenarios? No real funds are affected.",
                )
              ) {
                state.reset();
                setWorkspaceVersion((version) => version + 1);
                toast.success("Demo workspace reset");
              }
            }}
          >
            <RotateCcw size={13} /> Reset demo
          </button>
          <span className="rl-footer-status">
            <span className="rl-blue-dot" /> Local simulation
          </span>
        </div>
      </footer>
      {transaction && (
        <TransactionDialog
          kind={transaction}
          onClose={() => setTransaction(null)}
        />
      )}
    </div>
  );
}
