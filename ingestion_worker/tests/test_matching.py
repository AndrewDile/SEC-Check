"""Matching, using the same name splitting as the Core API's toWorkerDependency."""

import unittest
from datetime import UTC, datetime

from ingestion_worker.matching import find_matches
from ingestion_worker.models import Dependency
from ingestion_worker.sources.base import SourceEvent


def dependency(name: str, vendor_cik: str | None = None) -> Dependency:
    at = name.index(":") if ":" in name else name.find(" ")
    vendor = (name if at < 0 else name[:at]).strip()
    product = (name if at < 0 else name[at + 1 :]).strip() or vendor
    return Dependency(
        id=name, company_id="default", vendor=vendor, product=product, vendor_cik=vendor_cik
    )


def event(vendor: str, product: str | None = None, cik: str | None = None) -> SourceEvent:
    return SourceEvent(
        external_id="X-1",
        title="title",
        summary="summary",
        source_url="https://example.com/",
        published_at=datetime.now(UTC),
        priority_hint="high",
        vendor=vendor,
        product=product,
        vendor_cik=cik,
    )


def confidence(name: str, vendor: str, product: str | None = None) -> str | None:
    matches = find_matches(event(vendor, product), [dependency(name)]).get("default")
    return matches[0].confidence if matches else None


class KevMatching(unittest.TestCase):
    def test_names_and_confidence(self):
        cases = [
            # name, event vendor, event product, expected confidence
            ("Microsoft Windows", "Microsoft", "Windows", "high"),
            ("Progress MOVEit Transfer", "Progress", "MOVEit Transfer", "high"),
            ("Cisco Systems:IOS", "Cisco", "IOS", "high"),
            ("Palo Alto Networks:PAN-OS", "Palo Alto Networks", "PAN-OS", "high"),
            # the Core API splits this at the first space, so its vendor is "Palo"
            ("Palo Alto Networks PAN-OS", "Palo Alto Networks", "PAN-OS", "high"),
            ("Cisco IOS", "Cisco", "IOS and IOS XE", "medium"),
            ("Cisco Systems IOS", "Cisco", "IOS", "medium"),
            ("Microsoft", "Microsoft", "Multiple Products", "medium"),
            # vendor only
            ("Microsoft", "Microsoft", "Windows", "low"),
            ("Microsoft Corporation", "Microsoft", "Windows", "low"),
            ("Cisco Systems", "Cisco", "IOS", "low"),
            ("Palo Alto Networks", "Palo Alto Networks", "PAN-OS", "low"),
            # product only
            ("Windows", "Microsoft", "Windows", "low"),
            ("MOVEit Transfer", "Progress", "MOVEit Transfer", "low"),
            ("MOVEit", "Progress", "MOVEit Transfer", "low"),
            ("Windows 11", "Microsoft", "Windows", "low"),
            # aliases
            ("IBM WebSphere", "International Business Machines", "WebSphere", "high"),
            ("VMware vCenter", "Broadcom", "vCenter", "high"),
        ]
        for name, vendor, product, expected in cases:
            with self.subTest(name=name, vendor=vendor, product=product):
                self.assertEqual(confidence(name, vendor, product), expected)

    def test_no_match(self):
        cases = [
            ("Microsoft Office", "Microsoft", "Windows"),  # the same vendor's other product
            ("Oracle:Java", "Sun", "Java"),  # it names another vendor
            ("Acme:Windows", "Microsoft", "Windows"),
            ("Linux", "Microsoft", "Windows"),
            ("Server", "Microsoft", "Windows Server"),  # too vague without a vendor
            ("Acme Server", "Other", "Server"),
            ("Platform", "Other", "Platform"),
            ("Windows", "Microsoft", "Multiple Products"),  # no product to compare
        ]
        for name, vendor, product in cases:
            with self.subTest(name=name, vendor=vendor, product=product):
                self.assertIsNone(confidence(name, vendor, product))

    def test_reason_says_the_vendor_was_not_compared(self):
        match = find_matches(event("Microsoft", "Windows"), [dependency("Windows")])["default"][0]
        self.assertIn("vendor wasn't compared", match.reason)

    def test_strongest_match_comes_first(self):
        matches = find_matches(
            event("Microsoft", "Windows"),
            [dependency("Windows"), dependency("Microsoft"), dependency("Microsoft Windows")],
        )["default"]
        self.assertEqual(matches[0].dependency_id, "Microsoft Windows")
        self.assertEqual(matches[0].confidence, "high")
        self.assertEqual({m.confidence for m in matches[1:]}, {"low"})

    def test_groups_by_company(self):
        other = dependency("Microsoft Windows").model_copy(update={"company_id": "other"})
        matches = find_matches(event("Microsoft", "Windows"), [dependency("Windows"), other])
        self.assertEqual(set(matches), {"default", "other"})


class EdgarMatching(unittest.TestCase):
    """EDGAR events name a filing company and no product."""

    def test_names_and_confidence(self):
        cases = [
            ("Microsoft", "MICROSOFT CORP", "medium"),
            ("Microsoft Windows", "MICROSOFT CORP", "medium"),
            ("Oracle:Java", "ORACLE CORP", "medium"),
            ("Palo Alto Networks", "PALO ALTO NETWORKS INC", "medium"),
            ("Palo Alto Networks PAN-OS", "PALO ALTO NETWORKS INC", "medium"),
            ("Google Chrome", "Alphabet Inc.", "medium"),
            ("IBM", "INTERNATIONAL BUSINESS MACHINES CORP", "medium"),
            ("AWS", "AMAZON COM INC", "medium"),
            ("Windows", "MICROSOFT CORP", None),  # nothing names the filer
            ("Acme", "Acme Foods Holdings Worldwide", None),
        ]
        for name, vendor, expected in cases:
            with self.subTest(name=name, vendor=vendor):
                self.assertEqual(confidence(name, vendor), expected)

    def test_cik_match_ignores_leading_zeros(self):
        matches = find_matches(
            event("Renamed Filer Inc", cik="0000318154"),
            [dependency("Amgen", vendor_cik="318154")],
        )
        self.assertEqual(matches["default"][0].confidence, "high")

    def test_empty_vendor_matches_nothing(self):
        self.assertEqual(find_matches(event("---"), [dependency("Acme")]), {})
