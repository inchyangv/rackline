"""Shared PostgreSQL login challenges and live role revocation across API replicas."""

import time

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from hashcredit_gpu.db.product_models import ApiRole, ApiRoleEpoch, LoginChallenge

from .challenge import Challenge


class DatabaseChallengeStore:
    def __init__(self, engine):
        self.engine = engine

    def put(self, challenge: Challenge):
        with Session(self.engine) as session, session.begin():
            session.execute(delete(LoginChallenge).where(LoginChallenge.expires_at <= int(time.time())))
            session.add(LoginChallenge(nonce=challenge.nonce.hex(), wallet=challenge.wallet,
                chain_id=challenge.chain_id, app_domain=challenge.app_domain,
                borrower_hint=challenge.borrower_hint, issued_at=challenge.issued_at,
                expires_at=challenge.expires_at))

    def take(self, nonce: bytes):
        with Session(self.engine) as session, session.begin():
            row = session.execute(delete(LoginChallenge).where(LoginChallenge.nonce == nonce.hex())
                                  .returning(LoginChallenge)).scalar_one_or_none()
            if row is None:
                return None
            return Challenge(nonce, row.wallet, row.chain_id, row.app_domain, row.borrower_hint,
                             row.issued_at, row.expires_at)


class DatabaseRoleRegistry:
    def __init__(self, engine, chain_id):
        self.engine, self.chain_id = engine, chain_id

    def roles_of(self, wallet: str):
        with Session(self.engine) as session:
            return frozenset(session.scalars(select(ApiRole.role).where(ApiRole.chain_id == self.chain_id,
                ApiRole.wallet == wallet.lower(), ApiRole.active.is_(True))))

    def epoch(self, role: str):
        with Session(self.engine) as session:
            row = session.get(ApiRoleEpoch, (self.chain_id, role))
            return row.epoch if row else 0
