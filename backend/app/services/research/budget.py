"""Research budgets derived from settings. All loops are bounded by these."""

from dataclasses import dataclass

from app.config import Settings


@dataclass(frozen=True)
class Budget:
    max_search_rounds: int
    max_unique_sources: int
    max_report_words: int
    queries_per_subquestion: int = 3
    results_per_query: int = 5
    sources_per_subquestion: int = 4
    passages_per_source: int = 3
    max_claims_to_verify: int = 60
    verify_batch_size: int = 8
    coverage_threshold: float = 0.6

    @classmethod
    def from_settings(cls, s: Settings) -> "Budget":
        return cls(
            max_search_rounds=s.max_search_rounds,
            max_unique_sources=s.max_unique_sources,
            max_report_words=s.max_report_words,
        )
