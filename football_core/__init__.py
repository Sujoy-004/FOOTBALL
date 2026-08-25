"""football_core — the shared football intelligence kernel.

Layers, top to bottom:

- ``domain``      canonical truth vocabulary (MatchStatus,
                  ResultProvenance, DataAvailability) and store loaders
- ``signals``     five-signal ensemble: protocol, registry, blender,
                  implementations
- ``insight``     shared match intelligence over normalized result rows
- ``simulation``  generic Monte Carlo engine behind the SimulationRules
                  boundary (validation 1..1,000,000, isolated seeded RNG,
                  aggregation, SIMULATED provenance)
- infrastructure  Elo math/sync, Poisson model, knockout primitives,
                  provider protocols, persistence helpers

Hard layering rule: nothing here may import from ``competitions/*`` or
``web/*``. Competition brains own every format-specific rule.
"""

from football_core.domain import (  # noqa: F401
    CanonicalMatch,
    DataAvailability,
    MatchStatus,
    ResultProvenance,
)
from football_core.simulation import (  # noqa: F401
    MAX_SIMULATIONS,
    MonteCarloEngine,
    SimulationRequest,
    SimulationResult,
)
