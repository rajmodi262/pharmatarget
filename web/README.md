# PharmaTarget — frontend

React 18 + TypeScript + Vite + Tailwind. Talks to the FastAPI service in `../api`.

## Run it

The API must be running first — the frontend has no mock data by design, so
that a broken endpoint fails visibly instead of being papered over.

```bash
# terminal 1 — API on :8000
python -m uvicorn api.main:app

# terminal 2 — Vite on :5173
cd web && npm install && npm run dev
```

Vite proxies `/api` → `127.0.0.1:8000`, so the browser sees one origin and CORS
never comes up in development.

## Ship it

```bash
npm run build          # emits web/dist
python -m uvicorn api.main:app
```

`api/main.py` detects `web/dist` and serves it, including an SPA fallback so
`/app/targets` survives a hard refresh. One process, one URL, one deploy.

## Structure

```
src/
  design/tokens.css   every colour, type size and duration. Nothing is
                      hard-coded in a component.
  lib/
    api.ts            typed client, one function per endpoint
    types.ts          mirrors api/schemas.py
    format.ts         ALL number formatting. No inline toFixed anywhere else.
    scales.ts         the two decile ramps, read from CSS custom properties
  components/
    States.tsx        loading / error / empty / synthetic banner
    Primitives.tsx    evidence pills, decile chips, KPI tiles, caveats
    charts/Charts.tsx hand-rolled SVG. No charting library.
  app/
    AppShell.tsx  Overview.tsx  Targets.tsx  HcpDrawer.tsx
    Territories.tsx  Response.tsx  Method.tsx
```

## The rules this code follows

- **No number is hard-coded.** Everything renders from an API response, and a
  missing value shows `––`, never `0`. Conflating "absent" with "zero" is a
  quiet lie.
- **Every headline claim carries an evidence pill** — back-tested, arithmetic,
  scenario, or proxy. A reader always knows what kind of claim they are reading.
- **Filtering, sorting and pagination happen in SQL.** The browser never holds
  more than one page. This is why `/api/hcps` answers in ~70ms on 1.14M rows.
- **Two decile ramps.** Opportunity is chromatic; volume — the industry default
  this project argues against — is grey. The viewer absorbs the argument before
  reading a word, and the chromatic/neutral split is colour-blind safe.
- **All numerals are monospaced with tabular figures.** Columns align without
  effort and the product reads as an instrument rather than a web page.
- **No shadows in tool mode.** The 1px hairline is the structural device.
  Shadows on a data table read as consumer software.
- **Unfavourable numbers sit in the same frame as favourable ones**, same size.
  See the back-test panel on Overview.

## Not used, deliberately

No component library (MUI/Chakra/shadcn) — their defaults are recognisable at a
glance and the point of this interface is that it is not generic. No charting
library — each ships an opinionated theme that costs more to fight than the
marks cost to draw. No Mapbox — a token that expires will break the demo.
