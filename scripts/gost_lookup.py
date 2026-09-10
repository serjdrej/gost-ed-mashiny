"""Lookup current catalogue status for GOST standards used by this skill.

The ``status`` command normalizes whitespace in the designation.  A
designation containing the standalone letter ``Р`` (for example,
``ГОСТ Р 2.610-2019``) uses the national-standards catalogue; every other
designation uses the interstate-standards catalogue.  The two catalogue URLs
are deliberately pinned: if Rosstandart republishes the file under a new
name, this program fails explicitly instead of guessing a replacement.
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
        "data": (
            "https://www.rst.gov.ru/opendata/7706406291-nationalstandards/"
            "data-20240808-structure-20220330.csv"
        ),
    },
    "interstate": {
        "name": "Каталог межгосударственных стандартов (библиография)",
        "page": "https://www.rst.gov.ru/opendata/7706406291-interstatestandards",
        "data": (
            "https://www.rst.gov.ru/opendata/7706406291-interstatestandards/"
            "data-20240808-structure-20220330.csv"
        ),
    },
}

TRTS_ROUTE = "https://eec.eaeunion.org/comission/department/deptexreg/tr/TR_general.php"


def normalize_designation(value: str) -> str:
    """Trim a designation and replace every run of whitespace with one space."""
    return " ".join(value.split())


def choose_catalog(designation: str) -> dict[str, str]:
    """Choose the national catalogue only for a standalone Cyrillic Р token."""
    if re.search(r"(?:^|\s)Р(?:\s|$)", designation.upper()):
        return CATALOGS["national"]
    return CATALOGS["interstate"]


def stale_file_error(catalog: dict[str, str]) -> str:
    return (
        f"Expected file at {catalog['data']} is gone/changed — check "
        f"{catalog['page']} for the current filename."
    )


def download_rows(catalog: dict[str, str]) -> list[dict[str, str]]:
    """Download and validate a pinned Rosstandart CSV before reading it."""
    request = urllib.request.Request(
        catalog["data"], headers={"User-Agent": "gost-ed-mashiny-gost-lookup/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(stale_file_error(catalog)) from exc
        raise RuntimeError(
            f"Could not download {catalog['data']}: HTTP {exc.code}. No status was produced."
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not download {catalog['data']}: {exc.reason}. No status was produced."
        ) from exc

    try:
        text = payload.decode("cp1251")
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            f"{stale_file_error(catalog)} Expected cp1251 encoding could not be decoded."
        ) from exc

    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    if tuple(reader.fieldnames or ()) != EXPECTED_HEADERS:
        raise RuntimeError(
            f"{stale_file_error(catalog)} Expected semicolon-delimited columns: "
            f"{', '.join(EXPECTED_HEADERS)}."
        )

    rows = list(reader)
    if not rows or any(set(row) != set(EXPECTED_HEADERS) for row in rows):
        raise RuntimeError(
            f"{stale_file_error(catalog)} The CSV row shape does not match the expected columns."
        )
    return rows


def command_status(designation: str) -> int:
    designation = normalize_designation(designation)
    catalog = choose_catalog(designation)
    try:
        rows = download_rows(catalog)
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
        return 1

    print(f"Каталог: {catalog['name']}")
    print(f"Обозначение: {result['Обозначение']}")
    print(f"Заглавие на русском языке: {result['Заглавие на русском языке']}")
    print(f"Статус: {result['Статус']}")
    print(f"Код ОКС: {result['Код ОКС']}")
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
            "остальные — межгосударственный."
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
