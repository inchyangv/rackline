import { useEffect, useRef, useState, type ReactNode } from "react";
import { Dialog } from "radix-ui";
import {
  ArrowUpRight,
  Check,
  Cpu,
  ExternalLink,
  Layers3,
  Menu,
  RefreshCw,
  ShieldCheck,
  Wallet,
  X,
} from "lucide-react";
import {
  apiBase,
  errorMessage,
  exactAmount,
  parseAmount,
  request,
  validateConfig,
  type Config,
  type LpData,
  type Session,
  type TransactionContext,
} from "./client";
import type {
  ConnectionDTO,
  ControlDTO,
  CreditStatusDTO,
  FacilityDTO,
  OperationDTO,
  ProviderDTO,
  ReceivableDTO,
  RepaymentDTO,
  SettlementDTO,
} from "./generated/api";
import {
  executeTransaction,
  quoteVault,
  type Action,
  type Progress,
} from "./transactions";
import { useGpuRead, useSession } from "./use-gpu";
import "../preview/preview.css";
import "../preview/provider-pages.css";
import "../preview/transaction-dialog.css";
import "./gpu.css";

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
const pageFromHash = (): Page =>
  pages.includes(window.location.hash.slice(1) as Page)
    ? (window.location.hash.slice(1) as Page)
    : "overview";
type Context = {
  config: Config;
  configurationError?: string;
  session: Session;
  refresh: number;
  reload: () => void;
};
type Transaction = {
  action: Action;
  reference?: string;
  title: string;
  maximum?: string;
  shares?: boolean;
  shareDecimals?: number;
};
const staffRoles = ["operator", "servicer", "guardian"];
const pretty = (value: string | null | undefined) =>
  value
    ? value
        .replace(/_/g, " ")
        .toLowerCase()
        .replace(/^./, (char) => char.toUpperCase())
    : "Not available";
const addressLabel = (value: string) =>
  `${value.slice(0, 6)}…${value.slice(-4)}`;
function Badge({ children }: { children: ReactNode }) {
  return <span className="rl-badge">{children}</span>;
}
function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="rl-empty-small">
      <Layers3 size={24} />
      <p>{children}</p>
    </div>
  );
}
function Notice({ error, children }: { error?: boolean; children: ReactNode }) {
  return (
    <div
      className={`gpu-notice ${error ? "gpu-notice-error" : ""}`}
      role={error ? "alert" : "status"}
    >
      {children}
    </div>
  );
}
function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rl-panel gpu-panel">
      <h2>{title}</h2>
      {children}
    </section>
  );
}
function Metric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rl-metric">
      <span className="rl-muted">{label}</span>
      <strong>{value}</strong>
      <span className="rl-muted">{detail}</span>
    </div>
  );
}
function ReadState({ loading, error }: { loading: boolean; error: string }) {
  return error ? (
    <Notice error>{error}</Notice>
  ) : loading ? (
    <Notice>Loading your records…</Notice>
  ) : null;
}
function ChainLink({
  config,
  hash,
}: {
  config: Config;
  hash: string | null | undefined;
}) {
  return hash && /^0x[0-9a-fA-F]{64}$/.test(hash) && config.explorerUrl ? (
    <a
      className="rl-text-button"
      href={`${config.explorerUrl.replace(/\/$/, "")}/tx/${hash}`}
      target="_blank"
      rel="noreferrer"
    >
      {addressLabel(hash)} <ExternalLink size={12} />
    </a>
  ) : (
    <span>{hash ? "Transaction recorded" : "Not applied on-chain"}</span>
  );
}

export function GpuApp() {
  const [state, setState] = useState<{ config: Config | null; error: string }>({
    config: null,
    error: "",
  });
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const load = () =>
      request<Config>("/v1/config", { signal: controller.signal })
        .then(validateConfig)
        .then((config) => {
          if (!controller.signal.aborted)
            setState((current) =>
              !current.error &&
              JSON.stringify(current.config) === JSON.stringify(config)
                ? current
                : { config, error: "" },
            );
        })
        .catch((error) => {
          if (!controller.signal.aborted)
            setState((current) => ({ ...current, error: errorMessage(error) }));
        });
    void load();
    const timer = setInterval(() => {
      void load();
    }, 60_000);
    const visible = () => {
      if (document.visibilityState === "visible") void load();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      controller.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [retry]);
  if (!state.config)
    return (
      <div className="rl-app gpu-loading">
        <span className="rl-brand">
          rackline<span className="rl-brand-period">.</span>
        </span>
        <h1>GPU receivables finance</h1>
        <p>{state.error || "Connecting to the GPU application…"}</p>
        {state.error && (
          <button
            className="rl-button rl-button-primary"
            onClick={() => setRetry(retry + 1)}
          >
            Retry connection
          </button>
        )}
        <a className="rl-text-button" href="/demo">
          Explore the interactive demo <ArrowUpRight size={16} />
        </a>
        <small>
          {apiBase()
            ? "Service configuration is checked before any wallet request."
            : "The GPU API has not been configured for this build."}
        </small>
      </div>
    );
  return (
    <ConnectedApp
      key={JSON.stringify([
        state.config.manifestHash,
        state.config.executionProfile,
        state.config.chainId,
        state.config.deploymentId,
        state.config.contracts,
        state.config.appDomain,
        state.config.requiredVerification,
      ])}
      config={state.config}
      configurationError={state.error}
    />
  );
}

