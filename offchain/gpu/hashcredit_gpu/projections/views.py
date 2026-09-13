"""ABI-pinned business view reads at one explicit canonical block."""

import json
import re

from eth_abi import decode, encode

from ..transactions.abi import selector
from .decoders import ABI_DIR, _canonical_type, _json_safe


def _input_value(spec, value):
    if spec["type"].endswith("]"):
        inner = {**spec, "type": spec["type"][: spec["type"].rfind("[")]}
        return [_input_value(inner, item) for item in value]
    if re.fullmatch(r"u?int[0-9]*", spec["type"]) and isinstance(value, str):
        if not re.fullmatch(r"-?[0-9]+", value):
            raise ValueError("ABI integer inputs require exact decimal units")
        return int(value)
    if spec["type"].startswith("bytes") and isinstance(value, str):
        return bytes.fromhex(value.removeprefix("0x"))
    if spec["type"].startswith("tuple"):
        values = (
            [value[c["name"]] for c in spec["components"]] if isinstance(value, dict) else value
        )
        return tuple(_input_value(c, v) for c, v in zip(spec["components"], values, strict=True))
    return value


def _output_value(spec, value):
    if spec["type"].endswith("]"):
        inner = {**spec, "type": spec["type"][: spec["type"].rfind("[")]}
        return [_output_value(inner, item) for item in value]
    if spec["type"] == "tuple":
        return {
            c["name"] or str(i): _output_value(c, v)
            for i, (c, v) in enumerate(zip(spec["components"], value, strict=True))
        }
    return _json_safe(value)


class ContractViews:
    def __init__(self, rpc, contracts: dict[str, str]):
        self.rpc, self.contracts = rpc, contracts

    def read(self, contract: str, function: str, args: list, block: int):
        abi = json.loads((ABI_DIR / f"{contract}.json").read_text())
        matches = [
            x
            for x in abi
            if x.get("type") == "function"
            and x.get("name") == function
            and len(x["inputs"]) == len(args)
        ]
        if len(matches) != 1 or matches[0]["stateMutability"] not in {"view", "pure"}:
            raise ValueError("expected one pinned read-only contract function")
        fn = matches[0]
        types = [_canonical_type(i) for i in fn["inputs"]]
        data = selector(function + "(" + ",".join(types) + ")")
        data += encode(
            types, [_input_value(i, v) for i, v in zip(fn["inputs"], args, strict=True)]
        ).hex()
        raw = self.rpc.eth_call({"to": self.contracts[contract], "data": data}, hex(block))
        values = decode(
            [_canonical_type(o) for o in fn["outputs"]], bytes.fromhex(raw.removeprefix("0x"))
        )
        result = [_output_value(o, v) for o, v in zip(fn["outputs"], values, strict=True)]
        return result[0] if len(result) == 1 else result
