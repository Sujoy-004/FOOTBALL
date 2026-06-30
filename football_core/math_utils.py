"""Shared math utilities."""

import math


def sigmoid(x: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def wilson_score_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Compute Wilson score 95% CI for k successes in n trials.

    Closed-form using only math.sqrt. At n=50000, converges with
    Clopper-Pearson within 0.001.

    Args:
        k: Number of successes.
        n: Number of trials.
        z: Z-score for confidence level (1.96 = 95%).

    Returns:
        Tuple of (lower, upper) bounds rounded to 3 decimal places.
    """
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    z2 = z * z
    denominator = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denominator
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n) / denominator
    return (round(center - margin, 3), round(center + margin, 3))


def format_ci(k: int, n: int) -> str:
    """Format Wilson score CI as a display string.

    Args:
        k: Number of successes.
        n: Number of trials.

    Returns:
        Formatted string like "[0.496 — 0.504]" (em-dash separator).
    """
    low, high = wilson_score_ci(k, n)
    return f"[{low:.3f} \u2014 {high:.3f}]"


def wilson_ci_from_prob(p: float | None, n: int = 50000) -> str | None:
    """Convert a probability to Wilson CI display string.

    Converts probability to pseudo-count for the Wilson formula.

    Args:
        p: Probability value (0-1) or None.
        n: Number of pseudo-trials (default 50000).

    Returns:
        Formatted CI string, or None if p is None.
    """
    if p is None:
        return None
    k = round(p * n)
    return format_ci(k, n)
