// Per-repo analysis cache reader — workflow가 data/repos/{owner__repo}/analysis-cache.json에
// 누적해둔 결과를 web에서 재사용. live fetch보다 빠르고 cron 분석과 일치.
//
// 캐시 스키마는 src/analyze.py의 build_cache_dict() 출력 — web의 AnalysisResult와
// 일부 필드만 겹침. 변환 시 부재 필드(trend, riskyFiles 전체, full ai/human breakdown)는
// 빈 값 + source 마커로 표시.

import { promises as fs } from 'fs'
import path from 'path'

import type { AnalysisResult } from './analyzer'

const MONOREPO_ROOT = path.resolve(process.cwd(), '..')

interface CachedAnalysis {
  generated_at: string
  repo: string
  fix_rate: number
  summary: { total_prs: number; fix_prs: number; fix_rate: number }
  risky_files: { file: string; fix_count: number; domain: string }[]
  domain_counts: { domain: string; fix_count: number }[]
  ai_weak_domains: { domain: string; count: number }[]
  clusters: { start: number; end: number; size: number; domain: string }[]
}

export interface CachedAnalysisResult extends AnalysisResult {
  source: 'cache'
  generatedAt: string
}

/** 'owner/repo' → 'owner__repo' (repo_store.repo_slug() 정책 일치). */
function repoSlug(repo: string): string {
  return repo.replace('/', '__')
}

/** tracked 레포의 캐시를 읽어 web의 AnalysisResult로 변환. 없으면 null. */
export async function loadCachedResult(
  repo: string
): Promise<CachedAnalysisResult | null> {
  const cachePath = path.join(
    MONOREPO_ROOT,
    'data',
    'repos',
    repoSlug(repo),
    'analysis-cache.json'
  )
  let raw: string
  try {
    raw = await fs.readFile(cachePath, 'utf-8')
  } catch {
    return null
  }
  const cache: CachedAnalysis = JSON.parse(raw)

  return {
    source: 'cache',
    generatedAt: cache.generated_at,
    summary: {
      totalPRs: cache.summary.total_prs ?? 0,
      fixPRs: cache.summary.fix_prs ?? 0,
      fixRate: cache.summary.fix_rate ?? cache.fix_rate ?? 0,
    },
    // cache의 cluster는 PR detail 없음 — start/end/size/domain만.
    clusters: cache.clusters.map(c => ({
      prs: [],
      domain: c.domain,
      start: c.start,
      end: c.end,
    })),
    riskyFiles: cache.risky_files.map(f => ({
      file: f.file,
      fixCount: f.fix_count,
      domain: f.domain,
    })),
    domainCounts: cache.domain_counts.map(d => ({
      domain: d.domain,
      fixCount: d.fix_count,
    })),
    // cache는 ai_weak_domains만 — full ai/human breakdown 부재.
    // 표시단에서 source==='cache'면 위젯 비활성/축약 처리 필요.
    aiVsHuman: {
      ai: {
        total: 0,
        fixCount: 0,
        fixRate: 0,
        weakDomains: cache.ai_weak_domains ?? [],
      },
      human: { total: 0, fixCount: 0, fixRate: 0 },
    },
    // cache에 시계열 trend 부재 — live fetch에서만 채워짐.
    trend: [],
  }
}
