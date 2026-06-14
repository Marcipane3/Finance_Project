"""
Thesis writer for Track B.

Calls the Claude API to generate a ~1,500-word investment thesis for the
top-ranked stock pick. Accepts the pick row from run_ranker() plus the
remaining ranked candidates for "why not the alternatives" context.

Results are cached per ticker per calendar date — re-runs within the same
day return the cached thesis without consuming API tokens.

Requires ANTHROPIC_API_KEY in .env (loaded via python-dotenv).
"""

import logging
import os
from datetime import date
from pathlib import Path

import anthropic
import numpy as np
import pandas as pd
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_THESIS_CACHE_DIR = Path(__file__).parent.parent / "data" / "cache" / "thesis"

# Brief role prompt — kept small deliberately; the cached prefix is completed by
# _FORMAT_INSTRUCTIONS in the user message, which pushes the total past 1024 tokens.
_SYSTEM_PROMPT = """\
You are a professional equity research analyst writing for Marcel, a sophisticated individual \
investor managing a concentrated single-stock sleeve (~€2,000) with a medium-term horizon of \
4–12 weeks. Marcel has a master's degree in industrial engineering and management and a strong \
quantitative finance background. He can handle nuance and directness. Be direct and analytical \
— this is not marketing copy. Cite the specific data points provided. Flag genuine risks clearly \
and do not hedge everything.\
"""

# Static format instructions — placed as the first content block in the user message with
# cache_control: ephemeral. Combined with _SYSTEM_PROMPT this block exceeds the 1024-token
# minimum required for prompt caching to activate.
_FORMAT_INSTRUCTIONS = """\
Format the investment thesis according to the specifications below. These instructions are \
constant across all picks — only the pick data block that follows will change.

Write approximately 1,500 words in long-form markdown. Use the six section headers listed \
below, in order. Do not add sections, rename headers, or reorder them.

---

## Company Snapshot

Two to three sentences only. State what the company does, its sector, and its key revenue \
drivers. Include the current market cap, current price, and currency in the first sentence. \
Lead with what makes this business distinctive — its moat, pricing power, switching costs, \
or structural tailwind. Avoid generic sector descriptions such as "a leading player in the \
technology sector."

## Bull Case

Identify the two or three strongest reasons to own this stock right now. Each reason must be \
grounded in the signal data provided — not in general business quality. Reference specific \
numbers: earnings surprise magnitude, analyst upside percentage, revenue or earnings growth \
rate, and momentum figures. Focus on what has changed or is changing — a catalyst, an \
inflection point, a re-rating. A reader should understand why this week, not just why ever. \
Target 200–300 words.

## Bear Case & Key Risks

Identify the two or three most credible risks specific to this company and this entry point. \
Avoid generic macro risks unless they have a documented, outsized impact on this company's \
revenue model or cost structure. For each risk, name an observable trigger to watch — a data \
release, guidance revision, margin move, or price level — that would indicate the bear case \
is playing out. Target 200–300 words.

## Why Now

Explain what makes today a better entry point than one month ago or three months from now. \
Reference technical signals explicitly: RSI-14 level and what it implies (above 70 = \
overbought, below 30 = oversold, 40–60 = neutral), proximity to 52-week high (above 95% = \
at/near high; below 80% = significant pullback), and position relative to MA-50 (above = \
uptrend confirmed; below = caution). Classify the setup: new-high breakout, pullback to \
support, base breakout, or momentum continuation. Do not write generic statements about \
attractive valuations unless the forward P/E data supports them. Target 150–250 words.

## Why Not the Alternatives

For each runner-up candidate provided, write two to three sentences explaining why the top \
pick is preferred. Address the specific trade-off: does the alternative have better \
fundamentals but weaker momentum? Higher valuation with inferior earnings growth? Lower \
analyst conviction? The reader must understand the concrete reason — not a score comparison. \
If no alternatives are provided, state that explicitly.

## Position Parameters

Provide these bullet points exactly, with no additional prose:
- Entry rationale: one sentence only
- Stop-loss: -10% from current price — state the exact stop price and the EUR loss on a \
  €2,000 sleeve (format: "Stop: $XXX.XX — max loss ~€200 on €2,000 sleeve")
- Review cadence: monthly
- Sleeve size: ~€2,000, 100% in this single name
- Approximate shares: €2,000 ÷ current price, rounded to the nearest whole share

---

Data interpretation guidelines:
- earnings_surprise: percentage beat/miss vs. consensus EPS estimate. A value of 0.10 means \
  a 10% beat; -0.05 means a 5% miss. If N/A, note this — it may mean no consensus existed, \
  not that earnings were bad.
- momentum_12_1: 12-month return excluding the most recent month (avoids short-term reversal \
  noise). Positive = strong intermediate trend.
- momentum_1: 1-month return. Negative may indicate a pullback within a longer uptrend — \
  not automatically bearish.
- analyst_upside: (mean price target − current price) / current price. Represents analyst \
  consensus implied return. Treat with scepticism — targets lag price action.
- analyst_rating: 1.0 = strong buy, 2.0 = buy, 3.0 = hold, 4.0 = sell, 5.0 = strong sell. \
  Below 2.5 = bullish consensus; above 3.5 = bearish consensus.
- forward_pe: next-twelve-months P/E estimate. Evaluate relative to sector and historical \
  range — not as an absolute number.
- realized_vol_30d: 30-day annualised realised volatility. A value of 0.35 means 35% \
  annualised. Relevant context for interpreting the stop-loss level.

Quality standards:
- Every sentence must carry analytical weight. Remove filler ("It is worth noting that..."). \
- If signals are uniformly near median with no clear catalyst, state uncertainty directly \
  rather than manufacturing conviction. Marcel prefers honest uncertainty to confident noise.
- Begin directly with ## Company Snapshot — no preamble or introductory paragraph.
- Bold key figures and ticker symbols on first mention in each section.
- Percentages: one decimal place, always with % (e.g., +12.4%).
- Prices: two decimal places in local currency from pick data.
- When a signal is N/A or NaN, acknowledge the data gap — do not fabricate a trend.
- Do not end with a disclaimer, signature, or "Note:" footer.
"""


