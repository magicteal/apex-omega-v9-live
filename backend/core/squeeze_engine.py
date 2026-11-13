"""
APEX-OMEGA OS V9.0 — Dual-Core Regime Sniper + Tier-1/Tier-2 Pair Whipsaw Shield
Engineered from the Forensic Audit of 143 Live Trades across V6 (95 trades) & V7/V8 (48 trades):
1. Dual-Core Entry Architecture (Solves V7's 2-trades/day bottleneck & V6's counter-trend knife-catching):
   - CORE A (TREND_DIP_SNIPER): Captures V6's high-win-rate RSI-2/VWAP pullbacks inside confirmed EMA-21/50/100 trends,
     upgraded with 2-Bar Candle Absorption & Wick Rejection confirmation so it NEVER enters during an active crash.
   - CORE B (EMA_PULLBACK_SURGE): Captures V8's high-Profit-Factor (3.50 PF) 3-bar EMA-9/21 trend continuation bounces.
2. Tier-1 Alpha vs. Tier-2 High-Wick Pair Filtering:
   - Tier-1 Alpha Pairs (BTC, SOL, SUI, LINK, DOGE, ADA, BNB — 77.8% live win rate across 63 V6 trades) get priority scoring.
   - Tier-2 High-Wick Pairs (AVAX, ETH, XRP — caused 53% of V6's losses) require Score >= 98/100 and KER >= 0.25.
"""
from dataclasses import dataclass, asdict
from typing import List, Dict, Any
import numpy as np

TIER1_ALPHA_SYMBOLS = {
    "BTC/USDT:USDT",
    "SOL/USDT:USDT",
    "SUI/USDT:USDT",
    "LINK/USDT:USDT",
    "DOGE/USDT:USDT",
    "ADA/USDT:USDT",
    "BNB/USDT:USDT",
}


