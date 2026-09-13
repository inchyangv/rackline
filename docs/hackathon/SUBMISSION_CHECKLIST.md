# DoraHacks Submission Checklist — BUIDL CTC 2026 Fall (Rackline)

Hackathon page: https://dorahacks.io/hackathon/buidl-ctc-2026-fall/detail
Requirement this season: **every submission must leverage the Attestcoin Protocol** (we do, via `AttestcoinRevenueVerifier` on `0x0FD2`).
Deadline shown on DoraHacks: 2026-09-06 04:59, extended to **2026-09-14 03:59** (time zone as displayed; verify on the page before relying on it). Top 3 → CEIP fast track.

## 1. Eligibility (self-check)
- [ ] All team members: no criminal records / pending cases
- [ ] Not residents of, or subject to, sanctions
- [ ] Participation permitted under country-of-residence law

## 2. Project information (DoraHacks BUIDL form)
Source: `DORAHACKS.md` (paste-ready) + `docs/hackathon/SUBMISSION_VALUES.md`.
- [ ] Project name: Rackline (formerly HashCredit)
- [ ] Logo URL (`logo/logo.png` hosted publicly)
- [ ] Track: RWA (mention DePIN / DeFi fit in the description)
- [ ] Description (One-liner + Problem + Why we pivoted + Solution + Why Creditcoin)
- [ ] GitHub repo URL with updated `README.md`
- [ ] Deck PDF URL (export `Rackline_GPU_Deck.pptx` → PDF)
- [ ] Demo video URL (follow `SCRIPT.md`)
- [ ] Attestcoin usage paragraph (from `DORAHACKS.md` → "Attestcoin Protocol integration")

## 3. Team information (per member)
Use `docs/hackathon/TEAM_INFO.template.md`.
- [ ] Full name, email, role, short bio, residence, citizenship (Telegram / X / LinkedIn / resume optional)
- [ ] Team size

## 4. Project requirements
- [ ] New work during the hackathon period is identifiable: tag `v1-spring-2026` (before) and `v2-fall-2026` (submission); list in `DORAHACKS.md` → "What is new this hackathon vs. Spring"
- [ ] Testnet deployment: Creditcoin CC3 testnet (102031) v2 addresses + Sepolia source contracts filled in `DORAHACKS.md`, `TECH.md`, `README.md`
- [ ] Attestcoin: at least one `RevenueRecorded` tx on Blockscout that references a verified Sepolia tx (link it in the submission)
- [ ] No third-party IP infringement (logo, fonts, screenshots)

## 5. Honesty checks before submitting
- [ ] Every simulated component is labeled (network payout, settlement leg)
- [ ] No partnership claimed with Aethir / GPU.net; they are "targets"
- [ ] No fixed LP yield quoted
- [ ] "Trustless" used only for evidence, never for enforcement
- [ ] v1 addresses labeled legacy
- [ ] Brand consistent: UI (`apps/web/src/lib/brand.ts`), deck, video and submission text all say Rackline; legacy `HashCredit*` identifiers unchanged

## 6. Repo hygiene
- [ ] `README.md` reflects v2 + legacy v1
- [ ] `.env.example` has v2 variables (prover URL, chain keys, keeper key placeholder) and no secrets
- [ ] `forge test` green; web build green
- [ ] Local-only files (`DORAHACKS.md`, `DECK.md`, scripts, keys) not committed

## 7. After submission
- [ ] Post `TECH_DISCORD.md` in the Creditcoin Discord builders channel
- [ ] Prepare CEIP follow-up: `docs/hackathon/CEIP.md`, `CEIP_EMAIL.md` (update for v2)
