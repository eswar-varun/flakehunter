from __future__ import annotations

import math


def wilson_lower_bound(failures: int, trials: int, z: float = 1.96) -> float:
    """Lower end of the Wilson score interval for a failure rate (95% by default).

    Ranking by the raw rate puts a test that failed once in one run (100%) above one that
    failed 30 times in 100 runs (30%), though the second is far better evidence. The lower
    bound asks "how often does this fail, at least, given how much we've seen?", which
    rewards evidence: 1/1 scores ~0.21 and 30/100 scores ~0.22.
    """
    if trials <= 0:
        return 0.0
    if not 0 <= failures <= trials:
        raise ValueError(f"failures must be in [0, {trials}], got {failures}")
    p = failures / trials
    z2 = z * z
    centre = p + z2 / (2 * trials)
    margin = z * math.sqrt(p * (1 - p) / trials + z2 / (4 * trials * trials))
    return max(0.0, (centre - margin) / (1 + z2 / trials))
