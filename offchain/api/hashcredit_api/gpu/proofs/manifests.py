"""Manifest loading restricted to the repo's `config/attestcoin/` directory (GPU-075 artifacts)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ManifestSummary:
    manifest_id: str
    execution_profile: str
    mock: bool
    environment_status: str
    source_chain_id: int
    chain_key: int
    emitters: frozenset[str]
    proof_hosts: frozenset[str]
    manifest_hash: str | None


def _host(url: str) -> str | None:
    from urllib.parse import urlsplit

    p = urlsplit(url)
    if p.scheme != "https" and p.scheme != "http":
        return None
    return (p.hostname or "").lower() or None


def load_manifests(directory: Path) -> dict[str, ManifestSummary]:
    out: dict[str, ManifestSummary] = {}
    if not directory.is_dir():
        return out
    for f in sorted(directory.glob("*.json")):
        if f.name.endswith(".schema.json"):
            continue
        try:
            m = json.loads(f.read_text("utf-8"))
        except Exception:
            continue
        ps = m.get("proofService", {})
        hosts = {h for u in [ps.get("baseUrl"), *ps.get("alternateBaseUrls", [])] if u for h in [_host(u)] if h}
        src = m.get("source", {})
        out[m["manifestId"]] = ManifestSummary(
            manifest_id=m["manifestId"],
            execution_profile=m.get("executionProfile", ""),
            mock=bool(m.get("mock", False)),
            environment_status=m.get("environmentStatus", ""),
            source_chain_id=int(src.get("chainId", 0)),
            chain_key=int(src.get("chainKey", 0)),
            emitters=frozenset(str(e["address"]).lower() for e in src.get("emitters", []) if e.get("address")),
            proof_hosts=frozenset(hosts),
            manifest_hash=m.get("manifestHash"),
        )
    return out
