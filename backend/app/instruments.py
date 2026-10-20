"""
APEX-IN Instrument Resolver and Cache
Loads and parses MegaBull tradable instruments CSV.
Resolves Nifty and Sensex Spot, Futures, and Option contracts dynamically.
Never hardcodes tokens.
"""

import csv
import io
import re
import os
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime, date, timezone

logger = logging.getLogger(__name__)

# Standard exchange lot sizes (used as fallback when not provided in feed, verified from NSE/BSE)
EXCHANGE_DEFAULT_LOT_SIZES = {
    "NIFTY": 65,
    "SENSEX": 10,
    "BANKNIFTY": 30,
    "NIFTY BANK": 30,
    "FINNIFTY": 25,
}

MONTHS_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

def parse_contract_expiry(expiry_str: Optional[str], default_year: int = 2026) -> Optional[date]:
    if not expiry_str:
        return None
    parts = expiry_str.strip().split()
    if len(parts) == 2 and parts[1].upper() in MONTHS_MAP:
        try:
            return date(default_year, MONTHS_MAP[parts[1].upper()], int(parts[0]))
        except Exception:
            return None
    return None


@dataclass
class InstrumentContract:
    instrument_token: str
    trading_symbol: str
    instrument_name: str
    underlying: str  # "NIFTY", "SENSEX", etc.
    instrument_type: str  # "INDEX", "FUT", "CE", "PE"
    expiry_str: Optional[str] = None
    strike: Optional[float] = None
    lot_size: int = 1
    exchange: str = "NSE"

