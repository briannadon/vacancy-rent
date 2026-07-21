# vacancy-rent

Vacancy rates and rents for 526 US rental markets, plotted against each other.

Both numbers are published every month and almost never shown together. Apartment
List is the only source that puts out a rent estimate and a vacancy index on the
same geographies and the same monthly grid (Jan 2017 onward, national / state /
metro / county / city) — but on separate pages, never joined. This joins them and
puts a Plotly page on top.

## Sources

| | measure | frequency | from | coverage |
|---|---|---|---|---|
| Apartment List | asking rent on new leases, vacancy index | monthly | 2017 | 526 places |
| Census ACS 1-year | gross rent, rental vacancy rate | annual | 2005 | 1,572 places |
| Zillow ZORI | asking rent | monthly | 2015 | metros |
| Zillow ZHVI | typical home value | monthly | 1996 | metros |
| Zillow ZORDI | renter demand index | monthly | 2020 | metros |

466 places carry both a monthly and an annual history. Each source names places
differently, so `combine.py` joins them on a normalised key per geography level.

## What the page does

- **Rent over time** from up to three sources at once, for up to four markets.
  Colour marks the market, line style marks the source, so an asking rent and a
  survey rent for the same place read as one market's two measures.
- **Vacancy over time**, Apartment List against ACS, on its own panel — no second
  y-axis anywhere.
- **Home values, price-to-rent, and renter demand** from the Zillow indices.
- **Unit size held fixed** — all units, 1br, or 2br. Not square footage, but it
  removes the biggest composition effect in a median asking rent.
- **Every market at once**: one dot per market, sized by population, with a year
  slider and a play button. Switch the vertical axis between rent level and
  year-over-year growth, and the geography between metros, cities, counties and
  states. Selected markets stay labelled while everything else moves.
- **Lagged scatter**: vacancy in one month against rent growth *n* months later,
  with a least-squares fit and Pearson r. The lag slider is where the interesting
  part is — most markets show the relationship strengthening out to 6–12 months.

## Run it

```sh
uv run fetch-acs       # Census ACS, needs CENSUS_API_KEY in .env
uv run fetch-zillow    # ZORI, ZHVI, ZORDI
uv run build-data      # Apartment List, then merge everything into site/
xdg-open site/index.html
```

`build-data` runs the merge itself, so after the first full pull only that last
command is needed (add `--offline` to skip re-downloading Apartment List).

`site/index.html` is self-contained apart from `plotly.min.js` sitting next to it,
so it opens straight off the filesystem — no server, no network.

`--offline` reuses whatever is already in `data/raw/` instead of re-downloading.
Apartment List rotates its Contentful asset URLs every month, so the build scrapes
the download page for the current links rather than hardcoding them.

## The ACS panel (2005–2024)

Apartment List starts in 2017. For a longer history, `uv run fetch-acs` pulls the
Census ACS 1-year tables, where rent and vacancy come out of the same survey:

| | |
|---|---|
| `B25064_001` | median gross rent |
| `B25031_003/004` | median gross rent, 1br / 2br (2015 on only) |
| `B25003_003` | renter-occupied units |
| `B25004_002` | vacant units, for rent |

Rental vacancy rate is `B25004_002 / (B25003_003 + B25004_002)`, the same
construction the Housing Vacancy Survey uses. Output: `web/acs.json`, 1,577
geographies (512 metros, 721 counties, 292 cities, 52 states) over 19 years.

Needs a free Census API key in `.env` as `CENSUS_API_KEY=…`
([signup](https://api.census.gov/data/key_signup.html); the key has to be
activated from the confirmation email before it works). Raw responses are cached
under `data/acs/`, so re-runs cost nothing.

What this series is *not*: gross rent includes utilities and covers sitting
tenants, so it moves far more slowly than an asking rent and sits below it in
level. No 2020 release. 1-year tables only cover geographies above 65,000 people.
Metro boundaries were redrawn in 2013 and again in 2023, so a long series for one
CBSA code is not always the same set of counties; names shown are the most recent.

## Layout

```
src/vacancy_rent/build_data.py   fetch -> join -> emit
web/template.html                the page; "__DATA__" is the JSON injection point
web/data.json                    joined dataset, also usable on its own
site/                            built output
data/raw/                        downloaded CSVs (gitignored)
```

To change the page, edit `web/template.html` and re-run `uv run build-data --offline`.

## Reading the numbers

The vacancy index counts vacant units among properties that list on Apartment List,
so its level sits above Census Housing Vacancy Survey estimates for the same place.
Movement over time is the usable signal; the absolute level is not comparable to
Census figures. Rent estimates are medians for *new leases*, which turn faster than
the rent the average sitting tenant pays.

City and county series come from smaller samples than metros and are noisier.
Markets with fewer than 24 months of either series are dropped at build time.

Alternatives if you need something else: Census HVS for vacancy on a survey basis
(quarterly, 75 largest metros), Zillow ZORI for rent down to zip level.
