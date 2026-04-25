import { NextRequest, NextResponse } from 'next/server'
import { fetchMergedPRs } from '@/lib/github'
import { analyze } from '@/lib/analyzer'

export const maxDuration = 30

function makeBadgeSvg(label: string, value: string, color: string): string {
  const labelWidth = label.length * 6.5 + 14
  const valueWidth = value.length * 7 + 14
  const totalWidth = labelWidth + valueWidth

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${totalWidth}" height="20">
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r">
    <rect width="${totalWidth}" height="20" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#r)">
    <rect width="${labelWidth}" height="20" fill="#555"/>
    <rect x="${labelWidth}" width="${valueWidth}" height="20" fill="${color}"/>
    <rect width="${totalWidth}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
    <text x="${labelWidth / 2}" y="15" fill="#010101" fill-opacity=".3">${label}</text>
    <text x="${labelWidth / 2}" y="14">${label}</text>
    <text x="${labelWidth + valueWidth / 2}" y="15" fill="#010101" fill-opacity=".3">${value}</text>
    <text x="${labelWidth + valueWidth / 2}" y="14">${value}</text>
  </g>
</svg>`
}

export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ owner: string; repo: string }> }
) {
  const { owner, repo } = await params

  try {
    const prs = await fetchMergedPRs(owner, repo, 200)
    const { summary } = analyze(prs)

    const color =
      summary.fixRate > 20 ? '#e05d44' :
      summary.fixRate > 10 ? '#dfb317' :
      '#4c1'

    const svg = makeBadgeSvg('AI fix rate', `${summary.fixRate}%`, color)

    return new NextResponse(svg, {
      headers: {
        'Content-Type': 'image/svg+xml',
        'Cache-Control': 's-maxage=3600, stale-while-revalidate',
      },
    })
  } catch {
    const svg = makeBadgeSvg('AI fix rate', 'error', '#9f9f9f')
    return new NextResponse(svg, {
      headers: { 'Content-Type': 'image/svg+xml' },
    })
  }
}
