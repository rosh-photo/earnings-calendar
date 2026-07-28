#!/usr/bin/env python3
"""Live earnings calendar tracker for Big Tech & AI/semiconductor stocks.

Usage:
    python3 earnings_calendar.py              # upcoming earnings (next 60 days)
    python3 earnings_calendar.py --all        # include recent past results
    python3 earnings_calendar.py --weeks 2    # next 2 weeks only
    python3 earnings_calendar.py --json       # JSON output
    python3 earnings_calendar.py --html       # HTML output to outputs/
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

WATCHLIST: dict[str, list[tuple[str, str]]] = {
    "Big Tech": [
        ("AAPL", "Apple"),
        ("MSFT", "Microsoft"),
        ("GOOGL", "Alphabet"),
        ("AMZN", "Amazon"),
        ("META", "Meta"),
    ],
    "AI & Chips": [
        ("NVDA", "NVIDIA"),
        ("AVGO", "Broadcom"),
        ("AMD", "AMD"),
        ("ARM", "Arm Holdings"),
        ("TSM", "TSMC"),
        ("INTC", "Intel"),
        ("QCOM", "Qualcomm"),
        ("MRVL", "Marvell"),
    ],
    "Memory": [
        ("MU", "Micron"),
        ("000660.KS", "SK Hynix"),
        ("WDC", "Western Digital"),
        ("SNDK", "SanDisk"),
        ("285A.T", "Kioxia"),
    ],
    "AI Software & Cloud": [
        ("CRM", "Salesforce"),
        ("ORCL", "Oracle"),
        ("SNOW", "Snowflake"),
        ("PLTR", "Palantir"),
    ],
}

# Flatten for lookup
_SYMBOL_META: dict[str, tuple[str, str]] = {}  # symbol -> (name, category)
for _cat, _tickers in WATCHLIST.items():
    for _sym, _name in _tickers:
        _SYMBOL_META[_sym] = (_name, _cat)

ALL_SYMBOLS = list(_SYMBOL_META.keys())


def fetch_earnings(symbols: list[str]) -> list[dict]:
    """Fetch earnings calendar + recent results for all symbols."""
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance not installed: pip install yfinance", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    results = []

    for sym in symbols:
        name, category = _SYMBOL_META[sym]
        try:
            t = yf.Ticker(sym)

            # Currency for this ticker
            # trading currency (e.g. USD for TSM on NYSE)
            currency = getattr(t.fast_info, "currency", "USD") or "USD"
            # financial reporting currency (e.g. TWD for TSMC) — revenue/EPS
            # estimates from yfinance are denominated in this currency
            try:
                fin_currency = t.info.get("financialCurrency") or currency
            except Exception:
                fin_currency = currency

            # Calendar gives next earnings date + consensus estimates
            cal = t.calendar or {}
            next_dates = cal.get("Earnings Date", [])
            eps_est = cal.get("Earnings Average")
            rev_est = cal.get("Revenue Average")
            eps_hi = cal.get("Earnings High")
            eps_lo = cal.get("Earnings Low")

            # earnings_dates gives historical EPS + surprise
            ed = t.earnings_dates
            upcoming = []
            recent = []
            if ed is not None and not ed.empty:
                for dt_idx, row in ed.iterrows():
                    dt = dt_idx.to_pydatetime()
                    # BMO/AMC only meaningful for US-listed stocks;
                    # non-US stocks report during their local market hours
                    if currency == "USD":
                        timing = "AMC" if dt.hour >= 16 else "BMO" if dt.hour < 12 else "TBD"
                    else:
                        timing = ""
                    entry = {
                        "date": dt.strftime("%Y-%m-%d"),
                        "time": timing,
                        "eps_estimate": _safe_float(row.get("EPS Estimate")),
                        "eps_reported": _safe_float(row.get("Reported EPS")),
                        "surprise_pct": _safe_float(row.get("Surprise(%)")),
                    }
                    if dt >= now:
                        upcoming.append(entry)
                    else:
                        recent.append(entry)

            # Use calendar estimates for the next upcoming if available
            if upcoming and eps_est is not None:
                upcoming[0]["eps_consensus"] = round(eps_est, 2)
                upcoming[0]["rev_consensus"] = round(rev_est) if rev_est else None
                upcoming[0]["eps_range"] = (
                    f"{eps_lo:.2f}–{eps_hi:.2f}" if eps_lo and eps_hi else None
                )

            results.append({
                "symbol": sym,
                "name": name,
                "category": category,
                "currency": currency,
                "fin_currency": fin_currency,
                "next_date": next_dates[0].isoformat() if next_dates else None,
                "upcoming": upcoming,
                "recent": recent[:4],  # last 4 quarters
            })

        except Exception as e:
            print(f"  {sym}: {e}", file=sys.stderr)
            results.append({
                "symbol": sym, "name": name, "category": category,
                "next_date": None, "upcoming": [], "recent": [],
                "error": str(e),
            })

    return results


def _safe_float(v) -> float | None:
    try:
        import math
        f = float(v)
        return round(f, 2) if not math.isnan(f) else None
    except (TypeError, ValueError):
        return None


_CURRENCY_SYMBOLS = {
    "USD": "$", "CAD": "C$", "GBP": "\u00a3", "EUR": "\u20ac",
    "JPY": "\u00a5", "KRW": "\u20a9", "TWD": "NT$", "CNY": "\u00a5",
    "AUD": "A$", "INR": "\u20b9", "SGD": "S$",
}


def _cur(code: str) -> str:
    return _CURRENCY_SYMBOLS.get(code, code + " ")


def _fmt_rev(v: float | None, cur: str = "$") -> str:
    if v is None:
        return "\u2013"
    if v >= 1e12:
        return f"{cur}{v/1e12:.1f}T"
    if v >= 1e9:
        return f"{cur}{v/1e9:.1f}B"
    if v >= 1e6:
        return f"{cur}{v/1e6:.0f}M"
    return f"{cur}{v:,.0f}"


def _surprise_str(pct: float | None) -> str:
    if pct is None:
        return ""
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def print_calendar(results: list[dict], weeks: int = 8, show_recent: bool = False) -> None:
    """Print a formatted earnings calendar to stdout."""
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(weeks=weeks)

    # Collect all upcoming into a flat list for chronological display
    upcoming_all = []
    for r in results:
        for u in r.get("upcoming", []):
            dt = datetime.fromisoformat(u["date"]).replace(tzinfo=timezone.utc)
            if dt <= cutoff:
                upcoming_all.append({**u, **{
                    "symbol": r["symbol"],
                    "name": r["name"],
                    "category": r["category"],
                }})

    upcoming_all.sort(key=lambda x: x["date"])

    # Header
    print(f"\n{'═' * 80}")
    print(f"  EARNINGS CALENDAR — {len(ALL_SYMBOLS)} stocks tracked")
    print(f"  {now.strftime('%Y-%m-%d %H:%M UTC')} · Next {weeks} weeks")
    print(f"{'═' * 80}\n")

    if not upcoming_all:
        print("  No upcoming earnings in this window.\n")
    else:
        # Group by week
        current_week = None
        for item in upcoming_all:
            dt = datetime.fromisoformat(item["date"])
            week_start = dt - timedelta(days=dt.weekday())
            week_label = week_start.strftime("Week of %b %d")
            today_et = (now - timedelta(hours=4)).date()
            days_away = (dt.date() - today_et).days

            if week_label != current_week:
                current_week = week_label
                print(f"  ┌─ {week_label} {'─' * (80 - len(week_label) - 6)}")

            timing = item.get("time", "TBD")
            eps_est = item.get("eps_consensus") or item.get("eps_estimate")
            # Look up fin_currency for this symbol
            _r = next((r for r in results if r["symbol"] == item["symbol"]), {})
            _fc = _cur(_r.get("fin_currency", _r.get("currency", "USD")))
            eps_str = f"EPS est {_fc}{eps_est:.2f}" if eps_est else ""
            rev_str = _fmt_rev(item.get("rev_consensus"), _fc)
            rev_str = f"  Rev {rev_str}" if rev_str != "\u2013" else ""
            range_str = f"  ({item['eps_range']})" if item.get("eps_range") else ""
            days_str = f"in {days_away}d" if days_away >= 0 else "TODAY" if days_away == 0 else ""

            sym_display = f"{item['symbol']:>10s}"
            name_display = f"{item['name']:<16s}"
            date_display = dt.strftime("%a %b %d")

            print(f"  │  {date_display} {timing:>3s}  {sym_display}  {name_display}"
                  f"  {eps_str}{range_str}{rev_str}  {days_str}")

        print(f"  └{'─' * 79}\n")

    # Recent results (beat/miss summary)
    if show_recent:
        print(f"  {'─' * 80}")
        print(f"  RECENT RESULTS (last 4 quarters)")
        print(f"  {'─' * 80}\n")

        for r in results:
            if not r.get("recent"):
                continue
            beats = sum(1 for q in r["recent"] if q.get("surprise_pct") and q["surprise_pct"] > 0)
            streak = "🔥" if beats == len(r["recent"]) else ""

            cur = _cur(r.get("currency", "USD"))
            print(f"  {r['symbol']:>10s}  {r['name']:<16s}  ", end="")
            for q in r["recent"]:
                eps_r = q.get("eps_reported")
                surprise = q.get("surprise_pct")
                qdate = datetime.fromisoformat(q["date"]).strftime("%b")
                if eps_r is not None and surprise is not None:
                    marker = "▲" if surprise > 0 else "▼"
                    print(f"{qdate} {cur}{eps_r:,.2f} {marker}{abs(surprise):.1f}%  ", end="")
                else:
                    print(f"{qdate} –  ", end="")
            print(f"  {beats}/{len(r['recent'])} beats {streak}")

        print()

    # Summary: next up
    no_date = [r for r in results if not r.get("next_date") and not r.get("error")]
    if no_date:
        print(f"  ℹ  No date announced: {', '.join(r['symbol'] for r in no_date)}\n")


def write_json(results: list[dict], path: Path) -> None:
    path.write_text(json.dumps({
        "generated": datetime.now(timezone.utc).isoformat(),
        "stocks": results,
    }, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"  JSON → {path}", file=sys.stderr)


def write_html(results: list[dict], path: Path) -> None:
    """Generate a self-contained HTML earnings dashboard — flat one-row-per-stock."""
    now = datetime.now(timezone.utc)
    today_et = (now - timedelta(hours=4)).date()  # rough ET offset

    # Build one row per stock within a ±30-day window.
    # Stocks that already reported show the REPORTED date + actuals.
    # Stocks yet to report show the upcoming date + estimates.
    rows_html = []
    for r in results:
        sym = r["symbol"]
        name = r["name"]
        cat = r["category"]
        recent = r.get("recent", [])
        upcoming = r.get("upcoming", [])
        cat_cls = cat.lower().replace(" & ", "-").replace(" ", "-")
        fin_cur = _cur(r.get("fin_currency", r.get("currency", "USD")))
        cur = _cur(r.get("currency", "USD"))

        beats = sum(1 for q2 in recent if q2.get("surprise_pct") and q2["surprise_pct"] > 0)
        streak = f"{beats}/{len(recent)}" if recent else "\u2013"

        # Check if reported this cycle (within 30 days)
        reported_this_cycle = False
        if recent:
            q = recent[0]
            report_dt = datetime.fromisoformat(q["date"])
            days_since = (today_et - report_dt.date()).days
            if 0 <= days_since <= 30 and q.get("eps_reported") is not None:
                reported_this_cycle = True

        if reported_this_cycle:
            # --- REPORTED: show the completed quarter ---
            q = recent[0]
            dt = datetime.fromisoformat(q["date"])
            day_str = dt.strftime("%a")
            mdate_str = dt.strftime("%b %d")
            iso_date = dt.strftime("%Y-%m-%d")
            timing = q.get("time", "")
            days_away = -days_since  # negative = past
            # Estimate for the reported quarter (from earnings_dates, trading cur)
            eps_est = q.get("eps_estimate")
            eps_cell = f"{cur}{eps_est:,.2f}" if eps_est else "\u2013"
            # Actual
            eps_r = q.get("eps_reported")
            surp = q.get("surprise_pct")
            actual_cell = f"{cur}{eps_r:,.2f}" if eps_r is not None else "\u2013"
            surprise_cell = "\u2013"
            if surp is not None:
                color = "#34d399" if surp > 0 else "#f87171"
                arrow = "\u25b2" if surp > 0 else "\u25bc"
                sign = "+" if surp > 0 else ""
                actual_cell = f'<span style="color:{color}">{actual_cell}</span>'
                surprise_cell = f'<span style="color:{color}">{arrow} {sign}{surp:.1f}%</span>'
            rev_cell = "\u2013"
            days_cell = "\u2713"
            badge = "reported"
        else:
            # --- UPCOMING: show next earnings date + estimates ---
            actual_cell = "\u2013"
            surprise_cell = "\u2013"
            if upcoming:
                u = upcoming[0]
                dt = datetime.fromisoformat(u["date"])
                days_away = (dt.date() - today_et).days
                day_str = dt.strftime("%a")
                mdate_str = dt.strftime("%b %d")
                iso_date = dt.strftime("%Y-%m-%d")
                timing = u.get("time", "TBD")
                eps_est = u.get("eps_consensus") or u.get("eps_estimate")
                eps_cell = f"{fin_cur}{eps_est:,.2f}" if eps_est else "\u2013"
                rev = u.get("rev_consensus")
                rev_cell = _fmt_rev(rev, fin_cur)
                days_cell = "TODAY" if days_away <= 0 else f"{days_away}d"
                badge = "soon" if days_away <= 7 else "mid" if days_away <= 30 else "later"
            else:
                day_str = "\u2013"
                mdate_str = "TBD"
                iso_date = "9999-99-99"
                timing = ""
                eps_cell = "\u2013"
                rev_cell = "\u2013"
                days_cell = "\u2013"
                days_away = 999
                badge = "later"

        rows_html.append(f"""<tr class="{badge}" data-cat="{cat}" data-days="{days_away}">
  <td><strong>{sym}</strong></td>
  <td>{name}</td>
  <td><span class="cat {cat_cls}">{cat}</span></td>
  <td>{day_str}</td>
  <td data-sort="{iso_date}">{mdate_str}</td>
  <td>{timing}</td>
  <td class="num">{eps_cell}</td>
  <td class="num">{actual_cell}</td>
  <td class="num">{surprise_cell}</td>
  <td class="num">{rev_cell}</td>
  <td class="num">{days_cell}</td>
  <td class="num">{streak}</td>
