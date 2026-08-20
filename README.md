# wind-cal

Scrapes the windguru forecast for a spot, finds timeslots where average wind is
above a threshold for long enough, and publishes them as a `.ics` calendar feed
you can subscribe to from Google Calendar.

Default spot: Wijk aan Zee, NL. Default threshold: 15kt average, sustained for
at least 4 hours. Both configurable in `config.toml`.

## How it works

1. `scraper.py` fetches plain-text forecast data from windguru's
   `micro.windguru.cz` endpoint (a documented integration endpoint, not the
   main site) for the configured spot + model.
2. `analyzer.py` finds contiguous runs where every point is above the wind
   threshold and the run lasts long enough, and aggregates each run's total
   rain and average cloud cover alongside the wind numbers.
3. `ics_writer.py` updates `docs/wijk-aan-zee-wind.ics` in place — new windy
   slots are added, changed ones are updated, stale ones are removed. Existing
   unaffected events are left byte-identical. Each event's title ends with a
   weather emoji (🌧️ if measurable rain is expected, else ☀️/⛅/☁️ by cloud
   cover), and the description spells out the exact rain (mm) and cloud (%)
   figures plus which forecast model(s) it's based on.
4. A GitHub Actions workflow runs this hourly and commits the result, which
   is then reachable at a stable `raw.githubusercontent.com` URL.

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

## Publishing

1. Create a GitHub repository and push this project to `main`.
2. Make sure Actions are enabled for the repo (Settings → Actions → General —
   on by default) so the hourly workflow actually runs and commits updates.
3. Your feed URL is then:
   `https://raw.githubusercontent.com/<your-username>/<repo-name>/main/docs/wijk-aan-zee-wind.ics`

No extra hosting setup needed — GitHub serves any committed file's raw
content directly from the repo at that URL, updated the moment the workflow
pushes a change (no separate build/deploy step, unlike GitHub Pages, which
this project doesn't use).

The feed URL is public and unauthenticated — anyone with the link can read it.
That's fine here since it only contains wind timeslots, but don't add anything
sensitive to `config.toml`'s `calendar_name` or event content.

## Subscribing from Google Calendar

1. Google Calendar → left sidebar → "Other calendars" **+** → **"From URL"**.
2. Paste the feed URL from above → "Add calendar".
3. **Google only re-checks subscribed feeds roughly every 12–24 hours**, with
   no manual refresh option. The feed itself updates hourly, but your Google
   Calendar view will lag behind it by up to a day. This is a Google
   limitation, not something this project can speed up.

## Configuration (`config.toml`)

- `spot.id` — windguru spot ID (from `https://www.windguru.cz/<id>`)
- `forecast.primary_model` / `forecast.fallback_model` — micro.windguru.cz model
  codes (see `http://micro.windguru.cz/help.php` for the full list). The
  primary model is used for whatever forecast horizon it covers; the fallback
  model fills in the rest. Default: `harmnl` (HARM-NL 2km, high-resolution,
  Netherlands-specific, ~2-3 days out) falling back to `gfs` (GFS 13km, ~16
  day horizon). If the primary model's fetch fails outright, the pipeline logs
  a warning and uses the fallback model for the entire horizon instead of
  failing. Each event's description states which model(s) it's based on —
  a timeslot that happens to span the handoff point lists both.
- `thresholds.min_avg_wind_kt` / `thresholds.min_duration_hours` — the windy-slot
  criteria
- `output.*` — where the `.ics` and status files are written

The rain-vs-dry cutoff (0.5mm) and cloud-cover emoji tiers (<30% ☀️, 30-70% ⛅,
>70% ☁️) aren't in `config.toml` yet — they're constants near the top of
`ics_writer.py` (`RAIN_THRESHOLD_MM` and the tier checks in `_weather_emoji`)
if you want to tune them.

## If it stops updating

Check `docs/status.json` (also fetchable via the same raw-URL pattern) for `last_run_status` and
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
