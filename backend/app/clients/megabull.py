"""
APEX-IN MegaBull REST Client
Built strictly from observed schemas (docs/megabull_api.md and docs/megabull_openapi.json).
Enforces hard PAPER_MODE_ONLY guard, automatic 401/403 key expiry handling,
rate limiting (capped at 2 req/sec), and retry with backoff.
"""

import time
import logging
from typing import Dict, Any, List, Optional
import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# HARD GUARD: Paper trading on MegaBull simulator ONLY
PAPER_MODE_ONLY: bool = True

class MegaBullAuthException(Exception):
    """Raised when MegaBull returns 401/403 indicating missing, invalid, or expired API key."""
    pass

class MegaBullApiException(Exception):
    """Raised when MegaBull returns an API error response."""
    def __init__(self, status_code: int, error: str, messages: List[str], path: str):
        super().__init__(f"MegaBull API Error {status_code} at {path}: {error} - {messages}")
        self.status_code = status_code
        self.error = error
        self.messages = messages
        self.path = path

class MegaBullClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.megabull.in",
        timeout: float = 10.0,
        min_request_interval: float = 0.5, # Cap at 2 requests per second
    ):
        if not PAPER_MODE_ONLY:
            raise RuntimeError("CRITICAL SAFETY VIOLATION: PAPER_MODE_ONLY must be True!")

        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.min_request_interval = min_request_interval
        self._last_request_time = 0.0

    def _rate_limit(self):
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)
        self._last_request_time = time.monotonic()

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["api-key"] = self.api_key
        return headers

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        retries: int = 3,
    ) -> Any:
        url = f"{self.base_url}{path}"

        for attempt in range(retries):
            self._rate_limit()
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.request(
                        method=method,
                        url=url,
                        headers=self._headers(),
                        params=params,
                        json=json_body,
                    )

                if resp.status_code in (401, 403):
                    msg = "Invalid, missing, or expired MegaBull API key"
                    try:
                        err_data = resp.json()
                        msg = err_data.get("message", [msg])[0]
                    except Exception:
                        pass
                    logger.error(f"[MEGABULL] Key expired or unauthorized: {msg}")
                    raise MegaBullAuthException(msg)

                if resp.status_code >= 400:
                    try:
                        err = resp.json()
                        error_type = err.get("error", "Error")
                        messages = err.get("message", [resp.text])
                        req_path = err.get("path", path)
                    except Exception:
                        error_type = "HttpError"
                        messages = [resp.text]
                        req_path = path

                    # If server error (5xx) or 429, retry
                    if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                        time.sleep(1.0 * (2 ** attempt))
                        continue

                    raise MegaBullApiException(resp.status_code, error_type, messages, req_path)

                if resp.status_code == 204:
                    return None
                return resp.json()

            except (httpx.RequestError, httpx.TimeoutException) as e:
                if attempt < retries - 1:
                    time.sleep(1.0 * (2 ** attempt))
                    continue
                raise MegaBullApiException(0, "NetworkException", [str(e)], path)

    # ---------------- Read-Only Endpoints ----------------

    def get_profile(self) -> Dict[str, Any]:
        """GET /api/user/my - user profile and virtual money balance"""
        return self._request("GET", "/api/user/my")

    def get_marketwatch(self) -> List[Dict[str, Any]]:
        """GET /api/marketwatch/my - user watch list"""
        res = self._request("GET", "/api/marketwatch/my")
        return res if isinstance(res, list) else []

    def get_instruments_download_url(self) -> str:
        """GET /api/marketwatch/instruments - downloadUrl for instruments CSV"""
        data = self._request("GET", "/api/marketwatch/instruments")
        if isinstance(data, dict) and "downloadUrl" in data:
            return data["downloadUrl"]
        # Fallback to known S3 public URL
        return "https://megabull-open.s3.us-east-1.amazonaws.com/Instrument-dev.csv"

    def get_ltp(self, instrument_token: str) -> Dict[str, Any]:
        """GET /api/marketwatch/ltp/{instrumentToken}"""
        return self._request("GET", f"/api/marketwatch/ltp/{instrument_token}")

    def get_positions(self, room_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """GET /api/position/my"""
        params = {"roomId": room_id} if room_id is not None else None
        res = self._request("GET", "/api/position/my", params=params)
        return res if isinstance(res, list) else []

    def get_orders(self, room_id: Optional[int] = None) -> Dict[str, List[Dict[str, Any]]]:
        """GET /api/order/my -> {'open': [...], 'executed': [...]}"""
        params = {"roomId": room_id} if room_id is not None else None
        res = self._request("GET", "/api/order/my", params=params)
        if isinstance(res, dict):
            return res
        return {"open": [], "executed": []}

    def get_holdings(self, room_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """GET /api/holding/my"""
        params = {"roomId": room_id} if room_id is not None else None
        res = self._request("GET", "/api/holding/my", params=params)
        return res if isinstance(res, list) else []

    # ---------------- Order Execution Endpoints (Paper Simulator) ----------------

    def place_order(
        self,
        instrument_token: str,
        qty: int,
        side: str,  # "BUY" or "SELL"
        order_type: str = "LIMIT",  # "LIMIT", "MKT", "SL"
        price: Optional[float] = None,
        trigger_price: Optional[float] = None,
        duration: str = "MIS",
    ) -> Dict[str, Any]:
        """
        POST /api/order/buysell
        Places a simulated paper order.
        CRITICAL: Never send `id` in request body per MegaBull schema!
        """
        if not PAPER_MODE_ONLY:
            raise RuntimeError("CRITICAL SAFETY VIOLATION: PAPER_MODE_ONLY must be True!")

        body: Dict[str, Any] = {
            "instrumentToken": str(instrument_token),
            "qty": int(qty),
            "type": side.upper(),
            "duration": duration.upper(),
            "orderType": order_type.upper(),
        }
        if price is not None:
            body["price"] = float(price)
        if trigger_price is not None:
            body["triggerPrice"] = float(trigger_price)

        return self._request("POST", "/api/order/buysell", json_body=body)

    def modify_order(
        self,
        order_id: int,
        instrument_token: str,
        qty: int,
        side: str,
        order_type: str = "LIMIT",
        price: Optional[float] = None,
        trigger_price: Optional[float] = None,
        duration: str = "MIS",
    ) -> Dict[str, Any]:
        """PUT /api/order/buysell/{orderId}"""
        body: Dict[str, Any] = {
            "instrumentToken": str(instrument_token),
            "qty": int(qty),
            "type": side.upper(),
            "duration": duration.upper(),
            "orderType": order_type.upper(),
        }
        if price is not None:
            body["price"] = float(price)
        if trigger_price is not None:
            body["triggerPrice"] = float(trigger_price)

        return self._request("PUT", f"/api/order/buysell/{order_id}", json_body=body)

    def cancel_orders(self, order_ids: List[int], room_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """PUT /api/order/bulk/cancel with array of order IDs"""
        params = {"roomId": room_id} if room_id is not None else None
        res = self._request("PUT", "/api/order/bulk/cancel", params=params, json_body=order_ids)
        return res if isinstance(res, list) else []
