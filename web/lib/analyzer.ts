// PR 히스토리 분석 엔진 — analyze.py의 TypeScript 포트.
// 분류 정책은 profile-driven (scope-first → file/title pattern). hardcoded regex 제거.

import type { Profile } from './profiles'

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

export interface TrendPoint {
  month: string   // "2024-01"
  total: number
  fixCount: number
  fixRate: number
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
  trend: TrendPoint[]
}

const SCOPE_RE = /^\w+\(([^)]+)\):?/i

export function isFixPR(title: string, profile: Profile): boolean {
  return profile.fixPrRegex.test(title)
}

/** scope-first: `fix(scope):` → scope_to_domain → 매칭 없으면 file/title regex. */
export function classifyDomain(title: string, files: string[], profile: Profile): string {
  const scopeMatch = title.match(SCOPE_RE)
  if (scopeMatch) {
    const scope = scopeMatch[1].toLowerCase()
    for (const [key, domain] of Object.entries(profile.scopeToDomain)) {
      if (scope.includes(key)) return domain
    }
  }
  const combined = [title, ...files].join(' ')
  for (const [domain, pattern] of profile.domainPatterns) {
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

function analyzeTrend(prs: PR[]): TrendPoint[] {
  const byMonth: Record<string, { total: number; fix: number }> = {}
  for (const pr of prs) {
    const month = pr.mergedAt.slice(0, 7)
    if (!byMonth[month]) byMonth[month] = { total: 0, fix: 0 }
    byMonth[month].total++
    if (pr.isFix) byMonth[month].fix++
  }
  return Object.entries(byMonth)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([month, { total, fix }]) => ({
      month,
      total,
      fixCount: fix,
      fixRate: total > 0 ? Math.round((fix / total) * 1000) / 10 : 0,
    }))
    .slice(-12)
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

  // AI vs human (Co-Authored-By: Claude만 감지) — single-arm 환경에서 노이즈 큼.
  // 캐시 경로에서는 비어있고 live 경로에서만 채워진다.
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
    trend: analyzeTrend(prs),
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
