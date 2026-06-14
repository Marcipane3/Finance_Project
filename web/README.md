# Portfolio Cockpit (web)

A static, self-updating research terminal for both tracks. No server, no build step,
no framework — `index.html` + `styles.css` + `app.js` reading `data/latest.json`.

## Architecture

```
build_site.py  ──►  web/data/latest.json   (public research: picks, theses, rankings)
                    web/data/track_record.json
                         │
   GitHub Actions        ▼
   monthly-pick.yml ─► commits data ─► deploy-pages.yml ─► GitHub Pages
   daily-stoploss.yml ┘

browser localStorage  ──►  your real € positions (PRIVATE, never uploaded)
```

- **Public layer:** everything in `data/*.json`. Research only — no money figures.
- **Private layer:** holdings entered in the "My Holdings" tab live in `localStorage`
  (`cockpit.holdings.v1`). They never touch git or the network. Export/import as JSON to back up.

## Run locally

```bash
python build_site.py            # regenerate data/latest.json from pipeline output
python -m http.server -d web 8766
# open http://localhost:8766
```

## Deploy (one-time setup)

1. Push the repo to GitHub.
2. Settings → Pages → Source = **GitHub Actions**.
3. Settings → Secrets and variables → Actions → add **`ANTHROPIC_API_KEY`**.
4. The monthly/daily workflows commit fresh data; `deploy-pages.yml` publishes it.
   Trigger a first deploy manually via Actions → "Deploy cockpit" → Run workflow.

## Data contract (`data/latest.json`)

```jsonc
{
  "generated_at": "ISO-8601",
  "currency": "EUR",
  "fx": { "usd_eur", "gbp_eur", "dkk_eur", "jpy_eur" },
  "track_b": {
    "as_of", "pick": { ticker, name, sector, price_usd, recommendation:{action,stop_price} },
    "leaderboard": [ { rank, ticker, name, score, forward_pe, ... } ],
    "report_md": "full markdown thesis",
    "stop_loss": { status, ... }
  },
  "track_a": { "as_of", "n_eligible", "a1":{status,expected_return,cvar,tc_eur,positions[]}, "a2":{...}, "report_md" },
  "track_record": [ { ticker, pick_date, entry_price_usd, benchmark, return_pct, status } ]
}
```

`build_site.py` prefers a JSON sidecar next to each report; if none exists it parses the
markdown report. So the cockpit renders today's output and keeps working once the pipelines
emit sidecars directly.
