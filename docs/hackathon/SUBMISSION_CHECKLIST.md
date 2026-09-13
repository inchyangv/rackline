# DoraHacks Submission Checklist — BUIDL CTC 2026 Fall (Rackline)

Hackathon page: https://dorahacks.io/hackathon/buidl-ctc-2026-fall/detail
Requirement this season: **every submission must leverage the Attestcoin Protocol** (we do — official native verification only, `AttestcoinRevenueVerifier` over `INativeQueryVerifier` at `0x…0FD2`; artifacts pinned by GPU-075).
Deadline shown on DoraHacks: 2026-09-06 04:59, extended to **2026-09-14 03:59** (time zone as displayed; verify on the page before relying on it). Top 3 → CEIP fast track.

Status as of 2026-09-14: official artifacts pinned and testnet probed; **no v2 contract, worker or UI implemented or deployed; no native proof submitted.** The submission must say so. Do not fill an address that does not exist.

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
- [ ] Demo video URL (follow `SCRIPT.md`; Part A only unless Part B is built)
- [ ] Attestcoin usage paragraph (from `DORAHACKS.md` → "Attestcoin Protocol integration", with the pinned versions)

## 3. Team information (per member)
Use `docs/hackathon/TEAM_INFO.template.md`.
- [ ] Full name, email, role, short bio, residence, citizenship (Telegram / X / LinkedIn / resume optional)
- [ ] Team size

## 4. Project requirements
- [ ] New work during the hackathon period is identifiable: tag `v1-spring-2026` (before) and `v2-fall-2026` (submission); list in `DORAHACKS.md` → "What is new this hackathon vs. Spring"
- [ ] Testnet deployment: fill Creditcoin CC3 testnet (102031) v2 addresses + Sepolia source contracts in `DORAHACKS.md`, `TECH.md`, `README.md` **only if deployed**; otherwise keep `<TODO — not deployed>` and say so
- [ ] Attestcoin: if G-ASC (GPU-080) has run, link at least one `EventRecorded` tx on Blockscout that references a verified Sepolia tx; if not, link the `ASC-PROBE` report (`test/fixtures/gpu/attestcoin/probe/`) and state that no native proof has been submitted
- [ ] No third-party IP infringement (logo, fonts, screenshots)

## 5. Honesty checks before submitting (R2)
- [ ] Every simulated component is labelled (`Simulated payer`, `Mock settlement`, `partnerRevenue=SIMULATED`, `controlGrade=E1 (mock)`)
- [ ] No partnership claimed with Aethir / GPU.net; they are "targets"
- [ ] No fixed LP yield quoted
- [ ] "Trustless" not used for enforcement; evidence is "natively verified", enforcement is "contractual plus payment control, graded"
- [ ] No "GPU NFT", NFT lien / foreclosure, trailing-payout limit, or "attested fallback / lower advance rate" wording anywhere (retired draft)
- [ ] A proof is never called revenue; a past payout is never called a receivable; in-flight funds are never called repaid; Writability is not assumed
- [ ] Status claims match `docs/gpu/execution/ATTESTCOIN_GAP.md` §1 (planned vs implemented) and each ticket's `상태` in `TICKET.md`
- [ ] v1 addresses labelled legacy
- [ ] Brand consistent: UI (`apps/web/src/lib/brand.ts`), deck, video and submission text all say Rackline; legacy `HashCredit*` identifiers unchanged

## 6. Repo hygiene
- [ ] `README.md` reflects v2 (R2) + legacy v1, with the status table dated
- [ ] `.env.example` has no secrets; Attestcoin RPC / proof-service references come from `config/attestcoin/` manifests
- [ ] `forge test` green (v1 baseline: 192); `ASC-CHECK` / `ASC-TEST` green; web lint / build green
- [ ] Local-only files (`DORAHACKS.md`, `DECK.md`, scripts, keys, `*.pptx`) not committed

## 7. After submission
- [ ] Post `TECH_DISCORD.md` in the Creditcoin Discord builders channel
- [ ] Prepare CEIP follow-up: `docs/hackathon/CEIP.md`, `CEIP_EMAIL.md` (update for v2 receivables product and current status)