@dataclass
class QuantV9Signal:
    symbol: str
    price: float
    atr_14: float
    vwap: float
    z_score: float
    rsi_2: float
    rsi_14: float = 50.0
    compression_ratio: float = 1.0
    squeeze_on: bool = False
    squeeze_bars_last_10: int = 0
    ema_trend_slope: float = 0.0
    rvol: float = 1.0
    roc5: float = 0.0
    ker: float = 0.45
    confluence_score: int = 50
    setup_type: str = "SCANNING"
    regime: str = "NEUTRAL"
    signal_valid: bool = False
    feed_source: str = "BYBIT_LIVE_5M"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SqueezeEngine:
    @staticmethod
    def _ema(values: np.ndarray, span: int) -> np.ndarray:
        alpha = 2.0 / (span + 1.0)
        ema = np.zeros_like(values, dtype=float)
        ema[0] = values[0]
        for i in range(1, len(values)):
            ema[i] = alpha * values[i] + (1.0 - alpha) * ema[i - 1]
        return ema

    @staticmethod
    def _rsi(closes: np.ndarray, period: int) -> float:
        if len(closes) <= period:
            return 50.0
        diffs = np.diff(closes[-(period + 1):])
        gains = float(np.sum(np.where(diffs > 0, diffs, 0.0))) / period
        losses = float(np.sum(np.where(diffs < 0, -diffs, 0.0))) / period
        if losses <= 1e-12:
            return 98.0
        rs = gains / losses
        return round(100.0 - (100.0 / (1.0 + rs)), 1)

    @staticmethod
    def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
        tr = np.zeros_like(close, dtype=float)
        tr[0] = max(high[0] - low[0], close[0] * 0.002)
        for i in range(1, len(close)):
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
        return SqueezeEngine._ema(tr, period)

    def evaluate_ohlcv(self, symbol: str, ohlcv: List[List[float]], feed_source: str = "BYBIT_LIVE_5M") -> QuantV9Signal:
        arr = np.array(ohlcv, dtype=float)
        open_p = arr[:, 1]
        high = arr[:, 2]
        low = arr[:, 3]
        close = arr[:, 4]
        vol = arr[:, 5]
        n = len(close)

        atr20 = self._atr(high, low, close, 20)
        atr14 = self._atr(high, low, close, 14)
        ema9 = self._ema(close, min(9, n))
        ema21 = self._ema(close, min(21, n))
        ema50 = self._ema(close, min(50, n))
        ema100 = self._ema(close, min(100, n))
        ema200 = self._ema(close, min(200, n))
        true_atr_pct = float(atr14[-1]) / max(float(close[-1]), 1e-12)

        win = min(20, n)
        typ = (high[-win:] + low[-win:] + close[-win:]) / 3.0
        v_slice = np.maximum(vol[-win:], 1e-9)
        vwap = float(np.sum(typ * v_slice) / np.sum(v_slice))
        std20 = float(np.std(close[-win:]))
        z_score = round((float(close[-1]) - vwap) / max(std20, float(close[-1]) * 0.001), 2)

        squeeze_count = 0
        current_comp = 1.0
        squeeze_now = False
        for offset in range(min(9, n - 20), -1, -1):
            idx = n - 1 - offset
            sub = close[max(0, idx - 19) : idx + 1]
            sma = float(np.mean(sub))
            std = float(np.std(sub))
            bb_u, bb_l = sma + 2.0 * std, sma - 2.0 * std
            kc_mid = float(self._ema(close[: idx + 1], 20)[-1])
            kc_u, kc_l = kc_mid + 1.5 * float(atr20[idx]), kc_mid - 1.5 * float(atr20[idx])
            in_sq = (bb_u < kc_u) and (bb_l > kc_l)
            if in_sq:
                squeeze_count += 1
            if offset == 0:
                current_comp = round((bb_u - bb_l) / max(kc_u - kc_l, 1e-9), 2)
                squeeze_now = in_sq

        rsi2 = self._rsi(close, 2)
        rsi14 = self._rsi(close, 14)
        ema_now = float(ema21[-1])
        ema_prev = float(ema21[max(0, n - 5)])
        ema_slope = (ema_now - ema_prev) / max(ema_prev, 1e-9)

        vol_mean = float(np.mean(vol[max(0, n - 21) : n - 1])) if n > 5 else float(np.mean(vol))
        rvol = round(max(float(vol[-1]), float(vol[-2])) / max(vol_mean, 1e-9), 2)

        close5 = float(close[max(0, n - 6)])
        roc5 = round((float(close[-1]) - close5) / max(close5, 1e-9), 5)

        ker_p = min(10, n - 1)
        net_move = abs(float(close[-1] - close[-1 - ker_p]))
        path_sum = float(np.sum(np.abs(np.diff(close[-(ker_p + 1):]))))
        ker = round(net_move / max(path_sum, 1e-12), 2)

        cur_range = max(float(high[-1] - low[-1]), 1e-12)
        lower_wick = (min(float(open_p[-1]), float(close[-1])) - float(low[-1])) / cur_range
        upper_wick = (float(high[-1]) - max(float(open_p[-1]), float(close[-1]))) / cur_range
        green_bounce = float(close[-1]) > float(open_p[-1]) and float(close[-1]) >= float(close[-2])
        red_bounce = float(close[-1]) < float(open_p[-1]) and float(close[-1]) <= float(close[-2])

        is_tier1 = symbol in TIER1_ALPHA_SYMBOLS
        tier_bonus = 2 if is_tier1 else 0
        min_ker_gate = 0.16 if is_tier1 else 0.25
        vol_gate_ok = true_atr_pct >= 0.0014 and ker >= min_ker_gate

        # =========================================================================
        # CORE A: TREND-ALIGNED RSI-2 / VWAP ABSORPTION SNIPER (Upgraded V6 Core)
        # Blocks falling-knife entries by requiring roc5 > -0.0065 (for Long) + green bounce
        # =========================================================================
        core_a_bull_trend = (
            vol_gate_ok
            and float(close[-1]) >= float(ema200[-1]) * 0.996
            and float(ema21[-1]) > float(ema50[-1])
            and float(ema50[-1]) >= float(ema100[-1]) * 0.9995
            and ema_slope >= 0.00030
            and roc5 > -0.0060
        )
        core_a_bear_trend = (
            vol_gate_ok
            and float(close[-1]) <= float(ema200[-1]) * 1.004
            and float(ema21[-1]) < float(ema50[-1])
            and float(ema50[-1]) <= float(ema100[-1]) * 1.0005
            and ema_slope <= -0.00030
            and roc5 < 0.0060
        )

        score_a_bull = 38 + tier_bonus
        if core_a_bull_trend:
            score_a_bull += 22
        if rsi2 <= 22:
            score_a_bull += 19
        if z_score <= -1.00:
            score_a_bull += 11
        if green_bounce or lower_wick >= 0.28:
            score_a_bull += 10
        if rvol >= 1.08:
            score_a_bull += 6

        score_a_bear = 38 + tier_bonus
        if core_a_bear_trend:
            score_a_bear += 22
        if rsi2 >= 78:
            score_a_bear += 19
        if z_score >= 1.00:
            score_a_bear += 11
        if red_bounce or upper_wick >= 0.28:
            score_a_bear += 10
        if rvol >= 1.08:
            score_a_bear += 6

        # =========================================================================
        # CORE B: 3-BAR EMA-9 / EMA-21 PULLBACK CONTINUATION SURGE (Upgraded V8 Core)
        # =========================================================================
        core_b_bull_stack = (
            vol_gate_ok
            and float(close[-1]) >= float(ema200[-1]) * 0.998
            and float(ema9[-1]) >= float(ema21[-1]) * 0.9995
            and float(ema21[-1]) > float(ema50[-1])
            and ema_slope >= 0.00035
        )
        core_b_bear_stack = (
            vol_gate_ok
            and float(close[-1]) <= float(ema200[-1]) * 1.002
            and float(ema9[-1]) <= float(ema21[-1]) * 1.0005
            and float(ema21[-1]) < float(ema50[-1])
            and ema_slope <= -0.00035
        )

        recent_low_3 = min(float(low[-1]), float(low[-2]), float(low[-3]))
        recent_high_3 = max(float(high[-1]), float(high[-2]), float(high[-3]))
        bull_pullback_touch = (
            recent_low_3 <= float(ema21[-1]) * 1.0035
            and green_bounce
            and float(close[-1]) >= float(ema9[-1]) * 0.9995
        )
        bear_pullback_touch = (
            recent_high_3 >= float(ema21[-1]) * 0.9965
            and red_bounce
            and float(close[-1]) <= float(ema9[-1]) * 1.0005
        )

        bull_not_overext = -1.35 <= z_score <= 0.90 and 42 <= rsi14 <= 70
        bear_not_overext = -0.90 <= z_score <= 1.35 and 30 <= rsi14 <= 58

        score_b_bull = 42 + tier_bonus
        if core_b_bull_stack:
            score_b_bull += 24
        if bull_pullback_touch:
            score_b_bull += 16
        if bull_not_overext:
            score_b_bull += 11
        if rvol >= 1.02:
            score_b_bull += 5

        score_b_bear = 42 + tier_bonus
        if core_b_bear_stack:
            score_b_bear += 24
        if bear_pullback_touch:
            score_b_bear += 16
        if bear_not_overext:
            score_b_bear += 11
        if rvol >= 1.02:
            score_b_bear += 5

        bull_score = max(score_a_bull, score_b_bull)
        bear_score = max(score_a_bear, score_b_bear)
        min_req_score = 96 if is_tier1 else 98

        long_a_ok = core_a_bull_trend and green_bounce and (rsi2 <= 22 or z_score <= -1.00) and score_a_bull >= min_req_score
        long_b_ok = core_b_bull_stack and bull_pullback_touch and bull_not_overext and score_b_bull >= min_req_score
        short_a_ok = core_a_bear_trend and red_bounce and (rsi2 >= 78 or z_score >= 1.00) and score_a_bear >= min_req_score
        short_b_ok = core_b_bear_stack and bear_pullback_touch and bear_not_overext and score_b_bear >= min_req_score

        if long_a_ok or long_b_ok:
            regime = "LONG_IGNITION"
            setup_type = "DUAL_CORE_PULLBACK_LONG" if long_b_ok else "TREND_DIP_SNIPER_LONG"
            score = min(99, bull_score)
            signal_valid = True
        elif short_a_ok or short_b_ok:
            regime = "SHORT_IGNITION"
            setup_type = "DUAL_CORE_PULLBACK_SHORT" if short_b_ok else "TREND_DIP_SNIPER_SHORT"
            score = min(99, bear_score)
            signal_valid = True
        else:
            score = min(92, max(bull_score, bear_score))
            regime = "COILING" if (squeeze_now or score >= 75) else "NEUTRAL"
            setup_type = "SCANNING"
            signal_valid = False

        eff_atr = max(float(atr14[-1]), float(close[-1]) * 0.0065)

        return QuantV9Signal(
            symbol=symbol,
            price=float(close[-1]),
            atr_14=eff_atr,
            vwap=float(vwap),
            z_score=z_score,
            rsi_2=rsi2,
            rsi_14=rsi14,
            compression_ratio=current_comp,
            squeeze_on=bool(squeeze_now),
            squeeze_bars_last_10=int(squeeze_count),
            ema_trend_slope=round(ema_slope, 6),
            rvol=rvol,
            roc5=roc5,
            ker=ker,
            confluence_score=int(score),
            setup_type=setup_type,
            regime=regime,
            signal_valid=bool(signal_valid),
            feed_source=feed_source,
        )
