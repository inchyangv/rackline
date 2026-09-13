"""Opt-in cold-DB replay of an actual indexed journal; reads the source DB and writes only an ephemeral test DB."""

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from hashcredit_gpu.db.projections_models import (
    ChainBlock,
    ChainCursor,
    ChainDeployment,
    ChainLog,
    ProjectedEntity,
    ProjectedFacility,
)
from hashcredit_gpu.projections.indexer import ChainIndexer


@pytest.mark.skipif(
    not os.environ.get("GPU_NATIVE_REPLAY_RUNTIME"),
    reason="actual native runtime locator explicitly required",
)
def test_actual_native_journal_replays_from_cold_database_twice(migrated_db_url):
    locator = json.loads(Path(os.environ["GPU_NATIVE_REPLAY_RUNTIME"]).read_text())
    source = create_engine(
        locator["databaseUrl"], isolation_level="REPEATABLE READ", hide_parameters=True
    )
    try:
        with Session(source) as s, s.begin():
            deployment = s.scalar(
                select(ChainDeployment).where(ChainDeployment.execution_profile == "NATIVE_TESTNET")
            )
            assert deployment is not None
            identity = {
                c.name: getattr(deployment, c.name) for c in ChainDeployment.__table__.columns
            }
            blocks = {
                b.number: {
                    "number": hex(b.number),
                    "hash": b.hash,
                    "parentHash": b.parent_hash,
                    "timestamp": hex(b.timestamp),
                }
                for b in s.scalars(
                    select(ChainBlock).where(ChainBlock.deployment_id == deployment.deployment_id)
                )
            }
            assert 0 < len(blocks) <= 10000
            logs = [
                {
                    "address": r.address,
                    "topics": r.topics,
                    "data": r.data,
                    "blockNumber": hex(r.block_number),
                    "blockHash": r.block_hash,
                    "transactionHash": r.tx_hash,
                    "transactionIndex": hex(r.tx_index),
                    "logIndex": hex(r.log_index),
                }
                for r in s.scalars(
                    select(ChainLog).where(ChainLog.deployment_id == deployment.deployment_id)
                )
            ]
            assert logs
    finally:
        source.dispose()

    class CapturedRpc:
        def chain_id(self):
            return identity["chain_id"]

        def block_number(self):
            return max(blocks)

        def get_block(self, n):
            return blocks.get(n)

        def get_logs(self, addresses, start, end):
            return [
                log
                for log in logs
                if log["address"] in addresses and start <= int(log["blockNumber"], 16) <= end
            ]

        def get_receipt(self, txhash):
            log = next(log for log in logs if log["transactionHash"] == txhash)
            return {"status": "0x1", "blockHash": log["blockHash"]}

    engine = create_engine(migrated_db_url)
    try:
        with Session(engine) as s, s.begin():
            s.add(ChainDeployment(**identity))
        indexer = ChainIndexer(engine, CapturedRpc())
        while indexer.sync(identity["deployment_id"], chunk_size=5000)["lag"]:
            pass
        first = indexer.sync(identity["deployment_id"])
        second = indexer.sync(identity["deployment_id"])
        assert first == second and first["lag"] == 0
        with Session(engine) as s:
            assert s.get(ChainCursor, identity["deployment_id"]).last_block_number == max(blocks)
            assert list(s.scalars(select(ProjectedEntity)))
            assert all(
                r.principal >= 0 and r.fees >= 0 for r in s.scalars(select(ProjectedFacility))
            )
    finally:
        engine.dispose()
