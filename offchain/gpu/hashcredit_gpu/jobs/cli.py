"""
Operator CLI for the durable job queue (`python -m hashcredit_gpu.jobs.cli ...`).

    list [--state S] [--kind K] [--limit N]
    dead-letter                       -- list DEAD jobs (never auto-resumed)
    resume --job-id ID --actor A --role R --reason "..."   -- audited manual resume
    outbox-pending                    -- count of unpublished outbox rows

The database URL comes from HASHCREDIT_GPU_DATABASE_URL (or --url); it is never printed.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine

from ..db.settings import database_url
from .outbox import pending_outbox
from .queue import JobQueue, JobRow, ResumeRequiresReason


def _fmt(row: JobRow) -> str:
    return (
        f"{row.job_id} {row.kind:<26} {row.state:<9} attempt={row.attempt}/{row.max_attempts} "
        f"leased_by={row.leased_by or '-'} next={row.next_run_at.isoformat()} err={(row.last_error or '')[:80]!r}"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hashcredit-gpu-jobs")
    p.add_argument("--url", help="PostgreSQL URL (default: env HASHCREDIT_GPU_DATABASE_URL)")
    sub = p.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--state")
    ls.add_argument("--kind")
    ls.add_argument("--limit", type=int, default=100)
    sub.add_parser("dead-letter")
    rs = sub.add_parser("resume")
    rs.add_argument("--job-id", required=True)
    rs.add_argument("--actor", required=True)
    rs.add_argument("--role", required=True, help="operator | guardian | treasury | underwriter | system ...")
    rs.add_argument("--reason", required=True)
    sub.add_parser("outbox-pending")
    args = p.parse_args(argv)

    engine = create_engine(database_url(args.url))
    q = JobQueue(engine)
    if args.cmd == "list":
        for row in q.list_jobs(args.state, args.kind, args.limit):
            print(_fmt(row))
        return 0
    if args.cmd == "dead-letter":
        rows = q.list_jobs("DEAD")
        for row in rows:
            print(_fmt(row))
        print(f"{len(rows)} dead-lettered job(s)", file=sys.stderr)
        return 0
    if args.cmd == "resume":
        try:
            q.resume(args.job_id, actor=args.actor, actor_role=args.role, reason=args.reason)
        except (ResumeRequiresReason, ValueError, LookupError) as e:
            print(f"resume refused: {e}", file=sys.stderr)
            return 1
        print(f"resumed {args.job_id} (audited)")
        return 0
    if args.cmd == "outbox-pending":
        print(pending_outbox(engine))
        return 0
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
