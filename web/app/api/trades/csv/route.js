import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(request) {
  const botUrl = process.env.BOT_API_URL || "http://127.0.0.1:8000";
  const { searchParams } = new URL(request.url);

  try {
    const res = await fetch(`${botUrl}/api/trades.csv?${searchParams.toString()}`, { cache: "no-store" });
    if (!res.ok) {
      return new Response("Failed to fetch CSV from backend", { status: res.status });
    }

    const csvData = await res.arrayBuffer();
    return new Response(csvData, {
      status: 200,
      headers: {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": res.headers.get("content-disposition") || 'attachment; filename="apex_trades.csv"',
      },
    });
  } catch (err) {
    return new Response(`Error: ${err.message}`, { status: 500 });
  }
}
