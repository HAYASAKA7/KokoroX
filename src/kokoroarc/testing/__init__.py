"""Deterministic, data-only Character Pack testing primitives."""

from kokoroarc.testing.corpus import (
    CorpusLimits,
    PackTestCorpus,
    load_test_corpus,
)
from kokoroarc.testing.hard import hard_report_is_current, run_hard_validation
from kokoroarc.testing.soft import (
    aggregate_soft_evaluation,
    soft_report_is_current,
)

__all__ = [
    "CorpusLimits",
    "PackTestCorpus",
    "aggregate_soft_evaluation",
    "hard_report_is_current",
    "load_test_corpus",
    "run_hard_validation",
    "soft_report_is_current",
]
