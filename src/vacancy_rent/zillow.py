"""Pull the Zillow metro indices and key them so they join to the other sources.

    ZORI   asking rent, monthly, Jan 2015 on
    ZHVI   typical home value, monthly, Feb 1996 on
    ZORDI  renter demand (engagement with Zillow rental listings), Jun 2020 on

Zillow names metros in short form ("Austin, TX") while Apartment List and the
Census use full CBSA titles ("Austin-Round Rock-San Marcos, TX"), and Zillow's
RegionID is its own identifier rather than a CBSA code. Everything is therefore
keyed on (first city in the name, first state), which is stable across all three
sources and across the CBSA redefinitions.

Usage:
    uv run fetch-zillow
"""

from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
CACHE = ROOT / "data" / "zillow"

BASE = "https://files.zillowstatic.com/research/public_csvs"

FILES = {
    # asking rent, smoothed, all homes plus multifamily
    "zori": "zori/Metro_zori_uc_sfrcondomfr_sm_month.csv",
    # typical home value, mid tier (33rd-67th percentile), SFR + condo
    "zhvi": "zhvi/Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_month.csv",
    # renter demand index
    "zordi": "zordi/Metro_zordi_uc_sfrcondomfr_month.csv",
}


def split_name(name: str) -> tuple[list[str], str]:
    """'Austin-Round Rock-San Marcos, TX' -> (['austin','round rock','san marcos'], 'tx')."""
    name = name.strip()
    head, tail = name.rsplit(",", 1) if "," in name else (name, "")
    head = head.replace("/", "-").lower()
    # "Urban Honolulu" is the CBSA title for what everyone else calls Honolulu
    if head.startswith("urban "):
        head = head[6:]
    cities = [c.strip() for c in head.split("-") if c.strip()]
    state = tail.strip().split("-")[0].strip().lower()
    return cities, state


def market_key(name: str) -> str:
    """The primary key: first city plus first state."""
    cities, state = split_name(name)
    return f"{cities[0] if cities else ''}|{state}"


def alias_keys(name: str) -> list[str]:
    """Every city in the title against the state, since the lead city differs
    between sources (Zillow's 'Crestview, FL' is the Census's
    'Fort Walton Beach-Crestview-Destin, FL')."""
    cities, state = split_name(name)
    return [f"{c}|{state}" for c in cities]


def download(series: str) -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{series}.csv"
    if not cached.exists():
        url = f"{BASE}/{FILES[series]}"
        print(f"  {series:6s} <- {url.rsplit('/', 1)[-1]}", file=sys.stderr)
        r = requests.get(url, timeout=300)
        r.raise_for_status()
        cached.write_bytes(r.content)
    return list(csv.DictReader(io.StringIO(cached.read_text())))


def build() -> dict:
    out: dict[str, dict] = {}
    months: dict[str, list[str]] = {}

    for series in FILES:
        rows = download(series)
        if not rows:
            continue
        cols = [c for c in rows[0] if c[:4].isdigit() and len(c) == 10]
        months[series] = cols

        for row in rows:
            name = row["RegionName"]
            key = "usa" if row.get("RegionType") == "country" else market_key(name)
            rec = out.setdefault(key, {"n": name, "series": {}})
            if row.get("RegionType") != "country" and len(name) > len(rec["n"]):
                rec["n"] = name
            vals = []
            for c in cols:
                v = row[c]
                if not v:
                    vals.append(None)
                else:
                    # rents to the dollar, home values to the hundred, index as-is
                    f = float(v)
                    vals.append(round(f) if series != "zhvi" else round(f / 100) * 100)
            rec["series"][series] = vals

        print(f"  {series:6s} {len(rows)} regions, {cols[0][:7]} to {cols[-1][:7]}",
              file=sys.stderr)

    # alias -> primary key, so a caller can look a market up by any city in its
    # title; ambiguous aliases are dropped rather than guessed at
    index: dict[str, str | None] = {}
    for key, rec in out.items():
        for alias in alias_keys(rec["n"]):
            if alias in out and alias != key:
                continue  # never shadow a market's own primary key
            index[alias] = key if index.get(alias, key) == key else None
    index = {a: k for a, k in index.items() if k and a not in out}

    return {"months": months, "markets": out, "aliases": index}


def main() -> None:
    data = build()
    WEB.mkdir(exist_ok=True)
    out = WEB / "zillow.json"
    out.write_text(json.dumps(data, separators=(",", ":")))
    print(f"  {len(data['markets'])} markets -> {out.relative_to(ROOT)} "
          f"({out.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)


if __name__ == "__main__":
    main()
