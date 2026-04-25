import { NextResponse } from 'next/server'

const RAW_URL =
  'https://raw.githubusercontent.com/rladmsgh34/ai-dev-loop-analyzer/main/data/language-patterns.json'

export const revalidate = 3600

function makeBadge(label: string, value: string, color = '#4c1'): string {
  const lw = label.length * 6.5 + 14
  const vw = value.length * 7 + 14
  const tw = lw + vw
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${tw}" height="20">
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r"><rect width="${tw}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="${lw}" height="20" fill="#555"/>
    <rect x="${lw}" width="${vw}" height="20" fill="${color}"/>
    <rect width="${tw}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
    <text x="${lw / 2}" y="15" fill="#010101" fill-opacity=".3">${label}</text>
    <text x="${lw / 2}" y="14">${label}</text>
    <text x="${lw + vw / 2}" y="15" fill="#010101" fill-opacity=".3">${value}</text>
    <text x="${lw + vw / 2}" y="14">${value}</text>
  </g>
</svg>`
}

export async function GET() {
  let reposAnalyzed = 0
  let updatedAt = ''
  try {
    const res = await fetch(RAW_URL, { next: { revalidate: 3600 } })
    if (res.ok) {
      const data = await res.json()
      reposAnalyzed = data.total_repos_analyzed ?? 0
      updatedAt = data.updated_at ?? ''
    }
  } catch { /* fallback to 0 */ }

  const value = reposAnalyzed > 0
    ? `${reposAnalyzed} repos (${updatedAt})`
    : 'collecting...'
  const color = reposAnalyzed > 100 ? '#4c1' : reposAnalyzed > 0 ? '#dfb317' : '#9f9f9f'

  return new NextResponse(makeBadge('patterns learned', value, color), {
    headers: {
      'Content-Type': 'image/svg+xml',
      'Cache-Control': 's-maxage=3600, stale-while-revalidate',
    },
  })
}
