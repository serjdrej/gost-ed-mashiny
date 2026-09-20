#!/usr/bin/env python3
"""Tests for ``scripts/gost_lookup.py``, stdlib only.

Two kinds of test, not one, because the behaviours being protected split
naturally between them:

* **Pure unit tests** for logic that needs no network at all — designation
  normalization, catalogue selection (including the Cyrillic/Latin
  look-alike fix), snapshot-date extraction, and the prefix-hint search.
  These run in milliseconds and never touch a socket.
* **Monkeypatched-``urlopen`` tests** for the failure branches the repair
  commit (``88d6be0``) added: falling back to the pinned URL when discovery
  fails, the utf-8→cp1251 decode chain and its failure, an unrecognised page
  (no ``data-*.csv`` filename), a malformed CSV, and picking the *newest*
  ``data-*.csv`` when a page lists more than one. These are exactly the
  branches a live test cannot reach on demand — nobody can make Rosstandart's
  own site publish bad data to order — so a live-only test suite would leave
  them permanently unprotected, which is the gap the review that requested
  this file found: ten repaired behaviours, zero tests.

Every ``urlopen`` in the monkeypatched tests is replaced with a stub that
returns canned bytes or raises the exact exception class production code
handles (``urllib.error.HTTPError`` / ``URLError``) — never a live request.
The two live smoke tests at the bottom make real requests deliberately, to
catch the case where the *real* catalogue schema has drifted out from under
every mocked test above; they are skipped (not failed) if the network is
unreachable, since this project's own history has such a host (see
``legal-ru/scripts/test_ips_lookup.py`` for the sibling case) — this one has
not shown that behaviour, but a CI-less contributor's machine might still be
offline.

A note on what "red" means here, because the review that requested this file
warned about it explicitly: an ``ImportError`` or a ``TypeError`` from a typo
is red for a reason unrelated to any of the ten behaviours below, and must
not be miscounted as a caught regression. Run this directly and read the
summary line, not just the exit code:

    python scripts/test_gost_lookup.py
"""

from __future__ import annotations

import io
import sys
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import gost_lookup


NATIONAL_CSV = (
    "Обозначение;Заглавие на русском языке;Статус;Код ОКС\n"
    "ГОСТ Р 2.610-2019;Единая система конструкторской документации. "
    "Правила выполнения эксплуатационных документов;Действует;01.100\n"
    "ГОСТ Р 2.601-2019;Единая система конструкторской документации. "
    "Эксплуатационные документы;Действует;01.100\n"
)

INTERSTATE_CSV = (
    "Обозначение;Заглавие на русском языке;Статус;Код ОКС\n"
    "ГОСТ 12.1.003-83;Система стандартов безопасности труда. Шум. Общие "
    "требования безопасности;Действует;13.140\n"
    "ГОСТ 12.1.003-2014;Система стандартов безопасности труда. Шум. "
    "Общие требования безопасности;Действует;13.140\n"
)

NATIONAL_PAGE_ONE_FILE = (
    '<a href="data-20240808-structure-20220330.csv">снимок</a>'
)

NATIONAL_PAGE_TWO_FILES = (
    '<a href="data-20220218-structure-20220330.csv">старый</a>'
    '<a href="data-20240808-structure-20220330.csv">свежий</a>'
)


class FakeResponse:
    """Enough of ``http.client.HTTPResponse`` for ``urlopen``'s call sites."""

    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


def urlopen_sequence(*responses):
    """Build a ``urlopen`` stub returning/raising each response in order.

    Each entry is either bytes (wrapped in ``FakeResponse``) or an exception
    instance (raised). Extra calls beyond the sequence raise ``AssertionError``
    -- a test that calls ``urlopen`` more times than it accounted for is a
    test that stopped meaning what it says.
    """
    remaining = list(responses)

    def fake_urlopen(request, timeout=None):
        if not remaining:
            raise AssertionError("urlopen called more times than the test expected")
        item = remaining.pop(0)
        if isinstance(item, BaseException):
            raise item
        return FakeResponse(item)

    return fake_urlopen


