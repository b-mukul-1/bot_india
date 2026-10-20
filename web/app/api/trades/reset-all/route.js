import { NextResponse } from "next/server";

export async function POST(request) {
  const botUrl = process.env.BOT_API_URL || "http://127.0.0.1:8000";
  const sharedSecret = process.env.API_SHARED_SECRET || "37cd55de95dba6c76275c79c1489e269d52ebafc36ca13e990191fc24609bd50";

  try {
    const res = await fetch(`${botUrl}/api/trades/reset-all`, {
      method: "POST",
      headers: {
        "X-Shared-Secret": sharedSecret,
      },
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json({ error: err.message }, { status: 500 });
  }
}
