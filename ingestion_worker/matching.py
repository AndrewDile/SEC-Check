"""Decide which company dependencies a source event may affect.

Matching is by name, because KEV and EDGAR only give vendor and product names (and,
for EDGAR, the filer's CIK). Versions are not compared, because KEV has no version
data. The team that claims an incident checks whether their version is affected.

A dependency is one free-text name, and the Core API guesses where its vendor ends unless
the name says "vendor:product". So the rules here also compare the whole name.
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

# A vendor's other names, so that an SEC filer's legal name matches the name in KEV or a dependency.
_VENDOR_ALIASES = {
    "alphabet": "google",
    "amazon com": "amazon",
    "amazon web services": "amazon",
    "aws": "amazon",
    "facebook": "meta",
    "meta platforms": "meta",
    "hewlett packard enterprise": "hpe",
    "international business machines": "ibm",
    "vmware": "broadcom",
}

# Product names too vague to match without a vendor.
_GENERIC_WORDS = {
    "agent",
    "app",
    "application",
    "applications",
    "client",
    "cloud",
    "console",
    "core",
    "enterprise",
    "management",
    "manager",
    "multiple",
    "platform",
    "products",
    "server",
    "service",
    "services",
    "software",
    "suite",
    "system",
    "systems",
    "the",
    "web",
}

_CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}


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
    # The Core API shows the first match as the incident's dependency, so put the strongest first.
    for company_matches in matches.values():
        company_matches.sort(key=lambda match: _CONFIDENCE_ORDER[match.confidence])
    return matches


def _match(event: SourceEvent, dependency: Dependency) -> tuple[Confidence, str] | None:
    """Return (confidence, reason) if `event` may affect `dependency`, otherwise None."""
    event_cik, dependency_cik = event.vendor_cik, dependency.vendor_cik
    if event_cik and dependency_cik and event_cik.lstrip("0") == dependency_cik.lstrip("0"):
        return "high", "the vendor itself filed this report"

    event_vendor = _vendor_words(event.vendor)
    product = _product_of_vendor(dependency, event_vendor) if event_vendor else None
    if product is None:
        return _match_product_only(event, dependency)

    if event.product is None:
        return "medium", "vendor name matches"
    event_product = _words(event.product)
    if event_product == ["multiple", "products"]:
        return "medium", "vendor name matches; the source lists multiple affected products"
    if not product:
        return "low", "vendor name matches; the dependency doesn't name a product"
    if event_product == product:
        return "high", "vendor and product names match"
    if _contains(event_product, product) or _contains(product, event_product):
        return "medium", "vendor name matches and product names overlap"
    return None


def _product_of_vendor(dependency: Dependency, event_vendor: list[str]) -> list[str] | None:
    """The dependency's product words if `event_vendor` makes it, otherwise None.

    An empty list means the dependency names only the vendor.
    """
    name = _name_words(dependency)
    if _strip_vendor_suffixes(name) == event_vendor:
        return []
    if _vendor_words(dependency.vendor) == event_vendor:
        return _words(dependency.product)
    # The guessed split can be wrong: "Palo Alto Networks PAN-OS" has the vendor "Palo".
    if name[: len(event_vendor)] == event_vendor:
        return name[len(event_vendor) :]
    return None


def _match_product_only(
    event: SourceEvent, dependency: Dependency
) -> tuple[Confidence, str] | None:
    """Match on the whole name alone, for names like "Windows" or "MOVEit Transfer".

    Using the whole name means that a dependency naming another vendor ("Acme:Windows")
    doesn't match here.
    """
    if event.product is None:
        return None
    name, event_product = _name_words(dependency), _words(event.product)
    if _is_generic(name) or _is_generic(event_product):
        return None
    if name == event_product:
        return "low", "product name matches; the vendor wasn't compared"
    # "MOVEit" in "MOVEit Transfer", and "Windows" at the start of "Windows 11"
    if _contains(event_product, name) or name[: len(event_product)] == event_product:
        return "low", "product names overlap; the vendor wasn't compared"
    return None


def _words(name: str) -> list[str]:
    """'MOVEit Transfer' -> ['moveit', 'transfer']"""
    return re.findall(r"[a-z0-9]+", name.lower())


def _name_words(dependency: Dependency) -> list[str]:
    """The dependency's whole name. The Core API repeats a single word as vendor and product."""
    vendor, product = _words(dependency.vendor), _words(dependency.product)
    return vendor if vendor == product else vendor + product


def _vendor_words(name: str) -> list[str]:
    """'Cisco Systems, Inc.' -> ['cisco']"""
    return _strip_vendor_suffixes(_words(name))


def _strip_vendor_suffixes(words: list[str]) -> list[str]:
    words = list(words)
    while len(words) > 1 and words[-1] in _VENDOR_SUFFIXES:
        words.pop()
    alias = _VENDOR_ALIASES.get(" ".join(words))
    return [alias] if alias else words


def _is_generic(words: list[str]) -> bool:
    return all(word in _GENERIC_WORDS for word in words)


def _contains(words: list[str], phrase: list[str]) -> bool:
    """True if `phrase` appears in `words` as consecutive words."""
    n = len(phrase)
    return n > 0 and any(words[i : i + n] == phrase for i in range(len(words) - n + 1))
