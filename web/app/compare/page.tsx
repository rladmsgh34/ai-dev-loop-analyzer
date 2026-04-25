'use client'

import { useState, useTransition } from 'react'
import type { AnalysisResult } from '@/lib/analyzer'

interface RepoResult {
  owner: string
  repo: string
  result: AnalysisResult
  stars: number
}

const PRESETS = [
  ['vercel/next.js', 'facebook/react', 'sveltejs/svelte'],
  ['prisma/prisma', 'drizzle-team/drizzle-orm'],
  ['shadcn-ui/ui', 'radix-ui/primitives'],
]

function fixRateColor(rate: number) {
  if (rate > 20) return 'text-red-400'
  if (rate > 10) return 'text-yellow-400'
  return 'text-green-400'
}

export default function ComparePage() {
  const [input, setInput] = useState('')
  const [repos, setRepos] = useState<RepoResult[]>([])
  const [error, setError] = useState('')
  const [isPending, startTransition] = useTransition()

  function parseRepos(value: string): { owner: string; repo: string }[] {
    return value
      .split(/[\s,\n]+/)
      .map(s => s.trim().replace(/^https?:\/\/github\.com\//, '').replace(/\/$/, ''))
      .filter(Boolean)
      .map(s => {
        const m = s.match(/^([^/\s]+)\/([^/\s]+)$/)
        return m ? { owner: m[1], repo: m[2] } : null
      })
      .filter(Boolean) as { owner: string; repo: string }[]
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    const targets = parseRepos(input)
    if (targets.length < 2) {
      setError('레포를 2개 이상 입력해주세요 (줄바꿈 또는 쉼표로 구분)')
      return
    }
    if (targets.length > 6) {
      setError('최대 6개까지 비교 가능합니다')
      return
    }
    startTransition(async () => {
      const results = await Promise.allSettled(
        targets.map(async ({ owner, repo }) => {
          const res = await fetch(`/api/analyze?owner=${owner}&repo=${repo}`)
          if (!res.ok) throw new Error(`${owner}/${repo} 분석 실패`)
          const data = await res.json()
          const metaRes = await fetch(`https://api.github.com/repos/${owner}/${repo}`)
          const meta = metaRes.ok ? await metaRes.json() : {}
          return { owner, repo, result: data as AnalysisResult, stars: meta.stargazers_count ?? 0 }
        })
      )
      const ok = results.filter(r => r.status === 'fulfilled').map(r => (r as PromiseFulfilledResult<RepoResult>).value)
      const fail = results.filter(r => r.status === 'rejected').map((r, i) => targets[i] ? `${targets[i].owner}/${targets[i].repo}` : '')
      setRepos(ok)
      if (fail.length > 0) setError(`분석 실패: ${fail.filter(Boolean).join(', ')}`)
    })
  }

  function applyPreset(preset: string[]) {
    setInput(preset.join('\n'))
  }

  const sorted = [...repos].sort((a, b) => a.result.summary.fixRate - b.result.summary.fixRate)

  return (
    <main className="min-h-screen bg-gray-950 text-white">
      <div className="mx-auto max-w-4xl px-4 py-12">
        <a href="/" className="mb-6 inline-block text-xs text-gray-500 hover:text-gray-300">
          ← AI Dev Loop Analyzer
        </a>
        <h1 className="mb-2 text-2xl font-bold">레포 비교</h1>
        <p className="mb-8 text-sm text-gray-500">여러 레포의 fix율을 나란히 비교합니다</p>

        <form onSubmit={handleSubmit} className="mb-6 space-y-3">
          <textarea
            value={input}
            onChange={e => { setInput(e.target.value); setError('') }}
            placeholder={'vercel/next.js\nfacebook/react\nsveltejs/svelte'}
            rows={4}
            className="w-full rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm placeholder-gray-600 outline-none transition focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/30 font-mono resize-none"
          />
          {error && <p className="text-sm text-red-400">{error}</p>}
          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={isPending || !input.trim()}
              className="rounded-xl bg-blue-600 px-6 py-2.5 text-sm font-semibold transition hover:bg-blue-500 disabled:opacity-40"
            >
              {isPending ? '분석 중...' : '비교'}
            </button>
            <span className="text-xs text-gray-600">예시:</span>
            {PRESETS.map((p, i) => (
              <button
                key={i}
                type="button"
                onClick={() => applyPreset(p)}
                className="text-xs text-gray-500 underline underline-offset-2 transition hover:text-gray-300"
              >
                {p.length}개
              </button>
            ))}
          </div>
        </form>

        {sorted.length > 0 && (
          <>
            {/* 순위 테이블 */}
            <section className="mb-6 rounded-2xl border border-white/5 bg-white/[0.03] p-6">
              <h2 className="mb-4 text-sm font-semibold text-gray-300">📊 fix율 순위 (낮을수록 안정)</h2>
              <div className="space-y-3">
                {sorted.map((r, i) => (
                  <div key={`${r.owner}/${r.repo}`} className="flex items-center gap-4">
                    <span className="w-5 text-center text-xs text-gray-600">{i + 1}</span>
                    <a
                      href={`/r/${r.owner}/${r.repo}`}
                      className="w-44 truncate text-sm hover:text-blue-400 transition"
                    >
                      {r.owner}/{r.repo}
                    </a>
                    <div className="flex-1">
                      <div
                        className="h-1.5 rounded-full bg-blue-500/60"
                        style={{ width: `${Math.min(r.result.summary.fixRate * 3, 100)}%` }}
                      />
                    </div>
                    <span className={`w-12 text-right text-sm font-bold ${fixRateColor(r.result.summary.fixRate)}`}>
                      {r.result.summary.fixRate}%
                    </span>
                    <span className="w-16 text-right text-xs text-gray-600">
                      {r.result.summary.totalPRs.toLocaleString()} PR
                    </span>
                  </div>
                ))}
              </div>
            </section>

            {/* 도메인별 히트맵 */}
            <section className="rounded-2xl border border-white/5 bg-white/[0.03] p-6">
              <h2 className="mb-4 text-sm font-semibold text-gray-300">🏴 도메인별 fix 횟수 비교</h2>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr>
                      <th className="pb-3 text-left text-gray-500 font-normal w-28">도메인</th>
                      {sorted.map(r => (
                        <th key={`${r.owner}/${r.repo}`} className="pb-3 text-center text-gray-400 font-normal px-2">
                          <a href={`/r/${r.owner}/${r.repo}`} className="hover:text-blue-400 transition truncate block max-w-24">
                            {r.repo}
                          </a>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {['ci/cd', 'auth', 'payment', 'database', 'security', 'external-api', 'test/e2e', 'config'].map(domain => (
                      <tr key={domain} className="border-t border-white/5">
                        <td className="py-2 text-gray-500">{domain}</td>
                        {sorted.map(r => {
                          const d = r.result.domainCounts.find(x => x.domain === domain)
                          const count = d?.fixCount ?? 0
                          const maxCount = Math.max(...sorted.map(s => s.result.domainCounts.find(x => x.domain === domain)?.fixCount ?? 0), 1)
                          const intensity = count / maxCount
                          return (
                            <td key={`${r.owner}/${r.repo}`} className="py-2 text-center px-2">
                              <span
                                className="inline-block rounded px-2 py-0.5"
                                style={{
                                  background: count > 0 ? `rgba(59,130,246,${0.1 + intensity * 0.5})` : 'transparent',
                                  color: count > 0 ? `rgba(147,197,253,${0.4 + intensity * 0.6})` : 'rgba(75,85,99,1)',
                                }}
                              >
                                {count > 0 ? count : '—'}
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

            {/* 공유 URL */}
            <div className="mt-4 text-center">
              <button
                onClick={() => navigator.clipboard.writeText(
                  `${window.location.origin}/compare?repos=${repos.map(r => `${r.owner}/${r.repo}`).join(',')}`
                )}
                className="text-xs text-gray-600 underline underline-offset-2 hover:text-gray-400 transition"
              >
                🔗 이 비교 결과 공유
              </button>
            </div>
          </>
        )}
      </div>
    </main>
  )
}
