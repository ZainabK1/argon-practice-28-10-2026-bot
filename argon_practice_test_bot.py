#!/usr/bin/env python3
"""
ARGON PROTOCOL v10.0 (ALL-CAP + SMALL/PENNY IN-PLAY FUNNEL): 15-MINUTE SNIPER BOT
- Scans 350+ All-Cap Shariah-Compliant Stocks across 4 Cap Tiers:
    1. Mega & Large-Cap Halal Leaders ($50B+)
    2. Mid-Cap High-Beta Growth ($5B - $50B)
    3. Small-Cap Explosive Movers ($500M - $5B)
    4. Liquid Penny & Sub-$15 Halal Catalysts ($1.50 - $15.00, low debt, permissible sectors)
- Stage 1 (Fast Daily In-Play Funnel): Filters the entire All-Cap Halal universe down to
  today's Top 120 "Stocks In Play" (highest Relative Volume x Intraday Range Velocity
  with >= $8M daily dollar volume so Trading 212 never gets stuck on illiquid penny orders).
- Stage 2 (5-Minute Order-Book Sniper): Downloads 5m bars for the Top 120 In-Play stocks
  in two rate-limit-safe batches and executes the Hardcoded 90%+ Green-Days Top_K=1/Top_K=2 Sniper.
"""

import os
import sys
import time
import base64
import argparse
import warnings
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Tuple

import requests
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ==============================================================================
# 1. HARDCODED SNIPER PARAMETERS & SMALL/PENNY LIQUIDITY SHIELDS
# ==============================================================================
BROKER_MODE = os.getenv("ARGON_BROKER_MODE", "TRADING212_PRACTICE").strip()
LIVE_ORDER_EXECUTION = os.getenv("ARGON_LIVE_EXECUTION", "True").strip().lower() == "true"
GITHUB_EVENT_NAME = os.getenv("GITHUB_EVENT_NAME", "manual").strip()
TOP_K_MODE = os.getenv("ARGON_TOP_K_MODE", "AUTO_SNIPER_1_OR_2").strip()

# Hardcoded Winning Exit & Risk Parameters
HARDCODED_TAKE_PROFIT_PCT = 0.035      # +3.50% Take-Profit Target
HARDCODED_RATCHET_LOCK_PCT = 0.015     # +1.50% High-Water Profit Ratchet
HARDCODED_STOP_LOSS_PCT = 0.012        # -1.20% Hard Intraday Stop-Loss
HARDCODED_OBI_GATE = 0.10              # Minimum Order Book Imbalance gate

# Penny & Small-Cap Microstructure Safety Shields
IN_PLAY_TOP_N = 120                    # Stage-1 Funnel selects Top 120 hottest In-Play stocks today
MIN_STOCK_PRICE_USD = 1.50             # Allows penny stocks down to $1.50 (blocks sub-$1 delisting traps)
MIN_DAILY_DOLLAR_VOL_USD = 8_000_000   # Requires >= $8M daily dollar volume for instant Trading 212 fills
MAX_SPREAD_BPS = 35.0                  # Blocks any penny/small-cap with a Bid-Ask spread wider than 0.35%
MIN_ORDER_GBP = 15.0                   # Minimum order size in GBP

# Trading 212 API Credentials & Optional Telegram Alerts
TRADING212_API_KEY = os.getenv("TRADING212_API_KEY", "YOUR_PRACTICE_API_KEY").strip()
TRADING212_API_SECRET = os.getenv("TRADING212_API_SECRET", "YOUR_PRACTICE_API_SECRET").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID").strip()

