"""Glicko-1 Bayesian rating system with uncertainty propagation.

Provides closed-form Glicko-1 update rules where each team's strength is
represented as a Gaussian N(μ, σ²).  The rating deviation σ (RD) captures
uncertainty — less-frequently observed teams have higher σ, and the
:func:`g` function deflates win probability for high-uncertainty opponents.

Reference
---------
Glickman, M. E. (1999). "Parameter estimation in large dynamic paired
comparison experiments."  *Applied Statistics*, 48(3), 377–394.

All formulas are from the Glicko-1 closed-form update system, not the
full Glicko-2 Markov chain Monte Carlo procedure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ═══════════════════════════════════════════════════════════════════════════════
# ── Constants
# ═══════════════════════════════════════════════════════════════════════════════

Q: float = math.log(10) / 400  # ≈ 0.0057565 — Elo scale constant
"""Glicko-1 scale constant derived from the Elo 400-point scale."""

PI_SQ: float = math.pi ** 2
"""π², used in the g(RD) calculation."""

DEFAULT_MU: float = 1500.0
"""Default rating for new teams, matching football_core.elo DEFAULT_ELO."""

DEFAULT_SIGMA: float = 350.0
"""Default rating deviation (RD) for new teams — high uncertainty."""

MIN_SIGMA_SQ: float = 50.0 ** 2  # 2500.0
"""Minimum variance floor (RD floor = 50) preventing σ² collapse."""

C: float = 30.0
"""Rating volatility — RD increase per time period (unused in v1)."""


# ═══════════════════════════════════════════════════════════════════════════════
# ── Core Glicko-1 functions
# ═══════════════════════════════════════════════════════════════════════════════


def g(rd: float) -> float:
    """Glicko-1 g(RD) function — probability deflation factor.

    For an opponent with rating deviation *rd* (σ), :func:`g` returns a
    multiplier in (0, 1] that is applied to the rating difference when
    computing expected score.  A perfectly known rating (rd=0) gives
    g=1.0 (full impact, standard Elo).  Higher RD reduces the impact,
    pulling the expected probability closer to 0.5.

    Parameters
    ----------
    rd:
        Opponent rating deviation (σ, standard deviation of rating).

    Returns
    -------
    float
        Deflation factor :math:`g(\\sigma) = 1 / \\sqrt{1 + 3 Q^2 \\sigma^2 / \\pi^2}`.

    Examples
    --------
    >>> g(0.0)
    1.0
    """
    return 1.0 / math.sqrt(1.0 + 3.0 * Q ** 2 * rd ** 2 / PI_SQ)


def expected_score_bayesian(mu_a: float, mu_b: float, sigma_b: float) -> float:
    """Expected score for team A against team B with Bayesian uncertainty.

    Incorporates team B's rating deviation *sigma_b* via the g(RD)
    deflation factor.  When sigma_b = 0, this reduces to standard Elo
    expected score.

    Parameters
    ----------
    mu_a:
        Mean rating of team A.
    mu_b:
        Mean rating of team B.
    sigma_b:
        Rating deviation (σ) of team B.

    Returns
    -------
    float
        Expected score for team A (0.0–1.0).
    """
    return 1.0 / (1.0 + 10.0 ** (-g(sigma_b) * (mu_a - mu_b) / 400.0))


def update_glicko(
    mu: float,
    sigma_sq: float,
    opponent_mu: float,
    opponent_sigma_sq: float,
    score: float,
    k_multiplier: float = 1.0,
) -> tuple[float, float]:
    """Glicko-1 closed-form update for a single rating.

    Computes the posterior (μ_new, σ²_new) after observing a match result
    against a single opponent.  The *k_multiplier* scales the amount of
    information extracted from this match (e.g., goal-difference weighting).

    Parameters
    ----------
    mu:
        Current rating mean.
    sigma_sq:
        Current rating variance (σ²).
    opponent_mu:
        Opponent rating mean.
    opponent_sigma_sq:
        Opponent rating variance (σ²).
    score:
        Observed score: 1.0 for win, 0.5 for draw, 0.0 for loss.
    k_multiplier:
        Information multiplier (>0).  Larger values increase rating movement
        and uncertainty reduction.  Default 1.0.  Typical range 1.0–2.0.

    Returns
    -------
    tuple[float, float]
        (μ_new, σ²_new) — updated mean and variance.
        σ²_new is floored at MIN_SIGMA_SQ (50²).
    """
    # Opponent RD (σ) from variance
    rd_opp = math.sqrt(opponent_sigma_sq)
    g_opp = g(rd_opp)

    # Expected score given current ratings and opponent uncertainty
    e = 1.0 / (1.0 + 10.0 ** (-g_opp * (mu - opponent_mu) / 400.0))

    # Variance of the rating estimate (d² in Glicko-1 paper)
    d2 = 1.0 / (Q ** 2 * g_opp ** 2 * e * (1.0 - e))

    # Apply k_multiplier: scale information from this match
    # Larger k → more weight on the observed outcome in both the
    # variance reduction and the rating mean update.
    if k_multiplier > 0.0:
        d2 /= k_multiplier

    # Update mean and variance (Equation 4 in Glicko-1 paper)
    # σ²_new = 1 / (1/σ² + 1/d²) where 1/d² is smaller with larger k
    new_sigma_sq = 1.0 / (1.0 / sigma_sq + 1.0 / d2)
    # Scale the innovation directly so k>1 produces larger Δμ
    new_mu = mu + Q * new_sigma_sq * g_opp * (score - e) * k_multiplier

    # Apply minimum variance floor
    new_sigma_sq = max(new_sigma_sq, MIN_SIGMA_SQ)

    return new_mu, new_sigma_sq


def compute_glicko_k_factor(goal_diff: int, base_K: float = 1.0) -> float:
    """Goal-difference multiplier for Glicko updates.

    Mirrors :func:`football_core.elo.compute_k_factor` but returns a
    scale factor applied to the Glicko information weight rather than
    a K-addition to a point-estimate update.

    Parameters
    ----------
    goal_diff:
        Absolute goal difference (≥ 0).
    base_K:
        Base multiplier (default 1.0 — identity).

    Returns
    -------
    float
        Effective multiplier K_eff.
    """
    if goal_diff <= 1:
        return base_K
    if goal_diff == 2:
        return base_K * 1.5
    # goal_diff >= 3
    return base_K * (11.0 + goal_diff) / 8.0


# ═══════════════════════════════════════════════════════════════════════════════
# ── Data types
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class TeamRating:
    """Rating of a single team: N(μ, σ²).

    Attributes
    ----------
    mu:
        Mean rating (point estimate, on standard Elo scale ~1500).
    sigma:
        Standard deviation (RD — rating deviation, ≥ 0).
    """

    mu: float
    sigma: float

    @property
    def sigma_sq(self) -> float:
        """Variance σ² = sigma ** 2."""
        return self.sigma ** 2


# ═══════════════════════════════════════════════════════════════════════════════
# ── Rating system
# ═══════════════════════════════════════════════════════════════════════════════


class RatingSystem:
    """Manage Glicko-1 ratings for a set of teams.

    Provides get/set access, paired update (two-team match), serialization
    to/from dict, and a point-estimate compatibility shim.

    Parameters
    ----------
    initial_mu:
        Default rating for new teams (default: 1500.0).
    initial_sigma:
        Default RD for new teams (default: 350.0).
    """

    def __init__(
        self,
        initial_mu: float = DEFAULT_MU,
        initial_sigma: float = DEFAULT_SIGMA,
    ) -> None:
        self._initial_mu = initial_mu
        self._initial_sigma = initial_sigma
        self._ratings: dict[str, TeamRating] = {}

    # ── Accessors ──────────────────────────────────────────────────────

    def get_rating(self, team: str) -> TeamRating:
        """Return *team*'s current rating, or default if unseen."""
        if team not in self._ratings:
            return TeamRating(self._initial_mu, self._initial_sigma)
        return self._ratings[team]

    def set_rating(self, team: str, mu: float, sigma: float) -> None:
        """Set *team*'s rating directly (e.g., from a fetch)."""
        self._ratings[team] = TeamRating(mu, sigma)

    # ── Update ─────────────────────────────────────────────────────────

    def update_ratings(
        self,
        team_a: str,
        team_b: str,
        score_a: float,
        score_b: float,
        k_multiplier: float = 1.0,
    ) -> None:
        """Update both teams' ratings after a match.

        Parameters
        ----------
        team_a:
            Home / first team name.
        team_b:
            Away / second team name.
        score_a:
            Result for team A (1.0 win, 0.5 draw, 0.0 loss).
        score_b:
            Result for team B (1.0 - score_a).
        k_multiplier:
            Goal-difference information multiplier (default 1.0).
        """
        ra = self.get_rating(team_a)
        rb = self.get_rating(team_b)

        # Update team A (A's result vs B)
        mu_a_new, sigma_sq_a_new = update_glicko(
            ra.mu, ra.sigma_sq,
            rb.mu, rb.sigma_sq,
            score_a,
            k_multiplier=k_multiplier,
        )

        # Update team B (B's result vs A — uses A's *original* rating)
        mu_b_new, sigma_sq_b_new = update_glicko(
            rb.mu, rb.sigma_sq,
            ra.mu, ra.sigma_sq,
            score_b,
            k_multiplier=k_multiplier,
        )

        self._ratings[team_a] = TeamRating(mu_a_new, math.sqrt(sigma_sq_a_new))
        self._ratings[team_b] = TeamRating(mu_b_new, math.sqrt(sigma_sq_b_new))

    # ── Serialization ──────────────────────────────────────────────────

    def teams(self) -> list[tuple[str, TeamRating]]:
        """Return all stored ratings as (team, TeamRating) pairs.

        Only teams that have been explicitly set via :meth:`set_rating`
        or modified via :meth:`update_ratings` are included.  Teams that
        have only been read via :meth:`get_rating` (returning defaults)
        are excluded until explicitly set.
        """
        return list(self._ratings.items())

    def to_dict(self) -> dict[str, dict]:
        """Serialize all ratings to a plain dict.

        Returns
        -------
        dict[str, dict]
            ``{"team_name": {"mu": ..., "sigma": ...}, ...}``
        """
        return {
            team: {"mu": r.mu, "sigma": r.sigma}
            for team, r in self._ratings.items()
        }

    @classmethod
    def from_dict(cls, data: dict) -> RatingSystem:
        """Deserialize ratings from a dict (inverse of :meth:`to_dict`).

        Parameters
        ----------
        data:
            Dict in the same format as :meth:`to_dict`.

        Returns
        -------
        RatingSystem
            New instance with the saved ratings loaded.
        """
        rs = cls()
        for team, values in data.items():
            rs.set_rating(team, values["mu"], values["sigma"])
        return rs

    def to_elo_dict(self) -> dict[str, float]:
        """Compatibility shim: return point estimates (μ only).

        Returns
        -------
        dict[str, float]
            ``{"team_name": mu}`` — same format as
            :func:`football_core.elo.update_ratings`.
        """
        return {team: r.mu for team, r in self._ratings.items()}