function ConnectedApp({
  config,
  configurationError,
}: {
  config: Config;
  configurationError?: string;
}) {
  const auth = useSession(config);
  const [page, setPage] = useState<Page>(pageFromHash);
  const [menu, setMenu] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [transaction, setTransaction] = useState<Transaction | null>(null);
  useEffect(() => {
    const listener = () => setPage(pageFromHash());
    window.addEventListener("hashchange", listener);
    return () => window.removeEventListener("hashchange", listener);
  }, []);
  const allowedPages = auth.session?.roles.some((role) =>
    staffRoles.includes(role),
  )
    ? pages
    : pages.filter((item) => item !== "operations");
  const context = auth.session
    ? {
        config,
        configurationError,
        session: auth.session,
        refresh,
        reload: () => setRefresh((value) => value + 1),
      }
    : null;
  return (
    <div className="rl-app">
      <a className="rl-skip-link" href="#gpu-main">
        Skip to content
      </a>
      <header className="rl-header">
        <div className="rl-header-inner">
          <a className="rl-brand" href="#overview">
            <span className="rl-brand-mark">
              <i />
              <i />
              <i />
            </span>
            rackline<span className="rl-brand-period">.</span>
          </a>
          <nav
            className={`rl-nav ${menu ? "rl-nav-open" : ""}`}
            aria-label="Main navigation"
          >
            {allowedPages.map((item) => (
              <button
                key={item}
                aria-current={page === item ? "page" : undefined}
                onClick={() => {
                  window.location.hash = item;
                  setPage(item);
                  setMenu(false);
                }}
              >
                {pretty(item)}
              </button>
            ))}
          </nav>
          <div className="rl-header-actions">
            <span className="rl-network">
              <Layers3 size={15} />
              Chain {config.chainId}
            </span>
            <button
              className="rl-wallet-button"
              disabled={auth.busy}
              onClick={() =>
                auth.session ? auth.disconnect() : void auth.connect()
              }
            >
              <Wallet size={16} />
              <span>
                {auth.busy
                  ? "Signing in…"
                  : auth.session
                    ? addressLabel(auth.session.wallet)
                    : "Connect wallet"}
              </span>
            </button>
            <button
              className="rl-icon-button rl-mobile-toggle"
              aria-label={menu ? "Close navigation" : "Open navigation"}
              aria-expanded={menu}
              onClick={() => setMenu(!menu)}
            >
              {menu ? <X /> : <Menu />}
            </button>
          </div>
        </div>
      </header>
      <div className="rl-demo-bar">
        <div>
          <span className="rl-demo-pill">{config.executionProfile}</span>
          <span>
            {config.executionProfile === "PRODUCTION"
              ? "Connected GPU application"
              : "Test environment · test assets only"}{" "}
            ·{" "}
            {config.partnerRevenue === "SIMULATED"
              ? "Simulated partner revenue"
              : "Partner admission requires independent approval"}
          </span>
          <a href="/demo">
            Interactive demo <ArrowUpRight size={13} />
          </a>
        </div>
      </div>
      <main id="gpu-main" className="rl-main gpu-main" tabIndex={-1}>
        {auth.error && <Notice error>{auth.error}</Notice>}
        {!config.configured && (
          <Notice error>
            Deployment configuration is incomplete. Financial actions are
            unavailable. {config.configurationErrors?.join(" ")}
          </Notice>
        )}
        {!auth.session ? (
          <>
            <section className="rl-hero gpu-hero">
              <div className="rl-hero-copy">
                <div className="rl-eyebrow">
                  <span className="rl-blue-dot" /> EARNED REVENUE. WORKING
                  CAPITAL.
                </div>
                <h1>
                  Real compute.
                  <br />
                  <span>Productive capital.</span>
                </h1>
                <p>
                  Connect your wallet to view your GPU receivables, manage
                  credit, and supply the lending vault.
                </p>
                <div className="rl-hero-actions">
                  <button
                    className="rl-button rl-button-primary"
                    disabled={auth.busy}
                    onClick={() => void auth.connect()}
                  >
                    {auth.busy ? "Check your wallet…" : "Connect wallet"}{" "}
                    <ArrowUpRight size={16} />
                  </button>
                  <a className="rl-text-button" href="/demo">
                    Try the demo
                  </a>
                </div>
              </div>
              <div className="gpu-hero-art" aria-hidden="true">
                <Cpu size={104} strokeWidth={1} />
                <div>
                  <ShieldCheck size={20} /> Attestcoin required
                </div>
              </div>
            </section>
            <div className="gpu-grid">
              <Panel title="For GPU operators">
                <p>
                  Submit provider account and ownership references, review
                  payment control, and track each credit facility. Connection,
                  legal rights, native evidence, and credit approval are
                  separate checks.
                </p>
              </Panel>
              <Panel title="For capital providers">
                <p>
                  Supply the configured loan asset and receive vault shares.
                  Withdraw immediately when liquidity is available, or manage a
                  withdrawal request. Returns vary; capital is at risk.
                </p>
              </Panel>
            </div>
          </>
        ) : (
          context && (
            <div key={`${auth.session.wallet}:${auth.session.token}`}>
              <div className="gpu-heading">
                <div>
                  <p className="rl-eyebrow">YOUR GPU FINANCE WORKSPACE</p>
                  <h1 className="rl-page-heading">{pretty(page)}</h1>
                </div>
                <button
                  className="rl-button rl-button-secondary"
                  onClick={context.reload}
                >
                  <RefreshCw size={15} />
                  Refresh
                </button>
              </div>
              {configurationError && (
                <Notice error>
                  Service configuration is temporarily unavailable. New wallet
                  submissions are paused; already submitted transactions may
                  still confirm. {configurationError}
                </Notice>
              )}
              {(page === "overview" || page === "earn") && (
                <Lending {...context} transact={setTransaction} />
              )}
              {(page === "overview" || page === "borrow") && (
                <Facilities {...context} transact={setTransaction} />
              )}
              {page === "providers" && (
                <Providers
                  {...context}
                  reconnect={() => {
                    auth.disconnect();
                    void auth.connect();
                  }}
                />
              )}
              {page === "activity" && <Activity {...context} />}
              {page === "operations" &&
                (auth.session.roles.some((role) =>
                  staffRoles.includes(role),
                ) ? (
                  <Operations {...context} />
                ) : (
                  <Notice error>
                    Operations access requires an assigned operator, servicer,
                    or guardian role.
                  </Notice>
                ))}
              {transaction && (
                <TransactionDialog
                  key={`${transaction.action}:${transaction.reference}`}
                  {...context}
                  transaction={transaction}
                  close={() => setTransaction(null)}
                />
              )}
            </div>
          )
        )}
        <div className="gpu-disclosure">
          <ShieldCheck size={16} />
          <p>
            Official source proof, GPU revenue provenance, unpaid receivables,
            payment control, and destination cash are checked separately. Only
            received cash allocated to a facility reduces its debt. Native
            status: {config.nativeStatus || "Not established"}.
          </p>
        </div>
      </main>
      <footer className="gpu-footer">
        <span>
          Rackline · {config.deploymentId} · build {__APP_COMMIT__}
        </span>
        <span>API 1.0 · Wallet sessions stay in memory</span>
      </footer>
    </div>
  );
}

