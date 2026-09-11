export type TxState =
  | { status: 'idle' }
  | { status: 'signing'; label: string }
  | { status: 'pending'; label: string; hash: string }
  | { status: 'confirmed'; label: string; hash: string }
  | { status: 'error'; label: string; message: string }

export type TabId = 'dashboard' | 'ops' | 'proof' | 'admin' | 'config'

export type Eip1193Provider = {
  request: (args: { method: string; params?: unknown[] | Record<string, unknown> }) => Promise<unknown>
}
