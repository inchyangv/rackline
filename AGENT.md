# Agent Notes (Repo Policy)

## Commit Messages

- All commit subject lines must be written in English.
- Avoid non-ASCII (including Korean) in commit messages.
- If you accidentally pushed non-English commit messages, rewrite history and push with `--force-with-lease`.

## Do Not Commit (Local-Only Files)

- `DEPLOY.md`, `DEMO.md`, `DORAHACKS.md` are local-only (ignored by `.gitignore`).
- `docs/guides/` is local-only (ignored by `.gitignore`).
- `keys/` is local-only (deployment wallets/keys). Never commit or track it.
