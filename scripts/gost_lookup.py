"""Lookup current catalogue status for GOST standards used by this skill.

The ``status`` command normalizes whitespace in the designation.  A
designation containing the standalone letter ``Р`` (for example,
``ГОСТ Р 2.610-2019``) uses the national-standards catalogue; every other
designation uses the interstate-standards catalogue.

Each catalogue's open-data page (``CATALOGS[*]["page"]``) is fetched first to
discover the CSV filename Rosstandart currently publishes -- filenames are
dated (``data-YYYYMMDD-structure-YYYYMMDD.csv``) and change when Rosstandart
republishes. If discovery fails for any reason (network error, page moved,
pattern not found), this falls back to the last-known filename pinned in
``CATALOGS[*]["fallback_data"]`` -- itself downloaded and validated the same
way, never assumed fresh. Every ``status`` result reports which file was
actually read and its snapshot date, extracted from the filename, so a
"not found" or a stale "Действует" can be told apart from a genuinely current
answer instead of being silently indistinguishable from one.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import urllib.error
import urllib.request


EXPECTED_HEADERS = (
    "Обозначение",
    "Заглавие на русском языке",
    "Статус",
    "Код ОКС",
)

CATALOGS = {
    "national": {
        "name": "Каталог национальных стандартов (библиография)",
        "page": "https://www.rst.gov.ru/opendata/7706406291-nationalstandards",
        # Last-known filename, used only if live discovery (see
        # discover_data_url) fails. Confirmed current as of 2026-09-10;
        # do not treat this date as current without checking discovery's
        # own provenance line in the command's output.
        "fallback_data": (
            "https://www.rst.gov.ru/opendata/7706406291-nationalstandards/"
            "data-20240808-structure-20220330.csv"
        ),
    },
    "interstate": {
        "name": "Каталог межгосударственных стандартов (библиография)",
        "page": "https://www.rst.gov.ru/opendata/7706406291-interstatestandards",
        "fallback_data": (
            "https://www.rst.gov.ru/opendata/7706406291-interstatestandards/"
            "data-20240808-structure-20220330.csv"
        ),
    },
}

TRTS_ROUTE = "https://eec.eaeunion.org/comission/department/deptexreg/tr/TR_general.php"

DATA_FILENAME_RE = re.compile(r"data-(\d{8})-structure-(\d{8})\.csv")


def normalize_designation(value: str) -> str:
    """Trim a designation and replace every run of whitespace with one space."""
    return " ".join(value.split())


def choose_catalog(designation: str) -> dict[str, str]:
    """Choose the national catalogue only for a standalone Cyrillic Р token."""
    if re.search(r"(?:^|\s)Р(?:\s|$)", designation.upper()):
        return CATALOGS["national"]
    return CATALOGS["interstate"]


def discover_data_url(catalog: dict[str, str]) -> tuple[str, str]:
    """Find the CSV file the catalogue's open-data page currently publishes.

    Returns (url, provenance). provenance always says plainly whether the
    URL was discovered live or is the pinned fallback, and why -- this text
    is surfaced to the user, not just logged. Never raises: a discovery
    failure here just means falling back to the pinned URL, which
    download_rows still downloads and validates on its own before anything
    is trusted.
    """
    request = urllib.request.Request(
        catalog["page"], headers={"User-Agent": "gost-ed-mashiny-gost-lookup/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            page_bytes = response.read()
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        return (
            catalog["fallback_data"],
            f"обнаружить свежий снимок не удалось (страница каталога недоступна: {exc}) — используется последний известный файл",
        )

    page_text = None
    for encoding in ("utf-8", "cp1251"):
        try:
            page_text = page_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if page_text is None:
        return (
            catalog["fallback_data"],
            "обнаружить свежий снимок не удалось (кодировка страницы не распознана) — используется последний известный файл",
        )

    match = DATA_FILENAME_RE.search(page_text)
    if not match:
        return (
            catalog["fallback_data"],
            "обнаружить свежий снимок не удалось (имя файла data-*.csv не найдено на странице) — используется последний известный файл",
        )

    discovered_url = f"{catalog['page'].rstrip('/')}/{match.group(0)}"
    return discovered_url, "снимок обнаружен живым запросом к странице открытых данных"


def extract_snapshot_date(url: str) -> str | None:
    """Pull the data-date half of data-YYYYMMDD-structure-YYYYMMDD.csv from a URL."""
    match = DATA_FILENAME_RE.search(url)
    if not match:
        return None
    raw = match.group(1)
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"


def stale_file_error(data_url: str, catalog: dict[str, str]) -> str:
    return (
        f"Expected file at {data_url} is gone/changed — check "
        f"{catalog['page']} for the current filename."
    )


def download_rows(catalog: dict[str, str], data_url: str) -> list[dict[str, str]]:
    """Download and validate a resolved Rosstandart CSV before reading it."""
    request = urllib.request.Request(
        data_url, headers={"User-Agent": "gost-ed-mashiny-gost-lookup/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(stale_file_error(data_url, catalog)) from exc
        raise RuntimeError(
            f"Could not download {data_url}: HTTP {exc.code}. No status was produced."
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not download {data_url}: {exc.reason}. No status was produced."
        ) from exc

    try:
        text = payload.decode("cp1251")
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            f"{stale_file_error(data_url, catalog)} Expected cp1251 encoding could not be decoded."
        ) from exc

    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    if tuple(reader.fieldnames or ()) != EXPECTED_HEADERS:
        raise RuntimeError(
            f"{stale_file_error(data_url, catalog)} Expected semicolon-delimited columns: "
            f"{', '.join(EXPECTED_HEADERS)}."
        )

    rows = list(reader)
    if not rows or any(set(row) != set(EXPECTED_HEADERS) for row in rows):
        raise RuntimeError(
            f"{stale_file_error(data_url, catalog)} The CSV row shape does not match the expected columns."
        )
    return rows


def command_status(designation: str) -> int:
    designation = normalize_designation(designation)
    catalog = choose_catalog(designation)
    data_url, provenance = discover_data_url(catalog)
    snapshot_date = extract_snapshot_date(data_url) or "не удалось извлечь дату из имени файла"

    try:
        rows = download_rows(catalog, data_url)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    result = next(
        (row for row in rows if normalize_designation(row["Обозначение"]) == designation),
        None,
    )
    if result is None:
        print(
            f"Designation {designation!r} was not found in "
            f"{catalog['name']} ({catalog['page']}).",
            file=sys.stderr,
        )
        print(
            f"Проверено по снимку от {snapshot_date} ({provenance}): {data_url}. "
            "«Не найдено» означает «нет в этом снимке» — стандарт мог появиться "
            "или, наоборот, быть отменён позже даты снимка; не считать это "
            "равнозначным «такого стандарта не существует».",
            file=sys.stderr,
        )
        return 1

    print(f"Каталог: {catalog['name']}")
    print(f"Обозначение: {result['Обозначение']}")
    print(f"Заглавие на русском языке: {result['Заглавие на русском языке']}")
    print(f"Статус: {result['Статус']}")
    print(f"Код ОКС: {result['Код ОКС']}")
    print(f"Снимок каталога от: {snapshot_date} ({provenance})")
    print(f"Проверить самостоятельно: {data_url}")
    return 0


def command_trts_route() -> int:
    print(TRTS_ROUTE)
    print("Откройте перечень, найдите «О безопасности машин и оборудования (ТР ТС 010/2011)» и перейдите по его ссылке к действующему тексту.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Проверяет статус ГОСТ в открытых каталогах Росстандарта или выводит "
            "маршрут к ТР ТС 010/2011. Для status пробелы нормализуются; "
            "обозначение с отдельной буквой «Р» выбирает национальный каталог, "
            "остальные — межгосударственный. Перед чтением скрипт пытается "
            "обнаружить свежий снимок каталога живым запросом; при неудаче "
            "падает на последний известный файл — и то, и другое видно в выводе."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("status", help="найти статус ГОСТ в каталоге Росстандарта")
    status.add_argument("designation", help="например: ГОСТ Р 2.610-2019 или ГОСТ Р 2.601-2019")
    subparsers.add_parser("trts-route", help="вывести официальный маршрут к ТР ТС 010/2011")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "status":
        return command_status(args.designation)
    return command_trts_route()


if __name__ == "__main__":
    raise SystemExit(main())