function Lending(
  context: Context & { transact: (value: Transaction) => void },
) {
  const read = useGpuRead<LpData>(
    "/v1/lp",
    context.config,
    context.session,
    context.refresh,
  );
  const data = read.response?.data;
  if (!context.config.configured)
    return (
      <Panel title="Lending vault">
        <Notice>
          Contracts are not configured for this environment. Borrower onboarding
          and provider review remain available.
        </Notice>
      </Panel>
    );
  const availableShares =
    data?.availableShares ??
    (data
      ? (
          BigInt(data.shares) -
          data.withdrawals
            .filter((item) => String(item.epoch) === String(data.currentEpoch))
            .reduce((sum, item) => sum + BigInt(item.sharesRemaining), 0n)
        ).toString()
      : "0");
  const amount = (raw: string | null | undefined) =>
    `${exactAmount(raw, context.config.asset.decimals)} ${context.config.asset.symbol || "tokens"}`;
  return (
    <>
      <ReadState {...read} />
      {data && (
        <>
          <p className="gpu-subtle">
            Finalized balance view: block{" "}
            {read.response?.meta.canonicalBlock.number}. Confirmed transactions
            appear after indexer finality; this view refreshes automatically
            every 15 seconds.
          </p>
          {read.response?.meta.freshness !== "FRESH" && (
            <Notice error>
              The ledger is stale. Refresh before reviewing a transaction;
              contract checks still apply.
            </Notice>
          )}
          {data.epochRolloverRequired && (
            <Notice error>
              The current epoch has suffered a total loss. Deposits and new
              withdrawal requests wait for recapitalization. Existing funded
              claims and prior epoch recovery rights remain separate.
            </Notice>
          )}
          {context.config.executionProfile === "NATIVE_TESTNET" &&
            context.config.asset.testOnly && (
              <Notice>
                Use test tokens with no monetary value to try the connected
                vault. The faucet provides 10,000 tUSD once per day; your wallet
                needs test CTC for gas.
                <button
                  className="rl-button rl-button-secondary"
                  onClick={() =>
                    context.transact({
                      action: "faucet",
                      title: "Claim test-only tUSD",
                    })
                  }
                >
                  Get test tokens
                </button>
              </Notice>
            )}
          <section
            className="rl-metrics"
            aria-label="Canonical vault accounting"
          >
            <Metric
              label="Vault net assets"
              value={amount(data.nav)}
              detail="Cash plus loan assets, after impairment"
            />
            <Metric
              label="Available liquidity"
              value={amount(data.availableCash)}
              detail="Excludes borrower reserves and reserved claims"
            />
            <Metric
              label="Your vault position"
              value={amount(data.shareAssets)}
              detail={`Epoch ${data.currentEpoch} · subject to gains and losses`}
            />
            <Metric
              label="Your wallet"
              value={amount(data.walletBalance)}
              detail="Configured loan asset on this chain"
            />
          </section>
          <div className="gpu-grid">
            <Panel title="Supply & withdrawal">
              <p>
                Deposit with a 0.5% slippage limit. Withdrawal requests lock
                shares; unfilled shares remain exposed to NAV changes. Claim
                only after a request is funded.
              </p>
              <div className="gpu-actions">
                <button
                  className="rl-button rl-button-primary"
                  disabled={
                    !context.config.configured ||
                    data.depositsPaused ||
                    data.epochRolloverRequired
                  }
                  onClick={() =>
                    context.transact({
                      action: "deposit",
                      title: "Supply to the vault",
                      maximum: data.walletBalance,
                      shareDecimals: data.shareDecimals ?? 18,
                    })
                  }
                >
                  Supply <ArrowUpRight size={15} />
                </button>
                <button
                  className="rl-button rl-button-secondary"
                  disabled={BigInt(availableShares) <= 0n}
                  onClick={() =>
                    context.transact({
                      action: "withdraw",
                      title: "Withdraw shares",
                      maximum: availableShares,
                      shares: true,
                      shareDecimals: data.shareDecimals ?? 18,
                    })
                  }
                >
                  Withdraw
                </button>
                <button
                  className="rl-button rl-button-secondary"
                  disabled={
                    BigInt(availableShares) <= 0n || data.epochRolloverRequired
                  }
                  onClick={() =>
                    context.transact({
                      action: "requestWithdrawal",
                      title: "Request a queued withdrawal",
                      maximum: availableShares,
                      shares: true,
                      shareDecimals: data.shareDecimals ?? 18,
                    })
                  }
                >
                  Join withdrawal queue
                </button>
              </div>
              <dl className="gpu-facts">
                <div>
                  <dt>Available vault shares</dt>
                  <dd>
                    {exactAmount(availableShares, data.shareDecimals ?? 18)}
                  </dd>
                </div>
                <div>
                  <dt>Borrower-owned funds</dt>
                  <dd>{amount(data.borrowerOwned)}</dd>
                </div>
                <div>
                  <dt>Recognized impairment</dt>
                  <dd>{amount(data.impairment)}</dd>
                </div>
                <div>
                  <dt>Realized LP yield</dt>
                  <dd>
                    {data.realizedYield ??
                      "No validated period return available"}
                  </dd>
                </div>
              </dl>
            </Panel>
            <Panel title="Withdrawal queue">
              {data.withdrawals.length === 0 ? (
                <Empty>No withdrawal requests for this wallet.</Empty>
              ) : (
                data.withdrawals.map((item) => (
                  <div className="gpu-row" key={item.requestId}>
                    <div>
                      <strong>
                        Request #{item.requestId} · epoch {item.epoch}
                      </strong>
                      <p>
                        {item.cancelled
                          ? "Cancelled"
                          : `${exactAmount(item.sharesRemaining, data.shareDecimals ?? 18)} unfilled shares`}{" "}
                        · claimable{" "}
                        {amount(
                          (
                            BigInt(item.assetsReserved) -
                            BigInt(item.assetsClaimed)
                          ).toString(),
                        )}
                      </p>
                    </div>
                    <div className="gpu-actions">
                      <button
                        className="rl-button rl-button-secondary"
                        disabled={
                          item.cancelled || BigInt(item.sharesRemaining) === 0n
                        }
                        onClick={() =>
                          context.transact({
                            action: "cancelWithdrawal",
                            title: `Cancel request #${item.requestId}`,
                            reference: item.requestId,
                          })
                        }
                      >
                        Cancel
                      </button>
                      <button
                        className="rl-button rl-button-primary"
                        disabled={
                          BigInt(item.assetsReserved) <=
                          BigInt(item.assetsClaimed)
                        }
                        onClick={() =>
                          context.transact({
                            action: "claimWithdrawal",
                            title: `Claim request #${item.requestId}`,
                            reference: item.requestId,
                          })
                        }
                      >
                        Claim
                      </button>
                    </div>
                  </div>
                ))
              )}
              <button
                className="rl-text-button"
                onClick={() =>
                  context.transact({
                    action: "processWithdrawals",
                    title: "Process the next withdrawal requests",
                  })
                }
              >
                Allocate available liquidity to queued requests
              </button>
              {data.recoveries?.map((item) => (
                <div className="gpu-row" key={item.epoch}>
                  <span>
                    Prior epoch {item.epoch}: {amount(item.claimable)}
                  </span>
                  <button
                    className="rl-button rl-button-secondary"
                    disabled={BigInt(item.claimable) === 0n}
                    onClick={() =>
                      context.transact({
                        action: "claimEpochRecovery",
                        title: `Claim recovery for epoch ${item.epoch}`,
                        reference: String(item.epoch),
                      })
                    }
                  >
                    Claim recovery
                  </button>
                </div>
              ))}
            </Panel>
          </div>
        </>
      )}
    </>
  );
}

function Facilities(
  context: Context & { transact: (value: Transaction) => void },
) {
  const [cursor, setCursor] = useState("");
  const read = useGpuRead<FacilityDTO[]>(
    context.session.borrowerId ||
      context.session.roles.some((role) =>
        [
          "operator",
          "underwriter",
          "servicer",
          "treasury",
          "guardian",
          "keeper",
        ].includes(role),
      )
      ? `/v1/facilities?limit=20${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`
      : null,
    context.config,
    context.session,
    context.refresh,
  );
  if (
    !context.session.borrowerId &&
    !context.session.roles.some((role) =>
      [
        "operator",
        "underwriter",
        "servicer",
        "treasury",
        "guardian",
        "keeper",
      ].includes(role),
    )
  )
    return (
      <Panel title="Your credit facilities">
        <Empty>
          Register your borrower profile in Providers to start an account and
          rights review.
        </Empty>
        <a className="rl-text-button" href="#providers">
          Set up your borrower profile <ArrowUpRight size={15} />
        </a>
      </Panel>
    );
  return (
    <>
      <ReadState {...read} />
      {read.response?.data.length === 0 && (
        <Panel title="Your credit facilities">
          <Empty>
            No facilities have been approved for your account. Provider
            connection and review do not create a credit limit.
          </Empty>
        </Panel>
      )}
      {read.response?.data.map((facility) => (
        <Facility key={facility.facilityId} {...context} facility={facility} />
      ))}
      {read.response?.pagination?.nextCursor && (
        <button
          className="rl-button rl-button-secondary"
          onClick={() => setCursor(read.response!.pagination!.nextCursor!)}
        >
          Next facilities
        </button>
      )}
      {cursor && (
        <button className="rl-text-button" onClick={() => setCursor("")}>
          First page
        </button>
      )}
    </>
  );
}

