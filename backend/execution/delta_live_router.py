"""
APEX-OMEGA V9.0 LIVE — 1:1 Exact Delta Exchange India Execution Mirror
Executes the EXACT same entries, 5-Stage Asymmetric Ratchet stops, Stage-2 50% partial banking,
Stage-4 jackpot exits, and 25-Minute Time-Decay Scratch exits on Delta Exchange India (https://api.india.delta.exchange)
as the live V9 Paper Engine!
"""
import asyncio
import os
from typing import Dict, Any, Optional

try:
    import ccxt.async_support as ccxt
except Exception:
    ccxt = None


class DeltaIndiaLiveRouter:
    def __init__(self) -> None:
        self.execution_mode = os.getenv("EXECUTION_MODE", "PAPER").strip().upper()
        self.api_key = os.getenv("EXCHANGE_API_KEY", "").strip()
        self.api_secret = os.getenv("EXCHANGE_API_SECRET", "").strip()
        self.usd_inr_rate = float(os.getenv("USD_INR_CONV_RATE", "85.0"))
        self.exchange = None
        self.markets_loaded = False
        self.symbol_map: Dict[str, str] = {}

    def is_live(self) -> bool:
        return self.execution_mode == "LIVE" and bool(self.api_key) and bool(self.api_secret) and ccxt is not None

    async def ensure_ready(self) -> bool:
        if not self.is_live():
            return False
        if self.exchange is None:
            self.exchange = ccxt.delta({
                "apiKey": self.api_key,
                "secret": self.api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "swap"},
            })
            self.exchange.urls["api"] = {
                "public": "https://api.india.delta.exchange",
                "private": "https://api.india.delta.exchange",
            }
        if not self.markets_loaded:
            markets = await self.exchange.load_markets()
            self.markets_loaded = True
            for sym in markets:
                base = markets[sym].get("base", "")
                if markets[sym].get("swap") or markets[sym].get("future"):
                    candidate_key = f"{base}/USDT:USDT"
                    if candidate_key not in self.symbol_map:
                        self.symbol_map[candidate_key] = sym
        return True

    def resolve_symbol(self, scanner_symbol: str) -> Optional[str]:
        return self.symbol_map.get(scanner_symbol)

    async def open_live_trade(
        self,
        scanner_symbol: str,
        side: str,
        notional_inr: float,
        entry_price: float,
        stop_price: float,
    ) -> Optional[Dict[str, Any]]:
        if not await self.ensure_ready():
            return None
        delta_sym = self.resolve_symbol(scanner_symbol)
        if not delta_sym:
            return None
        try:
            market = self.exchange.market(delta_sym)
            contract_size = float(market.get("contractSize") or 1.0)
            notional_usd = notional_inr / max(self.usd_inr_rate, 1.0)
            raw_qty = notional_usd / max(entry_price * contract_size, 1e-9)
            qty = float(self.exchange.amount_to_precision(delta_sym, raw_qty))
            if qty <= 0:
                return None

            try:
                await self.exchange.set_margin_mode("isolated", delta_sym)
            except Exception:
                pass
            try:
                await self.exchange.set_leverage(8, delta_sym)
            except Exception:
                pass

            order_side = "buy" if side == "LONG" else "sell"
            stop_side = "sell" if side == "LONG" else "buy"

            entry_order = await self.exchange.create_order(delta_sym, "market", order_side, qty)
            fill_p = float(entry_order.get("average") or entry_order.get("price") or entry_price)

            stop_order = await self.exchange.create_order(
                delta_sym,
                "stop_market",
                stop_side,
                qty,
                None,
                {"stopPrice": float(self.exchange.price_to_precision(delta_sym, stop_price)), "reduceOnly": True},
            )
            return {
                "delta_symbol": delta_sym,
                "qty": qty,
                "remaining_qty": qty,
                "fill_price": fill_p,
                "entry_order_id": entry_order.get("id"),
                "stop_order_id": stop_order.get("id"),
            }
        except Exception as e:
            print(f"[DELTA_LIVE_ERR] open_live_trade({scanner_symbol}): {e}")
            return None

    async def bank_stage2_50pct_and_move_stop(
        self,
        delta_symbol: str,
        side: str,
        total_qty: float,
        old_stop_id: Optional[str],
        new_stop_price: float,
    ) -> Dict[str, Any]:
        """At Stage 2 (+0.68% move), banks 50% of contracts at market and moves hardware stop on remaining 50% to Entry + 0.46%."""
        if not await self.ensure_ready() or not delta_symbol or total_qty <= 0:
            return {"remaining_qty": total_qty, "stop_order_id": old_stop_id}
        try:
            half_qty = float(self.exchange.amount_to_precision(delta_symbol, total_qty * 0.50))
            rem_qty = float(self.exchange.amount_to_precision(delta_symbol, max(total_qty - half_qty, 0.0)))
            close_side = "sell" if side == "LONG" else "buy"

            if half_qty > 0 and rem_qty > 0:
                await self.exchange.create_order(delta_symbol, "market", close_side, half_qty, None, {"reduceOnly": True})
            else:
                rem_qty = total_qty

            new_stop_id = await self.update_hardware_stop(delta_symbol, side, rem_qty, old_stop_id, new_stop_price)
            return {"remaining_qty": rem_qty, "stop_order_id": new_stop_id}
        except Exception as e:
            print(f"[DELTA_LIVE_ERR] bank_stage2_50pct({delta_symbol}): {e}")
            return {"remaining_qty": total_qty, "stop_order_id": old_stop_id}

    async def update_hardware_stop(
        self,
        delta_symbol: str,
        side: str,
        qty: float,
        old_stop_id: Optional[str],
        new_stop_price: float,
    ) -> Optional[str]:
        """Updates the exchange-side STOP_MARKET order whenever Stage 0.5, Stage 1, Stage 2, or Stage 3 ratchets up."""
        if not await self.ensure_ready() or not delta_symbol or qty <= 0:
            return old_stop_id
        try:
            if old_stop_id:
                try:
                    await self.exchange.cancel_order(old_stop_id, delta_symbol)
                except Exception:
                    pass
            stop_side = "sell" if side == "LONG" else "buy"
            new_stop = await self.exchange.create_order(
                delta_symbol,
                "stop_market",
                stop_side,
                qty,
                None,
                {"stopPrice": float(self.exchange.price_to_precision(delta_symbol, new_stop_price)), "reduceOnly": True},
            )
            return new_stop.get("id")
        except Exception as e:
            print(f"[DELTA_LIVE_ERR] update_hardware_stop({delta_symbol}): {e}")
            return old_stop_id

    async def close_live_trade(
        self,
        delta_symbol: str,
        side: str,
        remaining_qty: float,
        stop_order_id: Optional[str],
    ) -> Optional[float]:
        """Flattens the live position at market on Stage 4 Jackpot, 25m Time-Decay Scratch, or Ratchet/Stop hit."""
        if not await self.ensure_ready() or not delta_symbol or remaining_qty <= 0:
            return None
        try:
            if stop_order_id:
                try:
                    await self.exchange.cancel_order(stop_order_id, delta_symbol)
                except Exception:
                    pass
            close_side = "sell" if side == "LONG" else "buy"
            close_order = await self.exchange.create_order(
                delta_symbol, "market", close_side, remaining_qty, None, {"reduceOnly": True}
            )
            return float(close_order.get("average") or close_order.get("price") or 0.0) or None
        except Exception as e:
            print(f"[DELTA_LIVE_ERR] close_live_trade({delta_symbol}): {e}")
            return None
