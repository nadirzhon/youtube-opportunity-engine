"""Learning loop (Phase 7): bandit, insights, niche priors, feedback closure."""
from .bandit import Bandit
from .insights import insights, niche_priors
from .feedback import (
    record_publication, package_to_experiment, learned_boost,
    rerank_with_experience, classify_hook, classify_title,
    publication_record, record_result_for_publication,
)
from .calibration import calibrate, calibration_report
__all__ = [
    "Bandit", "insights", "niche_priors",
    "record_publication", "package_to_experiment", "learned_boost",
    "rerank_with_experience", "classify_hook", "classify_title",
    "calibrate", "calibration_report",
]
