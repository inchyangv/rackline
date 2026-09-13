"""GPU-015: the API must import the shared hashcredit_gpu package (installed from offchain/gpu)."""


def test_hashcredit_gpu_importable():
    import hashcredit_gpu
    from hashcredit_gpu.domain import ExecutionProfile, Money

    assert hashcredit_gpu.__version__
    assert ExecutionProfile.PRODUCTION == "PRODUCTION"
    assert Money.__name__ == "Money"