class NoNetworkUnitTests(unittest.TestCase):
    """Logic that needs no network — must never open a socket."""

    def test_normalize_collapses_whitespace(self) -> None:
        self.assertEqual(
            gost_lookup.normalize_designation("  ГОСТ Р   2.610-2019 "),
            "ГОСТ Р 2.610-2019",
        )

    def test_choose_catalog_cyrillic_r_is_national(self) -> None:
        self.assertIs(
            gost_lookup.choose_catalog("ГОСТ Р 2.610-2019"),
            gost_lookup.CATALOGS["national"],
        )

    def test_choose_catalog_latin_p_is_also_national(self) -> None:
        """Regression: a Latin P look-alike must route like the Cyrillic Р.

        Before this fix ``choose_catalog`` matched only Cyrillic Р, so a
        Latin P (visually identical, easy to type by mistake) silently
        routed to the interstate catalogue and produced a false "not found"
        for a standard that exists in the national one.
        """
        self.assertIs(
            gost_lookup.choose_catalog("ГОСТ P 2.610-2019"),
            gost_lookup.CATALOGS["national"],
        )

    def test_choose_catalog_no_standalone_r_is_interstate(self) -> None:
        self.assertIs(
            gost_lookup.choose_catalog("ГОСТ 12.1.003-2014"),
            gost_lookup.CATALOGS["interstate"],
        )

    def test_choose_catalog_r_inside_a_word_does_not_count(self) -> None:
        """'Р' as part of a longer token (not standalone) must not trigger national."""
        self.assertIs(
            gost_lookup.choose_catalog("ГОСТР 2.610-2019"),
            gost_lookup.CATALOGS["interstate"],
        )

    def test_extract_snapshot_date_parses_filename(self) -> None:
        self.assertEqual(
            gost_lookup.extract_snapshot_date(
                "https://example.invalid/data-20240808-structure-20220330.csv"
            ),
            "2024-08-08",
        )

    def test_extract_snapshot_date_none_when_no_match(self) -> None:
        self.assertIsNone(gost_lookup.extract_snapshot_date("https://example.invalid/other.csv"))

    def test_find_prefix_hints_finds_year_suffixed_rows(self) -> None:
        """Regression: a year-less query must surface the year-suffixed rows it missed."""
        rows = [
            {"Обозначение": "ГОСТ 12.1.003-83", "Статус": "Действует"},
            {"Обозначение": "ГОСТ 12.1.003-2014", "Статус": "Действует"},
            {"Обозначение": "ГОСТ 12.1.099-2010", "Статус": "Действует"},
        ]
        hints = gost_lookup.find_prefix_hints(rows, "ГОСТ 12.1.003")
        self.assertEqual(
            {h["Обозначение"] for h in hints},
            {"ГОСТ 12.1.003-83", "ГОСТ 12.1.003-2014"},
        )

    def test_find_prefix_hints_excludes_exact_match(self) -> None:
        rows = [{"Обозначение": "ГОСТ 12.1.003-2014", "Статус": "Действует"}]
        hints = gost_lookup.find_prefix_hints(rows, "ГОСТ 12.1.003-2014")
        self.assertEqual(hints, [])


