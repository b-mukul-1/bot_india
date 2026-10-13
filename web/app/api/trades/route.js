import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET(request) {
  const botUrl = process.env.BOT_API_URL || "http://127.0.0.1:8000";
  const { searchParams } = new URL(request.url);

  try {
    const res = await fetch(`${botUrl}/api/trades?${searchParams.toString()}`, { cache: "no-store" });
    if (!res.ok) {
      return NextResponse.json({ error: "Backend error", status: res.status }, { status: res.status });
    }
    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    return NextResponse.json([]);
  }
}
