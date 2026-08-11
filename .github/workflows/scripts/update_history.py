#!/usr/bin/env python3

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "history.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SuperCombinazioniArchive/1.0)"
}

IT_MONTHS = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}


def get_page(url):
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def parse_official_month(year, month_name):
    url = f"https://www.superenalotto.it/archivio-estrazioni/{year}/{month_name}"

    try:
        html = get_page(url)
    except Exception:
        return []

    soup = BeautifulSoup(html, "html.parser")
    rows = []

    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")

        if len(tds) < 2:
            continue

        first = tds[0].get_text(" ", strip=True)

        match = re.search(
            r"Concorso\s*N[º°o]?\s*(\d+)\s+del\s+(\d{1,2})\s+([A-Za-zÀ-ÿ]+)\s+(\d{4})",
            first,
            re.I,
        )

        if not match:
            continue

        contest = int(match.group(1))
        day = int(match.group(2))
        month = IT_MONTHS.get(match.group(3).lower())
        draw_year = int(match.group(4))

        if not month:
            continue

        numbers = [
            int(x)
            for x in re.findall(
                r"\b\d{1,2}\b",
                tds[1].get_text(" ", strip=True),
            )
        ]

        if len(numbers) < 6:
            continue

        combo = numbers[:6]

        if len(set(combo)) != 6:
            continue

        if not all(1 <= n <= 90 for n in combo):
            continue

        jolly = None
        superstar = None

        if len(tds) >= 3:
            values = re.findall(
                r"\b\d{1,2}\b",
                tds[2].get_text(" ", strip=True),
            )
            if values:
                jolly = int(values[0])

        if len(tds) >= 4:
            values = re.findall(
                r"\b\d{1,2}\b",
                tds[3].get_text(" ", strip=True),
            )
            if values:
                superstar = int(values[0])

        rows.append(
            {
                "date": f"{draw_year:04d}-{month:02d}-{day:02d}",
                "contest": contest,
                "combo": sorted(combo),
                "jolly": jolly,
                "superstar": superstar,
                "source": "superenalotto.it",
            }
        )

    return rows


def validate(rows):
    good = []
    seen = set()

    for row in rows:
        combo = row.get("combo", [])

        if len(combo) != 6:
            continue

        if len(set(combo)) != 6:
            continue

        if not all(isinstance(n, int) and 1 <= n <= 90 for n in combo):
            continue

        key = (row["date"], tuple(combo))

        if key in seen:
            continue

        seen.add(key)
        good.append(row)

    return sorted(good, key=lambda x: x["date"])


def load_existing():
    if not OUT.exists():
        return []

    try:
        data = json.loads(OUT.read_text(encoding="utf-8"))
        return data.get("draws", [])
    except Exception:
        return []


def fetch_year(year):
    rows = []

    for month_name in IT_MONTHS:
        month_rows = parse_official_month(year, month_name)

        if month_rows:
            print(year, month_name, len(month_rows))

        rows.extend(month_rows)

        time.sleep(0.10)

    return validate(rows)


def main():
    now = datetime.now()
    full_rebuild = "--full" in sys.argv

    existing = load_existing()

    if not existing or full_rebuild:
        years = range(1997, now.year + 1)
        all_rows = []
    else:
        years = [now.year]
        all_rows = [
            row
            for row in existing
            if not row["date"].startswith(str(now.year))
        ]

    for year in years:
        rows = fetch_year(year)
        print("Anno", year, "estrazioni", len(rows))
        all_rows.extend(rows)

    all_rows = validate(all_rows)

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(all_rows),
        "first_date": all_rows[0]["date"] if all_rows else None,
        "last_date": all_rows[-1]["date"] if all_rows else None,
        "source": "superenalotto.it",
    }

    OUT.write_text(
        json.dumps(
            {
                "meta": meta,
                "draws": all_rows,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    print("Salvate", len(all_rows), "estrazioni in", OUT)


if __name__ == "__main__":
    main()
