import { NextResponse } from "next/server";

export async function POST(request) {
  const botUrl = process.env.BOT_API_URL || "http://127.0.0.1:8000";
  const sharedSecret = process.env.API_SHARED_SECRET || "apex-secret-key-replace-in-env";

  try {
    const body = await request.json();
    const { confirm } = body;

    if (confirm !== "HALT") {
      return NextResponse.json({ error: "Must confirm with 'HALT'" }, { status: 400 });
    }

    const res = await fetch(`${botUrl}/api/kill-switch?confirm=HALT`, {
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
