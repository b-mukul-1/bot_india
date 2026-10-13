import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  const botUrl = process.env.BOT_API_URL || "http://127.0.0.1:8000";
  try {
    const res = await fetch(`${botUrl}/api/status`, { cache: "no-store" });
    if (!res.ok) {
      return NextResponse.json({ error: "Backend error", status: res.status }, { status: res.status });
    }
    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json({
      error: "Backend offline",
      initial_capital: 500000.0,
      current_equity: 500000.0,
      peak_equity: 500000.0,
      drawdown_pct: 0.0,
      gross_pnl_today: 0.0,
      charges_today: 0.0,
      net_pnl_today: 0.0,
      trades_count_today: 0,
      total_trades_count: 0,
      sentinel_halted: false,
      kill_switch_active: false,
      paper_mode_only: true,
      market_session: { is_open: false, phase: "SIMULATED_STANDBY" }
    });
  }
}