def generate_thesis(
    pick: pd.Series,
    alternatives: pd.DataFrame,
    config: dict,
) -> str:
    """Return a ~1,500-word markdown thesis for the top-ranked pick.

    Parameters
    ----------
    pick         : single-row Series — iloc[0] of run_ranker() output
    alternatives : remaining rows — iloc[1:] of run_ranker() output (top 4 used)
    config       : parsed config.yaml

    Returns
    -------
    Markdown string. Cached per ticker per calendar date — safe to call multiple
    times in the same day without burning API tokens.
    """
    _THESIS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ticker = str(pick.get("ticker", "UNKNOWN"))
    cache_path = _THESIS_CACHE_DIR / f"{ticker.replace('/', '_')}_{date.today()}.md"

    if cache_path.exists():
        logger.info("Thesis: cache hit for %s (%s) — skipping API call", ticker, date.today())
        return cache_path.read_text(encoding="utf-8")

    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Add it to .env — see .env.example."
        )

    thesis_cfg = config["track_b"]["thesis"]
    model: str = thesis_cfg.get("model", "claude-sonnet-4-6")
    max_tokens: int = thesis_cfg.get("max_tokens_per_pick", 3500)

    pick_data = _build_user_message(pick, alternatives)
    logger.info("Thesis: calling %s for %s (max_tokens=%d)", model, ticker, max_tokens)

    client = anthropic.Anthropic(api_key=api_key)
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                # Static block cached at the 1024-token threshold with system prompt.
                # Free on all calls after the first each day.
                {
                    "type": "text",
                    "text": _FORMAT_INSTRUCTIONS,
                    "cache_control": {"type": "ephemeral"},
                },
                # Dynamic block with pick-specific data — not cached.
                {
                    "type": "text",
                    "text": pick_data,
                },
            ],
        }],
    ) as stream:
        message = stream.get_final_message()

    usage = message.usage
    logger.info(
        "Thesis: done — in=%d out=%d cache_read=%d cache_write=%d",
        usage.input_tokens,
        usage.output_tokens,
        getattr(usage, "cache_read_input_tokens", 0),
        getattr(usage, "cache_creation_input_tokens", 0),
    )
    if usage.output_tokens >= max_tokens - 50:
        logger.warning(
            "Thesis: output_tokens=%d ≥ max_tokens-50=%d — response likely truncated. "
            "Increase max_tokens_per_pick in config.yaml.",
            usage.output_tokens, max_tokens - 50,
        )

    thesis = message.content[0].text
    cache_path.write_text(thesis, encoding="utf-8")
    logger.info("Thesis: cached to %s", cache_path)
    return thesis


# ── prompt builders ───────────────────────────────────────────────────────────

def _build_user_message(pick: pd.Series, alternatives: pd.DataFrame) -> str:
    return "\n".join([
        "Generate the investment thesis for the following top pick.",
        "",
        "# Top Pick Data",
        "",
        _format_pick(pick),
        "",
        "# Runner-Up Candidates (for 'Why Not the Alternatives' section)",
        "",
        _format_alternatives(alternatives),
    ])


