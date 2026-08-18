# wind-cal

Scrapes the windguru forecast for a spot, finds timeslots where average wind is
above a threshold for long enough, and publishes them as a `.ics` calendar feed
you can subscribe to from Google Calendar.

Default spot: Wijk aan Zee, NL. Default threshold: 16kt average, sustained for
at least 3 hours. Both configurable in `config.toml`.

## How it works

1. `scraper.py` fetches plain-text forecast data from windguru's
   `micro.windguru.cz` endpoint (a documented integration endpoint, not the
   main site) for the configured spot + model.
2. `analyzer.py` finds contiguous runs where every point is above the wind
   threshold and the run lasts long enough.
3. `ics_writer.py` updates `docs/wijk-aan-zee-wind.ics` in place — new windy
   slots are added, changed ones are updated, stale ones are removed. Existing
   unaffected events are left byte-identical.
4. A GitHub Actions workflow runs this hourly and commits the result, which
   GitHub Pages serves at a stable URL.

## Local setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python pipeline.py
```

This writes `docs/wijk-aan-zee-wind.ics` and `docs/status.json`. Run it twice
in a row and diff the two — a second run with an unchanged forecast should
touch nothing but `status.json`'s timestamp.

To run the tests: `.venv/bin/pip install -r requirements-dev.txt && .venv/bin/pytest`

## Publishing via GitHub Pages

1. Create a GitHub repository and push this project to `main`.
2. In the repo: **Settings → Pages → Build and deployment → Source** → "Deploy
   from a branch" → branch `main`, folder `/docs` → Save.
3. After the first Pages build (~1-2 min), your feed URL will be:
   `https://<your-username>.github.io/<repo-name>/wijk-aan-zee-wind.ics`
4. Make sure Actions are enabled for the repo (Settings → Actions → General —
   on by default) so the hourly workflow actually runs.

The feed URL is public and unauthenticated — anyone with the link can read it.
That's fine here since it only contains wind timeslots, but don't add anything
sensitive to `config.toml`'s `calendar_name` or event content.

## Subscribing from Google Calendar

1. Google Calendar → left sidebar → "Other calendars" **+** → **"From URL"**.
2. Paste the GitHub Pages URL from above → "Add calendar".
3. **Google only re-checks subscribed feeds roughly every 12–24 hours**, with
   no manual refresh option. The feed itself updates hourly, but your Google
   Calendar view will lag behind it by up to a day. This is a Google
   limitation, not something this project can speed up.

## Configuration (`config.toml`)

- `spot.id` — windguru spot ID (from `https://www.windguru.cz/<id>`)
- `forecast.model` — micro.windguru.cz model code (default `gfs`; see
  `http://micro.windguru.cz/help.php` for the full list, e.g. `harmnl` for the
  higher-resolution, shorter-range Netherlands-specific model)
- `thresholds.min_avg_wind_kt` / `thresholds.min_duration_hours` — the windy-slot
  criteria
- `output.*` — where the `.ics` and status files are written

## If it stops updating

Check `docs/status.json` (also served via Pages) for `last_run_status` and
`error_message`. GitHub also emails the repo owner when a scheduled workflow
run fails. The most likely long-term failure mode is windguru changing their
forecast text format — if `scraper.py` starts raising `ScraperParseError`, use
`http://micro.windguru.cz/?s=<spot_id>&m=<model>&v=WSPD,GUST,WDIRN` to see the
current raw format and update the parsing regexes in `scraper.py` accordingly.

## Known limitations

- windguru's terms of service prohibit automated scraping of the main site.
  This project instead uses their documented `micro.windguru.cz` integration
  endpoint (built for third-party consumption, e.g. email forecast services),
  which is a meaningfully different and lower-risk situation — but the literal
  ToS text couldn't be confirmed to explicitly carve this out. Use accordingly.
- Google Calendar's subscription refresh lag (above) is outside this project's
  control.