function Facility(
  context: Context & {
    facility: FacilityDTO;
    transact: (value: Transaction) => void;
  },
) {
  const { facility } = context;
  const read = useGpuRead<TransactionContext>(
    `/v1/facilities/${encodeURIComponent(facility.facilityId)}/transaction-context`,
    context.config,
    context.session,
    context.refresh,
  );
  const tx = read.response?.data;
  const amount = (raw: string | null | undefined) =>
    `${exactAmount(raw, facility.loanAsset.decimals)} ${context.config.asset?.symbol || "tokens"}`;
  const canBorrow =
    tx &&
    facility.state === "ACTIVE" &&
    facility.executionProfile === context.config.executionProfile &&
    tx.wallet.toLowerCase() === context.session.wallet.toLowerCase() &&
    tx.availableDraw != null &&
    BigInt(tx.availableDraw) > 0n &&
    !tx.drawBlockedReason &&
    read.response?.meta.freshness === "FRESH";
  return (
    <Panel title={`Facility ${facility.facilityId}`}>
      <Badge>{pretty(facility.state)}</Badge>
      <dl className="gpu-facts">
        <div>
          <dt>Recorded principal</dt>
          <dd>{amount(facility.recordedPrincipal.amount)}</dd>
        </div>
        <div>
          <dt>Recorded unpaid interest</dt>
          <dd>{amount(facility.recordedUnpaidInterest.amount)}</dd>
        </div>
        <div>
          <dt>Recorded fees</dt>
          <dd>{amount(facility.recordedFees.amount)}</dd>
        </div>
        <div>
          <dt>Current chain debt</dt>
          <dd>{amount(tx?.debt)}</dd>
        </div>
        <div>
          <dt>Available to borrow</dt>
          <dd>{amount(tx?.availableDraw)}</dd>
        </div>
        <div>
          <dt>Draw reservations</dt>
          <dd>{amount(facility.recordedReservedDraws.amount)}</dd>
        </div>
        <div>
          <dt>Borrower APR</dt>
          <dd>{exactAmount(facility.rateBps, 2)}%</dd>
        </div>
        <div>
          <dt>Maturity</dt>
          <dd>
            {facility.maturityAt
              ? new Date(facility.maturityAt).toLocaleDateString()
              : "Not set"}
          </dd>
        </div>
      </dl>
      {read.response && (
        <p className="gpu-subtle">
          Finalized debt view: block {read.response.meta.canonicalBlock.number}
          {" · "}
          {pretty(read.response.meta.freshness)}. New transactions appear after
          indexer finality; this view refreshes every 15 seconds.
        </p>
      )}
      {read.response && read.response.meta.freshness !== "FRESH" && (
        <Notice error>
          Stale debt snapshot: newer confirmed transactions may be missing.
          New borrowing is paused. Direct repayment uses execution-time debt.
        </Notice>
      )}
      <p>
        Recorded balances may lag the chain. Current debt and the transaction
        binding are refreshed before signing. Loan repayment follows fees →
        interest → principal; excess belongs to the borrower.
      </p>
      {(read.error || tx?.drawBlockedReason) && (
        <Notice>
          {read.error ||
            explainDrawBlock(tx?.drawBlockedReason, facility.state)}{" "}
          Direct repayment remains available when the facility binding is
          valid.
          {tx?.drawBlockedReason && (
            <code className="gpu-code">{tx.drawBlockedReason}</code>
          )}
        </Notice>
      )}
      {facility.credit && !performing.has(facility.state) && (
        <CreditStatus
          config={context.config}
          credit={facility.credit}
          debt={tx?.debt}
          amount={amount}
        />
      )}
      <div className="gpu-actions">
        <button
          className="rl-button rl-button-primary"
          disabled={!canBorrow}
          onClick={() =>
            context.transact({
              action: "borrow",
              title: `Borrow · ${facility.facilityId}`,
              reference: facility.facilityId,
              maximum: tx?.availableDraw ?? undefined,
            })
          }
        >
          Borrow <ArrowUpRight size={15} />
        </button>
        <button
          className="rl-button rl-button-secondary"
          disabled={!tx || BigInt(tx.debt) <= 0n}
          onClick={() =>
            context.transact({
              action: "repay",
              title: `Repay · ${facility.facilityId}`,
              reference: facility.facilityId,
              maximum: tx?.debt,
            })
          }
        >
          Repay directly
        </button>
        <a className="rl-text-button" href="#activity">
          Evidence & repayment history
        </a>
      </div>
      <p className="gpu-subtle">
        {facility.state === "RECOVERY" || facility.state === "CLOSED_WITH_LOSS"
          ? "Repayments on a facility in recovery or written off reduce the legal debt and are recovered for lenders."
          : "Zero debt and released payment control are separate states."}{" "}
        Current control agreement:{" "}
        {facility.controlAgreementId || "Not established"}.
      </p>
    </Panel>
  );
}

const performing = new Set(["DRAFT", "UNDER_REVIEW", "CONTROL_PENDING", "ACTIVE"]);
const drawBlockText: Record<string, string> = {
  NO_ELIGIBLE_DRAW:
    "No eligible receivables in the borrowing base right now: the source checkpoint or the control observation is older than 15 minutes, or every assigned receivable has been paid.",
  INSUFFICIENT_VAULT_CASH: "The vault has no free cash to lend right now.",
  EVIDENCE_STALE:
    "Credit evidence is stale; new borrowing pauses until the indexer catches up.",
  DRAW_REQUIREMENTS_NOT_MET:
    "The chain refused the draw evaluation: a control or evidence requirement is not met.",
};
const notActiveText: Record<string, string> = {
  DRAW_FROZEN: "Draws are frozen by the guardian.",
  DELINQUENT: "An installment is overdue; draws resume after the cure.",
  DEFAULTED: "The facility is in default.",
  RECOVERY: "The facility is in recovery.",
  REPAID: "This facility is repaid; a new facility is opened for new borrowing.",
  RELEASED: "This facility is released.",
  CLOSED_WITH_LOSS: "This facility was written off.",
};
function explainDrawBlock(code: string | null | undefined, state: string) {
  if (!code) return "";
  if (code === "FACILITY_NOT_ACTIVE")
    return `${notActiveText[state] ?? "The facility is not active."} New borrowing is unavailable.`;
  return drawBlockText[code] ?? `New borrowing is unavailable (${code}).`;
}
const when = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString() : "—";
const label = (trigger: string, text: string | null) =>
  text ? text.replace(/_/g, " ") : `reference ${addressLabel(trigger)}`;

