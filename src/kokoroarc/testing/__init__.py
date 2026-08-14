"""Deterministic, data-only Character Pack testing primitives."""

from kokoroarc.testing.corpus import (
    CorpusLimits,
    PackTestCorpus,
    load_test_corpus,
)
from kokoroarc.testing.hard import hard_report_is_current, run_hard_validation

__all__ = [
    "CorpusLimits",
    "PackTestCorpus",
    "hard_report_is_current",
    "load_test_corpus",
    "run_hard_validation",
]
