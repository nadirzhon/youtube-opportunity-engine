"""
Multi-armed bandit for content hypotheses (Phase 7).

Thompson sampling over Beta(successes, failures) — each "arm" is a content
choice (an angle, a hook style, a title structure). As real publication results
arrive, arms update and the sampler shifts effort toward what works while still
exploring. Deterministic when seeded, so it's testable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from random import Random


@dataclass
class Arm:
    name: str
    alpha: float = 1.0   # prior successes + 1
    beta: float = 1.0    # prior failures + 1

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def pulls(self) -> int:
        return int(self.alpha + self.beta - 2)


@dataclass
class Bandit:
    seed: int = 7
    arms: dict[str, Arm] = field(default_factory=dict)

    def __post_init__(self):
        self._rng = Random(self.seed)

    def arm(self, name: str) -> Arm:
        return self.arms.setdefault(name, Arm(name))

    def update(self, name: str, *, success: bool, weight: float = 1.0) -> None:
        a = self.arm(name)
        if success:
            a.alpha += weight
        else:
            a.beta += weight

    def observe_reward(self, name: str, reward: float) -> None:
        """reward in [0,1] (e.g. normalized performance) → soft success/failure."""
        reward = max(0.0, min(1.0, reward))
        a = self.arm(name)
        a.alpha += reward
        a.beta += (1.0 - reward)

    def _sample_beta(self, a: float, b: float) -> float:
        # Beta via two Gammas (Marsaglia-Tsang) using the seeded RNG.
        return _gamma(a, self._rng) / (_gamma(a, self._rng) + _gamma(b, self._rng))

    def choose(self, candidates: list[str]) -> str:
        """Thompson sampling: pick the arm with the highest sampled value."""
        best, best_v = candidates[0], -1.0
        for c in candidates:
            arm = self.arm(c)
            v = self._sample_beta(arm.alpha, arm.beta)
            if v > best_v:
                best, best_v = c, v
        return best

    def ranking(self) -> list[tuple[str, float, int]]:
        return sorted(((a.name, round(a.mean, 3), a.pulls) for a in self.arms.values()),
                      key=lambda t: t[1], reverse=True)


def _gamma(k: float, rng: Random) -> float:
    """Marsaglia-Tsang gamma sampler (shape k, scale 1)."""
    if k < 1:
        return _gamma(k + 1, rng) * (rng.random() ** (1.0 / k))
    d = k - 1.0 / 3.0
    c = 1.0 / math.sqrt(9.0 * d)
    while True:
        x = rng.gauss(0, 1)
        v = (1 + c * x) ** 3
        if v <= 0:
            continue
        u = rng.random()
        if u < 1 - 0.0331 * x ** 4 or math.log(u) < 0.5 * x * x + d * (1 - v + math.log(v)):
            return d * v
