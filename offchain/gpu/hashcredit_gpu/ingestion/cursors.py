"""
Persistent per-(provider, stream) cursors over `ingest_cursors` (migration 0002).

`position` is JSON: `{"high_water": iso|null, "page_token": str|null, "window_end": iso|null,
"overlap_seconds": int}`. The high-water mark advances only after every page of a window has been committed;
a page token survives crashes so a 429/timeout in the middle of a window resumes at the same page.

There is no implicit start: a stream without a cursor must be opened with an explicit `initial_start`
(onboarding date / deployment block). "Restart from the last N blocks" (the legacy watcher default) does not
exist here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.engine import Connection


class MissingCursorError(LookupError):
    """The stream has no cursor and no explicit initial start was given."""


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


def _parse(v: str | None) -> datetime | None:
    if not v:
        return None
    dt = datetime.fromisoformat(v)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@dataclass(frozen=True)
class CursorState:
    provider_id: str
    stream: str
    high_water: (
        datetime | None
    )  # everything strictly before this has been collected (minus overlap)
    page_token: str | None  # in-flight page inside [window_start, window_end]
    window_end: datetime | None  # end of the window the page token belongs to
    overlap_seconds: int
    backfill_from: str | None = None

    def to_position(self) -> str:
        return json.dumps(
            {
                "high_water": _iso(self.high_water),
                "page_token": self.page_token,
                "window_end": _iso(self.window_end),
                "overlap_seconds": self.overlap_seconds,
            },
            sort_keys=True,
        )

    @classmethod
    def from_row(
        cls, provider_id: str, stream: str, position: str, backfill_from: str | None
    ) -> CursorState:
        d = json.loads(position)
        return cls(
            provider_id=provider_id,
            stream=stream,
            high_water=_parse(d.get("high_water")),
            page_token=d.get("page_token"),
            window_end=_parse(d.get("window_end")),
            overlap_seconds=int(d.get("overlap_seconds", 0)),
            backfill_from=backfill_from,
        )


class CursorStore:
    """All reads lock the row (`FOR UPDATE`) so two collectors on the same stream serialize."""

    @staticmethod
    def load(cx: Connection, provider_id: str, stream: str) -> CursorState | None:
        row = cx.execute(
            text(
                "SELECT position, backfill_from FROM ingest_cursors WHERE provider_id = :p AND stream = :s FOR UPDATE"
            ),
            {"p": provider_id, "s": stream},
        ).one_or_none()
        if row is None:
            return None
        return CursorState.from_row(provider_id, stream, row.position, row.backfill_from)

    @staticmethod
    def open(
        cx: Connection,
        provider_id: str,
        stream: str,
        *,
        initial_start: datetime | None,
        overlap_seconds: int,
    ) -> CursorState:
        """Load the cursor, or create it at `initial_start`. Never invents a start."""
        st = CursorStore.load(cx, provider_id, stream)
        if st is not None:
            return st
        if initial_start is None:
            raise MissingCursorError(
                f"{provider_id}/{stream}: no cursor and no initial_start (refusing to guess a start)"
            )
        if initial_start.tzinfo is None:
            raise ValueError("initial_start must include a timezone")
        st = CursorState(
            provider_id, stream, initial_start.astimezone(UTC), None, None, overlap_seconds
        )
        cx.execute(
            text(
                "INSERT INTO ingest_cursors (provider_id, stream, position_kind, position) "
                "VALUES (:p, :s, 'OPAQUE', :pos) ON CONFLICT (provider_id, stream) DO NOTHING"
            ),
            {"p": provider_id, "s": stream, "pos": st.to_position()},
        )
        # re-read under lock (a concurrent opener may have won the insert)
        st2 = CursorStore.load(cx, provider_id, stream)
        assert st2 is not None
        return st2

    @staticmethod
    def save(cx: Connection, st: CursorState) -> None:
        cx.execute(
            text(
                "UPDATE ingest_cursors SET position = :pos, backfill_from = :bf, updated_at = now() "
                "WHERE provider_id = :p AND stream = :s"
            ),
            {"pos": st.to_position(), "bf": st.backfill_from, "p": st.provider_id, "s": st.stream},
        )

    @staticmethod
    def with_page(st: CursorState, page_token: str | None, window_end: datetime) -> CursorState:
        return replace(st, page_token=page_token, window_end=window_end)

    @staticmethod
    def advanced(st: CursorState, window_end: datetime) -> CursorState:
        """Window fully collected: move the high-water mark, clear the in-flight page."""
        return replace(st, high_water=window_end.astimezone(UTC), page_token=None, window_end=None)