class InstrumentResolver:
    """Loads MegaBull instruments CSV and provides contract resolution."""

    def __init__(self, csv_path: Optional[str] = None):
        self.instruments_by_token: Dict[str, InstrumentContract] = {}
        self.instruments_by_symbol: Dict[str, InstrumentContract] = {}
        self.indices: Dict[str, InstrumentContract] = {}
        self.futures_by_underlying: Dict[str, List[InstrumentContract]] = {}
        self.options_by_underlying: Dict[str, List[InstrumentContract]] = {}
        self.last_loaded_at: Optional[datetime] = None

        if csv_path and os.path.exists(csv_path):
            self.load_from_file(csv_path)

    def load_from_text(self, csv_text: str) -> int:
        """Parses CSV text and populates lookup tables."""
        reader = csv.DictReader(io.StringIO(csv_text))
        count = self._parse_rows(reader)
        self.last_loaded_at = datetime.now(timezone.utc)
        return count

    def load_from_file(self, file_path: str) -> int:
        """Loads and parses instrument CSV from local file."""
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            count = self._parse_rows(reader)
        self.last_loaded_at = datetime.now(timezone.utc)
        return count

    def _parse_rows(self, reader: csv.DictReader) -> int:
        self.instruments_by_token.clear()
        self.instruments_by_symbol.clear()
        self.indices.clear()
        self.futures_by_underlying.clear()
        self.options_by_underlying.clear()

        count = 0
        for row in reader:
            symbol = row.get("tradingSymbol", "").strip()
            name = row.get("instrumentName", "").strip()
            token = row.get("instrumentToken", "").strip()

            if not token or not symbol:
                continue

            contract = self._parse_contract(symbol, name, token)
            if contract:
                self.instruments_by_token[token] = contract
                self.instruments_by_symbol[symbol] = contract

                if contract.instrument_type == "INDEX":
                    self.indices[contract.underlying] = contract
                elif contract.instrument_type == "FUT":
                    self.futures_by_underlying.setdefault(contract.underlying, []).append(contract)
                elif contract.instrument_type in ("CE", "PE"):
                    self.options_by_underlying.setdefault(contract.underlying, []).append(contract)

                count += 1

        logger.info(f"Loaded {count} instruments. Indices: {list(self.indices.keys())}")
        return count

    def _parse_contract(self, symbol: str, name: str, token: str) -> Optional[InstrumentContract]:
        # 1. Spot Indices
        if symbol in ("NIFTY 50", "NIFTY"):
            return InstrumentContract(
                instrument_token=token,
                trading_symbol=symbol,
                instrument_name=name,
                underlying="NIFTY",
                instrument_type="INDEX",
                exchange="NSE",
                lot_size=EXCHANGE_DEFAULT_LOT_SIZES["NIFTY"],
            )
        if symbol == "SENSEX":
            return InstrumentContract(
                instrument_token=token,
                trading_symbol=symbol,
                instrument_name=name,
                underlying="SENSEX",
                instrument_type="INDEX",
                exchange="BSE",
                lot_size=EXCHANGE_DEFAULT_LOT_SIZES["SENSEX"],
            )
        if symbol in ("NIFTY BANK", "BANKNIFTY"):
            return InstrumentContract(
                instrument_token=token,
                trading_symbol=symbol,
                instrument_name=name,
                underlying="BANKNIFTY",
                instrument_type="INDEX",
                exchange="NSE",
                lot_size=EXCHANGE_DEFAULT_LOT_SIZES["BANKNIFTY"],
            )
        if symbol == "INDIA VIX":
            return InstrumentContract(
                instrument_token=token,
                trading_symbol=symbol,
                instrument_name=name,
                underlying="INDIA VIX",
                instrument_type="INDEX",
                exchange="NSE",
                lot_size=1,
            )

        # 2. Options pattern in instrumentName:
        # e.g. "NIFTY 04 AUG 24750 CE", "SENSEX 06 AUG 78600 PE", "BANKNIFTY 25 AUG 51000 CE"
        opt_match = re.match(r"^(NIFTY|SENSEX|BANKNIFTY)\s+(\d{1,2}\s+[A-Z]{3})\s+(\d+(?:\.\d+)?)\s+(CE|PE)$", name, re.IGNORECASE)
        if opt_match:
            underlying = opt_match.group(1).upper()
            expiry_str = opt_match.group(2).upper()
            strike = float(opt_match.group(3))
            opt_type = opt_match.group(4).upper()
            exchange = "BSE" if underlying == "SENSEX" else "NSE"
            lot_size = EXCHANGE_DEFAULT_LOT_SIZES.get(underlying, 1)

            return InstrumentContract(
                instrument_token=token,
                trading_symbol=symbol,
                instrument_name=name,
                underlying=underlying,
                instrument_type=opt_type,
                expiry_str=expiry_str,
                strike=strike,
                lot_size=lot_size,
                exchange=exchange,
            )

        # 3. Futures pattern in instrumentName:
        # e.g. "NIFTY 25 AUG  FUT", "SENSEX 27 AUG  FUT"
        fut_match = re.match(r"^(NIFTY|SENSEX|BANKNIFTY)\s+(\d{1,2}\s+[A-Z]{3})\s+FUT$", name, re.IGNORECASE)
        if fut_match:
            underlying = fut_match.group(1).upper()
            expiry_str = fut_match.group(2).upper()
            exchange = "BSE" if underlying == "SENSEX" else "NSE"
            lot_size = EXCHANGE_DEFAULT_LOT_SIZES.get(underlying, 1)

            return InstrumentContract(
                instrument_token=token,
                trading_symbol=symbol,
                instrument_name=name,
                underlying=underlying,
                instrument_type="FUT",
                expiry_str=expiry_str,
                lot_size=lot_size,
                exchange=exchange,
            )

        # Other stocks or unparsed contracts
        return None

    def get_spot(self, underlying: str) -> Optional[InstrumentContract]:
        u = underlying.upper()
        if u in ("NIFTY", "NIFTY 50"):
            return self.indices.get("NIFTY")
        return self.indices.get(u)

    def get_futures(self, underlying: str, ref_date: Optional[date] = None) -> List[InstrumentContract]:
        u = underlying.upper()
        futs = self.futures_by_underlying.get(u, [])
        if not futs:
            return []
        current_d = ref_date or datetime.now(timezone.utc).date()
        # Filter unexpired and sort by nearest expiry
        valid = [f for f in futs if parse_contract_expiry(f.expiry_str) and parse_contract_expiry(f.expiry_str) >= current_d]
        if valid:
            valid.sort(key=lambda f: parse_contract_expiry(f.expiry_str))
            return valid
        return futs

    def get_options(
        self,
        underlying: str,
        expiry: Optional[str] = None,
        opt_type: Optional[str] = None
    ) -> List[InstrumentContract]:
        u = underlying.upper()
        opts = self.options_by_underlying.get(u, [])
        if expiry:
            opts = [o for o in opts if o.expiry_str == expiry.upper()]
        if opt_type:
            opts = [o for o in opts if o.instrument_type == opt_type.upper()]
        return opts

    def get_nearest_active_expiry(self, underlying: str, ref_date: Optional[date] = None) -> Optional[str]:
        current_d = ref_date or datetime.now(timezone.utc).date()
        opts = self.get_options(underlying)
        valid = []
        for o in opts:
            d = parse_contract_expiry(o.expiry_str)
            if d and d >= current_d:
                valid.append((d, o.expiry_str))
        if not valid:
            all_exp = [(parse_contract_expiry(o.expiry_str) or date(2099, 1, 1), o.expiry_str) for o in opts if o.expiry_str]
            if all_exp:
                all_exp.sort(key=lambda x: x[0], reverse=True)
                return all_exp[0][1]
            return None
        valid.sort(key=lambda x: x[0])
        return valid[0][1]

    def get_atm_options(
        self,
        underlying: str,
        spot_price: float,
        n_strikes: int = 5,
        expiry: Optional[str] = None
    ) -> Dict[str, List[InstrumentContract]]:
        """
        Returns ATM +/- n_strikes for CE and PE for the active unexpired contract.
        Sorts options so the closest ATM contract is first.
        """
        target_expiry = expiry or self.get_nearest_active_expiry(underlying)
        all_opts = self.get_options(underlying, expiry=target_expiry)
        if not all_opts:
            return {"CE": [], "PE": []}

        # Filter unique strikes
        strikes = sorted(list(set(o.strike for o in all_opts if o.strike is not None)))
        if not strikes:
            return {"CE": [], "PE": []}

        # Find closest strike to spot_price
        closest_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot_price))
        start_idx = max(0, closest_idx - n_strikes)
        end_idx = min(len(strikes), closest_idx + n_strikes + 1)
        target_strikes = set(strikes[start_idx:end_idx])

        ce_opts = [o for o in all_opts if o.instrument_type == "CE" and o.strike in target_strikes]
        pe_opts = [o for o in all_opts if o.instrument_type == "PE" and o.strike in target_strikes]

        # Closest ATM first
        ce_opts.sort(key=lambda o: abs((o.strike or 0.0) - spot_price))
        pe_opts.sort(key=lambda o: abs((o.strike or 0.0) - spot_price))

        return {"CE": ce_opts, "PE": pe_opts}

    def get_by_token(self, token: str) -> Optional[InstrumentContract]:
        return self.instruments_by_token.get(str(token))

    def get_by_symbol(self, symbol: str) -> Optional[InstrumentContract]:
        return self.instruments_by_symbol.get(symbol)
