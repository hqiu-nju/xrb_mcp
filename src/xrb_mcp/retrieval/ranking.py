from collections import defaultdict
from collections.abc import Hashable, Sequence


def reciprocal_rank_fusion(*rankings: Sequence[Hashable], k: int = 60) -> dict:
    scores: dict = defaultdict(float)
    for ranking in rankings:
        for rank, identifier in enumerate(dict.fromkeys(ranking), start=1):
            scores[identifier] += 1.0 / (k + rank)
    return dict(scores)
