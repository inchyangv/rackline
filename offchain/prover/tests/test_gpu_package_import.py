"""GPU-015: the prover/worker must import the shared hashcredit_gpu package (installed from offchain/gpu)."""


def test_hashcredit_gpu_importable():
    import hashcredit_gpu
    from hashcredit_gpu.db import Base

    assert hashcredit_gpu.__version__
    assert "facilities" in Base.metadata.tables
