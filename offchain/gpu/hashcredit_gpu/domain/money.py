"""Exact money: integer base units as strings + explicit asset reference (domain-model.md §3)."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator

_INT_RE = re.compile(r"^-?[0-9]+$")
_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


class AssetRef(BaseModel, frozen=True):
    chain_id: int = Field(ge=1)
    address: str | None
    symbol: str
    decimals: int = Field(ge=0, le=36)

    @field_validator("address")
    @classmethod
    def _addr(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not _ADDR_RE.match(v):
            raise ValueError("address must be 0x + 40 hex chars")
        return v.lower()

    @property
    def key(self) -> tuple[int, str, int]:
        return (self.chain_id, self.address or "", self.decimals)


class Money(BaseModel, frozen=True):
    amount: str
    asset: AssetRef

    @field_validator("amount")
    @classmethod
    def _amount(cls, v: str) -> str:
        if not isinstance(v, str) or not _INT_RE.match(v):
            raise ValueError("amount must be an integer string in base units")
        return v

    @property
    def units(self) -> int:
        return int(self.amount)

    def __add__(self, other: Money) -> Money:
        self._same_asset(other)
        return Money(amount=str(self.units + other.units), asset=self.asset)

    def __sub__(self, other: Money) -> Money:
        self._same_asset(other)
        return Money(amount=str(self.units - other.units), asset=self.asset)

    def _same_asset(self, other: Money) -> None:
        if self.asset.key != other.asset.key:
            raise ValueError(f"cannot combine different assets {self.asset.key} and {other.asset.key}")

    @model_validator(mode="after")
    def _no_float(self) -> Money:
        return self