</tr>""")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>Earnings Calendar \u2014 Big Tech, AI &amp; Memory</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:#0f172a;color:#e2e8f0;padding:20px 24px}}
  h1{{color:#5eead4;font-size:1.4rem;margin-bottom:2px;letter-spacing:-0.02em}}
  .meta{{color:#64748b;font-size:0.8rem;margin-bottom:16px}}
  table{{width:100%;border-collapse:collapse;font-size:0.85rem}}
  th{{background:#1e293b;color:#94a3b8;padding:8px 10px;text-align:left;
     font-weight:600;font-size:0.75rem;text-transform:uppercase;letter-spacing:0.05em;
     position:sticky;top:0;cursor:pointer;user-select:none;white-space:nowrap}}
  th:hover{{color:#5eead4}}
  td{{padding:7px 10px;border-bottom:1px solid #1e293b;white-space:nowrap}}
  td.num{{text-align:right;font-variant-numeric:tabular-nums}}
  tr:hover{{background:#1e293b}}
  tr.soon td{{background:rgba(250,204,21,0.08)}}
  tr.soon:hover td{{background:rgba(250,204,21,0.15)}}
  tr.reported td{{background:rgba(52,211,153,0.06)}}
  tr.reported:hover td{{background:rgba(52,211,153,0.12)}}
  .cat{{padding:2px 8px;border-radius:10px;font-size:0.7rem;font-weight:500}}
  .big-tech{{background:#312e81;color:#a5b4fc}}
  .ai-chips{{background:#064e3b;color:#6ee7b7}}
  .memory{{background:#7c2d12;color:#fdba74}}
  .ai-software-cloud{{background:#1e3a5f;color:#7dd3fc}}
  .bar{{margin:12px 0 8px;display:flex;gap:6px;flex-wrap:wrap;align-items:center}}
  .btn{{padding:4px 12px;border:1px solid #334155;border-radius:14px;
       background:transparent;color:#94a3b8;cursor:pointer;font-size:0.75rem;
       transition:all 0.15s}}
  .btn:hover{{border-color:#5eead4;color:#5eead4}}
  .btn.on{{background:#0d9488;color:#f0fdfa;border-color:#0d9488}}
  .footer{{margin-top:20px;color:#475569;font-size:0.75rem;text-align:center}}
</style>
</head>
<body>
<h1>Earnings Calendar</h1>
<p class="meta">Big Tech &middot; AI &amp; Chips &middot; Memory &middot; Updated {now.strftime('%b %d %Y %H:%M UTC')}</p>

<div class="bar">
  <button class="btn on" onclick="filt('all')">All ({len(results)})</button>
  {''.join(f'<button class="btn" onclick="filt(this,&apos;{cat}&apos;)">{cat} ({sum(1 for r in results if r["category"]==cat)})</button>' for cat in WATCHLIST)}
</div>

<table id="t">
<thead><tr>
  <th onclick="doSort(0)">Ticker</th>
  <th onclick="doSort(1)">Company</th>
  <th onclick="doSort(2)">Category</th>
  <th onclick="doSort(3)">Day</th>
  <th onclick="doSort(4,'d')">Date</th>
  <th onclick="doSort(5)">When</th>
  <th onclick="doSort(6)">EPS Est.</th>
  <th onclick="doSort(7)">Actual</th>
  <th onclick="doSort(8)">Surprise</th>
  <th onclick="doSort(9)">Rev Est.</th>
  <th onclick="doSort(10,'n')">In</th>
  <th onclick="doSort(11)">Beats</th>
</tr></thead>
<tbody>
{''.join(rows_html)}
</tbody>
</table>

<p class="footer">Data: Yahoo Finance via yfinance &middot; Estimates are consensus</p>

<script>
let sc=-1,sa=true;
function doSort(c,type){{
  const tb=document.querySelector('#t tbody');
  const rows=[...tb.querySelectorAll('tr')];
  if(sc===c)sa=!sa;else{{sc=c;sa=true}}
  rows.sort((a,b)=>{{
    let av,bv;
    if(type==='d'){{
      av=a.cells[c].dataset.sort||'9999';bv=b.cells[c].dataset.sort||'9999';
      return sa?av.localeCompare(bv):bv.localeCompare(av);
    }}
    av=a.cells[c].textContent.trim();bv=b.cells[c].textContent.trim();
    if(type==='n'){{
      const an=parseFloat(av)||9999,bn=parseFloat(bv)||9999;
      return sa?an-bn:bn-an;
    }}
    return sa?av.localeCompare(bv):bv.localeCompare(av);
  }});
  rows.forEach(r=>tb.appendChild(r));
}}
function filt(el,cat){{
  if(!cat)cat='all';
  document.querySelectorAll('.btn').forEach(b=>b.classList.remove('on'));
  (el||event.target).classList.add('on');
  document.querySelectorAll('#t tbody tr').forEach(tr=>{{
    tr.style.display=(cat==='all'||tr.dataset.cat===cat)?'':'none';
  }});
}}
doSort(4,'d');
</script>
</body>
</html>"""

    path.write_text(html, encoding="utf-8")
    print(f"  HTML \u2192 {path}", file=sys.stderr)


