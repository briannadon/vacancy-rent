"""Pull annual rent and rental-vacancy figures from the Census ACS 1-year tables.

Apartment List starts in 2017. The ACS goes back to 2005 and carries both
measures in one survey, so rent and vacancy are at least internally consistent:

    B25064_001  median gross rent, all renter-occupied units
    B25031_003  median gross rent, 1 bedroom
    B25031_004  median gross rent, 2 bedrooms
    B25003_003  renter-occupied units
    B25004_002  vacant units, for rent

    rental vacancy rate = B25004_002 / (B25003_003 + B25004_002)

which is the Census definition of the rate, matching the Housing Vacancy Survey
construction.

Caveats worth keeping in mind when reading the output: gross rent includes
utilities and covers *sitting* tenants, so its level runs below an asking-rent
series and it turns over more slowly. The 1-year tables only cover geographies
above 65,000 people, and 2020 was never released.

Needs a Census API key (free, instant: https://api.census.gov/data/key_signup.html)
in CENSUS_API_KEY, or in a .env file at the repo root.

Usage:
    uv run fetch-acs           # writes web/acs.json
    uv run fetch-acs --years 2019 2023
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
CACHE = ROOT / "data" / "acs"

API = "https://api.census.gov/data/{year}/acs/acs1"

CORE = {
    "rent_overall": "B25064_001E",
    "renter_occupied": "B25003_003E",
    "vacant_for_rent": "B25004_002E",
}

# B25031, median gross rent by bedroom count, carries its modern meaning only
# from 2015 on; the 2005 vintage published counts under the same variable ids
BEDROOM = {
    "rent_1br": "B25031_003E",
    "rent_2br": "B25031_004E",
}
BEDROOM_FIRST_YEAR = 2015

# ACS 1-year runs from 2005; the 2020 release was cancelled
YEARS = [y for y in range(2005, 2025) if y != 2020]

LEVELS = {
    "National": {"for": "us:*"},
    "Metro": {"for": "metropolitan statistical area/micropolitan statistical area:*"},
    "State": {"for": "state:*"},
    "County": {"for": "county:*", "in": "state:*"},
    "City": {"for": "place:*", "in": "state:*"},
}


def api_key() -> str:
    key = os.environ.get("CENSUS_API_KEY")
    if not key:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("CENSUS_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip("'\"")
    if not key:
        sys.exit(
            "Set CENSUS_API_KEY (get one at "
            "https://api.census.gov/data/key_signup.html), or put it in .env"
        )
    return key


def fetch(year: int, level: str, key: str, group: str = "core") -> list[list[str]]:
    """One request per year per geography level per variable group; cached."""
    CACHE.mkdir(parents=True, exist_ok=True)
    suffix = "" if group == "core" else "_" + group
    cached = CACHE / f"{year}_{level}{suffix}.json"
    if cached.exists():
        return json.loads(cached.read_text())

    params = dict(LEVELS[level])
    params["get"] = "NAME," + ",".join((CORE if group == "core" else BEDROOM).values())
    params["key"] = key

    r = requests.get(API.format(year=year), params=params, timeout=120)
    if r.status_code in (400, 404):
        # a variable group the vintage never published
        return []
    r.raise_for_status()
    if not r.text.lstrip().startswith("["):
        # the API answers with an HTML page for key problems
        title = "unexpected response"
        if "<title>" in r.text:
            title = r.text.split("<title>", 1)[1].split("</title>", 1)[0].strip()
        sys.exit(
            f"Census API said: {title}\n"
            "A new key has to be activated from the confirmation email before it works."
        )
    rows = r.json()
    cached.write_text(json.dumps(rows))
    time.sleep(0.3)
    return rows


def num(v: str | None) -> float | None:
    """ACS uses large negative sentinels for suppressed or unavailable cells."""
    if v in (None, "", "null"):
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    return None if f < 0 else f


def clean_name(name: str, level: str) -> tuple[str, str | None]:
    """Split 'Austin-Round Rock, TX Metro Area' into a name and a state."""
    name = name.replace(" Metro Area", "").replace(" Micro Area", "")
    if level == "National":
        return "United States", None
    if level in ("Metro", "County", "City") and "," in name:
        head, tail = name.rsplit(",", 1)
        return head.strip(), tail.strip()
    return name.strip(), None


def build(years: list[int], key: str) -> dict:
    # geo id -> record; ids are the concatenated FIPS the API returns
    records: dict[str, dict] = {}
    year_index = {y: i for i, y in enumerate(years)}

    def rows_by_geo(year, level, group, wanted):
        """Return {geo id: {var name: raw string}} for one request."""
        rows = fetch(year, level, key, group)
        if not rows:
            return {}, {}
        header, *data = rows
        col = {name: header.index(v) for name, v in wanted.items()}
        name_at = header.index("NAME")
        id_cols = [i for i in range(len(header))
                   if header[i] != "NAME" and header[i] not in wanted.values()]
        out, names = {}, {}
        for row in data:
            gid = "".join(row[i] for i in id_cols)
            out[gid] = {name: row[i] for name, i in col.items()}
            names[gid] = row[name_at]
        return out, names

    for level in LEVELS:
        for year in years:
            core, names = rows_by_geo(year, level, "core", CORE)
            if not core:
                continue
            bedroom = {}
            if year >= BEDROOM_FIRST_YEAR:
                bedroom, _ = rows_by_geo(year, level, "bedroom", BEDROOM)
            i = year_index[year]

            for gid, vals in core.items():
                rec = records.get(level + ":" + gid)
                n, st = clean_name(names[gid], level)
                if rec is None:
                    rec = records[level + ":" + gid] = {
                        "n": n,
                        "t": level,
                        "s": st,
                        "r": {k: [None] * len(years) for k in ("overall", "1br", "2br")},
                        "v": [None] * len(years),
                    }

                # geographies get renamed over time; keep the most recent name
                rec["n"], rec["s"] = n, st

                vals = {**vals, **bedroom.get(gid, {})}
                for bed, var in (("overall", "rent_overall"),
                                 ("1br", "rent_1br"), ("2br", "rent_2br")):
                    val = num(vals.get(var))
                    if val is not None:
                        rec["r"][bed][i] = round(val)

                occ = num(vals.get("renter_occupied"))
                vac = num(vals.get("vacant_for_rent"))
                if occ is not None and vac is not None and (occ + vac) > 0:
                    rec["v"][i] = round(vac / (occ + vac) * 10000)

        print(f"  {level}: {sum(1 for r in records.values() if r['t'] == level)} geographies",
              file=sys.stderr)

    geos = [r for r in records.values()
            if sum(x is not None for x in r["v"]) >= 5
            and sum(x is not None for x in r["r"]["overall"]) >= 5]
    geos.sort(key=lambda g: (g["t"], g["n"]))
    return {"years": years, "geos": geos}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--years", nargs=2, type=int, metavar=("FIRST", "LAST"),
                    help="year range to pull (default 2008-2024, minus 2020)")
    args = ap.parse_args()

    years = YEARS
    if args.years:
        lo, hi = args.years
        years = [y for y in range(lo, hi + 1) if y != 2020]

    data = build(years, api_key())
    WEB.mkdir(exist_ok=True)
    out = WEB / "acs.json"
    out.write_text(json.dumps(data, separators=(",", ":")))
    print(f"  {len(data['geos'])} geographies over {len(years)} years -> "
          f"{out.relative_to(ROOT)} ({out.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)


if __name__ == "__main__":
    main()