/** The explanation behind a non-performing state, from finalized manager / recovery / vault events. */
function CreditStatus({
  config,
  credit,
  debt,
  amount,
}: {
  config: Config;
  credit: CreditStatusDTO;
  debt: string | null | undefined;
  amount: (raw: string | null | undefined) => string;
}) {
  const s = credit.schedule;
  const grace = s ? `${Math.round(s.graceSeconds / 60)} min` : null;
  const summary: ReactNode = (() => {
    switch (credit.state) {
      case "DRAW_FROZEN":
        return `Draws were frozen by the guardian on ${when(credit.stateChangedAt)} (${label(credit.stateTrigger ?? "", credit.stateTriggerText)}). Repayment stays open; the underwriter reactivates the facility.`;
      case "DELINQUENT":
        return s
          ? `The installment of ${amount(s.dueAmount.amount)} due ${when(s.dueAt)} was not paid (grace ${grace}). Draws are refused until the installment is paid and the facility is cured.`
          : `Marked delinquent on ${when(credit.stateChangedAt)}.`;
      case "DEFAULTED":
        return `Default approved by the underwriter on ${when(credit.defaultApprovedAt)} (${label(credit.defaultReason ?? "", credit.defaultReasonText)}) and declared on ${when(credit.stateChangedAt)}. Interest accrual is ${credit.accrualFrozen ? "frozen" : "not frozen"}; the legal debt stays payable.`;
      case "RECOVERY":
        return `Recovery opened on ${when(credit.stateChangedAt)}. Reserve pledged ${amount(credit.reservePledged.amount)}, applied to the debt ${amount(credit.reserveApplied.amount)}. Repayments keep reducing the legal debt.`;
      case "REPAID":
        return `Repaid in full on ${when(credit.stateChangedAt)}. A repaid facility does not draw again; new borrowing needs a new facility.`;
      case "RELEASED":
        return `Payment control was released on ${when(credit.stateChangedAt)}.`;
      case "CLOSED_WITH_LOSS":
        return `Written off on ${when(credit.writtenOffAt ?? credit.stateChangedAt)}: the vault recognised a loss of ${amount(credit.lossAmount?.amount)} (${label(credit.lossId ?? credit.stateTrigger ?? "", null)}). Write-off is not forgiveness — the legal debt of ${amount(debt)} remains payable and any repayment is recovered for lenders.`;
      default:
        return null;
    }
  })();
  const facts: [string, string][] = [];
  if (s) {
    facts.push(["Installment due", when(s.dueAt)]);
    facts.push(["Installment", amount(s.dueAmount.amount)]);
    facts.push(["Grace period", grace ?? "—"]);
  }
  if (s?.disputed) facts.push(["Servicer dispute", "Open — default approval is blocked"]);
  if (credit.defaultApprovedAt) facts.push(["Default approved", when(credit.defaultApprovedAt)]);
  if (BigInt(credit.reserveApplied.amount) > 0n || BigInt(credit.reservePledged.amount) > 0n) {
    facts.push(["Recovery reserve", `${amount(credit.reservePledged.amount)} pledged · ${amount(credit.reserveApplied.amount)} applied`]);
  }
  if (BigInt(credit.impairment.amount) > 0n) facts.push(["Impairment recognised", amount(credit.impairment.amount)]);
  if (credit.lossAmount) facts.push(["Loss written off", amount(credit.lossAmount.amount)]);
  if (credit.accrualFrozen) facts.push(["Interest accrual", "Frozen"]);
  return (
    <section className="gpu-credit" aria-label="Credit status">
      <h3>Why this facility is {pretty(credit.state).toLowerCase()}</h3>
      {summary && <p>{summary}</p>}
      {facts.length > 0 && (
        <dl className="gpu-facts">
          {facts.map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
      )}
      <ol className="gpu-timeline">
        {[...credit.transitions].reverse().map((t) => (
          <li key={`${t.txHash}-${t.toState}`}>
            <span>
              <strong>{pretty(t.toState)}</strong> from {pretty(t.fromState).toLowerCase()} ·{" "}
              {label(t.trigger, t.triggerText)}
            </span>
            <span className="gpu-subtle">
              {when(t.at)} · <ChainLink config={config} hash={t.txHash} />
            </span>
          </li>
        ))}
      </ol>
      <p className="gpu-subtle">
        Replayed from finalized on-chain events (state changes, recovery schedule, reserve, impairment, write-off).
      </p>
    </section>
  );
}

function Providers(context: Context & { reconnect: () => void }) {
  const providers = useGpuRead<ProviderDTO[]>(
    "/v1/providers?limit=100",
    context.config,
    context.session,
    context.refresh,
  );
  const linked = Boolean(context.session.borrowerId);
  const connections = useGpuRead<ConnectionDTO[]>(
    linked ? "/v1/connections?limit=100" : null,
    context.config,
    context.session,
    context.refresh,
  );
  const controls = useGpuRead<ControlDTO[]>(
    linked ? "/v1/control-agreements?limit=100" : null,
    context.config,
    context.session,
    context.refresh,
  );
  const requests = useGpuRead<
    { applicationId: string; providerId: string; state: string }[]
  >(
    linked ? "/v1/connection-requests?limit=100" : null,
    context.config,
    context.session,
    context.refresh,
  );
  const [jurisdiction, setJurisdiction] = useState("");
  const [registration, setRegistration] = useState("");
  const [providerId, setProviderId] = useState("");
  const [account, setAccount] = useState("");
  const [evidence, setEvidence] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [failed, setFailed] = useState(false);
  const submission = useRef<{ payload: string; key: string } | null>(null);
  async function submit() {
    if (busy) return;
    setBusy(true);
    setNotice("");
    setFailed(false);
    const body = linked
      ? {
          providerId,
          externalAccountId: account.trim(),
          evidenceReference: evidence.trim(),
          reason: reason.trim(),
        }
      : {
          jurisdiction: jurisdiction.trim(),
          registrationReference: registration.trim(),
        };
    const payload = JSON.stringify(body);
    if (submission.current?.payload !== payload)
      submission.current = { payload, key: crypto.randomUUID() };
    try {
      await request(linked ? "/v1/connections" : "/v1/onboarding", {
        token: context.session.token,
        body: { ...body, idempotencyKey: submission.current.key },
      });
      setNotice(
        linked
          ? "Connection request saved for review. No provider access, payment control, or credit has been approved."
          : "Borrower profile saved with review pending. Reconnect your wallet to load its borrower scope.",
      );
      submission.current = null;
      context.reload();
    } catch (err) {
      setFailed(true);
      setNotice(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <ReadState {...providers} />
      <div className="gpu-grid">
        <Panel
          title={
            linked
              ? "Request a provider connection"
              : "Register your borrower profile"
          }
        >
          <p>
            Provide secure document references. Keep API keys, account
            passwords, and customer workload data out of these fields.
            Submissions are retained for authorized review.
          </p>
          <form
            className="gpu-form"
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            {!linked ? (
              <>
                <label>
                  Jurisdiction
                  <input
                    required
                    minLength={2}
                    maxLength={64}
                    value={jurisdiction}
                    onChange={(event) => setJurisdiction(event.target.value)}
                    placeholder="Country of legal registration"
                  />
                </label>
                <label>
                  Company registration reference
                  <input
                    required
                    minLength={5}
                    maxLength={240}
                    pattern="(doc|vault|secret)://.+"
                    value={registration}
                    onChange={(event) => setRegistration(event.target.value)}
                    placeholder="doc://company/registration"
                  />
                  <span className="gpu-subtle">
                    Use a doc://, vault://, or secret:// reference provided by
                    your review team.
                  </span>
                </label>
              </>
            ) : (
              <>
                <label>
                  Provider
                  <select
                    required
                    value={providerId}
                    onChange={(event) => setProviderId(event.target.value)}
                  >
                    <option value="">Choose a provider</option>
                    {providers.response?.data.map((provider) => (
                      <option
                        key={provider.providerId}
                        value={provider.providerId}
                      >
                        {provider.displayName} ·{" "}
                        {pretty(provider.environmentStatus)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Provider account reference
                  <input
                    required
                    maxLength={128}
                    value={account}
                    onChange={(event) => setAccount(event.target.value)}
                  />
                </label>
                <label>
                  Ownership / authority evidence reference
                  <input
                    required
                    minLength={5}
                    maxLength={240}
                    pattern={"(doc|vault|secret)://[^\\s]+"}
                    value={evidence}
                    onChange={(event) => setEvidence(event.target.value)}
                    placeholder="doc://ownership/provider-account"
                  />
                  <span className="gpu-subtle">
                    Reference only: do not enter an API key or access token.
                  </span>
                </label>
                <label>
                  Reason for request
                  <textarea
                    required
                    minLength={5}
                    maxLength={400}
                    rows={3}
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                  />
                </label>
              </>
            )}
            <button className="rl-button rl-button-primary" disabled={busy}>
              {busy
                ? "Saving request…"
                : linked
                  ? "Submit for review"
                  : "Register profile"}{" "}
              <ArrowUpRight size={15} />
            </button>
          </form>
          {notice && <Notice error={failed}>{notice}</Notice>}
          {!linked && notice && !failed && (
            <button className="rl-text-button" onClick={context.reconnect}>
              Reconnect wallet to continue
            </button>
          )}
        </Panel>
        <Panel title="Provider capabilities">
          {providers.response?.data.length === 0 && (
            <Empty>No source providers are admitted in this environment.</Empty>
          )}
          {providers.response?.data.map((provider) => (
            <div className="gpu-row gpu-provider" key={provider.providerId}>
              <div>
                <strong>{provider.displayName}</strong>
                <p>
                  {pretty(provider.environmentStatus)} ·{" "}
                  {provider.testOnly ? "Test-only source" : "Partner source"}
                </p>
                <p>Required verification: {provider.requiredVerification}</p>
                <p>
                  Source chain {provider.sourceChainId} · Attestcoin chain key{" "}
                  {provider.sourceChainKey}
                </p>
                <div className="gpu-tags">
                  {Object.entries(provider.capabilities).map(
                    ([name, value]) => (
                      <Badge key={name}>
                        {pretty(name)}: {pretty(value)}
                      </Badge>
                    ),
                  )}
                </div>
              </div>
            </div>
          ))}
          <p className="gpu-subtle">
            Unsupported or unconfirmed source capabilities cannot authorize
            borrowing. Account access does not establish E2 payment control.
          </p>
        </Panel>
      </div>
      {linked && (
        <>
          <Panel title="Account & rights review">
            <ReadState {...connections} />
            {connections.response?.data.length === 0 && (
              <Empty>No reviewed provider accounts yet.</Empty>
            )}
            {connections.response?.data.map((item) => (
              <div className="gpu-row" key={item.providerAccountId}>
                <strong>{item.externalAccountId}</strong>
                <span>Account review: {pretty(item.accountReviewState)}</span>
                <span>
                  Credentials:{" "}
                  {item.credentialConfigured ? "Configured" : "Not configured"}
                </span>
              </div>
            ))}
            <ReadState {...requests} />
            {requests.response?.data.map((item) => (
              <div className="gpu-row" key={item.applicationId}>
                <strong>{item.providerId}</strong>
                <Badge>{pretty(item.state)}</Badge>
                <span>Connection request retained for review</span>
              </div>
            ))}
          </Panel>
          <Panel title="Payment control">
            <ReadState {...controls} />
            {controls.response?.data.length === 0 && (
              <Empty>No payment control agreement has been recorded.</Empty>
            )}
            {controls.response?.data.map((control) => (
              <div
                className="gpu-row gpu-provider"
                key={control.controlAgreementId}
              >
                <div>
                  <strong>
                    {control.controlAgreementId} · {control.controlGrade}
                  </strong>
                  <p>
                    Observation: {pretty(control.observationFreshness)} ·
                    version {control.version}
                  </p>
                  <p>
                    Change authority: {control.changeAuthority} · expires{" "}
                    {control.effectiveTo
                      ? new Date(control.effectiveTo).toLocaleString()
                      : "not set"}
                  </p>
                  <p>
                    Receiver: {control.receiverAddress || "Not established"}
                  </p>
                  <p>
                    An observation is not an enforcement approval. E0 / E1,
                    expired control, or missing native evidence blocks new
                    credit.
                  </p>
                </div>
              </div>
            ))}
          </Panel>
          <ProofRequests
            {...context}
            accounts={connections.response?.data ?? []}
          />
        </>
      )}
    </>
  );
}

interface ProofRequest {
  proofRequestId: string;
  providerAccountId: string;
  txHash: string;
  status: string;
  nativeStatus?: string | null;
  artifactHash?: string | null;
  artifactVersion?: string | null;
}
function ProofRequests(context: Context & { accounts: ConnectionDTO[] }) {
  const [account, setAccount] = useState("");
  const [hash, setHash] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const key = useRef<{ payload: string; id: string } | null>(null);
  const read = useGpuRead<ProofRequest[]>(
    "/v1/proofs?limit=100",
    context.config,
    context.session,
    context.refresh,
  );
  async function submit() {
    if (busy) return;
    const body = { providerAccountId: account, txHash: hash.toLowerCase() };
    const payload = JSON.stringify(body);
    if (key.current?.payload !== payload)
      key.current = { payload, id: crypto.randomUUID() };
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await request<{ data: { proofRequestId: string } }>(
        "/v1/proofs",
        {
          token: context.session.token,
          body: { ...body, idempotencyKey: key.current.id },
        },
      );
      setNotice(
        `Proof request ${result.data.proofRequestId} received. This receipt is not native acceptance or business eligibility.`,
      );
      key.current = null;
      context.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Panel title="Official source proof requests">
      <p>
        Submit a source-chain transaction for an account linked to this
        borrower. The official proof worker checks the supported source; an API
        receipt never changes debt or establishes payment control.
      </p>
      {context.accounts.length === 0 ? (
        <Empty>
          A reviewed provider account is required before requesting its source
          proof.
        </Empty>
      ) : (
        <form
          className="gpu-form"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <label>
            Reviewed provider account
            <select
              required
              value={account}
              onChange={(event) => setAccount(event.target.value)}
            >
              <option value="">Choose a linked account</option>
              {context.accounts.map((item) => (
                <option
                  key={item.providerAccountId}
                  value={item.providerAccountId}
                >
                  {item.externalAccountId} · {item.providerId}
                </option>
              ))}
            </select>
          </label>
          <label>
            Source transaction hash
            <input
              required
              pattern="0x[0-9a-fA-F]{64}"
              maxLength={66}
              value={hash}
              onChange={(event) => setHash(event.target.value)}
              placeholder="0x…"
            />
          </label>
          <button className="rl-button rl-button-primary" disabled={busy}>
            {busy ? "Requesting proof…" : "Request official proof"}
          </button>
        </form>
      )}
      {error && <Notice error>{error}</Notice>}
      {notice && <Notice>{notice}</Notice>}
      <ReadState {...read} />
      {read.response?.data.length === 0 && (
        <Empty>No proof requests recorded for this wallet.</Empty>
      )}
      {read.response?.data.map((item) => (
        <div className="gpu-evidence" key={item.proofRequestId}>
          <div className="gpu-row">
            <strong>{item.proofRequestId}</strong>
            <Badge>{pretty(item.status)}</Badge>
          </div>
          <dl className="gpu-facts">
            <div>
              <dt>Source transaction</dt>
              <dd>{item.txHash}</dd>
            </div>
            <div>
              <dt>Native acceptance</dt>
              <dd>{pretty(item.nativeStatus)}</dd>
            </div>
            <div>
              <dt>Artifact hash / version</dt>
              <dd>
                {item.artifactHash || "Not ready"}
                {item.artifactVersion ? ` / ${item.artifactVersion}` : ""}
              </dd>
            </div>
          </dl>
        </div>
      ))}
    </Panel>
  );
}

function Activity(context: Context) {
  const scoped =
    Boolean(context.session.borrowerId) ||
    context.session.roles.some((role) =>
      ["operator", "underwriter"].includes(role),
    );
  const receivables = useGpuRead<ReceivableDTO[]>(
    scoped ? "/v1/receivables?limit=100" : null,
    context.config,
    context.session,
    context.refresh,
  );
  const settlements = useGpuRead<SettlementDTO[]>(
    scoped ? "/v1/settlements?limit=100" : null,
    context.config,
    context.session,
    context.refresh,
  );
  const repayments = useGpuRead<RepaymentDTO[]>(
    scoped ? "/v1/repayments?limit=100" : null,
    context.config,
    context.session,
    context.refresh,
  );
  if (!scoped)
    return (
      <Empty>
        No borrower activity is associated with this wallet. Your LP balances
        and withdrawal requests are available in Earn.
      </Empty>
    );
  return (
    <>
      <Panel title="Receivables & official evidence">
        <ReadState {...receivables} />
        {receivables.response?.data.length === 0 && (
          <Empty>No receivables have been recorded.</Empty>
        )}
        {receivables.response?.data.map((item) => (
          <div className="gpu-evidence" key={item.receivableId}>
            <div className="gpu-row">
              <strong>{item.receivableId}</strong>
              <Badge>
                {pretty(item.state)} · revision {item.revision}
              </Badge>
              <Badge>
                {item.recordOrigin === "FINALIZED_CHAIN_EVENTS"
                  ? "Finalized chain events"
                  : "Reviewed ledger import"}
              </Badge>
              <span>
                Unpaid{" "}
                {exactAmount(
                  item.unpaidAmount.amount,
                  item.unpaidAmount.asset.decimals,
                )}
              </span>
            </div>
            <dl className="gpu-facts">
              <div>
                <dt>Proof requested</dt>
                <dd>{pretty(item.evidence.proofRequestStatus)}</dd>
              </div>
              <div>
                <dt>Artifact ready</dt>
                <dd>
                  {item.evidence.proofReadyAt
                    ? new Date(item.evidence.proofReadyAt).toLocaleString()
                    : "Not recorded"}
                </dd>
              </div>
              <div>
                <dt>Native acceptance</dt>
                <dd>
                  {item.evidence.verificationMethod === "LOCAL_MOCK" ? (
                    "Local mock fixture · not native acceptance"
                  ) : (
                    <>
                      {pretty(item.evidence.nativeStatus)} ·{" "}
                      {item.evidence.nativeCanonical &&
                      item.evidence.verificationMethod === "ATTESTCOIN_NATIVE"
                        ? "Canonical consumption"
                        : "No canonical native consumption"}
                    </>
                  )}
                </dd>
              </div>
              <div>
                <dt>Verification method</dt>
                <dd>{pretty(item.evidence.verificationMethod)}</dd>
              </div>
              <div>
                <dt>Revenue provenance</dt>
                <dd>{pretty(item.evidence.earningsProvenance)}</dd>
              </div>
              <div>
                <dt>Business eligibility</dt>
                <dd>{pretty(item.evidence.businessEligibilityReason)}</dd>
              </div>
              <div>
                <dt>Source event reference</dt>
                <dd>{item.evidence.sourceEventId || "Unavailable"}</dd>
              </div>
            </dl>
            <p className="gpu-subtle">
              Proof acceptance does not update this facility's debt. Current
              unpaid eligibility requires its own authoritative assessment.
            </p>
          </div>
        ))}
      </Panel>
      <Panel title="Source settlement & destination cash">
        <ReadState {...settlements} />
        {settlements.response?.data.length === 0 && (
          <Empty>No settlements have been recorded.</Empty>
        )}
        {settlements.response?.data.map((item) => (
          <div className="gpu-evidence" key={item.settlementId}>
            <div className="gpu-row">
              <strong>{item.settlementId}</strong>
              <Badge>{pretty(item.state)}</Badge>
              <span>
                {item.destinationCashRecorded
                  ? "Destination receipt recorded"
                  : "Destination cash not received"}
              </span>
            </div>
            {item.destinationReceipts.map((cash) => (
              <div className="gpu-row" key={cash.cashReceiptId}>
                <span>
                  {exactAmount(cash.amount.amount, cash.amount.asset.decimals)}{" "}
                  · {pretty(cash.cashState)}
                </span>
                <ChainLink config={context.config} hash={cash.txHash} />
              </div>
            ))}
          </div>
        ))}
      </Panel>
      <Panel title="Facility repayment allocations">
        <ReadState {...repayments} />
        {repayments.response?.data.length === 0 && (
          <Empty>No cash has been allocated to repayment.</Empty>
        )}
        {repayments.response?.data.map((item) => (
          <div className="gpu-evidence" key={item.repaymentAllocationId}>
            <div className="gpu-row">
              <strong>{item.facilityId}</strong>
              <Badge>
                {item.repaymentApplied === true
                  ? "Applied · finalized event"
                  : "Application unconfirmed"}
              </Badge>
              {item.payerAddress && (
                <span className="gpu-subtle">payer {item.payerAddress}</span>
              )}
              <ChainLink config={context.config} hash={item.onchainTxHash} />
            </div>
            <dl className="gpu-facts">
              {[
                ["Received", item.received],
                ["Fees paid", item.feePaid],
                ["Interest paid", item.interestPaid],
                ["Principal paid", item.principalPaid],
                ["Borrower excess", item.excess],
                ["Recorded remaining debt", item.recordedNewDebt],
              ].map(([label, value]) => {
                const money = value as RepaymentDTO["received"];
                return (
                  <div key={String(label)}>
                    <dt>{String(label)}</dt>
                    <dd>{exactAmount(money.amount, money.asset.decimals)}</dd>
                  </div>
                );
              })}
            </dl>
          </div>
        ))}
      </Panel>
    </>
  );
}

type Operation = Omit<OperationDTO, "audit"> & {
  audit?: { action: string; reason: string; createdAt: string }[];
};
function Operations(context: Context) {
  const read = useGpuRead<Operation[]>(
    "/v1/operations?limit=100",
    context.config,
    context.session,
    context.refresh,
  );
  const [selected, setSelected] = useState("");
  const [reason, setReason] = useState("");
  const [action, setAction] = useState("acknowledge");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const key = useRef<{ payload: string; id: string } | null>(null);
  const item = read.response?.data.find((row) => row.exceptionId === selected);
  async function act() {
    if (!item || busy || item.version == null) return;
    const body = {
      action,
      reason: reason.trim(),
      expectedVersion: item.version,
    };
    const payload = JSON.stringify({ ...body, exceptionId: item.exceptionId });
    if (key.current?.payload !== payload)
      key.current = { payload, id: crypto.randomUUID() };
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await request(
        `/v1/operations/${encodeURIComponent(item.exceptionId)}/actions`,
        {
          token: context.session.token,
          body: { ...body, idempotencyKey: key.current.id },
        },
      );
      key.current = null;
      setReason("");
      setNotice(
        "Action recorded with your reason. Receipt or acknowledgment does not confirm financial effect.",
      );
      context.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="gpu-grid">
      <Panel title="Exception queue">
        <ReadState {...read} />
        {read.response?.meta.freshness === "STALE" && (
          <Notice error>
            Canonical ledger is stale. Review its watermark before acting.
          </Notice>
        )}
        {read.response?.data.length === 0 && (
          <Empty>No open operation cases.</Empty>
        )}
        {read.response?.data.map((row) => (
          <button
            className="gpu-case"
            aria-pressed={selected === row.exceptionId}
            key={row.exceptionId}
            onClick={() => {
              setSelected(row.exceptionId);
              setError("");
              setNotice("");
              setReason("");
            }}
          >
            <span>
              <strong>{pretty(row.kind)}</strong>
              <small>
                {row.exceptionId} · {row.entityType} / {row.entityId}
              </small>
            </span>
            <Badge>
              {pretty(row.state)} · {pretty(row.severity)}
            </Badge>
          </button>
        ))}
      </Panel>
      <Panel title="Case detail & audited action">
        {!item ? (
          <Empty>Select a case to review its context.</Empty>
        ) : (
          <>
            <dl className="gpu-facts">
              <div>
                <dt>Reference</dt>
                <dd>
                  {item.entityType} / {item.entityId}
                </dd>
              </div>
              <div>
                <dt>Version</dt>
                <dd>{item.version ?? "Unavailable"}</dd>
              </div>
              <div>
                <dt>Owner</dt>
                <dd>{item.owner || "Unassigned"}</dd>
              </div>
              <div>
                <dt>Response deadline</dt>
                <dd>{item.dueAt || "Not assigned"}</dd>
              </div>
              <div>
                <dt>Runbook</dt>
                <dd>{item.runbook || "Pending operational assignment"}</dd>
              </div>
              <div>
                <dt>Effective resolution</dt>
                <dd>{item.resolvedAt || "Not confirmed"}</dd>
              </div>
            </dl>
            <form
              className="gpu-form"
              onSubmit={(event) => {
                event.preventDefault();
                void act();
              }}
            >
              <label>
                Action
                <select
                  value={action}
                  onChange={(event) => setAction(event.target.value)}
                >
                  <option value="acknowledge">Acknowledge case</option>
                  <option value="assign">Assign to me</option>
                  <option value="retry">Request retry</option>
                  <option
                    value="resolve"
                    disabled={item.severity === "BLOCKING"}
                  >
                    Resolve a remediated non-blocking case
                  </option>
                </select>
              </label>
              <label>
                Reason for audit trail
                <textarea
                  required
                  minLength={5}
                  maxLength={400}
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  rows={3}
                />
              </label>
              <button
                className="rl-button rl-button-primary"
                disabled={
                  busy || item.version == null || reason.trim().length < 5
                }
              >
                {busy ? "Recording…" : "Submit action"}
              </button>
            </form>
            {error && <Notice error>{error}</Notice>}
            {notice && <Notice>{notice}</Notice>}
            {item.audit?.map((entry, index) => (
              <div className="gpu-row" key={`${entry.createdAt}:${index}`}>
                <strong>{pretty(entry.action)}</strong>
                <span>{entry.reason}</span>
                <time>{entry.createdAt}</time>
              </div>
            ))}
            <p className="gpu-subtle">
              Retries retain verification policy. An operator cannot mark proof
              verified, bypass native acceptance, or change repayment through
              this screen.
            </p>
          </>
        )}
      </Panel>
    </div>
  );
}

function TransactionDialog(
  context: Context & { transaction: Transaction; close: () => void },
) {
  const { transaction } = context;
  const needsAmount = [
    "deposit",
    "withdraw",
    "requestWithdrawal",
    "borrow",
    "repay",
  ].includes(transaction.action);
  const decimals = transaction.shares
    ? (transaction.shareDecimals ?? 18)
    : context.config.asset.decimals;
  const [input, setInput] = useState("");
  const [review, setReview] = useState(!needsAmount);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState<Progress | null>(null);
  const [quote, setQuote] = useState<Awaited<
    ReturnType<typeof quoteVault>
  > | null>(null);
  const inFlight = useRef(false);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  const unit = transaction.shares
    ? "vault shares"
    : context.config.asset.symbol || "tokens";
  async function confirm() {
    if (inFlight.current || context.configurationError) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      const amount = needsAmount ? parseAmount(input, decimals) : 0n;
      await executeTransaction(
        context.config,
        context.session,
        transaction.action,
        amount,
        transaction.reference,
        (state) => {
          if (active.current) setProgress(state);
        },
        quote,
      );
      if (active.current) context.reload();
    } catch (err) {
      if (active.current) setError(errorMessage(err));
    } finally {
      inFlight.current = false;
      if (active.current) setBusy(false);
    }
  }
  async function reviewAmount() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const amount = parseAmount(input, decimals);
      if (
        transaction.action !== "repay" &&
        transaction.maximum &&
        amount > BigInt(transaction.maximum)
      )
        throw new Error("Amount exceeds the current available balance.");
      if (
        ["deposit", "withdraw", "requestWithdrawal"].includes(
          transaction.action,
        )
      ) {
        const nextQuote = await quoteVault(
          context.config,
          context.session,
          transaction.action,
          amount,
        );
        if (!active.current) return;
        setQuote(nextQuote);
      }
      setReview(true);
    } catch (err) {
      if (active.current) setError(errorMessage(err));
    } finally {
      if (active.current) setBusy(false);
    }
  }
  return (
    <Dialog.Root
      open
      onOpenChange={(open) => {
        if (!open && !busy) context.close();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="rl-transaction-overlay" />
        <Dialog.Content
          className="rl-transaction"
          aria-describedby="gpu-tx-description"
        >
          <Dialog.Close
            className="rl-icon-button rl-transaction-close"
            aria-label="Close transaction"
            disabled={busy}
          >
            <X size={19} />
          </Dialog.Close>
          <div className="rl-transaction-symbol">
            <Wallet size={24} />
          </div>
          <p className="rl-eyebrow rl-transaction-eyebrow">
            {context.config.executionProfile}
          </p>
          <Dialog.Title className="rl-transaction-title">
            {transaction.title}
          </Dialog.Title>
          <Dialog.Description
            id="gpu-tx-description"
            className="rl-transaction-description"
          >
            {transaction.action === "repay"
              ? "Enter a maximum repayment cap, including any interest that may accrue before execution. The router transfers only the smaller of this cap and execution-time debt, then allocates fees, interest, and principal. Source proof is not required for direct repayment."
              : transaction.action === "processWithdrawals"
                ? "Process up to 20 requests in queue order using available vault cash. This does not prioritize your own request."
                : "This action submits a real wallet transaction on the configured chain. Review the amount and destination before signing."}
          </Dialog.Description>
          {context.configurationError && (
            <Notice error>
              New wallet submissions are paused until service configuration is
              available. An already submitted transaction may still confirm.
            </Notice>
          )}
          {progress?.stage === "confirmed" ? (
            <>
              <Notice>
                <Check size={16} />
                Transaction confirmed with two block confirmations.
              </Notice>
              <p className="gpu-subtle">
                Balances refresh automatically after the canonical indexer
                reaches finality. Two confirmations do not mean the displayed
                ledger has caught up yet.
              </p>
              <ChainLink config={context.config} hash={progress.hash} />
              <button
                className="rl-button rl-button-primary rl-transaction-submit"
                onClick={context.close}
              >
                Done
              </button>
            </>
          ) : (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (review) void confirm();
                else void reviewAmount();
              }}
            >
              {needsAmount && !review ? (
                <div className="rl-transaction-amount-block">
                  <label htmlFor="gpu-tx-amount">Amount in {unit}</label>
                  <div className="rl-transaction-input-row">
                    <input
                      id="gpu-tx-amount"
                      inputMode="decimal"
                      autoComplete="off"
                      value={input}
                      onChange={(event) => {
                        setInput(event.target.value);
                        setError("");
                      }}
                      placeholder="0"
                      maxLength={78}
                    />
                    {transaction.maximum && (
                      <button
                        type="button"
                        className="rl-transaction-max"
                        onClick={() =>
                          setInput(
                            exactAmount(transaction.maximum, decimals).replace(
                              /,/g,
                              "",
                            ),
                          )
                        }
                      >
                        MAX
                      </button>
                    )}
                  </div>
                  <p>
                    {transaction.action === "repay"
                      ? "Current debt (may accrue)"
                      : "Available"}
                    : {exactAmount(transaction.maximum, decimals)} {unit}
                  </p>
                </div>
              ) : (
                needsAmount && (
                  <div className="rl-transaction-review-amount">
                    <span>Review amount</span>
                    <strong>
                      {input} <small>{unit}</small>
                    </strong>
                    {!busy && (
                      <button
                        type="button"
                        className="rl-transaction-edit"
                        onClick={() => setReview(false)}
                      >
                        Edit amount
                      </button>
                    )}
                  </div>
                )
              )}
              <div className="rl-transaction-details">
                <div>
                  <span>Wallet</span>
                  <strong>{addressLabel(context.session.wallet)}</strong>
                </div>
                <div>
                  <span>Chain</span>
                  <strong>{context.config.chainId}</strong>
                </div>
                <div>
                  <span>Reference</span>
                  <strong>
                    {transaction.reference ||
                      addressLabel(
                        transaction.action === "faucet"
                          ? context.config.contracts.asset!
                          : context.config.contracts.vault!,
                      )}
                  </strong>
                </div>
                {quote && review && (
                  <>
                    <div>
                      <span>Expected output</span>
                      <strong>
                        {exactAmount(
                          quote.quoted.toString(),
                          transaction.action === "deposit"
                            ? (transaction.shareDecimals ?? 18)
                            : context.config.asset.decimals,
                        )}{" "}
                        {transaction.action === "deposit"
                          ? "vault shares"
                          : context.config.asset.symbol}
                      </strong>
                    </div>
                    <div>
                      <span>Minimum output</span>
                      <strong>
                        {exactAmount(
                          quote.minimum.toString(),
                          transaction.action === "deposit"
                            ? (transaction.shareDecimals ?? 18)
                            : context.config.asset.decimals,
                        )}
                      </strong>
                    </div>
                  </>
                )}
                {["deposit", "withdraw", "requestWithdrawal"].includes(
                  transaction.action,
                ) && (
                  <div>
                    <span>Maximum slippage</span>
                    <strong>0.5% · two-minute quote</strong>
                  </div>
                )}
                <div>
                  <span>Token approval</span>
                  <strong>Exact amount only, if required</strong>
                </div>
              </div>
              {error && (
                <p className="rl-transaction-error" role="alert">
                  {error}
                </p>
              )}
              {progress && (
                <div role="status" className="gpu-notice">
                  {progress.message}
                  <ChainLink config={context.config} hash={progress.hash} />
                </div>
              )}
              <button
                className="rl-button rl-button-primary rl-transaction-submit"
                disabled={busy || Boolean(context.configurationError)}
              >
                {busy
                  ? "Transaction in progress…"
                  : review
                    ? "Confirm in wallet"
                    : "Review transaction"}{" "}
                <ArrowUpRight size={16} />
              </button>
              <p className="rl-transaction-footnote">
                Rejected or reverted transactions do not update balances.
                Approved tokens may remain approved if the following transaction
                is cancelled.
              </p>
            </form>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
