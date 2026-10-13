"""
APEX-IN F&O Charges Engine
Computes comprehensive statutory levies and brokerage for Indian Futures and Options trades
per leg and per round-trip using Decimal precision rounded to paise.
Verified against post-April-2026 STT rate schedules and NSE/BSE transaction circulars.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, Optional
from dataclasses import dataclass
import os
import yaml

PAISE = Decimal("0.01")

def round_paise(val: Decimal) -> Decimal:
    """Rounds a Decimal value to the nearest paise (2 decimal places)."""
    return val.quantize(PAISE, rounding=ROUND_HALF_UP)

@dataclass
class LegCharges:
    side: str  # "BUY" or "SELL"
    instrument_type: str  # "FUT", "CE", "PE"
    exchange: str  # "NSE" or "BSE"
    price: Decimal
    quantity: int
    turnover: Decimal
    brokerage: Decimal
    stt: Decimal
    exchange_txn: Decimal
    sebi_fee: Decimal
    stamp_duty: Decimal
    ipft: Decimal
    gst: Decimal
    total_charges: Decimal
    charges_as_pct_of_turnover: Decimal

    def to_dict(self) -> Dict[str, Any]:
        return {
            "side": self.side,
            "instrument_type": self.instrument_type,
            "exchange": self.exchange,
            "price": float(self.price),
            "quantity": self.quantity,
            "turnover": float(self.turnover),
            "brokerage": float(self.brokerage),
            "stt": float(self.stt),
            "exchange_txn": float(self.exchange_txn),
            "sebi_fee": float(self.sebi_fee),
            "stamp_duty": float(self.stamp_duty),
            "ipft": float(self.ipft),
            "gst": float(self.gst),
            "total_charges": float(self.total_charges),
            "charges_as_pct_of_turnover": float(self.charges_as_pct_of_turnover),
        }

@dataclass
class RoundTripCharges:
    entry_leg: LegCharges
    exit_leg: LegCharges
    total_turnover: Decimal
    brokerage: Decimal
    stt: Decimal
    exchange_txn: Decimal
    sebi_fee: Decimal
    stamp_duty: Decimal
    ipft: Decimal
    gst: Decimal
    total_charges: Decimal
    charges_as_pct_of_turnover: Decimal
    gross_pnl: Decimal
    net_pnl: Decimal

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_leg": self.entry_leg.to_dict(),
            "exit_leg": self.exit_leg.to_dict(),
            "total_turnover": float(self.total_turnover),
            "brokerage": float(self.brokerage),
            "stt": float(self.stt),
            "exchange_txn": float(self.exchange_txn),
            "sebi_fee": float(self.sebi_fee),
            "stamp_duty": float(self.stamp_duty),
            "ipft": float(self.ipft),
            "gst": float(self.gst),
            "total_charges": float(self.total_charges),
            "charges_as_pct_of_turnover": float(self.charges_as_pct_of_turnover),
            "gross_pnl": float(self.gross_pnl),
            "net_pnl": float(self.net_pnl),
        }

class ChargesEngine:
    """Loads rates from rates.yaml and computes exact F&O trading charges."""

    def __init__(self, rates_file: Optional[str] = None):
        if rates_file is None:
            rates_file = os.path.join(os.path.dirname(__file__), "rates.yaml")
        self.rates_file = rates_file
        self.rates = self._load_rates(rates_file)

    def _load_rates(self, file_path: str) -> Dict[str, Any]:
        with open(file_path, "r") as f:
            data = yaml.safe_load(f)
        return data

    def calculate_leg(
        self,
        side: str,  # "BUY" or "SELL"
        instrument_type: str,  # "FUT", "CE", "PE"
        price: float | Decimal,
        quantity: int,
        exchange: str = "NSE",
        brokerage_per_order: Optional[float | Decimal] = None,
    ) -> LegCharges:
        side_norm = side.upper()
        inst_type_norm = instrument_type.upper()
        exch_norm = exchange.upper()

        if side_norm not in ("BUY", "SELL"):
            raise ValueError(f"Invalid side: {side}. Must be 'BUY' or 'SELL'.")
        if inst_type_norm not in ("FUT", "CE", "PE", "OPT"):
            raise ValueError(f"Invalid instrument_type: {instrument_type}")
        if quantity <= 0:
            raise ValueError(f"Quantity must be positive: {quantity}")

        dec_price = Decimal(str(price))
        if dec_price < Decimal("0"):
            raise ValueError(f"Price cannot be negative: {price}")

        # Traded turnover (for options, premium turnover = premium * qty; for futures = price * qty)
        turnover = dec_price * Decimal(str(quantity))

        # 1. Brokerage
        if brokerage_per_order is not None:
            raw_brokerage = Decimal(str(brokerage_per_order))
        else:
            default_brokerage = Decimal(str(self.rates["brokerage"]["default_per_order_inr"]))
            raw_brokerage = default_brokerage
        brokerage = round_paise(raw_brokerage)

        # 2. STT (Securities Transaction Tax) - ONLY on SELL side
        stt = Decimal("0.00")
        if side_norm == "SELL":
            if inst_type_norm == "FUT":
                stt_rate = Decimal(str(self.rates["stt"]["futures"]["rate"]))
                stt = round_paise(turnover * stt_rate)
            else:  # Options (CE/PE/OPT)
                stt_rate = Decimal(str(self.rates["stt"]["options"]["rate"]))
                stt = round_paise(turnover * stt_rate)

        # 3. Exchange Transaction Charges - Both sides
        exch_key = "nse" if exch_norm == "NSE" else "bse"
        exch_conf = self.rates["exchange_txn"][exch_key]
        if inst_type_norm == "FUT":
            exch_rate = Decimal(str(exch_conf["futures_rate"]))
        else:
            exch_rate = Decimal(str(exch_conf["options_rate"]))
        exchange_txn = round_paise(turnover * exch_rate)

        # 4. SEBI Turnover Fee - Both sides (Rs 10 per crore = 0.0001%)
        sebi_rate = Decimal(str(self.rates["sebi_fee"]["rate"]))
        sebi_fee = round_paise(turnover * sebi_rate)

        # 5. Stamp Duty - ONLY on BUY side
        stamp_duty = Decimal("0.00")
        if side_norm == "BUY":
            if inst_type_norm == "FUT":
                stamp_rate = Decimal(str(self.rates["stamp_duty"]["futures_rate"]))
            else:
                stamp_rate = Decimal(str(self.rates["stamp_duty"]["options_rate"]))
            stamp_duty = round_paise(turnover * stamp_rate)

        # 6. IPFT (Investor Protection Fund) - Both sides
        ipft_conf = self.rates["ipft"].get(exch_key, {})
        if inst_type_norm == "FUT":
            ipft_rate = Decimal(str(ipft_conf.get("futures_rate", "0.0000010")))
        else:
            ipft_rate = Decimal(str(ipft_conf.get("options_rate", "0.0000050")))
        ipft = round_paise(turnover * ipft_rate)

        # 7. GST - 18% on (Brokerage + Exchange Txn + SEBI Fee + IPFT)
        gst_base = brokerage + exchange_txn + sebi_fee + ipft
        gst_rate = Decimal(str(self.rates["gst"]["rate"]))
        gst = round_paise(gst_base * gst_rate)

        # Total Leg Charges
        total_charges = (
            brokerage + stt + exchange_txn + sebi_fee + stamp_duty + ipft + gst
        )

        pct_turnover = Decimal("0.0000")
        if turnover > Decimal("0"):
            pct_turnover = (total_charges / turnover * Decimal("100")).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )

        return LegCharges(
            side=side_norm,
            instrument_type=inst_type_norm,
            exchange=exch_norm,
            price=dec_price,
            quantity=quantity,
            turnover=turnover,
            brokerage=brokerage,
            stt=stt,
            exchange_txn=exchange_txn,
            sebi_fee=sebi_fee,
            stamp_duty=stamp_duty,
            ipft=ipft,
            gst=gst,
            total_charges=total_charges,
            charges_as_pct_of_turnover=pct_turnover,
        )

    def calculate_round_trip(
        self,
        instrument_type: str,  # "FUT", "CE", "PE"
        entry_side: str,  # "BUY" (for long) or "SELL" (for short)
        entry_price: float | Decimal,
        exit_price: float | Decimal,
        quantity: int,
        exchange: str = "NSE",
        brokerage_per_order: Optional[float | Decimal] = None,
    ) -> RoundTripCharges:
        entry_side_norm = entry_side.upper()
        exit_side_norm = "SELL" if entry_side_norm == "BUY" else "BUY"

        entry_leg = self.calculate_leg(
            side=entry_side_norm,
            instrument_type=instrument_type,
            price=entry_price,
            quantity=quantity,
            exchange=exchange,
            brokerage_per_order=brokerage_per_order,
        )

        exit_leg = self.calculate_leg(
            side=exit_side_norm,
            instrument_type=instrument_type,
            price=exit_price,
            quantity=quantity,
            exchange=exchange,
            brokerage_per_order=brokerage_per_order,
        )

        total_turnover = entry_leg.turnover + exit_leg.turnover
        brokerage = entry_leg.brokerage + exit_leg.brokerage
        stt = entry_leg.stt + exit_leg.stt
        exchange_txn = entry_leg.exchange_txn + exit_leg.exchange_txn
        sebi_fee = entry_leg.sebi_fee + exit_leg.sebi_fee
        stamp_duty = entry_leg.stamp_duty + exit_leg.stamp_duty
        ipft = entry_leg.ipft + exit_leg.ipft
        gst = entry_leg.gst + exit_leg.gst
        total_charges = entry_leg.total_charges + exit_leg.total_charges

        # Gross PnL: for Long (BUY entry), (exit_price - entry_price) * qty
        # for Short (SELL entry), (entry_price - exit_price) * qty
        dec_entry_price = Decimal(str(entry_price))
        dec_exit_price = Decimal(str(exit_price))
        dec_qty = Decimal(str(quantity))

        if entry_side_norm == "BUY":
            gross_pnl = round_paise((dec_exit_price - dec_entry_price) * dec_qty)
        else:
            gross_pnl = round_paise((dec_entry_price - dec_exit_price) * dec_qty)

        net_pnl = gross_pnl - total_charges

        pct_turnover = Decimal("0.0000")
        if total_turnover > Decimal("0"):
            pct_turnover = (total_charges / total_turnover * Decimal("100")).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )

        return RoundTripCharges(
            entry_leg=entry_leg,
            exit_leg=exit_leg,
            total_turnover=total_turnover,
            brokerage=brokerage,
            stt=stt,
            exchange_txn=exchange_txn,
            sebi_fee=sebi_fee,
            stamp_duty=stamp_duty,
            ipft=ipft,
            gst=gst,
            total_charges=total_charges,
            charges_as_pct_of_turnover=pct_turnover,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
        )
