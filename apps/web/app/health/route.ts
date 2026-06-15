import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({
    status: "ok",
    service: "teacher-assistant-frontend",
    environment: process.env.NODE_ENV ?? "development",
  });
}

export function HEAD() {
  return new Response(null, { status: 200 });
}
