import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  const botUrl = process.env.BOT_API_URL || "http://127.0.0.1:8000";
  try {
    const res = await fetch(`${botUrl}/api/charges/summary`, { cache: "no-store" });
    if (!res.ok) {
      return NextResponse.json({ error: "Backend error", status: res.status }, { status: res.status });
    }
    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json({
      totals: {
        brokerage: 0,
        stt: 0,
        exchange_txn: 0,
        sebi_fee: 0,
        stamp_duty: 0,
        ipft: 0,
        gst: 0,
        total_charges: 0,
      },
      gross_pnl_total: 0,
      net_pnl_total: 0,
      charges_as_pct_of_gross: 0,
      total_trades: 0,
    });
  }
}
