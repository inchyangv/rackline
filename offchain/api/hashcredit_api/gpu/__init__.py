"""
GPU product API (GPU-018): wallet authentication, object-level permissions, credential handling and the
R2 proof-query guard.

Everything here is an *auxiliary* path (R2-D03/D04): a session or a signature authenticates a caller;
it never creates a source fact, never marks anything verified, and the production API holds no signing key.
"""

from .runtime import GpuRuntime, build_gpu_runtime
from .router import build_gpu_router

__all__ = ["GpuRuntime", "build_gpu_runtime", "build_gpu_router"]
