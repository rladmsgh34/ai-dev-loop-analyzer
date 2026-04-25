// PR 히스토리 분석 엔진 — analyze.py의 TypeScript 포트

export interface PR {
  number: number
  title: string
  mergedAt: string
  additions: number
  deletions: number
  isFix: boolean
  domain: string
  isAiGenerated?: boolean
}

export interface Cluster {
  prs: PR[]
  domain: string
  start: number
  end: number
}

export interface AnalysisResult {
  summary: { totalPRs: number; fixPRs: number; fixRate: number }
  clusters: Cluster[]
  riskyFiles: { file: string; fixCount: number; domain: string }[]
  domainCounts: { domain: string; fixCount: number }[]
  aiVsHuman: {
    ai: { total: number; fixCount: number; fixRate: number; weakDomains: { domain: string; count: number }[] }
    human: { total: number; fixCount: number; fixRate: number }
  }
}

const DOMAIN_PATTERNS: [string, RegExp][] = [
  ['ci/cd',        /deploy|docker|dockerfile|ci\b|workflow|buildx|healthcheck|compose|musl|alpine/i],
  ['auth',         /auth|login|signup|session|jwt|credential|signin/i],
  ['payment',      /payment|portone|checkout|order|cart|purchase|결제|주문|장바구니/i],
  ['database',     /prisma|migration|schema/i],
  ['security',     /csp|xss|csrf|rate.?limit|sanitize|allowlist/i],
  ['external-api', /kakao|postcode|우편번호|google.?maps|gcs|sentry|daum/i],
  ['test/e2e',     /\.test\.|\.spec\.|e2e|playwright|vitest|coverage/i],
  ['config',       /next\.config|env\.ts|tsconfig|biome|tailwind|npmrc/i],
]

export function classifyDomain(title: string, files: string[] = []): string {
  const combined = [title, ...files].join(' ')
  for (const [domain, pattern] of DOMAIN_PATTERNS) {
    if (pattern.test(combined)) return domain
  }
  return 'general'
}

export function detectClusters(prs: PR[], windowSize = 8, threshold = 2): Cluster[] {
  const sorted = [...prs].sort((a, b) => a.number - b.number)
  const inCluster = new Set<number>()
  const clusters: Cluster[] = []

  for (let i = 0; i < sorted.length; i++) {
    if (!sorted[i].isFix || inCluster.has(i)) continue
    const group = [i]
    for (let j = i + 1; j < sorted.length && sorted[j].number - sorted[i].number < windowSize * 3; j++) {
      if (sorted[j].isFix) group.push(j)
      if (group.length >= 8) break
    }
    if (group.length >= threshold) {
      const groupPRs = group.map(idx => sorted[idx])
      const domainCounts: Record<string, number> = {}
      for (const pr of groupPRs) domainCounts[pr.domain] = (domainCounts[pr.domain] ?? 0) + 1
      const domain = Object.entries(domainCounts).sort((a, b) => b[1] - a[1])[0][0]
      clusters.push({ prs: groupPRs, domain, start: groupPRs[0].number, end: groupPRs.at(-1)!.number })
      group.forEach(idx => inCluster.add(idx))
    }
  }
  return clusters
}

export function analyze(prs: PR[]): AnalysisResult {
  const fixPRs = prs.filter(p => p.isFix)
  const fixRate = prs.length ? Math.round((fixPRs.length / prs.length) * 1000) / 10 : 0
  const clusters = detectClusters(prs)

  const domainCounter: Record<string, number> = {}
  for (const pr of fixPRs) domainCounter[pr.domain] = (domainCounter[pr.domain] ?? 0) + 1
  const domainCounts = Object.entries(domainCounter)
    .map(([domain, fixCount]) => ({ domain, fixCount }))
    .sort((a, b) => b.fixCount - a.fixCount)

  // AI vs human
  const aiPRs = prs.filter(p => p.isAiGenerated)
  const humanPRs = prs.filter(p => !p.isAiGenerated)
  const aiFixPRs = aiPRs.filter(p => p.isFix)
  const humanFixPRs = humanPRs.filter(p => p.isFix)
  const aiDomainCounter: Record<string, number> = {}
  for (const pr of aiFixPRs) aiDomainCounter[pr.domain] = (aiDomainCounter[pr.domain] ?? 0) + 1

  return {
    summary: { totalPRs: prs.length, fixPRs: fixPRs.length, fixRate },
    clusters,
    riskyFiles: [],
    domainCounts,
    aiVsHuman: {
      ai: {
        total: aiPRs.length,
        fixCount: aiFixPRs.length,
        fixRate: aiPRs.length ? Math.round(aiFixPRs.length / aiPRs.length * 1000) / 10 : 0,
        weakDomains: Object.entries(aiDomainCounter)
          .map(([domain, count]) => ({ domain, count }))
          .sort((a, b) => b.count - a.count),
      },
      human: {
        total: humanPRs.length,
        fixCount: humanFixPRs.length,
        fixRate: humanPRs.length ? Math.round(humanFixPRs.length / humanPRs.length * 1000) / 10 : 0,
      },
    },
  }
}
