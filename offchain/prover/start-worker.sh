#!/bin/sh
set -eu

ADDRESSES_PATH="${ADDRESSES_FILE:-/app/addresses.json}"

if [ -n "${ADDRESSES_JSON_B64:-}" ]; then
  echo "$ADDRESSES_JSON_B64" | base64 -d > "$ADDRESSES_PATH"
elif [ -n "${ADDRESSES_JSON:-}" ]; then
  # Write exactly as provided (must be valid JSON)
  printf "%s" "$ADDRESSES_JSON" > "$ADDRESSES_PATH"
fi

if [ ! -f "$ADDRESSES_PATH" ]; then
  echo "ERROR: addresses file not found at $ADDRESSES_PATH" >&2
  echo "Set ADDRESSES_FILE to a mounted file path, or set ADDRESSES_JSON / ADDRESSES_JSON_B64." >&2
  exit 1
fi

# Allow optional extra args via env (e.g. \"--confirmations 6 --poll-interval 60\").
# shellcheck disable=SC2086
exec python -m hashcredit_prover.cli run-relayer "$ADDRESSES_PATH" ${RELAYER_ARGS:-}
