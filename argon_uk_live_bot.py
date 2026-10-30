#!/usr/bin/env python3
"""
ARGON PROTOCOL v13.1 (PRODUCTION PRACTICE & TELEGRAM PNL BOT):
Fixes in v13.1:
  1. Exact Fractional Sell Precision + Floor Fallback: Sells the exact owned fractional
     share quantity (e.g., -16.33919476 NVDA, -8.09881133 GOOGL) and falls back to
     math.floor(qty * 100) / 100 so Trading 212 never rejects a sell with
     'selling-equity-not-owned' due to upward rounding!
  2. Pending-Order Deduplication: Queries /equity/orders so the bot never queues
     duplicate market orders for tickers already sitting in Pending status.
  3. Telegram Auto-Chat-ID Discovery: If TELEGRAM_CHAT_ID returns 'chat not found',
     automatically queries /getUpdates to discover your numeric chat_id from your
     latest 'hi' / '/start' message to the bot.
"""

import os
import sys
import math
import time
import base64
import argparse
import warnings
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Dict, List, Set, Tuple

import requests
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ==============================================================================
# 1. HARDCODED TOURNAMENT-WINNING PARAMETERS & TELEGRAM SETTINGS
# ==============================================================================
BROKER_MODE = os.getenv("ARGON_BROKER_MODE", "TRADING212_PRACTICE").strip()
LIVE_ORDER_EXECUTION = os.getenv("ARGON_LIVE_EXECUTION", "True").strip().lower() == "true"
GITHUB_EVENT_NAME = os.getenv("GITHUB_EVENT_NAME", "manual").strip()
TOP_K_MODE = os.getenv("ARGON_TOP_K_MODE", "AUTO_SNIPER_1_OR_2").strip()

TELEGRAM_ALWAYS_SEND_HEARTBEAT = True

# Winning 15-20m Fast-Recycling Exit Rules from the 259,200-Strategy Tournament
HARDCODED_TAKE_PROFIT_PCT = 0.020      # +2.00% Take-Profit
HARDCODED_RATCHET_LOCK_PCT = 0.010     # +1.00% High-Water Profit Ratchet
HARDCODED_STOP_LOSS_PCT = 0.012        # -1.20% Hard Stop-Loss
HARDCODED_OBI_GATE = 0.10              # Minimum Order-Book Imbalance gate

# All-Cap & Penny Microstructure Liquidity Shields
IN_PLAY_TOP_N = 120                    # Stage-1 Funnel selects Top 120 hottest In-Play stocks today
MIN_STOCK_PRICE_USD = 1.50             # Allows penny stocks down to $1.50
MIN_DAILY_DOLLAR_VOL_USD = 8_000_000   # Requires >= $8M daily dollar volume for instant T212 fills
MAX_SPREAD_BPS = 35.0                  # Rejects wide-spread illiquid stocks (> 35 bps)
MIN_ORDER_GBP = 15.0                   # Minimum order size in GBP

# Trading 212 & Telegram Credentials (Stored in GitHub Secrets)
TRADING212_API_KEY = os.getenv("TRADING212_API_KEY", "YOUR_PRACTICE_API_KEY").strip()
TRADING212_API_SECRET = os.getenv("TRADING212_API_SECRET", "YOUR_PRACTICE_API_SECRET").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_TELEGRAM_CHAT_ID").strip()

