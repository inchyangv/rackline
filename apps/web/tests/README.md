# Local demo tests

Run from `apps/web` after `npm ci`:

```sh
npm run test:unit
npm run test:e2e
```

The browser suite starts Vite on `http://127.0.0.1:4173`, or reuses an existing
server there outside CI. It runs Chromium at desktop 1440px and mobile 390px
widths. On macOS it automatically uses the installed Google Chrome application.
Elsewhere, install the Playwright browser with `npx playwright install chromium`,
or set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to an existing Chromium executable.

Each browser test has fresh demo storage. The suite checks navigation and mobile
overflow, transaction validation and balances, reload persistence, provider
consent, proof/control interruptions, and withdrawal queue settlement and claims.
An injected-wallet sentinel and HTTP request guard reject real wallet calls,
external requests, POST requests, and application API requests. The tests also
fail on uncaught browser exceptions.

These checks cover the local simulated frontend only. They do not validate live
provider connections, lending contracts, Attestcoin proofs, or real transfers.

Screenshots and failure traces are written beneath
`node_modules/.cache/playwright/test-results/`. Node store tests are separate from
the Playwright `*.spec.ts` discovery pattern and require no browser.
