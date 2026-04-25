'use client'

const DOMAIN_COLORS: Record<string, string> = {
  'ci/cd':        'bg-orange-500/20 text-orange-300 border-orange-500/30',
  'auth':         'bg-blue-500/20 text-blue-300 border-blue-500/30',
  'payment':      'bg-green-500/20 text-green-300 border-green-500/30',
  'database':     'bg-purple-500/20 text-purple-300 border-purple-500/30',
  'security':     'bg-red-500/20 text-red-300 border-red-500/30',
  'external-api': 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
  'test/e2e':     'bg-cyan-500/20 text-cyan-300 border-cyan-500/30',
  'config':       'bg-gray-500/20 text-gray-300 border-gray-500/30',
  'api':          'bg-indigo-500/20 text-indigo-300 border-indigo-500/30',
  'ui':           'bg-pink-500/20 text-pink-300 border-pink-500/30',
}

const LANG_EMOJI: Record<string, string> = {
  typescript: '🔷', python: '🐍', go: '🐹', rust: '🦀',
  java: '☕', javascript: '🟨', kotlin: '🟣', swift: '🍎',
}

function DomainBadge({ domain }: { domain: string }) {
  const cls = DOMAIN_COLORS[domain] ?? 'bg-gray-500/20 text-gray-300 border-gray-500/30'
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${cls}`}>
      {domain}
    </span>
  )
}

interface LangStats {
  repos_analyzed: number
  avg_fix_rate: number
  avg_clusters: number
  domain_avg_fix_rates: Record<string, number>
  top_domains: string[]
  sample_repos: string[]
}

interface Props {
  data: {
    updated_at: string
    total_repos_analyzed: number
    languages: Record<string, LangStats>
  } | null
}

export default function LanguagesClient({ data }: Props) {
  const isEmpty = !data || !data.updated_at || Object.keys(data.languages).length === 0

  const languages = data
    ? Object.entries(data.languages).sort((a, b) => b[1].avg_fix_rate - a[1].avg_fix_rate)
    : []

  const maxFixRate = languages[0]?.[1].avg_fix_rate ?? 1

  // 전체 도메인 순위 (언어 통합)
  const globalDomainMap: Record<string, number[]> = {}
  for (const [, stats] of languages) {
    for (const [domain, rate] of Object.entries(stats.domain_avg_fix_rates)) {
      globalDomainMap[domain] = [...(globalDomainMap[domain] ?? []), rate]
    }
  }
  const globalDomains = Object.entries(globalDomainMap)
    .map(([domain, rates]) => ({ domain, avg: rates.reduce((a, b) => a + b, 0) / rates.length }))
    .sort((a, b) => b.avg - a.avg)
    .slice(0, 8)

  return (
    <main className="min-h-screen bg-gray-950 text-white">
      <div className="mx-auto max-w-4xl px-4 py-12">
        <a href="/" className="mb-6 inline-block text-xs text-gray-500 hover:text-gray-300">
          ← AI Dev Loop Analyzer
        </a>
        <div className="mb-8 flex items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold">언어별 회귀 패턴</h1>
            <p className="mt-1 text-sm text-gray-500">
              오픈소스 레포 PR 히스토리를 언어별로 집계한 회귀 패턴 데이터
            </p>
          </div>
          {data?.updated_at && (
            <span className="shrink-0 text-xs text-gray-600">
              마지막 업데이트: {data.updated_at}<br />
              분석 레포: {data.total_repos_analyzed.toLocaleString()}개
            </span>
          )}
        </div>

        {isEmpty ? (
          <div className="rounded-2xl border border-white/5 bg-white/[0.03] p-12 text-center">
            <div className="mb-3 text-4xl">⏳</div>
            <p className="text-gray-400">데이터 수집 중입니다.</p>
            <p className="mt-1 text-sm text-gray-600">
              매주 일요일 오전 11시(KST)에 자동으로 업데이트됩니다.
            </p>
            <p className="mt-4 text-xs text-gray-700">
              지금 바로 수집하려면 GitHub Actions에서{' '}
              <a
                href="https://github.com/rladmsgh34/ai-dev-loop-analyzer/actions/workflows/learn-patterns.yml"
                target="_blank"
                rel="noreferrer"
                className="text-blue-500 hover:underline"
              >
                Learn Language Patterns
              </a>{' '}
              워크플로우를 수동 실행하세요.
            </p>
          </div>
        ) : (
          <>
            {/* 전체 도메인 위험 순위 */}
            <section className="mb-6 rounded-2xl border border-white/5 bg-white/[0.03] p-6">
              <h2 className="mb-4 text-sm font-semibold text-gray-300">🌐 전체 언어 통합 — 도메인별 평균 fix율</h2>
              <div className="space-y-3">
                {globalDomains.map(({ domain, avg }) => (
                  <div key={domain} className="flex items-center gap-3">
                    <DomainBadge domain={domain} />
                    <div className="flex-1">
                      <div
                        className="h-1.5 rounded-full bg-blue-500/60"
                        style={{ width: `${Math.min(avg * 4, 100)}%` }}
                      />
                    </div>
                    <span className={`w-12 text-right text-xs font-semibold ${
                      avg > 20 ? 'text-red-400' : avg > 10 ? 'text-yellow-400' : 'text-green-400'
                    }`}>
                      {avg.toFixed(1)}%
                    </span>
                  </div>
                ))}
              </div>
            </section>

            {/* 언어별 카드 */}
            <section className="mb-6">
              <h2 className="mb-4 text-sm font-semibold text-gray-300">🔠 언어별 상세</h2>
              <div className="grid gap-4 sm:grid-cols-2">
                {languages.map(([lang, stats]) => (
                  <div key={lang} className="rounded-2xl border border-white/5 bg-white/[0.03] p-5">
                    <div className="mb-3 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-xl">{LANG_EMOJI[lang] ?? '📦'}</span>
                        <span className="font-semibold capitalize">{lang}</span>
                      </div>
                      <div className="text-right">
                        <div className={`text-lg font-bold ${
                          stats.avg_fix_rate > 20 ? 'text-red-400' :
                          stats.avg_fix_rate > 10 ? 'text-yellow-400' : 'text-green-400'
                        }`}>
                          {stats.avg_fix_rate}%
                        </div>
                        <div className="text-xs text-gray-600">평균 fix율</div>
                      </div>
                    </div>

                    {/* fix율 bar */}
                    <div className="mb-3">
                      <div className="h-1 w-full rounded-full bg-white/5">
                        <div
                          className="h-1 rounded-full bg-blue-500/60"
                          style={{ width: `${(stats.avg_fix_rate / maxFixRate) * 100}%` }}
                        />
                      </div>
                    </div>

                    <div className="mb-3 flex flex-wrap gap-1.5">
                      {stats.top_domains.slice(0, 4).map(d => (
                        <DomainBadge key={d} domain={d} />
                      ))}
                    </div>

                    <div className="flex items-center justify-between text-xs text-gray-600">
                      <span>{stats.repos_analyzed}개 레포 분석</span>
                      <span>클러스터 평균 {stats.avg_clusters}개</span>
                    </div>

                    {stats.sample_repos.length > 0 && (
                      <div className="mt-2 text-xs text-gray-700 truncate">
                        {stats.sample_repos.slice(0, 2).join(', ')}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </section>

            {/* 히트맵 */}
            <section className="rounded-2xl border border-white/5 bg-white/[0.03] p-6">
              <h2 className="mb-4 text-sm font-semibold text-gray-300">🗺️ 언어 × 도메인 히트맵</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr>
                      <th className="pb-3 text-left text-gray-500 font-normal w-24">도메인</th>
                      {languages.map(([lang]) => (
                        <th key={lang} className="pb-3 text-center text-gray-400 font-normal px-2 capitalize">
                          {LANG_EMOJI[lang]} {lang.slice(0, 2)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {globalDomains.map(({ domain }) => (
                      <tr key={domain} className="border-t border-white/5">
                        <td className="py-2 text-gray-500">{domain}</td>
                        {languages.map(([lang, stats]) => {
                          const rate = stats.domain_avg_fix_rates[domain] ?? 0
                          const maxRate = Math.max(...languages.map(([, s]) => s.domain_avg_fix_rates[domain] ?? 0), 1)
                          const intensity = rate / maxRate
                          return (
                            <td key={lang} className="py-2 text-center px-2">
                              <span
                                className="inline-block rounded px-1.5 py-0.5"
                                style={{
                                  background: rate > 0 ? `rgba(239,68,68,${0.05 + intensity * 0.4})` : 'transparent',
                                  color: rate > 0 ? `rgba(252,165,165,${0.4 + intensity * 0.6})` : 'rgba(75,85,99,1)',
                                }}
                              >
                                {rate > 0 ? `${rate}%` : '—'}
                              </span>
                            </td>
                          )
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          </>
        )}

        <div className="mt-8 text-center text-xs text-gray-700">
          <a
            href="https://github.com/rladmsgh34/ai-dev-loop-analyzer"
            target="_blank"
            rel="noreferrer"
            className="hover:text-gray-500 transition"
          >
            github.com/rladmsgh34/ai-dev-loop-analyzer
          </a>
        </div>
      </div>
    </main>
  )
}
