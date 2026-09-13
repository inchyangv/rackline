import { useCallback, useEffect, useRef, useState } from "react";
import {
  BrowserProvider,
  type Eip1193Provider,
  type TypedDataField,
} from "ethers";
import {
  ApiFailure,
  errorMessage,
  request,
  validateLogin,
  validateRead,
  type Config,
  type Envelope,
  type Session,
} from "./client";

type WalletProvider = Eip1193Provider & {
  on?: (event: string, listener: () => void) => void;
  removeListener?: (event: string, listener: () => void) => void;
};
export function walletProvider(): WalletProvider {
  const provider = (window as unknown as { ethereum?: WalletProvider })
    .ethereum;
  if (!provider?.request)
    throw new Error(
      "Install or enable an Ethereum-compatible browser wallet to continue.",
    );
  return provider;
}

export function useSession(config: Config) {
  const [session, setSession] = useState<Session | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const disconnect = useCallback(() => {
    generation.current += 1;
    setSession(null);
    setBusy(false);
  }, []);
  useEffect(() => {
    let provider: WalletProvider;
    try {
      provider = walletProvider();
    } catch {
      return;
    }
    const changed = () => {
      disconnect();
      setError(
        "Wallet account or network changed. Sign in again to load its records.",
      );
    };
    provider.on?.("accountsChanged", changed);
    provider.on?.("chainChanged", changed);
    return () => {
      provider.removeListener?.("accountsChanged", changed);
      provider.removeListener?.("chainChanged", changed);
      generation.current += 1;
    };
  }, [disconnect]);
  useEffect(() => {
    if (!session) return;
    const timer = setTimeout(
      () => {
        disconnect();
        setError("Your session expired. Sign in again to continue.");
      },
      Math.max(0, session.expiresAt * 1000 - Date.now()),
    );
    return () => clearTimeout(timer);
  }, [session, disconnect]);
  async function connect() {
    if (busy) return;
    const current = ++generation.current;
    setBusy(true);
    setError("");
    try {
      const injected = walletProvider();
      const provider = new BrowserProvider(injected);
      await provider.send("eth_requestAccounts", []);
      const chain = Number((await provider.getNetwork()).chainId);
      if (chain !== config.chainId) {
        try {
          await injected.request({
            method: "wallet_switchEthereumChain",
            params: [{ chainId: `0x${config.chainId.toString(16)}` }],
          });
        } catch (switchError) {
          const cause = switchError as {
            code?: number;
            data?: { originalError?: { code?: number } };
          };
          if (
            (cause.code !== 4902 && cause.data?.originalError?.code !== 4902) ||
            config.chainId !== 102031 ||
            !config.rpcUrl
          )
            throw switchError;
          await injected.request({
            method: "wallet_addEthereumChain",
            params: [
              {
                chainId: "0x18e8f",
                chainName: "Creditcoin Testnet",
                nativeCurrency: {
                  name: "Creditcoin",
                  symbol: "CTC",
                  decimals: 18,
                },
                rpcUrls: [config.rpcUrl],
                blockExplorerUrls: config.explorerUrl
                  ? [config.explorerUrl]
                  : [],
              },
            ],
          });
        }
        if (current === generation.current)
          setError("Network switched. Connect again to sign in.");
        return;
      }
      const signer = await provider.getSigner();
      const wallet = await signer.getAddress();
      const walletCode = await provider.getCode(wallet);
      // Delegated EOAs retain ordinary EOA signatures; contract wallets use the
      // server's allowlisted ERC-1271 checker, never a browser-local verdict.
      const walletKind =
        walletCode === "0x" || /^0xef0100[0-9a-f]{40}$/i.test(walletCode)
          ? "eoa"
          : "erc1271";
      const challenge = await request<{
        nonce: string;
        typedData: {
          domain: Record<string, unknown>;
          types: Record<string, TypedDataField[]>;
          primaryType: string;
          message: Record<string, unknown>;
        };
      }>("/gpu/auth/challenge", { body: { wallet, chainId: config.chainId } });
      if (current !== generation.current) return;
      validateLogin(challenge.typedData, config, wallet);
      const loginTypes = { ...challenge.typedData.types };
      delete loginTypes.EIP712Domain;
      const signature = await signer.signTypedData(
        challenge.typedData.domain,
        loginTypes,
        challenge.typedData.message,
      );
      if (current !== generation.current) return;
      const verified = await request<Session>("/gpu/auth/verify", {
        body: {
          wallet,
          chainId: config.chainId,
          nonce: challenge.nonce,
          signature,
          walletKind,
        },
      });
      if (current !== generation.current) return;
      if (
        verified.wallet.toLowerCase() !== wallet.toLowerCase() ||
        verified.expiresAt <= Date.now() / 1000
      )
        throw new Error("The login session is invalid.");
      setSession(verified);
    } catch (err) {
      if (current === generation.current) setError(errorMessage(err));
    } finally {
      if (current === generation.current) setBusy(false);
    }
  }
  return { session, busy, error, connect, disconnect };
}

export function useGpuRead<T>(
  path: string | null,
  config: Config,
  session: Session,
  refresh: number,
) {
  const [state, setState] = useState<{
    response: Envelope<T> | null;
    loading: boolean;
    error: string;
  }>({ response: null, loading: true, error: "" });
  useEffect(() => {
    const controller = new AbortController();
    // A previous wallet/profile response is never rendered for the new request.
    Promise.resolve().then(() => {
      if (!controller.signal.aborted)
        setState({ response: null, loading: Boolean(path), error: "" });
    });
    let pending = false;
    const load = () => {
      if (!path || pending || controller.signal.aborted) return;
      pending = true;
      void request<Envelope<T>>(path, {
        token: session.token,
        signal: controller.signal,
      })
        .then((response) => {
          if (response.schemaVersion !== "1.0")
            throw new ApiFailure(
              "INVALID_RESPONSE",
              "The API response version is unsupported.",
            );
          validateRead(response.meta, config);
          if (!controller.signal.aborted)
            setState({ response, loading: false, error: "" });
        })
        .catch((err) => {
          if (!controller.signal.aborted)
            setState({
              response: null,
              loading: false,
              error: errorMessage(err),
            });
        })
        .finally(() => {
          pending = false;
        });
    };
    load();
    const visible = () => {
      if (document.visibilityState === "visible") load();
    };
    const timer = setInterval(visible, 15000);
    document.addEventListener("visibilitychange", visible);
    return () => {
      controller.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [path, config, session.token, refresh]);
  return state;
}

export async function assertWallet(
  config: Config,
  session: Session,
): Promise<BrowserProvider> {
  if (session.expiresAt <= Date.now() / 1000)
    throw new ApiFailure("UNAUTHENTICATED", "Your session expired.");
  const provider = new BrowserProvider(walletProvider());
  const accounts = (await provider.send("eth_accounts", [])) as string[];
  const network = await provider.getNetwork();
  if (
    Number(network.chainId) !== config.chainId ||
    accounts[0]?.toLowerCase() !== session.wallet.toLowerCase()
  )
    throw new Error(
      "The current wallet account or network differs from this session. Reconnect before signing.",
    );
  return provider;
}