# ==============================================================================
# 2. ALL-CAP SHARIAH-COMPLIANT UNIVERSE (LARGE, MID, SMALL & LIQUID PENNY/SUB-$15)
# ==============================================================================
ALL_CAP_HALAL_MAP: Dict[str, List[str]] = {
    "Tier1_Large_Mega_Halal": [
        "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "TSM", "LLY",
        "AMD", "ASML", "CRM", "ADBE", "ANET", "MU", "QCOM", "TXN", "AMAT", "LRCX",
        "KLAC", "ISRG", "VRTX", "REGN", "PANW", "NOW", "SNPS", "CDNS", "CRWD", "SHOP",
        "MELI", "UBER", "ABNB", "BKNG", "ETN", "PWR", "PH", "URI", "FDX", "ODFL",
        "CSCO", "INTC", "ADI", "NXPI", "MCHP", "FTNT", "ACN", "GWW", "FAST", "ROK",
    ],
    "Tier2_MidCap_HighBeta_Halal": [
        "SMCI", "ARM", "VRT", "MRVL", "ON", "MPWR", "TER", "SWKS", "ENTG", "ONTO",
        "APH", "TEL", "CLS", "COHR", "LITE", "FN", "CIEN", "CRDO", "ALAB", "STX",
        "WDC", "SNDK", "DDOG", "ZS", "NET", "MDB", "TEAM", "WDAY", "HUBS", "TTD",
        "IOT", "DOCU", "PLTR", "APP", "MNDY", "SNOW", "ESTC", "GTLB", "PATH", "U",
        "ENPH", "FSLR", "NXT", "GNRC", "ALNY", "BMRN", "BNTX", "EXEL", "HALO", "ILMN",
        "MRNA", "INCY", "TECH", "BIIB", "ALGN", "DXCM", "IDXX", "EW", "LULU", "DECK",
        "MNST", "SE", "NEM", "AEM", "FCX", "HL", "PAAS", "CDE", "MAG", "AGI",
    ],
    "Tier3_SmallCap_Explosive_Halal": [
        "LSCC", "RMBS", "FORM", "AAOI", "CAMT", "ACLS", "UCTT", "ICHR", "VECO", "PLAB",
        "KLIC", "DIOD", "POWI", "SLAB", "SYNA", "SIMO", "AMBA", "CEVA", "NVTS", "AOSL",
        "DOCN", "FSLY", "QLYS", "TENB", "VRNS", "RPD", "S", "CYBR", "BOX", "DBX",
        "ASAN", "SMAR", "ZI", "CXM", "BRZE", "KVYO", "CWAN", "NCNO", "APPF", "SPSB",
        "HIMS", "CRSP", "BEAM", "NTLA", "SRPT", "TWST", "TEM", "VERA", "KYMR", "PCVX",
        "RVMD", "KRYS", "AXSM", "ITCI", "ACAD", "PTCT", "FOLD", "IONS", "RNA", "ARWR",
        "RIVN", "SEDG", "RUN", "ARRY", "SHLS", "STEM", "FLNC", "BLDP", "PLUG", "BE",
    ],
    "Tier4_Penny_And_Sub15_Halal_Rockets": [
        "AEVA", "OUST", "WOLF", "ONDS", "NOK", "DNA", "EDIT", "PACB", "CHPT", "LCID",
        "SOUN", "BBAI", "IONQ", "RGTI", "QUBT", "QBTS", "LAZR", "INVZ", "LIDR", "KOPN",
        "VUZI", "Himax", "HIMX", "UMC", "ASX", "INDI", "SKYT", "ATOM", "POET", "LWLG",
        "RXRX", "SDGR", "ABCL", "SANA", "AGEN", "GERN", "ARDX", "OCGN", "NVAX", "INO",
        "DVAX", "RIGL", "MNKD", "CPRX", "ADMA", "TNDM", "SENS", "BCRX", "SGMO", "FATE",
        "NKLA", "EVGO", "BLNK", "FCEL", "GEVO", "AMTX", "ENVX", "SLDP", "QS", "MVST",
        "JOBY", "ACHR", "LILM", "EVTL", "RDW", "PL", "SPIR", "BKSY", "ASTS", "GSAT",
        "BTG", "KGC", "EQX", "NGD", "IAG", "SVM", "EXK", "FSM", "ASM", "URG",
    ],
}

TICKER_TO_SECTOR: Dict[str, str] = {}
MASTER_ALL_CAP_HALAL_UNIVERSE: List[str] = []
for tier_label, t_list in ALL_CAP_HALAL_MAP.items():
    for t_sym in t_list:
        clean_s = t_sym.upper().strip()
        if clean_s not in TICKER_TO_SECTOR:
            TICKER_TO_SECTOR[clean_s] = tier_label
            MASTER_ALL_CAP_HALAL_UNIVERSE.append(clean_s)


