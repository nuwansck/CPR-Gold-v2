"""OANDA execution layer for the CPR Gold Bot.

Handles pricing, order placement, trade lookup, stop updates, and retry-safe
HTTP communication with OANDA.
"""
from __future__ import annotations

import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config_loader import load_secrets, load_settings

log = logging.getLogger(__name__)


def make_oanda_session(allowed_methods: list | None = None) -> requests.Session:
    """Shared OANDA HTTP session factory with retry policy.

    Use this in every class that talks to OANDA so retry config
    stays in one place (M-02 fix).
    """
    retries = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=allowed_methods or ["GET", "POST", "PUT"],
    )
    adapter = HTTPAdapter(max_retries=retries)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class OandaTrader:
    def __init__(self, demo: bool = True):
        secrets = load_secrets()
        self.api_key = secrets.get("OANDA_API_KEY", "")
        self.account_id = secrets.get("OANDA_ACCOUNT_ID", "")
        self.base_url = "https://api-fxpractice.oanda.com" if demo else "https://api-fxtrade.oanda.com"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        self.session = make_oanda_session(allowed_methods=["GET", "POST", "PUT"])

        masked = f"{self.api_key[:8]}****" if self.api_key else "(missing)"
        log.info("OANDA | Mode: %s", "DEMO" if demo else "LIVE")
        log.info("Account: %s | API Key: %s", self.account_id, masked)

        # Instrument spec cache — populated lazily by get_instrument_specs().
        # Defined here in __init__ so it is always present on the instance
        # without relying on the hasattr() anti-pattern.
        self._specs_cache: dict = {}

    def _request(self, method: str, path: str, **kwargs):
        return self.session.request(
            method,
            f"{self.base_url}{path}",
            headers=self.headers,
            timeout=kwargs.pop("timeout", 15),
            **kwargs,
        )

    def login_with_summary(self) -> dict | None:
        """Single-call replacement for login_with_balance() + get_account_summary().

        Returns a normalised account dict on success, or None on auth/network failure.
        Callers should treat a None return as a fatal login failure.
        """
        try:
            r = self._request("GET", f"/v3/accounts/{self.account_id}")
            if r.status_code == 200:
                account = r.json().get("account", {})
                bal = float(account.get("balance", 0) or 0)
                log.info("Login success! Balance: $%.2f", bal)
                return {
                    "balance":          bal,
                    "nav":              float(account.get("NAV", 0) or 0),
                    "margin_available": float(account.get("marginAvailable", 0) or 0),
                    "margin_used":      float(account.get("marginUsed", 0) or 0),
                    "open_trade_count": int(account.get("openTradeCount", 0) or 0),
                }
            log.error("Login failed: %s %s", r.status_code, r.text[:200])
            return None
        except Exception as e:
            log.error("Login error: %s", e)
            return None

    def get_price(self, instrument):
        try:
            r = self._request(
                "GET", f"/v3/accounts/{self.account_id}/pricing", params={"instruments": instrument}, timeout=10
            )
            if r.status_code != 200:
                log.error("get_price failed: %s %s", r.status_code, r.text[:200])
                return None, None, None
            price = r.json()["prices"][0]
            bid = float(price["bids"][0]["price"])
            ask = float(price["asks"][0]["price"])
            mid = (bid + ask) / 2
            return mid, bid, ask
        except Exception as e:
            log.error("get_price error: %s", e)
            return None, None, None

    def get_instrument_specs(self, instrument):
        if instrument in self._specs_cache:
            return self._specs_cache[instrument]

        settings = load_settings()
        configured_xau_margin = float(settings.get("xau_margin_rate_override", 0.20) or 0.20)
        defaults = {
            "name": instrument,
            "tradeUnitsPrecision": 0,
            "minimumTradeSize": 1,
            "pipLocation": -2 if instrument == "XAU_USD" else -4,
            "displayPrecision": 2 if instrument == "XAU_USD" else 5,
            "marginRate": configured_xau_margin if instrument == "XAU_USD" else 0.05,
        }
        try:
            r = self._request(
                "GET", f"/v3/accounts/{self.account_id}/instruments", params={"instruments": instrument}, timeout=10
            )
            if r.status_code != 200:
                self._specs_cache[instrument] = defaults
                return defaults
            instruments = r.json().get("instruments", [])
            if not instruments:
                self._specs_cache[instrument] = defaults
                return defaults
            d = instruments[0]
            margin_rate = float(d.get("marginRate", defaults.get("marginRate", 0.05)) or defaults.get("marginRate", 0.05))
            if instrument == "XAU_USD":
                # Gold margin varies by broker configuration. Use the more conservative
                # of the live instrument value and the configured floor so we never
                # underestimate required margin on small accounts.
                margin_rate = max(margin_rate, configured_xau_margin)
            result = {
                "name": d.get("name", instrument),
                "tradeUnitsPrecision": int(d.get("tradeUnitsPrecision", defaults["tradeUnitsPrecision"])),
                "minimumTradeSize": float(d.get("minimumTradeSize", defaults["minimumTradeSize"])),
                "pipLocation": int(d.get("pipLocation", defaults["pipLocation"])),
                "displayPrecision": int(d.get("displayPrecision", defaults["displayPrecision"])),
                "marginRate": margin_rate,
            }
            self._specs_cache[instrument] = result
            return result
        except Exception as e:
            log.warning("get_instrument_specs error: %s", e)
            self._specs_cache[instrument] = defaults
            return defaults

    def get_position(self, instrument):
        try:
            r = self._request("GET", f"/v3/accounts/{self.account_id}/positions/{instrument}", timeout=10)
            if r.status_code == 200:
                pos = r.json()["position"]
                long_units = int(float(pos["long"]["units"]))
                short_units = int(float(pos["short"]["units"]))
                if long_units != 0 or short_units != 0:
                    return pos
            return None
        except Exception as e:
            log.error("get_position error: %s", e)
            return None

    def get_open_trades(self, instrument: str | None = None) -> list:
        try:
            r = self._request("GET", f"/v3/accounts/{self.account_id}/openTrades", timeout=10)
            if r.status_code == 200:
                trades = r.json().get("trades", [])
                if instrument:
                    trades = [t for t in trades if t.get("instrument") == instrument]
                return trades
            log.warning("get_open_trades failed: %s %s", r.status_code, r.text[:200])
            return []
        except Exception as e:
            log.error("get_open_trades error: %s", e)
            return []

    def get_open_trades_count(self, instrument: str) -> int:
        return len(self.get_open_trades(instrument))

    def get_recent_closed_trades(self, instrument: str | None = None, count: int = 20) -> list:
        try:
            r = self._request(
                "GET",
                f"/v3/accounts/{self.account_id}/trades",
                params={"state": "CLOSED", "count": count},
                timeout=10,
            )
            if r.status_code == 200:
                trades = r.json().get("trades", [])
                if instrument:
                    trades = [t for t in trades if t.get("instrument") == instrument]
                return trades
            log.warning("get_recent_closed_trades failed: %s %s", r.status_code, r.text[:200])
            return []
        except Exception as e:
            log.error("get_recent_closed_trades error: %s", e)
            return []

    def check_pnl(self, position):
        try:
            long_pnl = float(position["long"].get("unrealizedPL", 0))
            short_pnl = float(position["short"].get("unrealizedPL", 0))
            return long_pnl + short_pnl
        except Exception:
            return 0

    def estimate_required_margin(self, instrument: str, units: float, price: float | None = None) -> float:
        specs = self.get_instrument_specs(instrument)
        margin_rate = float(specs.get("marginRate", 0.05) or 0.05)
        if price is None or price <= 0:
            mid, bid, ask = self.get_price(instrument)
            price = ask or bid or mid or 0
        if price <= 0 or units <= 0:
            return 0.0
        return round(abs(float(units)) * float(price) * margin_rate, 2)

    def normalize_units(self, instrument: str, size: float) -> float:
        specs = self.get_instrument_specs(instrument)
        units_precision = int(specs.get("tradeUnitsPrecision", 0))
        minimum_trade_size = float(specs.get("minimumTradeSize", 1) or 1)
        factor = 10 ** max(units_precision, 0)
        normalized = int(abs(float(size)) * factor) / factor
        return normalized if normalized >= minimum_trade_size else 0.0

    def place_order(self, instrument, direction, size, stop_distance, limit_distance,
                    bid: float = None, ask: float = None, trailing_distance_pips: float = None):
        """Place a market order with SL, TP and optional server-side trailing stop.

        trailing_distance_pips: when provided, OANDA enforces a trailing
        stop server-side at this distance from the best price reached. No polling
        loop required. Pass 0 or None to omit.
        """
        try:
            specs = self.get_instrument_specs(instrument)
            units_precision   = int(specs.get("tradeUnitsPrecision", 0))
            display_precision = int(specs.get("displayPrecision", 2))
            pip_location      = int(specs.get("pipLocation", -2))
            pip               = 10 ** pip_location

            normalized_size = self.normalize_units(instrument, size)
            if normalized_size <= 0:
                return {"success": False, "error": "Normalized size below instrument minimum"}
            units_value = normalized_size if direction == "BUY" else -normalized_size
            units_str = f"{units_value:.{units_precision}f}" if units_precision > 0 else str(int(units_value))

            if bid is None or ask is None:
                price, bid, ask = self.get_price(instrument)
                if price is None:
                    return {"success": False, "error": "Cannot get price"}

            entry = ask if direction == "BUY" else bid
            if direction == "BUY":
                sl_price = round(entry - (stop_distance * pip), display_precision)
                tp_price = round(entry + (limit_distance * pip), display_precision)
            else:
                sl_price = round(entry + (stop_distance * pip), display_precision)
                tp_price = round(entry - (limit_distance * pip), display_precision)

            log.info(
                "Placing %s %s | units=%s | entry=%.2f | SL=%.2f | TP=%.2f | trail=%s pips",
                direction, instrument, units_str, entry, sl_price, tp_price,
                f"{trailing_distance_pips:.0f}" if trailing_distance_pips else "off",
            )

            order = {
                "type":             "MARKET",
                "instrument":       instrument,
                "units":            units_str,
                "timeInForce":      "FOK",
                "stopLossOnFill":   {"price": str(sl_price), "timeInForce": "GTC"},
                "takeProfitOnFill": {"price": str(tp_price), "timeInForce": "GTC"},
            }

            # ── Server-side trailing stop ───────────────────────────
            # OANDA trailing distance is in price units, not pips.
            # XAU/USD pipLocation=-2, so pip=0.01 and 190 pips = 1.90 price units.
            if trailing_distance_pips and trailing_distance_pips > 0:
                trail_price = round(trailing_distance_pips * pip, display_precision)
                order["trailingStopLossOnFill"] = {
                    "distance":    f"{trail_price:.{display_precision}f}",
                    "timeInForce": "GTC",
                }
                log.info("Trailing stop set at %.{dp}f price units ({pips:.0f} pips)".format(
                    dp=display_precision, pips=trailing_distance_pips), trail_price)

            payload = {"order": order}
            r    = self._request("POST", f"/v3/accounts/{self.account_id}/orders", json=payload, timeout=15)
            data = r.json()
            log.info("Order response: %s %s", r.status_code, str(data)[:300])

            if r.status_code in [200, 201]:
                if "orderFillTransaction" in data:
                    fill     = data["orderFillTransaction"]
                    trade_id = fill.get("id", "N/A")
                    try:
                        fill_price = float(fill.get("price", 0))
                    except (TypeError, ValueError):
                        fill_price = None
                    log.info("Trade placed! ID: %s | Fill price: %s | Trail: %s pips",
                             trade_id, fill_price, trailing_distance_pips)
                    return {"success": True, "trade_id": trade_id, "fill_price": fill_price}
                if "orderCancelTransaction" in data:
                    cancel = data["orderCancelTransaction"]
                    reason = cancel.get("reason", "Unknown")
                    return {
                        "success":     False,
                        "error":       f"Order cancelled: {reason}",
                        "cancel_reason": reason,
                        "raw_response": data,
                    }
                return {"success": True}

            error = data.get("errorMessage", str(data))
            return {"success": False, "error": error, "raw_response": data}
        except Exception as e:
            log.error("place_order error: %s", e)
            return {"success": False, "error": str(e)}

    def get_trade_pnl(self, trade_id: str):
        try:
            r = self._request("GET", f"/v3/accounts/{self.account_id}/trades/{trade_id}", timeout=10)
            if r.status_code == 200:
                trade = r.json().get("trade", {})
                if trade.get("state") == "CLOSED":
                    pnl = trade.get("realizedPL")
                    return float(pnl) if pnl is not None else None
            return None
        except Exception as e:
            log.warning("get_trade_pnl error: %s", e)
            return None

    def modify_sl(self, trade_id: str, new_sl_price: float) -> dict:
        try:
            payload = {"stopLoss": {"price": f"{new_sl_price:.2f}", "timeInForce": "GTC"}}
            r = self._request("PUT", f"/v3/accounts/{self.account_id}/trades/{trade_id}/orders", json=payload, timeout=15)
            data = r.json()
            if r.status_code in [200, 201]:
                log.info("SL moved to %.2f for trade %s", new_sl_price, trade_id)
                return {"success": True}
            log.warning("modify_sl failed: %s %s", r.status_code, str(data)[:200])
            return {"success": False, "error": data.get("errorMessage", str(data))}
        except Exception as e:
            log.error("modify_sl error: %s", e)
            return {"success": False, "error": str(e)}

    def close_partial(self, trade_id: str, units: float) -> dict:
        """Close `units` lots of an open trade (partial exit). 

        Pass a positive float regardless of direction — OANDA reduces the
        position and infers the sign from the open trade automatically.
        """
        try:
            payload = {"units": str(round(abs(units), 1))}
            r = self._request(
                "PUT",
                f"/v3/accounts/{self.account_id}/trades/{trade_id}/close",
                json=payload,
                timeout=15,
            )
            data = r.json()
            if r.status_code in [200, 201]:
                fill      = data.get("orderFillTransaction", {})
                realized  = 0.0
                try:
                    realized = float(fill.get("pl", 0))
                except (TypeError, ValueError):
                    pass
                log.info(
                    "Partial close %.1f units | trade %s | realized PL: $%.2f",
                    units, trade_id, realized,
                )
                return {"success": True, "realized_pnl": realized, "fill": fill}
            log.warning("close_partial failed: %s %s", r.status_code, str(data)[:200])
            return {"success": False, "error": data.get("errorMessage", str(data))}
        except Exception as e:
            log.error("close_partial error: %s", e)
            return {"success": False, "error": str(e)}

    def get_open_trade(self, trade_id: str) -> dict | None:
        try:
            r = self._request("GET", f"/v3/accounts/{self.account_id}/trades/{trade_id}", timeout=10)
            if r.status_code == 200:
                trade = r.json().get("trade", {})
                if trade.get("state") == "OPEN":
                    return trade
            return None
        except Exception as e:
            log.warning("get_open_trade error: %s", e)
            return None


    def get_today_closed_transactions(self, instrument: str, today_sgt: str) -> list:
        """Fetch all closing ORDER_FILL transactions for today (SGT date YYYY-MM-DD).

        Uses the OANDA /v3/accounts/.../transactions endpoint with a UTC time
        window derived from the SGT calendar day.  Returns a list of transaction
        dicts that contain tradesClosed entries (i.e. actual closing fills).

        Called by startup_oanda_reconcile() in reconcile_state.py to ensure the
        loss cap sees correct counts even after a mid-day redeploy.
        """
        import pytz
        from datetime import datetime, timedelta

        sgt = pytz.timezone("Asia/Singapore")
        utc = pytz.utc
        try:
            day_start = sgt.localize(datetime.strptime(today_sgt, "%Y-%m-%d"))
        except Exception as exc:
            log.warning("get_today_closed_transactions: bad date %s: %s", today_sgt, exc)
            return []
        day_end  = day_start + timedelta(days=1)
        from_utc = day_start.astimezone(utc).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
        to_utc   = day_end.astimezone(utc).strftime("%Y-%m-%dT%H:%M:%S.000000000Z")

        try:
            r = self._request(
                "GET",
                f"/v3/accounts/{self.account_id}/transactions",
                params={"from": from_utc, "to": to_utc, "type": "ORDER_FILL"},
                timeout=20,
            )
            if r.status_code == 200:
                txns = r.json().get("transactions", [])
                # Keep only fills that closed a trade on the given instrument
                closing = [
                    t for t in txns
                    if t.get("instrument") == instrument and t.get("tradesClosed")
                ]
                return closing
            log.warning(
                "get_today_closed_transactions HTTP %s: %s",
                r.status_code, r.text[:200],
            )
            return []
        except Exception as exc:
            log.error("get_today_closed_transactions error: %s", exc)
            return []

    def close_position(self, instrument):
        try:
            r = self._request(
                "PUT",
                f"/v3/accounts/{self.account_id}/positions/{instrument}/close",
                json={"longUnits": "ALL", "shortUnits": "ALL"},
                timeout=15,
            )
            if r.status_code == 200:
                return {"success": True}
            err = r.text[:300] if r.text else f"HTTP {r.status_code}"
            log.error("close_position failed: HTTP %s — %s", r.status_code, err)
            return {"success": False, "error": err}
        except Exception as e:
            log.error("close_position error: %s", e)
            return {"success": False, "error": str(e)}
