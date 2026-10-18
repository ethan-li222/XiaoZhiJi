import re

ALIASES = {
    "ICML": ("ICML", "International Conference on Machine Learning"),
    "NeurIPS": ("NeurIPS", "NIPS", "Neural Information Processing Systems"),
    "ICLR": ("ICLR", "International Conference on Learning Representations"),
    "CVPR": ("CVPR", "Computer Vision and Pattern Recognition"),
    "TPAMI": (
        "TPAMI",
        "TAPMI",
        "IEEE PAMI",
        "Transactions on Pattern Analysis and Machine Intelligence",
    ),
}
PORTALS = {
    "ICML": "https://proceedings.mlr.press/",
    "NeurIPS": "https://papers.nips.cc/",
    "ICLR": "https://openreview.net/group?id=ICLR.cc",
    "CVPR": "https://openaccess.thecvf.com/",
    "TPAMI": "https://www.computer.org/csdl/journal/tp",
    "IEEE": "https://ieeexplore.ieee.org/",
}


def canonical_venue(value):
    for name, aliases in ALIASES.items():
        if any(
            re.search(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", value or "", re.I)
            for alias in aliases
        ):
            return name
    return (value or "").strip()


def venue_metadata(indexed="", claims="", publisher=""):
    venue = canonical_venue(indexed)
    status = "indexed" if indexed else "unknown"
    if not indexed or venue.casefold() in {"arxiv", "arxiv.org", "arxiv (cornell university)"}:
        for name in ALIASES:
            if canonical_venue(claims) == name:
                venue, status = name, "author_claim"
                break
    if re.search(
        r"\bIEEE\b|Institute of Electrical and Electronics Engineers", publisher or "", re.I
    ):
        publisher = "IEEE"
    return {
        "venue": venue or None,
        "venue_status": status,
        "publisher": publisher or None,
        "venue_claim": claims or "",
    }


def matches_venue(paper, venues=None, publisher=None, include_claimed=False):
    requested = [canonical_venue(v) for v in venues or []]
    if requested:
        if paper.venue_status == "unknown" or (
            paper.venue_status == "author_claim" and not include_claimed
        ):
            return False
        if canonical_venue(paper.venue or "").casefold() not in {v.casefold() for v in requested}:
            return False
    return not publisher or publisher.casefold() in (paper.publisher or "").casefold()
