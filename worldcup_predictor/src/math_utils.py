"""Shared math utilities for the prediction pipeline."""

import math


def sigmoid(x: float) -> float:
    """Compute sigmoid function using math.exp (pure stdlib).

    Args:
        x: Input value (real number).

    Returns:
        Sigmoid output in (0, 1).
    """
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0