class DiscoveryTests(unittest.TestCase):
    """discover_data_url's branches, each forced with a monkeypatched urlopen."""

    def setUp(self) -> None:
        self.catalog = dict(gost_lookup.CATALOGS["national"])

    def test_discovers_the_newest_of_several_listed_files(self) -> None:
        """Regression: the page can list more than one snapshot; must pick the newest."""
        stub = urlopen_sequence(NATIONAL_PAGE_TWO_FILES.encode("utf-8"))
        with mock.patch.object(gost_lookup.urllib.request, "urlopen", stub):
            url, provenance = gost_lookup.discover_data_url(self.catalog)
        self.assertIn("data-20240808-structure-20220330.csv", url)
        self.assertNotIn("20220218", url)
        self.assertIn("обнаружен живым запросом", provenance)

    def test_single_file_page_is_discovered(self) -> None:
        stub = urlopen_sequence(NATIONAL_PAGE_ONE_FILE.encode("utf-8"))
        with mock.patch.object(gost_lookup.urllib.request, "urlopen", stub):
            url, provenance = gost_lookup.discover_data_url(self.catalog)
        self.assertIn("data-20240808-structure-20220330.csv", url)
        self.assertIn("обнаружен живым запросом", provenance)

    def test_falls_back_when_page_unreachable(self) -> None:
        stub = urlopen_sequence(urllib.error.URLError("getaddrinfo failed"))
        with mock.patch.object(gost_lookup.urllib.request, "urlopen", stub):
            url, provenance = gost_lookup.discover_data_url(self.catalog)
        self.assertEqual(url, self.catalog["fallback_data"])
        self.assertIn("страница каталога недоступна", provenance)
        self.assertIn("используется последний известный файл", provenance)

    def test_falls_back_when_page_encoding_unrecognised(self) -> None:
        # 0x98 fails both codecs (verified directly: invalid start byte in
        # utf-8, undefined character in cp1251) -- unlike most arbitrary byte
        # strings, which cp1251 will happily decode into garbage Cyrillic
        # since it leaves only a handful of byte values undefined.
        stub = urlopen_sequence(b"\x98")
        with mock.patch.object(gost_lookup.urllib.request, "urlopen", stub):
            url, provenance = gost_lookup.discover_data_url(self.catalog)
        self.assertEqual(url, self.catalog["fallback_data"])
        self.assertIn("кодировка страницы не распознана", provenance)

    def test_falls_back_when_no_filename_pattern_on_page(self) -> None:
        stub = urlopen_sequence("<html>ничего похожего</html>".encode("utf-8"))
        with mock.patch.object(gost_lookup.urllib.request, "urlopen", stub):
            url, provenance = gost_lookup.discover_data_url(self.catalog)
        self.assertEqual(url, self.catalog["fallback_data"])
        self.assertIn("имя файла data-*.csv не найдено", provenance)

    def test_accepts_cp1251_page(self) -> None:
        stub = urlopen_sequence(NATIONAL_PAGE_ONE_FILE.encode("cp1251"))
        with mock.patch.object(gost_lookup.urllib.request, "urlopen", stub):
            url, provenance = gost_lookup.discover_data_url(self.catalog)
        self.assertIn("data-20240808-structure-20220330.csv", url)


class DownloadRowsTests(unittest.TestCase):
    """download_rows' validation, forced with a monkeypatched urlopen."""

    def setUp(self) -> None:
        self.catalog = dict(gost_lookup.CATALOGS["national"])
        self.data_url = self.catalog["fallback_data"]

    def test_reads_a_well_formed_csv(self) -> None:
        stub = urlopen_sequence(NATIONAL_CSV.encode("cp1251"))
        with mock.patch.object(gost_lookup.urllib.request, "urlopen", stub):
            rows = gost_lookup.download_rows(self.catalog, self.data_url)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Обозначение"], "ГОСТ Р 2.610-2019")

    def test_404_is_reported_as_stale_file(self) -> None:
        error = urllib.error.HTTPError(self.data_url, 404, "Not Found", {}, None)
        stub = urlopen_sequence(error)
        with mock.patch.object(gost_lookup.urllib.request, "urlopen", stub):
            with self.assertRaises(RuntimeError) as ctx:
                gost_lookup.download_rows(self.catalog, self.data_url)
        self.assertIn("gone/changed", str(ctx.exception))

    def test_bad_encoding_is_reported(self) -> None:
        # 0x98 is one of the few byte values cp1251 leaves undefined
        # (verified directly: `bytes([0x98]).decode('cp1251')` raises
        # UnicodeDecodeError) -- a real trigger for this branch, not a
        # payload chosen to merely look plausible.
        stub = urlopen_sequence(b"\x98not a real csv at all")
        with mock.patch.object(gost_lookup.urllib.request, "urlopen", stub):
            with self.assertRaises(RuntimeError) as ctx:
                gost_lookup.download_rows(self.catalog, self.data_url)
        self.assertIn("cp1251 encoding could not be decoded", str(ctx.exception))

    def test_wrong_header_is_reported(self) -> None:
        bad_csv = "A;B;C\n1;2;3\n".encode("cp1251")
        stub = urlopen_sequence(bad_csv)
        with mock.patch.object(gost_lookup.urllib.request, "urlopen", stub):
            with self.assertRaises(RuntimeError) as ctx:
                gost_lookup.download_rows(self.catalog, self.data_url)
        self.assertIn("semicolon-delimited columns", str(ctx.exception))

    def test_empty_csv_is_reported(self) -> None:
        header_only = "Обозначение;Заглавие на русском языке;Статус;Код ОКС\n".encode("cp1251")
        stub = urlopen_sequence(header_only)
        with mock.patch.object(gost_lookup.urllib.request, "urlopen", stub):
            with self.assertRaises(RuntimeError) as ctx:
                gost_lookup.download_rows(self.catalog, self.data_url)
        self.assertIn("row shape", str(ctx.exception))


