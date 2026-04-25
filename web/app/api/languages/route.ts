import { NextResponse } from 'next/server'

const RAW_URL =
  'https://raw.githubusercontent.com/rladmsgh34/ai-dev-loop-analyzer/main/data/language-patterns.json'

export const revalidate = 3600  // 1시간 캐시

export async function GET() {
  try {
    const res = await fetch(RAW_URL, { next: { revalidate: 3600 } })
    if (!res.ok) throw new Error(`fetch failed: ${res.status}`)
    const data = await res.json()
    return NextResponse.json(data)
  } catch (e) {
    return NextResponse.json({ error: '데이터를 불러올 수 없습니다.' }, { status: 500 })
  }
}
