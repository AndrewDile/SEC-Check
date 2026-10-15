"""Decide which company dependencies a source event may affect.

Matching is by name, because KEV and EDGAR only give vendor and product names (and,
for EDGAR, the filer's CIK). Versions are not compared, because KEV has no version
data. The team that claims an incident checks whether their version is affected.
"""

import re
from collections import defaultdict

from ingestion_worker.models import Confidence, Dependency, MatchedDependency
from ingestion_worker.sources.base import SourceEvent

# Words dropped from the end of vendor names, so that "Cisco Systems, Inc." matches "Cisco".
_VENDOR_SUFFIXES = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "llc",
    "ltd",
    "limited",
    "plc",
    "holdings",
    "group",
    "software",
    "technologies",
    "technology",
    "systems",
}


def find_matches(
    event: SourceEvent, dependencies: list[Dependency]
) -> dict[str, list[MatchedDependency]]:
    """Return the dependencies `event` may affect, grouped by company_id."""
    matches: dict[str, list[MatchedDependency]] = defaultdict(list)
    for dependency in dependencies:
        result = _match(event, dependency)
        if result is None:
            continue
        confidence, reason = result
        matches[dependency.company_id].append(
            MatchedDependency(
                dependency_id=dependency.id,
                vendor=dependency.vendor,
                product=dependency.product,
                version=dependency.version,
                confidence=confidence,
                reason=reason,
            )
        )
    return matches


def _match(event: SourceEvent, dependency: Dependency) -> tuple[Confidence, str] | None:
    """Return (confidence, reason) if `event` may affect `dependency`, otherwise None."""
    event_cik, dependency_cik = event.vendor_cik, dependency.vendor_cik
    if event_cik and dependency_cik and event_cik.lstrip("0") == dependency_cik.lstrip("0"):
        return "high", "the vendor itself filed this report"

    vendor = _vendor_words(dependency.vendor)
    if not vendor or vendor != _vendor_words(event.vendor):
        return None
    if event.product is None:
        return "medium", "vendor name matches"

    event_product, dependency_product = _words(event.product), _words(dependency.product)
    if event_product == dependency_product:
        return "high", "vendor and product names match"
    if event_product == ["multiple", "products"]:
        return "medium", "vendor name matches; the source lists multiple affected products"
    if _contains(event_product, dependency_product) or _contains(dependency_product, event_product):
        return "medium", "vendor name matches and product names overlap"
    return None


def _words(name: str) -> list[str]:
    """'MOVEit Transfer' -> ['moveit', 'transfer']"""
    return re.findall(r"[a-z0-9]+", name.lower())


def _vendor_words(name: str) -> list[str]:
    """'Cisco Systems, Inc.' -> ['cisco']"""
    words = _words(name)
    while len(words) > 1 and words[-1] in _VENDOR_SUFFIXES:
        words.pop()
    return words


def _contains(words: list[str], phrase: list[str]) -> bool:
    """True if `phrase` appears in `words` as consecutive words."""
    n = len(phrase)
    return n > 0 and any(words[i : i + n] == phrase for i in range(len(words) - n + 1))
