'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'

export default function Home() {
  const router = useRouter()
  const [input, setInput] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  function parseRepo(value: string): { owner: string; repo: string } | null {
    const cleaned = value.trim().replace(/\/$/, '')
    const match = cleaned.match(/(?:github\.com\/)?([^/\s]+)\/([^/\s]+)/)
    if (!match) return null
    return { owner: match[1], repo: match[2] }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    const parsed = parseRepo(input)
    if (!parsed) {
      setError('올바른 형식을 입력해주세요 (예: facebook/react)')
      return
    }
    setLoading(true)
    router.push(`/r/${parsed.owner}/${parsed.repo}`)
  }

  const examples = ['vercel/next.js', 'shadcn-ui/ui', 'prisma/prisma']

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

        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="flex gap-2">
            <div className="relative flex-1">
              <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 select-none text-gray-500 text-sm">
                github.com/
              </span>
              <input
                value={input}
                onChange={e => { setInput(e.target.value); setError('') }}
                placeholder="owner/repo"
                className="w-full rounded-xl border border-white/10 bg-white/5 py-3.5 pl-[7.5rem] pr-4 text-sm placeholder-gray-600 outline-none transition focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/30"
                autoFocus
              />
            </div>
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="rounded-xl bg-blue-600 px-6 py-3.5 text-sm font-semibold transition hover:bg-blue-500 disabled:opacity-40"
            >
              {loading ? '...' : '분석'}
            </button>
          </div>
          {error && <p className="text-sm text-red-400">{error}</p>}
        </form>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <span className="text-xs text-gray-600">예시:</span>
          {examples.map(ex => (
            <button
              key={ex}
              type="button"
              onClick={() => { setInput(ex); setError('') }}
              className="text-xs text-gray-500 transition hover:text-gray-300 underline underline-offset-2"
            >
              {ex}
            </button>
          ))}
          <span className="text-gray-700">|</span>
          <a href="/compare" className="text-xs text-gray-500 transition hover:text-gray-300 underline underline-offset-2">
            여러 레포 비교 →
          </a>
        </div>

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
      </div>
    </main>
  )
}
