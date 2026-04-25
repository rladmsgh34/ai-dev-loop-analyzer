'use client'

import type { AnalysisResult } from '@/lib/analyzer'
import { useState } from 'react'

const DOMAIN_COLORS: Record<string, string> = {
  'ci/cd':        'bg-orange-500/20 text-orange-300 border-orange-500/30',
  'auth':         'bg-blue-500/20 text-blue-300 border-blue-500/30',
  'payment':      'bg-green-500/20 text-green-300 border-green-500/30',
  'database':     'bg-purple-500/20 text-purple-300 border-purple-500/30',
  'security':     'bg-red-500/20 text-red-300 border-red-500/30',
  'external-api': 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
  'test/e2e':     'bg-cyan-500/20 text-cyan-300 border-cyan-500/30',
  'config':       'bg-gray-500/20 text-gray-300 border-gray-500/30',
}

function DomainBadge({ domain }: { domain: string }) {
  const cls = DOMAIN_COLORS[domain] ?? 'bg-gray-500/20 text-gray-300 border-gray-500/30'
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${cls}`}>
      {domain}
    </span>
  )
}

interface Props {
  result: AnalysisResult
  owner: string
  repo: string
  meta: { stars: number; description: string }
}

export default function ResultClient({ result, owner, repo, meta }: Props) {
  const [copied, setCopied] = useState(false)
  const { summary, clusters, domainCounts, aiVsHuman } = result
  const shareUrl = typeof window !== 'undefined' ? window.location.href : ''

  function copyShare() {
    navigator.clipboard.writeText(shareUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const maxFixCount = domainCounts[0]?.fixCount ?? 1

  return (
    <main className="min-h-screen bg-gray-950 text-white">
      <div className="mx-auto max-w-3xl px-4 py-12">
        {/* 헤더 */}
        <div className="mb-8 flex items-start justify-between gap-4">
          <div>
            <a href="/" className="mb-3 inline-block text-xs text-gray-500 hover:text-gray-300">
              ← AI Dev Loop Analyzer
            </a>
            <h1 className="text-2xl font-bold">
              <a
                href={`https://github.com/${owner}/${repo}`}
                target="_blank"
                rel="noreferrer"
                className="hover:text-blue-400 transition"
              >
                {owner}/{repo}
              </a>
            </h1>
            {meta.description && (
              <p className="mt-1 text-sm text-gray-500">{meta.description}</p>
            )}
            <p className="mt-1 text-xs text-gray-600">⭐ {meta.stars.toLocaleString()}</p>
          </div>
          <button
            onClick={copyShare}
            className="shrink-0 rounded-xl border border-white/10 bg-white/5 px-4 py-2 text-xs transition hover:bg-white/10"
          >
            {copied ? '✓ 복사됨' : '🔗 공유'}
          </button>
        </div>

        {/* 요약 카드 */}
        <div className="mb-6 grid grid-cols-3 gap-3">
          {[
            { label: '총 PR', value: summary.totalPRs.toLocaleString() },
            { label: 'fix PR', value: summary.fixPRs.toLocaleString() },
            {
              label: 'fix 비율',
              value: `${summary.fixRate}%`,
              highlight: summary.fixRate > 20 ? 'text-red-400' : summary.fixRate > 10 ? 'text-yellow-400' : 'text-green-400',
            },
          ].map(card => (
            <div key={card.label} className="rounded-2xl border border-white/5 bg-white/[0.03] p-5 text-center">
              <div className={`text-3xl font-bold ${card.highlight ?? ''}`}>{card.value}</div>
              <div className="mt-1 text-xs text-gray-500">{card.label}</div>
            </div>
          ))}
        </div>

        {/* 회귀 클러스터 */}
        {clusters.length > 0 && (
          <section className="mb-6 rounded-2xl border border-white/5 bg-white/[0.03] p-6">
            <h2 className="mb-4 text-sm font-semibold text-gray-300">📍 회귀 클러스터</h2>
            <div className="space-y-2">
              {clusters.map((c, i) => (
                <div key={i} className="flex items-center gap-3 text-sm">
                  <DomainBadge domain={c.domain} />
                  <span className="text-gray-400">
                    #{c.start} → #{c.end}
                  </span>
                  <span className="text-xs text-gray-600">{c.prs.length}개 연속 fix</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* 도메인별 fix */}
        <section className="mb-6 rounded-2xl border border-white/5 bg-white/[0.03] p-6">
          <h2 className="mb-4 text-sm font-semibold text-gray-300">🏴 도메인별 fix 횟수</h2>
          <div className="space-y-3">
            {domainCounts.map(d => (
              <div key={d.domain} className="flex items-center gap-3">
                <DomainBadge domain={d.domain} />
                <div className="flex-1">
                  <div
                    className="h-1.5 rounded-full bg-blue-500/60"
                    style={{ width: `${(d.fixCount / maxFixCount) * 100}%` }}
                  />
                </div>
                <span className="w-6 text-right text-xs text-gray-400">{d.fixCount}</span>
              </div>
            ))}
          </div>
        </section>

        {/* AI vs 사람 */}
        {(aiVsHuman.ai.total > 0 || aiVsHuman.human.total > 0) && (
          <section className="mb-6 rounded-2xl border border-white/5 bg-white/[0.03] p-6">
            <h2 className="mb-4 text-sm font-semibold text-gray-300">🤖 AI 생성 PR vs 사람 PR</h2>
            <div className="grid grid-cols-2 gap-4">
              {[
                { label: 'AI 생성', data: aiVsHuman.ai },
                { label: '사람 작성', data: aiVsHuman.human },
              ].map(({ label, data }) => (
                <div key={label} className="rounded-xl border border-white/5 p-4">
                  <div className="mb-1 text-xs text-gray-500">{label}</div>
                  <div className="text-2xl font-bold">{data.fixRate}%</div>
                  <div className="text-xs text-gray-600">fix율 ({data.total}개 PR)</div>
                </div>
              ))}
            </div>
            {aiVsHuman.ai.weakDomains.length > 0 && (
              <div className="mt-4">
                <p className="mb-2 text-xs text-gray-500">AI가 특히 취약한 도메인:</p>
                <div className="flex flex-wrap gap-2">
                  {aiVsHuman.ai.weakDomains.map(d => (
                    <span key={d.domain} className="flex items-center gap-1">
                      <DomainBadge domain={d.domain} />
                      <span className="text-xs text-gray-600">{d.count}회</span>
                    </span>
                  ))}
                </div>
              </div>
            )}
          </section>
        )}

        {/* 푸터 */}
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
