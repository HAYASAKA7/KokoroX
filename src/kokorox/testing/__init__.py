"""Deterministic, data-only Character Pack testing primitives."""

from kokorox.testing.corpus import (
    CorpusLimits,
    PackTestCorpus,
    load_test_corpus,
)
from kokorox.testing.hard import hard_report_is_current, run_hard_validation
from kokorox.testing.promotion import create_promotion_record
from kokorox.testing.publication import (
    assess_publication_readiness,
    publication_report_is_current,
)
from kokorox.testing.soft import (
    aggregate_soft_evaluation,
    soft_report_is_current,
)
from kokorox.testing.storage import (
    load_published_promotion_record,
    publish_promotion_record,
)

__all__ = [
    "CorpusLimits",
    "PackTestCorpus",
    "aggregate_soft_evaluation",
    "assess_publication_readiness",
    "create_promotion_record",
    "hard_report_is_current",
    "load_test_corpus",
    "load_published_promotion_record",
    "publish_promotion_record",
    "publication_report_is_current",
    "run_hard_validation",
    "soft_report_is_current",
]