def _format_pick(pick: pd.Series) -> str:
    ticker   = pick.get("ticker", "?")
    name     = pick.get("name", "")
    index_   = pick.get("index", "")
    sector   = pick.get("sector", "")
    industry = pick.get("industry", "")
    currency = str(pick.get("currency", "USD"))

    lines = [
        f"**Ticker:** {ticker} | **Name:** {name} | **Index:** {index_}",
        f"**Sector:** {sector} | **Industry:** {industry}",
        f"**Currency:** {currency} | "
        f"**Current Price:** {_fmt(pick.get('current_price'))} {currency} | "
        f"**Market Cap:** {_fmt_market_cap(pick.get('market_cap'), currency)}",
        "",
        "### Technical Signals",
        f"- RSI-14: {_fmt(pick.get('rsi_14'))}",
        f"- Price vs 52-week high: {_fmt(pick.get('price_vs_52w_high'), pct=True)}"
        f" ({'at/near high' if _gt(pick.get('price_vs_52w_high'), 0.95) else 'below high'})",
        f"- Price vs MA-50: {_fmt(pick.get('price_vs_ma50'), pct=True)}"
        f" ({'above' if _gt(pick.get('price_vs_ma50'), 1.0) else 'below'} 50-day average)",
        f"- Realized volatility (30d annualised): {_fmt(pick.get('realized_vol_30d'), pct=True)}",
        f"- Momentum 12m-1m: {_fmt(pick.get('momentum_12_1'), pct=True)}",
        f"- Momentum 1m: {_fmt(pick.get('momentum_1'), pct=True)}",
        "",
        "### Fundamental Signals",
        f"- Forward P/E: {_fmt(pick.get('forward_pe'))}x",
        f"- Revenue growth (YoY): {_fmt(pick.get('revenue_growth'), pct=True)}",
        f"- Earnings growth (YoY): {_fmt(pick.get('earnings_growth'), pct=True)}",
        f"- Profit margin: {_fmt(pick.get('profit_margin'), pct=True)}",
        "",
        "### Analyst & Sentiment Signals",
        f"- Analyst upside to mean price target: {_fmt(pick.get('analyst_upside'), pct=True)}",
        f"- Analyst rating (1=Strong Buy … 5=Strong Sell): {_fmt(pick.get('analyst_rating'))}",
        f"- Short ratio: {_fmt(pick.get('short_ratio'))}",
        f"- Net analyst upgrades (last 30d): {_fmt(pick.get('analyst_upgrade_30d'))}",
        f"- News items published (last 30d): {_fmt(pick.get('news_volume_30d'))}",
        f"- Earnings surprise (most recent quarter): {_fmt(pick.get('earnings_surprise'), pct=True)}",
        "",
        f"**Composite rank score:** {_fmt(pick.get('composite_score'))}",
    ]
    return "\n".join(lines)


def _format_alternatives(alternatives: pd.DataFrame) -> str:
    top4 = alternatives.head(4)
    if top4.empty:
        return "_No runner-up candidates provided._"
    rows: list[str] = []
    for _, row in top4.iterrows():
        ticker   = row.get("ticker", "?")
        name     = row.get("name", "")
        sector   = row.get("sector", "")
        score    = _fmt(row.get("composite_score"))
        upside   = _fmt(row.get("analyst_upside"), pct=True)
        eg       = _fmt(row.get("earnings_growth"), pct=True)
        fwd_pe   = _fmt(row.get("forward_pe"))
        mom12    = _fmt(row.get("momentum_12_1"), pct=True)
        rows.append(
            f"- **{ticker}** ({name}, {sector}): "
            f"score={score}, analyst_upside={upside}, earnings_growth={eg}, "
            f"forward_pe={fwd_pe}x, momentum_12m={mom12}"
        )
    return "\n".join(rows)


# ── formatting helpers ────────────────────────────────────────────────────────

def _fmt(val, pct: bool = False) -> str:
    try:
        f = float(val)
        if not np.isfinite(f):
            return "N/A"
        return f"{f * 100:.1f}%" if pct else f"{f:.2f}"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_market_cap(val, currency: str) -> str:
    try:
        mc = float(val)
        if not np.isfinite(mc):
            return "N/A"
        # yfinance returns UK market_cap in GBp (pence) — convert to GBP
        if currency.upper() == "GBP":
            mc /= 100
        if mc >= 1e12:
            return f"{mc / 1e12:.2f}T {currency}"
        if mc >= 1e9:
            return f"{mc / 1e9:.1f}B {currency}"
        if mc >= 1e6:
            return f"{mc / 1e6:.0f}M {currency}"
        return f"{mc:.0f} {currency}"
    except (TypeError, ValueError):
        return "N/A"


def _gt(val, threshold: float) -> bool:
    try:
        return float(val) > threshold
    except (TypeError, ValueError):
        return False
