"""Shuffle test order when ZOO_SHUFFLE_SEED is set, as pytest-randomly would.

Order-dependent tests only reveal themselves when the order changes between runs, so the
evaluation harness gives every run a different seed.
"""

import os
import random


def pytest_collection_modifyitems(session, config, items):
    seed = os.environ.get("ZOO_SHUFFLE_SEED")
    if seed is not None:
        random.Random(int(seed)).shuffle(items)
