import { NextResponse } from 'next/server'

const RAW_URL =
  'https://raw.githubusercontent.com/rladmsgh34/ai-dev-loop-analyzer/main/data/language-patterns.json'

export const revalidate = 3600

export async function GET() {
  try {
    const res = await fetch(RAW_URL, { next: { revalidate: 3600 } })
    if (!res.ok) throw new Error('fetch failed')
    const data = await res.json()

    const reposAnalyzed: number = data.total_repos_analyzed ?? 0
    const languages: number = Object.keys(data.languages ?? {}).length
    const updatedAt: string = data.updated_at ?? ''

    // 총 청크 수 추정: 언어 요약 + 도메인 상세 + 레포 결과
    let estimatedChunks = reposAnalyzed
    for (const stats of Object.values(data.languages ?? {}) as any[]) {
      estimatedChunks += 1 + Object.keys(stats.domain_avg_fix_rates ?? {}).length
    }

    return NextResponse.json({ reposAnalyzed, languages, updatedAt, estimatedChunks })
  } catch {
    return NextResponse.json({ reposAnalyzed: 0, languages: 0, updatedAt: '', estimatedChunks: 0 })
  }
}
