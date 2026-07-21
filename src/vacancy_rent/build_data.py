"""Fetch Apartment List rent + vacancy CSVs and join them into one dataset.

Apartment List publishes monthly rent estimates and a monthly vacancy index as
separate CSVs, at national/state/metro/county/city level, back to Jan 2017.
Nobody publishes them joined. This does that.

Usage:
    uv run build-data            # fetch, join, write web/data.json and site/index.html
    uv run build-data --offline  # reuse whatever is already in data/raw/
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
WEB = ROOT / "web"
SITE = ROOT / "site"

INDEX_URL = "https://www.apartmentlist.com/research/category/data-rent-estimates"
CSV_RE = re.compile(r"//assets\.ctfassets\.net/[^\"'\s]+?\.csv")
BEDS = ("overall", "1br", "2br")


def discover_csv_urls() -> dict[str, str]:
    """Scrape the download page for the current month's asset URLs.

    Apartment List rotates the Contentful asset hash every month, so the URLs
    cannot be hardcoded.
    """
    html = requests.get(INDEX_URL, timeout=60).text
    urls = {}
    for path in CSV_RE.findall(html):
        url = "https:" + path
        name = url.rsplit("/", 1)[-1]
        if "Rent_Estimates" in name and "Summary" not in name:
            urls["rent"] = url
        elif "Vacancy_Index" in name:
            urls["vacancy"] = url
    missing = {"rent", "vacancy"} - urls.keys()
    if missing:
        raise RuntimeError(f"could not find CSV links for: {sorted(missing)}")
    return urls


def download(urls: dict[str, str]) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for key, url in urls.items():
        dest = RAW / f"{key}.csv"
        print(f"  {key:8s} <- {url.rsplit('/', 1)[-1]}", file=sys.stderr)
        dest.write_bytes(requests.get(url, timeout=180).content)


def month_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if len(c) == 7 and c[:4].isdigit() and c[4] == "_"]


def build() -> dict:
    rent = pd.read_csv(RAW / "rent.csv")
    vac = pd.read_csv(RAW / "vacancy.csv")

    months = month_columns(vac)
    rent_months = month_columns(rent)
    if months != rent_months:
        # Keep only months present in both, in order.
        months = [m for m in rent_months if m in set(months)]

    key = ["location_name", "location_type"]
    vac_ix = vac.drop_duplicates(key).set_index(key)
    rent_ix = {
        bed: rent[rent.bed_size == bed].drop_duplicates(key).set_index(key)
        for bed in BEDS
    }

    geos = []
    for loc in vac_ix.index:
        if loc not in rent_ix["overall"].index:
            continue
        vrow = vac_ix.loc[loc]
        # vacancy index is a fraction; store as basis points to keep JSON small
        vals = [None if pd.isna(x) else int(round(x * 10000)) for x in vrow[months]]

        rents = {}
        for bed in BEDS:
            if loc in rent_ix[bed].index:
                row = rent_ix[bed].loc[loc]
                rents[bed] = [
                    None if pd.isna(x) else int(round(x)) for x in row[months]
                ]

        # drop markets too sparse to plot
        if sum(x is not None for x in vals) < 24:
            continue
        if sum(x is not None for x in rents.get("overall", [])) < 24:
            continue

        geos.append(
            {
                "n": loc[0],
                "t": loc[1],
                "s": None if pd.isna(vrow.state) else vrow.state,
                "p": 0 if pd.isna(vrow.population) else int(vrow.population),
                "r": rents,
                "v": vals,
            }
        )

    geos.sort(key=lambda g: -g["p"])
    print(f"  {len(geos)} markets, {len(months)} months", file=sys.stderr)
    return {"months": months, "geos": geos}


def write_outputs(data: dict) -> None:
    WEB.mkdir(exist_ok=True)
    (WEB / "data.json").write_text(json.dumps(data, separators=(",", ":")))

    # the page reads the merged payload, not the Apartment List data alone
    from .combine import combine

    payload = json.dumps(combine(), separators=(",", ":"))
    (WEB / "combined.json").write_text(payload)

    template = (WEB / "template.html").read_text()
    if "__DATA__" not in template:
        raise RuntimeError("web/template.html is missing the __DATA__ placeholder")
    SITE.mkdir(exist_ok=True)
    out = SITE / "index.html"
    out.write_text(template.replace('"__DATA__"', payload))
    print(f"  wrote {out.relative_to(ROOT)} ({out.stat().st_size / 1e6:.1f} MB)",
          file=sys.stderr)

    # plotly is vendored so the page opens straight off the filesystem
    shutil.copyfile(ROOT / "vendor" / "plotly.min.js", SITE / "plotly.min.js")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--offline",
        action="store_true",
        help="skip the download and reuse data/raw/*.csv",
    )
    args = ap.parse_args()

    if not args.offline:
        print("fetching Apartment List CSVs", file=sys.stderr)
        download(discover_csv_urls())
    write_outputs(build())


if __name__ == "__main__":
    main()