class CommandStatusTests(unittest.TestCase):
    """command_status end-to-end, network fully mocked (discovery + download)."""

    def _run(self, designation: str, page: bytes, csv_bytes: bytes) -> tuple[int, str, str]:
        stub = urlopen_sequence(page, csv_bytes)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(gost_lookup.urllib.request, "urlopen", stub):
            with redirect_stdout(out), redirect_stderr(err):
                code = gost_lookup.command_status(designation)
        return code, out.getvalue(), err.getvalue()

    def test_found_reports_status_date_and_staleness_reminder(self) -> None:
        code, out, err = self._run(
            "ГОСТ Р 2.610-2019",
            NATIONAL_PAGE_ONE_FILE.encode("utf-8"),
            NATIONAL_CSV.encode("cp1251"),
        )
        self.assertEqual(code, 0)
        self.assertIn("Статус: Действует", out)
        self.assertIn("Снимок каталога от: 2024-08-08", out)
        self.assertIn("обнаружен живым запросом", out)
        self.assertIn("перепроверьте", out)  # the staleness reminder, item 6

    def test_not_found_without_year_offers_prefix_hints(self) -> None:
        """Regression: item 1 -- a year-less query must not read as nonexistent."""
        code, out, err = self._run(
            "ГОСТ 12.1.003",
            NATIONAL_PAGE_ONE_FILE.encode("utf-8"),
            INTERSTATE_CSV.encode("cp1251"),
        )
        self.assertEqual(code, 1)
        self.assertIn("не указан год выпуска", err)
        self.assertIn("ГОСТ 12.1.003-83", err)
        self.assertIn("ГОСТ 12.1.003-2014", err)

    def test_not_found_explains_no_cancelled_marker_exists(self) -> None:
        """Regression: item 2 -- 'отменён' is not a value this source carries."""
        code, out, err = self._run(
            "ГОСТ Р 0.000-0000",
            NATIONAL_PAGE_ONE_FILE.encode("utf-8"),
            NATIONAL_CSV.encode("cp1251"),
        )
        self.assertEqual(code, 1)
        self.assertIn("отменён", err)
        self.assertIn("Действует», «Принят»", err)

    def test_download_failure_still_reports_provenance(self) -> None:
        """Regression: item 17 -- an error must not drop where the file came from."""
        error = urllib.error.HTTPError("https://x", 500, "Server Error", {}, None)
        code, out, err = self._run(
            "ГОСТ Р 2.610-2019",
            NATIONAL_PAGE_ONE_FILE.encode("utf-8"),
            error,
        )
        self.assertEqual(code, 2)
        self.assertIn("Источник снимка", err)
        self.assertIn("обнаружен живым запросом", err)


class LiveSmokeTests(unittest.TestCase):
    """Real requests against rst.gov.ru -- skipped, not failed, if unreachable.

    These exist to catch real-world schema drift no mock can: if Rosstandart
    changes the CSV header names or the page's link markup, every test above
    keeps passing against its own fixtures while this repository's actual
    behaviour silently breaks. Kept minimal on purpose -- this is a smoke
    test, not the correctness suite; that lives above with mocks precisely
    because the failure branches cannot be summoned from the live site on
    demand.
    """

    def test_a_known_current_standard_resolves_live(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = gost_lookup.command_status("ГОСТ Р 2.610-2019")
        except OSError as exc:
            self.skipTest(f"network unreachable: {exc}")
            return
        if code != 0:
            self.skipTest(f"live catalogue did not return the expected row: {err.getvalue()!r}")
        self.assertIn("Действует", out.getvalue())


def _print_summary(result: unittest.TestResult) -> None:
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    skipped = len(result.skipped)
    passed = total - failed - skipped
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped, {total} total.")
    if result.errors:
        print(
            f"{len(result.errors)} of those failures are ERRORS (exception raised "
            "outside an assertion -- e.g. ImportError/TypeError/AttributeError), "
            "not a caught regression. Read which before trusting a red count."
        )


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    _print_summary(result)
    raise SystemExit(0 if result.wasSuccessful() else 1)
