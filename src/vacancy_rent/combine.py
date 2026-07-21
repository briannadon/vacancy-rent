"""Merge the three sources into the single payload the page reads.

    Apartment List  asking rent + vacancy index   monthly   2017 on
    Census ACS      gross rent + vacancy rate     annual    2005 on
    Zillow          ZORI, ZHVI, ZORDI             monthly   2015 / 1996 / 2020 on

Each source names places its own way — "New York City, NY" against "New York
city", "Los Angeles County, CA" against "Los Angeles County", "Austin-Round Rock-
Georgetown" against "Austin". Joining happens on a normalised key per geography
level, and Zillow's metro-only coverage attaches to the metro records.

Usage:
    uv run combine        # web/{data,acs,zillow}.json -> web/combined.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .zillow import alias_keys, market_key

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"

CITY_SUFFIXES = (" city", " town", " village", " borough", " municipality", " cdp")


def geo_key(level: str, name: str, state: str | None) -> str:
    """A key that means the same place in every source."""
    name = name.strip()

    if level == "Metro":
        full = name if "," in name else f"{name}, {state or ''}"
        return "metro:" + market_key(full)

    if level == "National":
        return "national:us"

    if level == "State":
        return "state:" + name.lower()

    # City and County: drop the trailing state, then the type word
    if "," in name:
        name = name.rsplit(",", 1)[0]
    low = name.lower().strip()
    if level == "County":
        low = low.removesuffix(" county").removesuffix(" parish").strip()
    else:
        for suffix in CITY_SUFFIXES:
            if low.endswith(suffix):
                low = low[: -len(suffix)].strip()
                break
    return f"{level.lower()}:{low}|{(state or '').lower()}"


def load(name: str) -> dict:
    path = WEB / name
    if not path.exists():
        sys.exit(f"missing {path.relative_to(ROOT)} — run the fetcher for it first")
    return json.loads(path.read_text())


def combine() -> dict:
    al = load("data.json")
    acs = load("acs.json")
    zil = load("zillow.json")

    geos: dict[str, dict] = {}

    def record(level, name, state, pop=0):
        key = geo_key(level, name, state)
        rec = geos.get(key)
        if rec is None:
            rec = geos[key] = {"n": name, "t": level, "s": state, "p": pop,
                               "al": None, "acs": None, "z": None}
        if pop > rec["p"]:
            rec["p"] = pop
        return rec

    for g in al["geos"]:
        rec = record(g["t"], g["n"], g["s"], g.get("p", 0))
        rec["al"] = {"r": g["r"], "v": g["v"]}

    for g in acs["geos"]:
        rec = record(g["t"], g["n"], g["s"])
        rec["acs"] = {"r": g["r"], "v": g["v"]}
        # ACS titles are the canonical ones for places the other sources skip
        if rec["al"] is None:
            rec["n"] = g["n"]

    # Zillow covers metros and the nation
    markets, aliases = zil["markets"], zil["aliases"]

    def zillow_for(level, name, state):
        if level == "National":
            return markets.get("usa")
        if level != "Metro":
            return None
        full = name if "," in name else f"{name}, {state or ''}"
        key = market_key(full)
        if key in markets:
            return markets[key]
        for alias in alias_keys(full):
            if alias in markets:
                return markets[alias]
            if alias in aliases:
                return markets[aliases[alias]]
        return None

    joined = 0
    for rec in geos.values():
        hit = zillow_for(rec["t"], rec["n"], rec["s"])
        if hit:
            rec["z"] = hit["series"]
            joined += 1

    out = [g for g in geos.values() if g["al"] or g["acs"]]
    out.sort(key=lambda g: (-g["p"], g["n"]))

    have = lambda k: sum(1 for g in out if g[k])
    print(f"  {len(out)} places: {have('al')} Apartment List, {have('acs')} ACS, "
          f"{joined} Zillow", file=sys.stderr)
    both = sum(1 for g in out if g["al"] and g["acs"])
    print(f"  {both} carry both monthly and annual history", file=sys.stderr)

    return {
        "al_months": al["months"],
        "acs_years": acs["years"],
        "z_months": zil["months"],
        "geos": out,
    }


def main() -> None:
    data = combine()
    out = WEB / "combined.json"
    out.write_text(json.dumps(data, separators=(",", ":")))
    print(f"  wrote {out.relative_to(ROOT)} ({out.stat().st_size / 1e6:.1f} MB)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