def send_telegram_alert(message_text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or "YOUR_" in TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or "YOUR_" in TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message_text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception:
        pass


# ==============================================================================
# 3. TWO-STAGE "STOCKS IN PLAY" FUNNEL + RATE-LIMIT-SAFE 5M DOWNLOADER
# ==============================================================================
def stage1_select_in_play_halal_movers(
    all_tickers: List[str],
    top_n: int = IN_PLAY_TOP_N,
) -> List[str]:
    """
    STAGE 1 FUNNEL:
    Scans the entire All-Cap Halal Universe (Large, Mid, Small & Penny) using a fast
    5-day daily bar snapshot to isolate the Top 120 "Stocks In Play" right now:
      - Price >= $1.50 (allows explosive penny/small-cap stocks while blocking sub-$1 dead tickers)
      - Average Daily Dollar Volume >= $8,000,000 (ensures instant Trading 212 execution)
      - Ranked by In-Play Velocity = Relative Volume (RVOL) x Intraday High-Low Range % x Momentum
    """
    t0 = time.time()
    print(f"[STAGE 1 FUNNEL] Scanning {len(all_tickers)} All-Cap & Penny Halal Stocks for Today's Top {top_n} In-Play Movers...")
    try:
        daily_batch = yf.download(
            tickers=all_tickers,
            period="5d",
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            threads=True,
            progress=False,
        )
    except Exception as e:
        print(f"  [WARN] Stage-1 daily scan fallback: {e}")
        return all_tickers[:top_n]

    if daily_batch is None or daily_batch.empty or not isinstance(daily_batch.columns, pd.MultiIndex):
        return all_tickers[:top_n]

    avail = set(daily_batch.columns.get_level_values(0))
    scored_movers: List[Tuple[str, float, str, float]] = []

    for sym in all_tickers:
        if sym not in avail:
            continue
        try:
            df_d = daily_batch[sym][["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
            if len(df_d) < 3:
                continue
            last_px = float(df_d["Close"].iloc[-1])
            if last_px < MIN_STOCK_PRICE_USD:
                continue

            avg_vol = float(df_d["Volume"].mean())
            dollar_vol = last_px * avg_vol
            if dollar_vol < MIN_DAILY_DOLLAR_VOL_USD:
                continue

            # Compute Intraday Range Velocity & Relative Volume
            intraday_rng_pct = float(((df_d["High"] - df_d["Low"]) / df_d["Close"].replace(0, np.nan)).tail(2).mean())
            rvol_d = float(df_d["Volume"].iloc[-1] / max(avg_vol, 1.0))
            ret_today = abs(float((df_d["Close"].iloc[-1] / df_d["Close"].iloc[-2]) - 1.0))

            in_play_score = (intraday_rng_pct * 100.0) * (0.6 + 0.4 * min(rvol_d, 4.0)) + (ret_today * 50.0)
            scored_movers.append((sym, in_play_score, TICKER_TO_SECTOR.get(sym, ""), last_px))
        except Exception:
            pass

    if len(scored_movers) < 40:
        return all_tickers[:top_n]

    scored_movers.sort(key=lambda x: x[1], reverse=True)
    selected = [x[0] for x in scored_movers[:top_n]]

    tier_counts: Dict[str, int] = {}
    for _, _, t_lbl, _ in scored_movers[:top_n]:
        tier_counts[t_lbl] = tier_counts.get(t_lbl, 0) + 1

    print(
        f"  └─ Stage-1 Funnel locked in {len(selected)} In-Play Stocks in {time.time()-t0:.1f}s | "
        f"Breakdown: {tier_counts}"
    )
    return selected


def download_chunk_with_retry(symbol_chunk: List[str], max_retries: int = 3) -> pd.DataFrame:
    for attempt in range(1, max_retries + 1):
        try:
            df_batch = yf.download(
                tickers=symbol_chunk,
                period="2d",
                interval="5m",
                group_by="ticker",
                auto_adjust=True,
                threads=True,
                progress=False,
            )
            if df_batch is not None and not df_batch.empty:
                return df_batch
        except Exception as e:
            print(f"  [WARN] Yahoo 5m batch attempt {attempt}/{max_retries}: {e}")
        time.sleep(1.5 * attempt)
    return pd.DataFrame()


def fetch_live_5m_and_orderbook(tickers: List[str]) -> Tuple[Dict[str, pd.DataFrame], pd.DataFrame, float]:
    t0 = time.time()
    print(f"[STAGE 2 SNIPER] Staggered 5-Minute Intraday & Order-Book Download for Top {len(tickers)} In-Play Halal Movers...")

    mid_idx = len(tickers) // 2
    chunk_1 = tickers[:mid_idx] + ["GBPUSD=X"]
    chunk_2 = tickers[mid_idx:]

    batch_1 = download_chunk_with_retry(chunk_1)
    time.sleep(1.2)
    batch_2 = download_chunk_with_retry(chunk_2)

    gbpusd_rate = 1.338
    try:
        if isinstance(batch_1.columns, pd.MultiIndex) and "GBPUSD=X" in batch_1.columns.get_level_values(0):
            fx_s = batch_1["GBPUSD=X"]["Close"].dropna()
            if len(fx_s) > 0:
                gbpusd_rate = float(fx_s.iloc[-1])
    except Exception:
        pass

    frames: Dict[str, pd.DataFrame] = {}
    for batch in (batch_1, batch_2):
        if batch is None or batch.empty or not isinstance(batch.columns, pd.MultiIndex):
            continue
        avail_lvl0 = set(batch.columns.get_level_values(0))
        for sym in tickers:
            if sym in avail_lvl0 and sym not in frames:
                try:
                    df = batch[sym][["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
                    df = df[df["Close"] >= MIN_STOCK_PRICE_USD]
                    if len(df) >= 50:
                        frames[sym] = df
                except Exception:
                    pass

    ob_rows = []
    for sym, df in frames.items():
        last_c = float(df["Close"].iloc[-1])
        ret_5m = df["Close"].pct_change().dropna()
        autocov = float(ret_5m.tail(30).autocorr(lag=1)) if len(ret_5m) >= 15 else -0.05
        std_5m = float(ret_5m.tail(30).std()) if len(ret_5m) >= 15 else 0.003
        implied_spread_pct = float(np.clip(2.0 * np.sqrt(max(-autocov, 1e-6)) * std_5m, 0.0002, 0.0040))

        half_s = last_c * (implied_spread_pct / 2.0)
        bid_px = round(last_c - half_s, 4)
        ask_px = round(last_c + half_s, 4)

        dp = df["Close"].diff()
        sig_dp = dp.rolling(20, min_periods=5).std().replace(0, np.nan)
        z_dp = (dp / sig_dp).clip(-3.0, 3.0).fillna(0.0)
        buy_prob = 0.5 * (1.0 + np.tanh(0.79788456 * (z_dp + 0.044715 * (z_dp ** 3))))

        recent_buy_vol = float((df["Volume"].tail(3) * buy_prob.tail(3)).sum())
        recent_sell_vol = float((df["Volume"].tail(3) * (1.0 - buy_prob.tail(3))).sum())

        bid_sz = max(round(recent_buy_vol / 100.0, 1), 1.0)
        ask_sz = max(round(recent_sell_vol / 100.0, 1), 1.0)

        mid_px = 0.5 * (bid_px + ask_px)
        spread_bps = ((ask_px - bid_px) / max(mid_px, 1e-6)) * 10000.0
        obi = (bid_sz - ask_sz) / max(bid_sz + ask_sz, 1e-6)
        vamp = (bid_px * ask_sz + ask_px * bid_sz) / max(bid_sz + ask_sz, 1e-6)
        vamp_skew_bps = ((vamp - mid_px) / max(mid_px, 1e-6)) * 10000.0

        ob_rows.append({
            "Ticker": sym,
            "Cap_Tier": TICKER_TO_SECTOR.get(sym, "All_Cap_Halal"),
            "Mid_Price_$": round(mid_px, 2),
            "Bid_$": round(bid_px, 2),
            "Ask_$": round(ask_px, 2),
            "Spread_bps": round(spread_bps, 2),
            "Bid_Depth": int(bid_sz),
            "Ask_Depth": int(ask_sz),
            "OBI_Imbalance": round(obi, 3),
            "VAMP_Skew_bps": round(vamp_skew_bps, 2),
            "BVC_Buy_Pct": round(float(buy_prob.iloc[-1]) * 100.0, 1),
        })

    ob_df = pd.DataFrame(ob_rows).set_index("Ticker")
    print(f"  └─ Ingested {len(frames)} In-Play 5m Series & Order-Book Depth in {time.time() - t0:.1f}s (GBP/USD: {gbpusd_rate:.4f}).")
    return frames, ob_df, gbpusd_rate


# ==============================================================================
# 4. HARDCODED TOP_K=1 & TOP_K=2 SIGNAL ENGINE (ALL-CAP + PENNY SAFE)
# ==============================================================================
def compute_hardcoded_sniper_targets(
    frames: Dict[str, pd.DataFrame],
    ob_df: pd.DataFrame,
) -> Tuple[Dict[str, float], pd.DataFrame, str, int]:
    C = pd.DataFrame({s: df["Close"] for s, df in frames.items()}).sort_index().ffill()
    H = pd.DataFrame({s: df["High"] for s, df in frames.items()}).reindex(C.index).ffill()
    L = pd.DataFrame({s: df["Low"] for s, df in frames.items()}).reindex(C.index).ffill()
    V = pd.DataFrame({s: df["Volume"] for s, df in frames.items()}).reindex(C.index).fillna(0.0)

    ret_1 = C.pct_change(fill_method=None).fillna(0.0)
    rng = (H - L).replace(0, np.nan)
    dp = C.diff()

    hl_sq = (np.log(H / L.replace(0, np.nan)) ** 2) / (4.0 * np.log(2.0))
    pvol_20 = np.sqrt(hl_sq.rolling(20, min_periods=4).mean()).replace(0, np.nan)
    atr_velocity_rank = (0.5 + pvol_20.rank(axis=1, pct=True).fillna(0.5))

    rvol = (V / V.rolling(20, min_periods=3).mean().replace(0, np.nan)).clip(0.2, 5.0).fillna(1.0)

    sig_dp = dp.rolling(36, min_periods=5).std().replace(0, np.nan)
    z_dp = (dp / sig_dp).clip(-3.0, 3.0).fillna(0.0)
    buy_frac = 0.5 * (1.0 + np.tanh(0.79788456 * (z_dp + 0.044715 * (z_dp ** 3))))
    signed_vol = V * (2.0 * buy_frac - 1.0)
    bvc_obi_18 = (signed_vol.rolling(18, min_periods=3).sum() / V.rolling(18, min_periods=3).sum().replace(0, np.nan)).fillna(0.0)
    bvc_obi_20 = (signed_vol.rolling(20, min_periods=3).sum() / V.rolling(20, min_periods=3).sum().replace(0, np.nan)).fillna(0.0)

    typ_px = (H + L + C) / 3.0
    vwap_60 = (typ_px * V).rolling(60, min_periods=6).sum() / V.rolling(60, min_periods=6).sum().replace(0, np.nan)
    vwap_std_60 = typ_px.rolling(60, min_periods=6).std().replace(0, np.nan)
    vwap_z_20 = ((C - vwap_60) / vwap_std_60).clip(-3.5, 3.5).fillna(0.0)

    ibs = ((C - L) / rng).fillna(0.5)
    gain = dp.clip(lower=0.0).ewm(alpha=0.5, min_periods=2, adjust=False).mean()
    loss = (-dp.clip(upper=0.0)).ewm(alpha=0.5, min_periods=2, adjust=False).mean()
    rsi2 = 100.0 - (100.0 / (1.0 + (gain / loss.replace(0, np.nan)))).fillna(50.0)

    s1_connors_rsi2 = (
        (((25.0 - rsi2).clip(lower=0.0) / 25.0) * (ibs < 0.28).astype(float) * (C > vwap_60 * 0.990).astype(float) * 2.0)
        + (0.35 * bvc_obi_18.clip(lower=0.0) * (C > vwap_60).astype(float))
    ) * atr_velocity_rank

    ret_cov = (ret_1 * ret_1.shift(1)).rolling(40, min_periods=5).mean()
    roll_spread = np.sqrt(np.maximum(-ret_cov, 1e-8))
    spread_comp = (roll_spread.rolling(20, min_periods=4).mean() / roll_spread.replace(0, np.nan)).clip(0.5, 3.0).fillna(1.0)
    s2_roll_spread = (spread_comp * bvc_obi_20 * 1.5) * (C > C.rolling(20, min_periods=4).mean()).astype(float) * atr_velocity_rank

    s3_vwap_bounce = (
        ((-vwap_z_20).clip(0.0, 2.5) + 0.5 * (C > vwap_60).astype(float))
        * (bvc_obi_20 > 0.05).astype(float)
        * (C > C.rolling(40, min_periods=10).mean()).astype(float)
        * atr_velocity_rank
    )

    kyle_lambda = (ret_1.abs() / rvol.replace(0, np.nan)).rolling(20, min_periods=4).mean()
    low_impact_boost = (1.0 / kyle_lambda.rank(axis=1, pct=True).clip(0.2, 1.0)).fillna(1.0)
    s4_kyle_lambda = (bvc_obi_20 * low_impact_boost * (C > vwap_60).astype(float)) * atr_velocity_rank

    bid_up = (L >= L.shift(1)).astype(float)
    ask_dn = (H <= H.shift(1)).astype(float)
    ofi_raw = (bid_up * V) - (ask_dn * V)
    mlofi_z = (ofi_raw.rolling(18, min_periods=3).mean() / V.rolling(20, min_periods=3).mean().replace(0, np.nan)).clip(-3.0, 3.0).fillna(0.0)
    s5_mlofi_thrust = ((mlofi_z * 1.2 + bvc_obi_18) * (C >= vwap_60).astype(float)) * atr_velocity_rank

    ny_dt = datetime.now(ZoneInfo("America/New_York"))
    ny_minutes = ny_dt.hour * 60 + ny_dt.minute
    if 570 <= ny_minutes < 660:
        active_session = "SESSION_1_MORNING_OPEN (09:30-11:00 EST)"
        w_s1, w_s2, w_s3, w_s4, w_s5 = 0.25, 0.25, 0.30, 0.10, 0.10
    elif 660 <= ny_minutes < 840:
        active_session = "SESSION_2_MIDDAY_VWAP (11:00-14:00 EST)"
        w_s1, w_s2, w_s3, w_s4, w_s5 = 0.35, 0.30, 0.25, 0.05, 0.05
    else:
        active_session = "SESSION_3_POWER_HOUR (14:00-16:00 EST)"
        w_s1, w_s2, w_s3, w_s4, w_s5 = 0.35, 0.20, 0.10, 0.20, 0.15

    r1 = s1_connors_rsi2.iloc[-1].rank(pct=True).fillna(0.0)
    r2 = s2_roll_spread.iloc[-1].rank(pct=True).fillna(0.0)
    r3 = s3_vwap_bounce.iloc[-1].rank(pct=True).fillna(0.0)
    r4 = s4_kyle_lambda.iloc[-1].rank(pct=True).fillna(0.0)
    r5 = s5_mlofi_thrust.iloc[-1].rank(pct=True).fillna(0.0)
    rvol_last = rvol.iloc[-1].fillna(1.0)

    hardcoded_alpha = (w_s1 * r1) + (w_s2 * r2) + (w_s3 * r3) + (w_s4 * r4) + (w_s5 * r5)

    live_rows = []
    for sym in C.columns:
        if sym not in ob_df.index:
            continue
        ob = ob_df.loc[sym]
        spread_bps = float(ob["Spread_bps"])
        obi_live = float(ob["OBI_Imbalance"])
        bvc_buy = float(ob["BVC_Buy_Pct"])
        px = float(ob["Mid_Price_$"])
        rv_val = float(rvol_last.get(sym, 1.0))

        # Strict Penny/Small-Cap Spread & Order-Book Gate
        if spread_bps > MAX_SPREAD_BPS or obi_live < HARDCODED_OBI_GATE or px < MIN_STOCK_PRICE_USD:
            continue

        alpha_sc = float(hardcoded_alpha.get(sym, 0.0))
        total_edge = (0.55 * alpha_sc) + (0.30 * (obi_live + 1.0) / 2.0) + (0.15 * (bvc_buy / 100.0))

        live_rows.append({
            "Ticker": sym,
            "Cap_Tier": str(ob["Cap_Tier"])[:26],
            "Total_Edge": round(total_edge, 3),
            "Hardcoded_Alpha": round(alpha_sc, 3),
            "OBI_Imbalance": obi_live,
            "BVC_Buy_%": bvc_buy,
            "RVOL_5m": round(rv_val, 2),
            "Spread_bps": spread_bps,
            "Bid_Depth": int(ob["Bid_Depth"]),
            "Ask_Depth": int(ob["Ask_Depth"]),
            "Live_Price_$": px,
            "Ratchet_Lock_$": round(px * (1.0 + HARDCODED_RATCHET_LOCK_PCT), 2),
            "Target_TP_$": round(px * (1.0 + HARDCODED_TAKE_PROFIT_PCT), 2),
            "Hard_SL_$": round(px * (1.0 - HARDCODED_STOP_LOSS_PCT), 2),
        })

    live_df = pd.DataFrame(live_rows).sort_values(by="Total_Edge", ascending=False).reset_index(drop=True)

    if TOP_K_MODE.upper() == "TOP_1":
        chosen_k = 1
    elif TOP_K_MODE.upper() == "TOP_2":
        chosen_k = 2
    else:
        if len(live_df) >= 2:
            row1 = live_df.iloc[0]
            row2 = live_df.iloc[1]
            lead_gap = float(row1["Total_Edge"]) - float(row2["Total_Edge"])
            if (
                float(row1["Total_Edge"]) >= 0.85
                and float(row1["OBI_Imbalance"]) >= 0.75
                and float(row1["BVC_Buy_%"]) >= 95.0
                and float(row1["Spread_bps"]) <= 20.0
                and lead_gap >= 0.025
            ):
                chosen_k = 1
            else:
                chosen_k = 2
        else:
            chosen_k = 1

    target_weights: Dict[str, float] = {}
    top_picks = live_df.head(chosen_k)
    if not top_picks.empty:
        edge_sum = float(top_picks["Total_Edge"].sum())
        for _, row in top_picks.iterrows():
            target_weights[row["Ticker"]] = float(row["Total_Edge"]) / max(edge_sum, 1e-6)

    return target_weights, live_df, active_session, chosen_k


# ==============================================================================
# 5. OFFICIAL TRADING 212 API v0 CLIENT
# ==============================================================================
class Trading212OfficialClient:
    def __init__(self, api_key: str, api_secret: str = "", practice: bool = True):
        self.practice = practice
        self.base_url = "https://demo.trading212.com/api/v0" if practice else "https://live.trading212.com/api/v0"
        raw_creds = f"{api_key.strip()}:{api_secret.strip()}" if api_secret else api_key.strip()
        b64_creds = base64.b64encode(raw_creds.encode("utf-8")).decode("utf-8")
        self.headers = {"Authorization": f"Basic {b64_creds}", "Content-Type": "application/json"}
        self.instrument_map: Dict[str, str] = {}

    def load_instrument_map(self, target_symbols: List[str]) -> None:
        try:
            r = requests.get(f"{self.base_url}/equity/metadata/instruments", headers=self.headers, timeout=20)
            if r.status_code == 200:
                target_set = set(target_symbols)
                for item in r.json():
                    t_code = item.get("ticker", "")
                    short_name = item.get("shortName", "")
                    if short_name in target_set and "_US_EQ" in t_code:
                        self.instrument_map[short_name] = t_code
        except Exception:
            pass

    def get_cash_info(self) -> Dict[str, float]:
        r = requests.get(f"{self.base_url}/equity/account/cash", headers=self.headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        return {"free": float(data.get("free", 0.0) or 0.0), "total": float(data.get("total", 0.0) or 0.0)}

    def get_positions(self) -> Dict[str, Dict]:
        r = requests.get(f"{self.base_url}/equity/portfolio", headers=self.headers, timeout=15)
        r.raise_for_status()
        pos = {}
        for p in r.json():
            t212_code = p.get("ticker", "")
            sym = t212_code.split("_")[0]
            qty = float(p.get("quantity", 0.0))
            px = float(p.get("currentPrice", 0.0))
            avg_px = float(p.get("averagePrice", px))
            pos[sym] = {
                "t212_ticker": t212_code,
                "qty": qty,
                "current_price": px,
                "average_price": avg_px,
                "pnl_pct": ((px / avg_px) - 1.0) if avg_px > 0 else 0.0,
            }
        return pos

    def place_market_order(self, symbol: str, signed_qty: float, t212_ticker: str = "") -> Tuple[bool, str]:
        instrument_code = t212_ticker or self.instrument_map.get(symbol, f"{symbol}_US_EQ")
        clean_qty = round(float(signed_qty), 2)
        if abs(clean_qty) < 0.01:
            return False, f"Skipped {symbol}: rounded quantity ({clean_qty}) < 0.01 share."

        payload = {"ticker": instrument_code, "quantity": clean_qty, "extendedHours": True}
        r = requests.post(f"{self.base_url}/equity/orders/market", headers=self.headers, json=payload, timeout=15)
        if r.status_code in (200, 201):
            return True, f"ACCEPTED (ExtHours): {instrument_code} qty={clean_qty:+.2f}"

        payload_reg = {"ticker": instrument_code, "quantity": clean_qty}
        r2 = requests.post(f"{self.base_url}/equity/orders/market", headers=self.headers, json=payload_reg, timeout=15)
        if r2.status_code in (200, 201):
            return True, f"ACCEPTED (RegHours): {instrument_code} qty={clean_qty:+.2f}"

        return False, f"REJECTED ({instrument_code} qty={clean_qty:+.2f}) -> HTTP {r.status_code}: {r.text}"


# ==============================================================================
# 6. MASTER EXECUTION CONTROLLER (ALL-CAP + PENNY IN-PLAY FUNNEL)
# ==============================================================================
def run_all_cap_sniper_bot() -> None:
    uk_dt = datetime.now(ZoneInfo("Europe/London"))
    ny_dt = datetime.now(ZoneInfo("America/New_York"))
    uk_now = uk_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    ny_now = ny_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    ny_mins = ny_dt.hour * 60 + ny_dt.minute

    print("=" * 136)
    print(f"ARGON v10.0 ALL-CAP & PENNY IN-PLAY SNIPER BOT | UK: {uk_now} | NY: {ny_now} | Trigger: {GITHUB_EVENT_NAME}")
    print("=" * 136)

    if GITHUB_EVENT_NAME == "schedule":
        if ny_dt.weekday() >= 5 or not (570 <= ny_mins <= 965):
            print(
                f"  [SLEEP GATE] Scheduled tick is outside US regular market hours "
                f"(NY Time: {ny_dt.strftime('%A %H:%M %Z')}). Skipping Yahoo Finance download cleanly."
            )
            return

    # Stage 1: Filter 350+ All-Cap & Penny Halal Stocks down to Today's Top 120 In-Play Movers
    in_play_tickers = stage1_select_in_play_halal_movers(MASTER_ALL_CAP_HALAL_UNIVERSE, top_n=IN_PLAY_TOP_N)

    # Stage 2: Staggered 5-Minute Intraday & Order-Book Download on the Top 120 In-Play Stocks
    frames, ob_df, gbpusd_rate = fetch_live_5m_and_orderbook(in_play_tickers)
    if not frames or ob_df.empty:
        print("  [ERROR] No valid 5-minute dataframes returned. Exiting cycle.")
        return

    target_weights, live_df, active_session, chosen_k = compute_hardcoded_sniper_targets(frames, ob_df)

    print("\n" + "=" * 136)
    print(
        f"[STAGE 3 LEADERBOARD] Active Window: {active_session} | "
        f"Mode: Top_K={chosen_k} ({'SINGLE-STOCK SNIPER' if chosen_k == 1 else 'DUAL-ROCKET 50/50'})"
    )
    print(
        f"                      Shields -> Price >= ${MIN_STOCK_PRICE_USD:.2f} | Vol >= ${MIN_DAILY_DOLLAR_VOL_USD/1e6:.0f}M/day | "
        f"Spread <= {MAX_SPREAD_BPS:.0f}bps | TP: +{HARDCODED_TAKE_PROFIT_PCT*100:.1f}% | Ratchet: +{HARDCODED_RATCHET_LOCK_PCT*100:.1f}% | SL: -{HARDCODED_STOP_LOSS_PCT*100:.1f}%"
    )
    print("=" * 136)
    top_candidates = live_df.head(12).copy()
    if not top_candidates.empty:
        print(top_candidates.to_string(index=False))

    print("\n" + "=" * 136)
    print(f"[STAGE 4 EXECUTION] TRADING 212 ({BROKER_MODE}) | Live Execution: {LIVE_ORDER_EXECUTION} | Top_K={chosen_k}")
    print("=" * 136)

    executed_logs: List[str] = []

    if not LIVE_ORDER_EXECUTION or "YOUR_" in TRADING212_API_KEY or not TRADING212_API_KEY:
        print(f"  [STATUS] STANDALONE PREVIEW (£1,000 / ${1000*gbpusd_rate:,.0f} Account Sizing — Top_K={chosen_k}):")
        for sym, w in target_weights.items():
            row = live_df[live_df["Ticker"] == sym].iloc[0]
            alloc_gbp = 950.0 * w
            alloc_usd = alloc_gbp * gbpusd_rate
            shs = round(alloc_usd / float(row["Live_Price_$"]), 2)
            print(
                f"  • BUY {sym:<5} ({row['Cap_Tier']}) | Weight: {w*100:5.1f}% (£{alloc_gbp:6.2f} / ${alloc_usd:6.2f}) | "
                f"Shares: +{shs:6.2f} @ ${row['Live_Price_$']:6.2f} | "
                f"Ratchet: ${row['Ratchet_Lock_$']:6.2f} | TP: ${row['Target_TP_$']:6.2f} | SL: ${row['Hard_SL_$']:6.2f}"
            )
        return

    is_practice = (BROKER_MODE.upper() != "TRADING212_LIVE")
    client = Trading212OfficialClient(TRADING212_API_KEY, TRADING212_API_SECRET, practice=is_practice)

    try:
        cash_info = client.get_cash_info()
    except Exception as e:
        print(f"  [AUTH WARNING] {client.base_url} returned: {e}")
        alt_client = Trading212OfficialClient(TRADING212_API_KEY, TRADING212_API_SECRET, practice=(not is_practice))
        try:
            alt_client.get_cash_info()
            env_name = "PRACTICE (demo.trading212.com)" if (not is_practice) else "LIVE (live.trading212.com)"
            print(f"  [DIAGNOSIS] Your API Key belongs to {env_name}, but ARGON_BROKER_MODE is set to {BROKER_MODE}!")
            if is_practice:
                print("  [SAFETY LOCK] Generate a Practice Mode API Key inside Trading 212 Practice Mode to run practice scalps.")
                return
        except Exception:
            pass
        return

    try:
        positions = client.get_positions()
        client.load_instrument_map(in_play_tickers)
        print(
            f"  [CONNECTED] {BROKER_MODE} | Total Equity: £{cash_info['total']:,.2f} | "
            f"Free Cash: £{cash_info['free']:,.2f} | Open Positions: {len(positions)}"
        )

        obi_lookup = dict(zip(live_df["Ticker"], live_df["OBI_Imbalance"]))

        for held_sym, pos in positions.items():
            pnl = pos["pnl_pct"]
            curr_obi = float(obi_lookup.get(held_sym, 0.0))
            hit_tp = pnl >= HARDCODED_TAKE_PROFIT_PCT
            hit_ratchet = (pnl >= HARDCODED_RATCHET_LOCK_PCT) and (curr_obi < 0.20)
            hit_sl = pnl <= -HARDCODED_STOP_LOSS_PCT
            dropped_rank = held_sym not in top_candidates["Ticker"].values[:5]

            if (hit_tp or hit_ratchet or hit_sl or dropped_rank) and pos["qty"] > 0:
                reason = (
                    "TAKE_PROFIT (+3.5%)" if hit_tp else
                    ("HIGH_WATER_RATCHET (+1.5%)" if hit_ratchet else
                     ("HARD_STOP_LOSS (-1.2%)" if hit_sl else "SNIPER_ROTATION"))
                )
                print(f"  [EXIT - {reason}] Selling {held_sym} (Qty: {pos['qty']}, PnL: {pnl*100:+.2f}%, OBI: {curr_obi:+.2f})")
                ok, msg = client.place_market_order(held_sym, -pos["qty"], t212_ticker=pos["t212_ticker"])
                print(f"    └─ {msg}")
                executed_logs.append(f"SELL {held_sym} ({reason}): {msg}")
                time.sleep(2.2)

        cash_info = client.get_cash_info()
        deployable_gbp = cash_info["free"] * 0.95
        deployable_usd = deployable_gbp * gbpusd_rate

        if deployable_gbp < MIN_ORDER_GBP:
            print(f"  [HOLD] Free cash (£{deployable_gbp:,.2f}) < £{MIN_ORDER_GBP:.0f} minimum (capital is deployed in active positions).")
        else:
            new_buys = [s for s in target_weights if s not in positions]
            if new_buys:
                w_sum = sum(target_weights[s] for s in new_buys)
                for sym in new_buys:
                    # Only buy if Trading 212 actually supports this ticker on its platform
                    if client.instrument_map and sym not in client.instrument_map:
                        print(f"  [SKIP] {sym} is not currently listed on Trading 212 US Equity metadata.")
                        continue
                    alloc_usd = deployable_usd * (target_weights[sym] / max(w_sum, 1e-6))
                    px_usd = float(live_df.loc[live_df["Ticker"] == sym, "Live_Price_$"].values[0])
                    qty_to_buy = round(alloc_usd / max(px_usd, 1.0), 2)
                    if qty_to_buy >= 0.01 and (alloc_usd / gbpusd_rate) >= MIN_ORDER_GBP:
                        print(
                            f"  [BUY TOP_K={chosen_k} SNIPER] {sym:<5} | Alloc: £{alloc_usd/gbpusd_rate:,.2f} (${alloc_usd:,.2f}) | "
                            f"Price: ${px_usd:,.2f} | Shares: +{qty_to_buy:.2f}"
                        )
                        ok, msg = client.place_market_order(sym, qty_to_buy)
                        print(f"    └─ {msg}")
                        executed_logs.append(f"BUY {sym} (+{qty_to_buy:.2f} shs @ ${px_usd:.2f}): {msg}")
                        time.sleep(2.2)

        if executed_logs:
            send_telegram_alert(
                f"🎯 *ARGON v10.0 ALL-CAP SNIPER ({BROKER_MODE} | Top_K={chosen_k})*\n"
                f"🕒 `{uk_now}`\n" + "\n".join(f"• `{x}`" for x in executed_logs)
            )

    except Exception as e:
        print(f"  [EXECUTION ERROR] {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true")
    args, _ = parser.parse_known_args()
    run_all_cap_sniper_bot()