DEPLOY_REPO = Path(__file__).resolve().parent.parent / "earnings-deploy"
PAGES_URL = "https://rosh-photo.github.io/earnings-calendar/"


def deploy(html_path: Path) -> None:
    """Copy HTML to the GitHub Pages repo, commit, and push."""
    import subprocess

    if not DEPLOY_REPO.is_dir():
        print(f"  Deploy repo not found at {DEPLOY_REPO}", file=sys.stderr)
        print("  Run: git clone git@github.com:rosh-photo/earnings-calendar.git "
              f"{DEPLOY_REPO}", file=sys.stderr)
        return

    import shutil
    dest = DEPLOY_REPO / "index.html"
    shutil.copy2(html_path, dest)

    subprocess.run(["git", "add", "index.html"], cwd=DEPLOY_REPO, check=True)

    # Check if there are changes to commit
    result = subprocess.run(["git", "diff", "--cached", "--quiet"],
                            cwd=DEPLOY_REPO)
    if result.returncode == 0:
        print("  No changes to deploy.", file=sys.stderr)
        print(f"  Live at {PAGES_URL}", file=sys.stderr)
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    subprocess.run(["git", "commit", "-m", f"Update earnings calendar — {now}"],
                   cwd=DEPLOY_REPO, check=True)
    subprocess.run(["git", "push"], cwd=DEPLOY_REPO, check=True)
    print(f"  Deployed → {PAGES_URL}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Earnings calendar tracker")
    parser.add_argument("--weeks", type=int, default=8, help="Look-ahead window in weeks")
    parser.add_argument("--all", action="store_true", help="Include recent past results")
    parser.add_argument("--json", action="store_true", help="Write JSON output")
    parser.add_argument("--html", action="store_true", help="Write HTML dashboard")
    parser.add_argument("--deploy", action="store_true",
                        help="Generate HTML, commit and push to GitHub Pages")
    parser.add_argument("--output", type=str,
                        help="Write HTML to specific path (for CI)")
    args = parser.parse_args()

    print(f"Fetching earnings for {len(ALL_SYMBOLS)} stocks...", file=sys.stderr)
    results = fetch_earnings(ALL_SYMBOLS)

    if not args.output:
        print_calendar(results, weeks=args.weeks, show_recent=args.all)

    out_dir = Path(__file__).resolve().parent.parent / "outputs"
    out_dir.mkdir(exist_ok=True)

    if args.json:
        write_json(results, out_dir / "earnings_calendar.json")

    if args.output:
        write_html(results, Path(args.output))
    elif args.html or args.deploy:
        write_html(results, out_dir / "earnings_calendar.html")

    if args.deploy:
        deploy(out_dir / "earnings_calendar.html")


if __name__ == "__main__":
    main()
