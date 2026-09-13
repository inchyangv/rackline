"""Capability-gated partner actions. API acknowledgement never grants E2 or records cash."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.ledgers import Job, Outbox
from ..db.models import ProviderAccount
from ..domain import Money
from ..jobs import JobQueue, TerminalError, TransientError
from ..jobs.outbox import emit
from ..jobs.queue import write_audit
from ..providers.errors import UnsupportedOperation
from ..providers.types import AccountRef, ClaimRequest, ControlChangeRequest


@dataclass(frozen=True)
class WriteBinding:
    provider_id: str
    execution_profile: str
    partner_binding: str
    credential_scope: frozenset[str]
    allowed_receivers: frozenset[str]
    receiver_chain_id: int
    claim_cap: int
    approval_ref: str
    idempotent_requests: bool


@dataclass(frozen=True)
class EffectObservation:
    applied: bool
    reference: str | None


class EffectReader(Protocol):
    def observe(self, action: dict) -> EffectObservation: ...
    def release_permitted(self, action: dict) -> bool: ...


class ControlExecutor:
    def __init__(self, engine, adapter, binding: WriteBinding, effects: EffectReader):
        self.engine, self.adapter, self.binding, self.effects = engine, adapter, binding, effects
        self.queue = JobQueue(engine)

    def _authorize(self, session, action, *, write=True):
        binding, identity = self.binding, self.adapter.identity()
        if (
            not binding.approval_ref
            or not binding.idempotent_requests
            or identity.provider_slug != binding.provider_id
            or identity.execution_profile.value != binding.execution_profile
        ):
            raise TerminalError("write binding is missing or inconsistent")
        if binding.execution_profile != "LOCAL_MOCK" and binding.partner_binding not in {
            "SANDBOX_VERIFIED",
            "LIVE_VERIFIED",
        }:
            raise TerminalError("partner write binding is unconfigured")
        if binding.execution_profile == "PRODUCTION" and (
            identity.is_mock or binding.partner_binding != "LIVE_VERIFIED"
        ):
            raise TerminalError("production requires live partner write authority")
        operation = "claim_revenue" if action["kind"] == "CLAIM" else "request_control_change"
        if action["kind"] not in {"CLAIM", "SET_RECEIVER", "RELEASE"}:
            raise TerminalError("unsupported provider action")
        account = session.get(ProviderAccount, action["providerAccountId"])
        if not account or account.provider_id != binding.provider_id:
            raise TerminalError("provider account binding mismatch")
        if write and (
            operation not in binding.credential_scope or operation not in account.auth_scope
        ):
            raise TerminalError("partner write scope revoked or unavailable")
        if (
            not action.get("reason")
            or not action.get("approvedBy")
            or action.get("approvalRef") != binding.approval_ref
        ):
            raise TerminalError("reason and bound approval required")
        if action.get("approvedRole") not in {"operator", "treasury"}:
            raise TerminalError("action requires operator or treasury approval")
        if write and int(action["deadline"]) <= int(datetime.now(UTC).timestamp()):
            raise TerminalError("provider action deadline expired")
        if write:
            try:
                self.adapter.capabilities().require(operation)
            except UnsupportedOperation as exc:
                raise TerminalError("partner operation unsupported") from exc
        if action["kind"] == "CLAIM":
            amount = Money.model_validate(action["amount"])
            if (
                amount.units <= 0
                or amount.units > binding.claim_cap
                or amount.asset not in identity.supported_assets
            ):
                raise TerminalError("claim amount or asset exceeds approved binding")
        else:
            if (
                action.get("receiver") not in binding.allowed_receivers
                or action.get("receiverChainId") != binding.receiver_chain_id
            ):
                raise TerminalError("receiver is outside approved agreement targets")
            if write and action["kind"] == "RELEASE" and not self.effects.release_permitted(action):
                raise TerminalError(
                    "release blocked by debt, unresolved refunds or active agreement"
                )
        return AccountRef(
            provider_slug=account.provider_id, external_account_id=account.external_account_id
        )

    def enqueue(self, session, action: dict) -> str:
        self._authorize(session, action)
        action_id = action.get("actionId")
        if not isinstance(action_id, str) or not action_id or len(action_id) > 128:
            raise ValueError("bounded semantic actionId required")
        semantic_key = f"provider-action:{self.binding.provider_id}:{action_id}"
        existing = session.scalar(select(Job).where(Job.semantic_idempotency_key == semantic_key))
        if existing and existing.payload != action:
            raise ValueError("provider actionId already bound to different request")
        return self.queue.enqueue(
            "PROVIDER_ACTION", dict(action), semantic_key, max_attempts=100, cx=session.connection()
        )

    def handle(self, cx, job):
        action = job.payload
        with Session(bind=cx) as session:
            account = self._authorize(session, action, write=False)
            effect = self.effects.observe(action)
            ack_key = f"provider-ack:{self.binding.provider_id}:{action['actionId']}"
            ack = session.scalar(select(Outbox).where(Outbox.idempotency_key == ack_key))
            if not effect.applied and not ack:
                self._authorize(
                    session, action
                )  # Recheck revoked scope and expiry before another write.
                if action["kind"] == "CLAIM":
                    result = self.adapter.claim_revenue(
                        ClaimRequest(
                            account=account,
                            amount=Money.model_validate(action["amount"]),
                            idempotency_key=action["actionId"],
                        )
                    )
                else:
                    result = self.adapter.request_control_change(
                        ControlChangeRequest(
                            account=account,
                            new_receiver=action["receiver"],
                            new_receiver_chain_id=action["receiverChainId"],
                            idempotency_key=action["actionId"],
                        )
                    )
                if result.account != account or result.idempotency_key != action["actionId"]:
                    raise TerminalError("provider acknowledgement binding mismatch")
                if not result.accepted:
                    raise TerminalError("provider rejected approved action")
                # Persist acknowledgement independently; worker may crash before the effect becomes visible.
                with self.engine.begin() as own:
                    emit(
                        own,
                        aggregate_type="provider_action",
                        aggregate_id=action["actionId"],
                        event_type="PROVIDER_ACTION_ACKNOWLEDGED",
                        idempotency_key=ack_key,
                        payload={
                            "providerRef": result.provider_ref,
                            "cashState": "NONE",
                            "controlGradeEffect": "NONE",
                        },
                    )
                effect = self.effects.observe(action)
            if not effect.applied or not effect.reference:
                raise TransientError("provider action acknowledged; applied effect not observed")
            emitted = emit(
                cx,
                aggregate_type="provider_action",
                aggregate_id=action["actionId"],
                event_type="PROVIDER_ACTION_EFFECT_OBSERVED",
                idempotency_key=f"provider-effect:{self.binding.provider_id}:{action['actionId']}",
                payload={
                    "effectRef": effect.reference,
                    "cashState": "NONE",
                    "controlGradeEffect": "NONE",
                    "partnerBinding": self.binding.partner_binding,
                },
            )
            if emitted:
                write_audit(
                    cx,
                    actor=action["approvedBy"],
                    actor_role=action["approvedRole"],
                    action="PROVIDER_EFFECT_OBSERVED",
                    entity_table="provider_accounts",
                    entity_id=action["providerAccountId"],
                    before=None,
                    after={
                        "actionId": action["actionId"],
                        "effectRef": effect.reference,
                        "reason": action["reason"],
                    },
                    correlation_id=job.job_id,
                )
