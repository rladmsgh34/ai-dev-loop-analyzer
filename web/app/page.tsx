import Link from 'next/link'
import { fetchMergedPRs, validateRepo } from '../lib/github'
import { analyze, type AnalysisResult } from '../lib/analyzer'
import { getProfileForRepo, isTrackedRepo } from '../lib/profiles'
import { loadCachedResult } from '../lib/cache'
import HomeForm from './HomeForm'

const FEATURED_REPOS = [
  { owner: 'vercel', repo: 'next.js' },
  { owner: 'facebook', repo: 'react' },
  { owner: 'microsoft', repo: 'vscode' },
  { owner: 'prisma', repo: 'prisma' },
  { owner: 'vitejs', repo: 'vite' },
]

interface FeaturedRepoData {
  owner: string
  repo: string
  stars: number
  fixRate: number
  clusterCount: number
  topDomain: string | null
}

async function fetchFeaturedRepo(owner: string, repo: string): Promise<FeaturedRepoData | null> {
  const fullRepo = `${owner}/${repo}`
  try {
    const repoInfo = await validateRepo(owner, repo)
    let result: AnalysisResult

    // tracked 레포는 cache 우선 — featured 그리드 빌드 비용 절감.
    if (await isTrackedRepo(fullRepo)) {
      const cached = await loadCachedResult(fullRepo)
      if (cached) {
        result = cached
      } else {
        const profile = await getProfileForRepo(fullRepo)
        const prs = await fetchMergedPRs(owner, repo, 200, profile)
        result = analyze(prs)
      }
    } else {
      const profile = await getProfileForRepo(fullRepo)
      const prs = await fetchMergedPRs(owner, repo, 200, profile)
      result = analyze(prs)
    }

    const topDomain = result.domainCounts[0]?.domain ?? null
    return {
      owner,
      repo,
      stars: repoInfo.stars,
      fixRate: result.summary.fixRate,
      clusterCount: result.clusters.length,
      topDomain,
    }
  } catch {
    return null
  }
}

function fixRateColor(rate: number): string {
  if (rate <= 10) return 'text-green-400'
  if (rate <= 20) return 'text-yellow-400'
  return 'text-red-400'
}

function formatStars(stars: number): string {
  if (stars >= 1000) return `${(stars / 1000).toFixed(1)}k`
  return String(stars)
}

export const revalidate = 86400 // 하루 캐시

export default async function Home() {
  const featuredResults = await Promise.all(
    FEATURED_REPOS.map(({ owner, repo }) => fetchFeaturedRepo(owner, repo))
  )
  const featuredRepos = featuredResults.filter((r): r is FeaturedRepoData => r !== null)

  return (
    <main className="min-h-screen bg-gradient-to-br from-gray-950 via-gray-900 to-gray-950 text-white">
      <div className="mx-auto max-w-2xl px-4 py-24">
        <div className="mb-12 text-center">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-1.5 text-xs text-gray-400">
            <span className="h-1.5 w-1.5 rounded-full bg-green-400 inline-block" />
            Public repos · No auth required
          </div>
          <h1 className="mt-4 text-4xl font-bold tracking-tight md:text-5xl">
            AI Dev Loop
            <span className="bg-gradient-to-r from-blue-400 to-violet-400 bg-clip-text text-transparent">
              {' '}Analyzer
            </span>
          </h1>
          <p className="mt-4 text-lg text-gray-400">
            PR 히스토리에서 회귀 패턴을 감지하고
            <br />
            AI 코딩 어시스턴트 규칙을 자동 제안합니다
          </p>
        </div>

        <HomeForm />

        <div className="mt-16 grid gap-4 sm:grid-cols-3">
          {[
            { icon: '🔍', title: '회귀 클러스터 감지', desc: 'fix PR이 같은 도메인에서 연속 발생한 구간 자동 탐지' },
            { icon: '🤖', title: 'AI vs 사람 비교', desc: 'AI 생성 코드가 특히 취약한 도메인 분리 분석' },
            { icon: '💡', title: 'CLAUDE.md 규칙 제안', desc: '데이터 기반 AI 어시스턴트 규칙 자동 생성' },
          ].map(card => (
            <div key={card.title} className="rounded-2xl border border-white/5 bg-white/[0.03] p-5">
              <div className="mb-2 text-2xl">{card.icon}</div>
              <div className="mb-1 text-sm font-semibold">{card.title}</div>
              <div className="text-xs text-gray-500">{card.desc}</div>
            </div>
          ))}
        </div>

        <div className="mt-4 text-center">
          <a
            href="/languages"
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/5 bg-white/[0.03] px-4 py-2 text-xs text-gray-500 transition hover:bg-white/[0.06] hover:text-gray-300"
          >
            🌐 언어별 회귀 패턴 데이터 →
          </a>
        </div>

        {featuredRepos.length > 0 && (
          <section className="mt-20">
            <div className="mb-6 flex items-center gap-3">
              <div className="h-px flex-1 bg-white/5" />
              <span className="text-xs font-medium text-gray-500 tracking-widest uppercase">
                인기 레포 분석 결과
              </span>
              <div className="h-px flex-1 bg-white/5" />
            </div>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {featuredRepos.map(repo => (
                <div
                  key={`${repo.owner}/${repo.repo}`}
                  className="rounded-2xl border border-white/5 bg-white/[0.03] p-5 transition hover:border-white/10 hover:bg-white/[0.05]"
                >
                  <div className="mb-3">
                    <p className="text-xs text-gray-500">{repo.owner}/</p>
                    <p className="text-sm font-semibold text-white">{repo.repo}</p>
                  </div>

                  <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
                    <span className="flex items-center gap-1 text-xs text-gray-400">
                      ⭐ {formatStars(repo.stars)}
                    </span>
                    <span className={`text-xs font-semibold ${fixRateColor(repo.fixRate)}`}>
                      fix율 {repo.fixRate}%
                    </span>
                    <span className="text-xs text-gray-500">
                      클러스터 {repo.clusterCount}개
                    </span>
                  </div>

                  {repo.topDomain && (
                    <div className="mb-4">
                      <span className="inline-block rounded-full border border-white/10 bg-white/5 px-2.5 py-0.5 text-[11px] text-gray-400">
                        {repo.topDomain}
                      </span>
                    </div>
                  )}

                  <Link
                    href={`/r/${repo.owner}/${repo.repo}`}
                    className="inline-flex items-center gap-1 text-xs text-blue-400 transition hover:text-blue-300"
                  >
                    분석 보기 →
                  </Link>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </main>
  )
}
