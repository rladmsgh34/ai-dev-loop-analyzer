'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'

function parseRepo(value: string): { owner: string; repo: string } | null {
  const cleaned = value.trim().replace(/\/$/, '')
  const match = cleaned.match(/(?:github\.com\/)?([^/\s]+)\/([^/\s]+)/)
  if (!match) return null
  return { owner: match[1], repo: match[2] }
}

export default function HomeForm() {
  const router = useRouter()
  const [input, setInput] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

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
    <>
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
    </>
  )
}