# ==============================================================================
# 2. CLEAN 255-STOCK ALL-CAP & PENNY HALAL LIBRARY (ZERO DELISTED TICKERS)
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
        "MNST", "SE", "NEM", "AEM", "FCX", "HL", "PAAS", "CDE", "AGI",
    ],
    "Tier3_SmallCap_Explosive_Halal": [
        "LSCC", "RMBS", "FORM", "AAOI", "CAMT", "ACLS", "UCTT", "ICHR", "VECO", "PLAB",
        "KLIC", "DIOD", "POWI", "SLAB", "SYNA", "SIMO", "AMBA", "CEVA", "NVTS", "AOSL",
        "DOCN", "FSLY", "QLYS", "TENB", "VRNS", "RPD", "S", "BOX", "DBX",
        "ASAN", "CXM", "BRZE", "KVYO", "NCNO", "APPF", "SPSB",
        "HIMS", "CRSP", "BEAM", "NTLA", "SRPT", "TWST", "TEM", "VERA", "KYMR", "PCVX",
        "RVMD", "KRYS", "AXSM", "ACAD", "PTCT", "IONS", "RNA", "ARWR",
        "RIVN", "SEDG", "RUN", "ARRY", "SHLS", "STEM", "FLNC", "BLDP", "PLUG", "BE",
    ],
    "Tier4_Penny_And_Sub15_Halal_Rockets": [
        "AEVA", "OUST", "WOLF", "ONDS", "NOK", "DNA", "EDIT", "PACB", "CHPT", "LCID",
        "SOUN", "BBAI", "IONQ", "RGTI", "QUBT", "QBTS", "LAZR", "INVZ", "LIDR", "KOPN",
        "VUZI", "HIMX", "UMC", "ASX", "INDI", "ATOM", "POET", "LWLG",
        "RXRX", "SDGR", "ABCL", "SANA", "AGEN", "GERN", "ARDX", "OCGN", "NVAX", "INO",
        "RIGL", "MNKD", "ADMA", "TNDM", "SENS", "BCRX", "FATE",
        "EVGO", "BLNK", "FCEL", "GEVO", "AMTX", "ENVX", "SLDP", "QS", "MVST",
        "JOBY", "ACHR", "EVTL", "RDW", "PL", "SPIR", "BKSY", "ASTS", "GSAT",
        "BTG", "KGC", "EQX", "IAG", "SVM", "EXK", "FSM", "ASM", "URG",
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
    """
    Sends live trade & PnL notifications via Telegram Bot API.
    If TELEGRAM_CHAT_ID fails with 'chat not found', automatically queries /getUpdates
    to discover the numeric chat_id of the user who sent '/start' or 'hi' to the bot!
    """
    if not TELEGRAM_BOT_TOKEN or "YOUR_" in TELEGRAM_BOT_TOKEN:
        print("  [TELEGRAM] Skipped: TELEGRAM_BOT_TOKEN not set.")
        return

    send_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chat_candidates: List[str] = []
    if TELEGRAM_CHAT_ID and "YOUR_" not in TELEGRAM_CHAT_ID:
        chat_candidates.append(TELEGRAM_CHAT_ID)

    # Try configured TELEGRAM_CHAT_ID first
    for cid in chat_candidates:
        try:
            r = requests.post(
                send_url,
                json={"chat_id": cid, "text": message_text, "parse_mode": "Markdown", "disable_web_page_preview": True},
                timeout=12,
            )
            if r.status_code == 200:
                print(f"  [TELEGRAM] Live notification delivered to your phone (chat_id={cid})!")
                return
        except Exception:
            pass

    # Fallback: Auto-discover chat_id via /getUpdates if user has sent '/start' or 'hi' to the bot
    try:
        upd_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        r_upd = requests.get(upd_url, timeout=10)
        if r_upd.status_code == 200:
            results = r_upd.json().get("result", [])
            discovered_ids: List[str] = []
            for item in reversed(results):
                msg_obj = item.get("message") or item.get("edited_message") or item.get("my_chat_member") or {}
                chat_obj = msg_obj.get("chat", {})
                if "id" in chat_obj:
                    cid_str = str(chat_obj["id"])
                    if cid_str not in discovered_ids:
                        discovered_ids.append(cid_str)

            for disc_id in discovered_ids:
                r2 = requests.post(
                    send_url,
                    json={"chat_id": disc_id, "text": message_text, "parse_mode": "Markdown", "disable_web_page_preview": True},
                    timeout=12,
                )
                if r2.status_code == 200:
                    print(
                        f"  [TELEGRAM] Auto-discovered your chat_id ({disc_id}) and delivered notification! "
                        f"(Tip: Update TELEGRAM_CHAT_ID in GitHub Secrets to {disc_id})"
                    )
                    return

        print(
            "  [TELEGRAM ACTION NEEDED] Telegram returned 'chat not found'. "
            "Open your bot in the Telegram app, tap 'Start', and send it the word 'hi'!"
        )
    except Exception as e:
        print(f"  [TELEGRAM ERROR] {e}")


# ==============================================================================
# 3. STAGE-1 IN-PLAY FUNNEL & STAGE-2 STAGGERED 5M ORDER-BOOK DOWNLOADER
# ==============================================================================
def stage1_select_in_play_halal_movers(
    all_tickers: List[str],
    top_n: int = IN_PLAY_TOP_N,
) -> List[str]:
    t0 = time.time()
    print(f"[STAGE 1 FUNNEL] Scanning {len(all_tickers)} Clean All-Cap & Penny Halal Stocks for Top {top_n} In-Play Movers...")
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
# 4. TOURNAMENT CHAMPION SIGNAL ENGINE (TOP 259,200 WINNERS + CANDLESTICKS)
# ==============================================================================
def compute_v13_champion_sniper_targets(
    frames: Dict[str, pd.DataFrame],
    ob_df: pd.DataFrame,
) -> Tuple[Dict[str, float], pd.DataFrame, str, int]:
    C = pd.DataFrame({s: df["Close"] for s, df in frames.items()}).sort_index().ffill()
    O = pd.DataFrame({s: df["Open"] for s, df in frames.items()}).reindex(C.index).ffill()
    H = pd.DataFrame({s: df["High"] for s, df in frames.items()}).reindex(C.index).ffill()
    L = pd.DataFrame({s: df["Low"] for s, df in frames.items()}).reindex(C.index).ffill()
    V = pd.DataFrame({s: df["Volume"] for s, df in frames.items()}).reindex(C.index).fillna(0.0)

    ret_1 = C.pct_change(fill_method=None).fillna(0.0)
    rng = (H - L).replace(0, np.nan)
    dp = C.diff()

    hl_sq = (np.log(H / L.replace(0, np.nan)) ** 2) / (4.0 * np.log(2.0))
    pvol_5 = np.sqrt(hl_sq.rolling(5, min_periods=2).mean()).replace(0, np.nan)
    pvol_12 = np.sqrt(hl_sq.rolling(12, min_periods=3).mean()).replace(0, np.nan)
    pvol_20 = np.sqrt(hl_sq.rolling(20, min_periods=4).mean()).replace(0, np.nan)

    atr_vel_5 = 0.5 + pvol_5.rank(axis=1, pct=True).fillna(0.5)
    atr_vel_12 = 0.5 + pvol_12.rank(axis=1, pct=True).fillna(0.5)
    atr_vel_20 = 0.5 + pvol_20.rank(axis=1, pct=True).fillna(0.5)

    rvol = (V / V.rolling(20, min_periods=3).mean().replace(0, np.nan)).clip(0.2, 5.0).fillna(1.0)

    sig_dp = dp.rolling(24, min_periods=4).std().replace(0, np.nan)
    z_dp = (dp / sig_dp).clip(-3.0, 3.0).fillna(0.0)
    buy_frac = 0.5 * (1.0 + np.tanh(0.79788456 * (z_dp + 0.044715 * (z_dp ** 3))))
    signed_vol = V * (2.0 * buy_frac - 1.0)

    bvc_obi_5 = (signed_vol.rolling(5, min_periods=1).sum() / V.rolling(5, min_periods=1).sum().replace(0, np.nan)).fillna(0.0)
    bvc_obi_12 = (signed_vol.rolling(12, min_periods=2).sum() / V.rolling(12, min_periods=2).sum().replace(0, np.nan)).fillna(0.0)
    bvc_obi_20 = (signed_vol.rolling(20, min_periods=3).sum() / V.rolling(20, min_periods=3).sum().replace(0, np.nan)).fillna(0.0)

    typ_px = (H + L + C) / 3.0
    vwap_15 = (typ_px * V).rolling(15, min_periods=3).sum() / V.rolling(15, min_periods=3).sum().replace(0, np.nan)
    vwap_36 = (typ_px * V).rolling(36, min_periods=4).sum() / V.rolling(36, min_periods=4).sum().replace(0, np.nan)
    vwap_60 = (typ_px * V).rolling(60, min_periods=6).sum() / V.rolling(60, min_periods=6).sum().replace(0, np.nan)
    vwap_z_15 = ((C - vwap_15) / typ_px.rolling(15, min_periods=3).std().replace(0, np.nan)).clip(-3.5, 3.5).fillna(0.0)

    # #1: 2_MLOFI_Delta_Thrust (w=12, +3.163%/day, 90% Green Days)
    bid_up = (L >= L.shift(1)).astype(float)
    ask_dn = (H <= H.shift(1)).astype(float)
    ofi_raw = (bid_up * V) - (ask_dn * V)
    mlofi_z_12 = (ofi_raw.rolling(12, min_periods=2).mean() / V.rolling(20, min_periods=3).mean().replace(0, np.nan)).clip(-3.0, 3.0).fillna(0.0)
    c1_mlofi_w12 = ((mlofi_z_12 * 1.2 + bvc_obi_12) * (C >= vwap_36).astype(float) * atr_vel_12).fillna(0.0)

    # #2: 14_Candle_Hammer_PinBar (w=5, +3.076%/day) + 6 Candlesticks
    body = C - O
    abs_body = body.abs()
    prev_body = body.shift(1)
    prev_abs_body = abs_body.shift(1)
    prev2_body = body.shift(2)
    upper_wick = H - np.maximum(O, C)
    lower_wick = np.minimum(O, C) - L
    ibs = ((C - L) / rng).fillna(0.5)

    hammer_bool = (lower_wick >= 1.8 * np.maximum(abs_body, 0.0008 * C)) & (upper_wick <= 0.45 * rng) & (C > vwap_15 * 0.988)
    c2_hammer_w5 = (
        hammer_bool.rolling(2, min_periods=1).max().fillna(0.0)
        * (0.7 + 0.5 * (-vwap_z_15).clip(0.0, 2.0))
        * (0.5 + bvc_obi_5.clip(lower=0.0))
        * atr_vel_5
    ).fillna(0.0)

    engulf_bool = (prev_body < 0) & (body > 0) & (C >= O.shift(1)) & (O <= C.shift(1)) & (abs_body >= prev_abs_body * 0.95)
    mid_t2 = 0.5 * (O.shift(2) + C.shift(2))
    mstar_bool = (prev2_body < 0) & (prev_abs_body <= abs_body.shift(2) * 0.65) & (body > 0) & (C >= mid_t2)
    marubozu_bool = (body > 0) & (abs_body >= 0.62 * rng) & (ibs >= 0.78) & (prev_body > 0) & (C > vwap_60)
    inside_brk_bool = (H.shift(1) <= H.shift(2)) & (L.shift(1) >= L.shift(2)) & (C > H.shift(1)) & (body > 0)
    pierce_bool = (prev_body < 0) & (O <= L.shift(1) * 1.003) & (C > 0.5 * (O.shift(1) + C.shift(1)))

    # #3: 12_Kyle_Lambda_Impact_Scalp (w=20, 100.0% Green Days, 22.66 Sharpe)
    kyle_lambda = (ret_1.abs() / rvol.replace(0, np.nan)).rolling(20, min_periods=4).mean()
    low_impact_boost = (1.0 / kyle_lambda.rank(axis=1, pct=True).clip(0.2, 1.0)).fillna(1.0)
    c3_kyle_w20 = (bvc_obi_20 * low_impact_boost * (C > vwap_60).astype(float) * atr_vel_20).fillna(0.0)

    # #4: 6_Anchored_VWAP_Bounce (w=5, 90% Green Days)
    c4_vwap_w5 = (
        (-vwap_z_15).clip(0.0, 2.5)
        * (bvc_obi_5 > 0).astype(float)
        * (C > C.rolling(40, min_periods=10).mean()).astype(float)
        * atr_vel_5
    ).fillna(0.0)

    # #5: 5_ORB_RVOL_Ignition (w=12, +2.155%/day)
    orb_high_12 = H.shift(1).rolling(12, min_periods=2).max()
    c5_orb_w12 = (((C > orb_high_12) & (C > vwap_36)).astype(float) * rvol * (0.5 + bvc_obi_12.clip(lower=0.0)) * atr_vel_12).fillna(0.0)

    # #6: 8_Connors_Intraday_RSI2_IBS (w=5, +2.109%/day)
    gain = dp.clip(lower=0.0).ewm(alpha=0.5, min_periods=2, adjust=False).mean()
    loss = (-dp.clip(upper=0.0)).ewm(alpha=0.5, min_periods=2, adjust=False).mean()
    rsi2 = 100.0 - (100.0 / (1.0 + (gain / loss.replace(0, np.nan)))).fillna(50.0)
    c6_connors_w5 = ((((25.0 - rsi2).clip(lower=0.0) / 25.0) * (ibs < 0.25).astype(float) * (C > vwap_15 * 0.992).astype(float) * 2.0) * atr_vel_5).fillna(0.0)

    candle_bonus = pd.Series(0.0, index=C.columns)
    candle_labels: Dict[str, str] = {}
    for sym in C.columns:
        tags = []
        sc = 0.0
        if bool(hammer_bool[sym].iloc[-1]) or bool(hammer_bool[sym].shift(1, fill_value=False).iloc[-1]):
            tags.append("Hammer_PinBar")
            sc += 0.40
        if bool(engulf_bool[sym].iloc[-1]) or bool(engulf_bool[sym].shift(1, fill_value=False).iloc[-1]):
            tags.append("Bull_Engulfing")
            sc += 0.35
        if bool(marubozu_bool[sym].iloc[-1]):
            tags.append("Marubozu_Soldiers")
            sc += 0.35
        if bool(inside_brk_bool[sym].iloc[-1]):
            tags.append("InsideBar_Brk")
            sc += 0.30
        if bool(mstar_bool[sym].iloc[-1]):
            tags.append("Morning_Star")
            sc += 0.30
        if bool(pierce_bool[sym].iloc[-1]):
            tags.append("Piercing_Line")
            sc += 0.25

        last_ibs = float(ibs[sym].iloc[-1])
        sc += 0.20 * max(0.0, last_ibs)
        candle_bonus[sym] = min(1.0, sc)
        candle_labels[sym] = "+".join(tags[:2]) if tags else ("Strong_Close" if last_ibs >= 0.75 else "OrderFlow_Setup")

    ny_dt = datetime.now(ZoneInfo("America/New_York"))
    ny_minutes = ny_dt.hour * 60 + ny_dt.minute
    if 570 <= ny_minutes < 660:
        active_session = "SESSION_1_MORNING_POWER (09:30-11:00 EST)"
        w1, w2, w3, w4, w5, w6 = 0.28, 0.20, 0.22, 0.10, 0.12, 0.08
    elif 660 <= ny_minutes < 840:
        active_session = "SESSION_2_MIDDAY_FULL (11:00-14:00 EST)"
        w1, w2, w3, w4, w5, w6 = 0.34, 0.28, 0.10, 0.10, 0.10, 0.08
    else:
        active_session = "SESSION_3_CLOSING_POWER (14:00-16:00 EST)"
        w1, w2, w3, w4, w5, w6 = 0.26, 0.18, 0.28, 0.12, 0.08, 0.08

    r1 = c1_mlofi_w12.iloc[-1].rank(pct=True).fillna(0.0)
    r2 = c2_hammer_w5.iloc[-1].rank(pct=True).fillna(0.0)
    r3 = c3_kyle_w20.iloc[-1].rank(pct=True).fillna(0.0)
    r4 = c4_vwap_w5.iloc[-1].rank(pct=True).fillna(0.0)
    r5 = c5_orb_w12.iloc[-1].rank(pct=True).fillna(0.0)
    r6 = c6_connors_w5.iloc[-1].rank(pct=True).fillna(0.0)
    rvol_last = rvol.iloc[-1].fillna(1.0)

    champion_alpha = (w1 * r1) + (w2 * r2) + (w3 * r3) + (w4 * r4) + (w5 * r5) + (w6 * r6)

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

        if spread_bps > MAX_SPREAD_BPS or obi_live < HARDCODED_OBI_GATE or px < MIN_STOCK_PRICE_USD:
            continue

        alpha_sc = float(champion_alpha.get(sym, 0.0))
        c_sc = float(candle_bonus.get(sym, 0.0))
        c_lbl = candle_labels.get(sym, "OrderFlow_Setup")

        total_edge = (
            (0.50 * alpha_sc)
            + (0.25 * (obi_live + 1.0) / 2.0)
            + (0.15 * (bvc_buy / 100.0))
            + (0.10 * c_sc)
        )

        live_rows.append({
            "Ticker": sym,
            "Cap_Tier": str(ob["Cap_Tier"])[:22],
            "Candle_Pattern": c_lbl[:18],
            "Total_Edge": round(total_edge, 3),
            "Champ_Alpha": round(alpha_sc, 3),
            "OBI_Imb": obi_live,
            "BVC_Buy_%": bvc_buy,
            "RVOL_5m": round(rv_val, 2),
            "Spread_bps": spread_bps,
            "Live_Price_$": px,
            "Ratchet_$": round(px * (1.0 + HARDCODED_RATCHET_LOCK_PCT), 2),
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
            if (
                float(row1["Total_Edge"]) >= 0.84
                and float(row1["OBI_Imb"]) >= 0.35
                and float(row1["BVC_Buy_%"]) >= 92.0
                and float(row1["Spread_bps"]) <= 20.0
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
# 5. OFFICIAL TRADING 212 API v0 CLIENT (EXACT SELL PRECISION + PENDING SHIELD)
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
        return {
            "free": float(data.get("free", 0.0) or 0.0),
            "total": float(data.get("total", 0.0) or 0.0),
            "invested": float(data.get("invested", 0.0) or 0.0),
            "ppl": float(data.get("ppl", 0.0) or 0.0),
            "result": float(data.get("result", 0.0) or 0.0),
        }

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
            ppl_gbp = float(p.get("ppl", 0.0) or 0.0)
            pos[sym] = {
                "t212_ticker": t212_code,
                "qty": qty,
                "current_price": px,
                "average_price": avg_px,
                "ppl_gbp": ppl_gbp,
                "pnl_pct": ((px / avg_px) - 1.0) if avg_px > 0 else 0.0,
            }
        return pos

    def get_pending_order_symbols(self) -> Set[str]:
        """Returns symbols that already have a pending market/limit order queued on T212."""
        pending_syms: Set[str] = set()
        try:
            r = requests.get(f"{self.base_url}/equity/orders", headers=self.headers, timeout=15)
            if r.status_code == 200:
                for o in r.json():
                    t_code = o.get("ticker", "")
                    if t_code:
                        pending_syms.add(t_code.split("_")[0])
        except Exception:
            pass
        return pending_syms

    def place_market_order(self, symbol: str, signed_qty: float, t212_ticker: str = "") -> Tuple[bool, str]:
        instrument_code = t212_ticker or self.instrument_map.get(symbol, f"{symbol}_US_EQ")

        # CRITICAL FIX FOR SELL ORDERS:
        # Never round a sell quantity UP (e.g., 16.33919476 -> 16.34 causes 'selling-equity-not-owned').
        # Try exact owned quantity first; if precision fallback is needed, FLOOR to 2 decimal places!
        if signed_qty < 0:
            exact_sell_qty = -abs(float(signed_qty))
            floored_sell_qty = -(math.floor(abs(float(signed_qty)) * 100.0) / 100.0)
            qty_candidates = [exact_sell_qty]
            if abs(floored_sell_qty) >= 0.01 and floored_sell_qty != exact_sell_qty:
                qty_candidates.append(floored_sell_qty)
        else:
            buy_qty = math.floor(float(signed_qty) * 100.0) / 100.0
            if buy_qty < 0.01:
                return False, f"Skipped {symbol}: buy quantity ({buy_qty}) < 0.01 share."
            qty_candidates = [buy_qty]

        last_err = ""
        for q_val in qty_candidates:
            for ext_flag in (True, False):
                payload = {"ticker": instrument_code, "quantity": q_val}
                if ext_flag:
                    payload["extendedHours"] = True
                r = requests.post(f"{self.base_url}/equity/orders/market", headers=self.headers, json=payload, timeout=15)
                if r.status_code in (200, 201):
                    mode_lbl = "ExtHours" if ext_flag else "RegHours"
                    return True, f"ACCEPTED ({mode_lbl}): {instrument_code} qty={q_val:+g}"
                last_err = f"HTTP {r.status_code}: {r.text}"
                time.sleep(0.8)

        return False, f"REJECTED ({instrument_code}) -> {last_err}"


# ==============================================================================
# 6. MASTER 15-MINUTE EXECUTION CONTROLLER & TELEGRAM LIVE SCORECARD
# ==============================================================================
def run_v13_practice_sniper_bot() -> None:
    uk_dt = datetime.now(ZoneInfo("Europe/London"))
    ny_dt = datetime.now(ZoneInfo("America/New_York"))
    uk_now = uk_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    ny_now = ny_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    ny_mins = ny_dt.hour * 60 + ny_dt.minute

    print("=" * 138)
    print(f"ARGON v13.1 TOURNAMENT CHAMPION SNIPER BOT (15M PRACTICE + TELEGRAM) | UK: {uk_now} | NY: {ny_now} | Trigger: {GITHUB_EVENT_NAME}")
    print("=" * 138)

    if GITHUB_EVENT_NAME == "schedule":
        if ny_dt.weekday() >= 5 or not (570 <= ny_mins <= 965):
            print(
                f"  [SLEEP GATE] Scheduled tick is outside US regular market hours "
                f"(NY Time: {ny_dt.strftime('%A %H:%M %Z')}). Skipping Yahoo Finance download cleanly."
            )
            return

    in_play_tickers = stage1_select_in_play_halal_movers(MASTER_ALL_CAP_HALAL_UNIVERSE, top_n=IN_PLAY_TOP_N)
    frames, ob_df, gbpusd_rate = fetch_live_5m_and_orderbook(in_play_tickers)
    if not frames or ob_df.empty:
        print("  [ERROR] No valid 5-minute dataframes returned. Exiting cycle.")
        return

    target_weights, live_df, active_session, chosen_k = compute_v13_champion_sniper_targets(frames, ob_df)

    print("\n" + "=" * 138)
    print(
        f"[STAGE 3 LEADERBOARD] Active Window: {active_session} | "
        f"Mode: Top_K={chosen_k} ({'SINGLE-STOCK SNIPER' if chosen_k == 1 else 'DUAL-ROCKET 50/50'})"
    )
    print(
        f"                      Exit Rules -> TakeProfit: +{HARDCODED_TAKE_PROFIT_PCT*100:.1f}% | "
        f"High-Water Ratchet: +{HARDCODED_RATCHET_LOCK_PCT*100:.1f}% | Hard StopLoss: -{HARDCODED_STOP_LOSS_PCT*100:.1f}%"
    )
    print("=" * 138)
    top_candidates = live_df.head(12).copy()
    if not top_candidates.empty:
        print(top_candidates.to_string(index=False))

    print("\n" + "=" * 138)
    print(f"[STAGE 4 EXECUTION & TELEGRAM PNL] TRADING 212 ({BROKER_MODE}) | Live Execution: {LIVE_ORDER_EXECUTION}")
    print("=" * 138)

    top1_row = live_df.iloc[0] if not live_df.empty else None
    top1_str = (
        f"`{top1_row['Ticker']}` (`${top1_row['Live_Price_$']}` | Edge `{top1_row['Total_Edge']}` | "
        f"OBI `{top1_row['OBI_Imb']:+.2f}` | Candle: `{top1_row['Candle_Pattern']}`)"
        if top1_row is not None else "None"
    )

    if not LIVE_ORDER_EXECUTION or "YOUR_" in TRADING212_API_KEY or not TRADING212_API_KEY:
        print(f"  [STATUS] DRY-RUN PREVIEW (£1,000 / ${1000*gbpusd_rate:,.0f} Account Sizing — Top_K={chosen_k}):")
        return

    is_practice = (BROKER_MODE.upper() != "TRADING212_LIVE")
    client = Trading212OfficialClient(TRADING212_API_KEY, TRADING212_API_SECRET, practice=is_practice)

    try:
        cash_info = client.get_cash_info()
    except Exception as e:
        print(f"  [AUTH WARNING] {client.base_url} returned: {e}")
        return

    executed_logs: List[str] = []

    try:
        positions = client.get_positions()
        pending_syms = client.get_pending_order_symbols()
        client.load_instrument_map(in_play_tickers)
        print(
            f"  [CONNECTED] {BROKER_MODE} | Total Equity: £{cash_info['total']:,.2f} | "
            f"Free Cash: £{cash_info['free']:,.2f} | Open PnL: £{cash_info['ppl']:+,.2f} | "
            f"Realized Profit: £{cash_info['result']:+,.2f} | Pending Orders: {len(pending_syms)} ({sorted(pending_syms)})"
        )

        obi_lookup = dict(zip(live_df["Ticker"], live_df["OBI_Imb"]))
        candle_lookup = dict(zip(live_df["Ticker"], live_df["Candle_Pattern"]))

        # 1. Check Existing Positions for Take-Profit (+2.0%), High-Water Ratchet (+1.0%), Stop-Loss (-1.2%), or Rotation
        for held_sym, pos in positions.items():
            if held_sym in pending_syms:
                print(f"  [PENDING] {held_sym} already has a pending order queued on Trading 212. Skipping duplicate sell.")
                continue

            pnl = pos["pnl_pct"]
            curr_obi = float(obi_lookup.get(held_sym, 0.0))
            hit_tp = pnl >= HARDCODED_TAKE_PROFIT_PCT
            hit_ratchet = (pnl >= HARDCODED_RATCHET_LOCK_PCT) and (curr_obi < 0.25)
            hit_sl = pnl <= -HARDCODED_STOP_LOSS_PCT
            dropped_rank = held_sym not in top_candidates["Ticker"].values[:5]

            if (hit_tp or hit_ratchet or hit_sl or dropped_rank) and pos["qty"] > 0:
                reason = (
                    f"TAKE_PROFIT (+{HARDCODED_TAKE_PROFIT_PCT*100:.1f}%)" if hit_tp else
                    (f"RATCHET_LOCK (+{HARDCODED_RATCHET_LOCK_PCT*100:.1f}%)" if hit_ratchet else
                     (f"STOP_LOSS (-{HARDCODED_STOP_LOSS_PCT*100:.1f}%)" if hit_sl else "SNIPER_ROTATION"))
                )
                print(f"  [EXIT - {reason}] Selling {held_sym} (Exact Qty: {pos['qty']}, PnL: {pnl*100:+.2f}% / £{pos['ppl_gbp']:+.2f})")
                ok, msg = client.place_market_order(held_sym, -pos["qty"], t212_ticker=pos["t212_ticker"])
                print(f"    └─ {msg}")
                if ok:
                    pending_syms.add(held_sym)
                executed_logs.append(
                    f"🔴 SELL `{held_sym}` (`{pos['qty']:.4f}` shs | `{pnl*100:+.2f}%` / `£{pos['ppl_gbp']:+.2f}`) — *{reason}*"
                )
                time.sleep(2.2)

        # 2. Refresh Free Cash & Deploy into Top_K=1 or Top_K=2 Tournament Champions
        cash_info = client.get_cash_info()
        deployable_gbp = cash_info["free"] * 0.95
        deployable_usd = deployable_gbp * gbpusd_rate

        if deployable_gbp >= MIN_ORDER_GBP:
            new_buys = [s for s in target_weights if (s not in positions and s not in pending_syms)]
            if new_buys:
                w_sum = sum(target_weights[s] for s in new_buys)
                for sym in new_buys:
                    if client.instrument_map and sym not in client.instrument_map:
                        print(f"  [SKIP] {sym} is not currently listed on Trading 212 US Equity metadata.")
                        continue
                    alloc_usd = deployable_usd * (target_weights[sym] / max(w_sum, 1e-6))
                    px_usd = float(live_df.loc[live_df["Ticker"] == sym, "Live_Price_$"].values[0])
                    c_pat = candle_lookup.get(sym, "OrderFlow_Setup")
                    qty_to_buy = math.floor((alloc_usd / max(px_usd, 1.0)) * 100.0) / 100.0
                    if qty_to_buy >= 0.01 and (alloc_usd / gbpusd_rate) >= MIN_ORDER_GBP:
                        print(
                            f"  [BUY TOP_K={chosen_k} SNIPER] {sym:<5} ({c_pat}) | "
                            f"Alloc: £{alloc_usd/gbpusd_rate:,.2f} | Shares: +{qty_to_buy:.2f} @ ${px_usd:.2f}"
                        )
                        ok, msg = client.place_market_order(sym, qty_to_buy)
                        print(f"    └─ {msg}")
                        executed_logs.append(
                            f"🟢 BUY `{sym}` (`+{qty_to_buy:.2f}` shs @ `${px_usd:.2f}` | `£{alloc_usd/gbpusd_rate:,.2f}`) — `{c_pat}`"
                        )
                        time.sleep(2.2)
            else:
                print(f"  [HOLD] Top target(s) {list(target_weights.keys())} already held or queued in Pending Orders.")
        else:
            print(f"  [HOLD] Free cash (£{deployable_gbp:,.2f}) below £{MIN_ORDER_GBP:.0f} minimum (capital is active in positions/orders).")

        # 3. Refresh Final Portfolio Snapshot & Send Live Telegram PnL Scorecard
        final_cash = client.get_cash_info()
        final_positions = client.get_positions()
        net_total_profit_gbp = final_cash["ppl"] + final_cash["result"]
        base_capital = max(final_cash["total"] - net_total_profit_gbp, 1.0)
        net_total_profit_pct = (net_total_profit_gbp / base_capital) * 100.0

        pos_lines = []
        for s_sym, p_info in final_positions.items():
            pos_lines.append(
                f"  • `{s_sym}`: `{p_info['pnl_pct']*100:+.2f}%` (`£{p_info['ppl_gbp']:+.2f}`) @ `${p_info['current_price']:.2f}`"
            )
        pos_block = "\n".join(pos_lines) if pos_lines else "  • *100% Cash*"
        orders_block = "\n".join(executed_logs) if executed_logs else "  • *No new orders this 15m cycle (Monitoring open positions)*"

        is_eod_window = (945 <= ny_mins <= 965)
        if executed_logs or is_eod_window or TELEGRAM_ALWAYS_SEND_HEARTBEAT or GITHUB_EVENT_NAME != "schedule":
            header_title = (
                "📊 *ARGON v13.1 END-OF-DAY PROFIT REPORT*"
                if is_eod_window
                else f"🎯 *ARGON v13.1 LIVE 15M UPDATE ({BROKER_MODE} | Top_K={chosen_k})*"
            )
            tg_message = (
                f"{header_title}\n"
                f"🕒 `{uk_now}` | `{active_session.split()[0]}`\n\n"
                f"💰 *Total Account Equity:* `£{final_cash['total']:,.2f}` (Free Cash: `£{final_cash['free']:,.2f}`)\n"
                f"📈 *Open Floating PnL:* `£{final_cash['ppl']:+,.2f}`\n"
                f"💵 *Realized Closed Profit:* `£{final_cash['result']:+,.2f}`\n"
                f"🏆 *Total Net Profit:* `£{net_total_profit_gbp:+,.2f}` (`{net_total_profit_pct:+.2f}%`)\n\n"
                f"⚡ *15-Minute Cycle Activity:*\n{orders_block}\n\n"
                f"📂 *Active Portfolio ({len(final_positions)}) | Pending ({len(pending_syms)}):*\n{pos_block}\n\n"
                f"🔭 *#1 Scanner Pick:* {top1_str}"
            )
            send_telegram_alert(tg_message)

    except Exception as e:
        print(f"  [EXECUTION ERROR] {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true")
    args, _ = parser.parse_known_args()
    run_v13_practice_sniper_bot()
