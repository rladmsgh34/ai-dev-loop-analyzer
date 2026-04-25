import { Suspense } from 'react'
import LanguagesClient from './LanguagesClient'

export const revalidate = 3600

async function fetchPatterns() {
  try {
    const res = await fetch(
      'https://raw.githubusercontent.com/rladmsgh34/ai-dev-loop-analyzer/main/data/language-patterns.json',
      { next: { revalidate: 3600 } }
    )
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

export default async function LanguagesPage() {
  const data = await fetchPatterns()
  return (
    <Suspense>
      <LanguagesClient data={data} />
    </Suspense>
  )
}
