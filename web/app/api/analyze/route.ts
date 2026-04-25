import { NextRequest, NextResponse } from 'next/server'
import { fetchMergedPRs } from '@/lib/github'
import { analyze } from '@/lib/analyzer'

export const maxDuration = 30

export async function GET(req: NextRequest) {
  const owner = req.nextUrl.searchParams.get('owner')
  const repo = req.nextUrl.searchParams.get('repo')

  if (!owner || !repo) {
    return NextResponse.json({ error: 'owner, repo 파라미터 필요' }, { status: 400 })
  }

  try {
    const prs = await fetchMergedPRs(owner, repo, 200)
    if (prs.length === 0) {
      return NextResponse.json({ error: '머지된 PR이 없습니다.' }, { status: 404 })
    }
    const result = analyze(prs)
    return NextResponse.json(result, {
      headers: { 'Cache-Control': 's-maxage=3600, stale-while-revalidate' },
    })
  } catch (e) {
    const msg = e instanceof Error ? e.message : '분석 중 오류 발생'
    return NextResponse.json({ error: msg }, { status: 500 })
  }
}
