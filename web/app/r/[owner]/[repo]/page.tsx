import { fetchMergedPRs, validateRepo, fetchLanguagePatterns } from '@/lib/github'
import { analyze } from '@/lib/analyzer'
import ResultClient from './ResultClient'

interface Props {
  params: Promise<{ owner: string; repo: string }>
}

export async function generateMetadata({ params }: Props) {
  const { owner, repo } = await params
  return { title: `${owner}/${repo} — AI Dev Loop Analyzer` }
}

export default async function ResultPage({ params }: Props) {
  const { owner, repo } = await params

  try {
    const [prs, repoMeta, langPatterns] = await Promise.all([
      fetchMergedPRs(owner, repo, 200),
      validateRepo(owner, repo),
      fetchLanguagePatterns(),
    ])

    if (prs.length === 0) {
      return <ErrorPage message="머지된 PR이 없습니다." owner={owner} repo={repo} />
    }

    const result = analyze(prs)
    const langStats = langPatterns?.languages[repoMeta.language] ?? null
    const allFixRates = langPatterns?.repo_results
      .filter(r => r.language === repoMeta.language)
      .map(r => r.fix_rate) ?? []

    return (
      <ResultClient
        result={result}
        owner={owner}
        repo={repo}
        meta={repoMeta}
        benchmark={{ langStats, allFixRates, language: repoMeta.language }}
      />
    )
  } catch (e) {
    const msg = e instanceof Error ? e.message : '분석 중 오류가 발생했습니다.'
    return <ErrorPage message={msg} owner={owner} repo={repo} />
  }
}

function ErrorPage({ message, owner, repo }: { message: string; owner: string; repo: string }) {
  return (
    <main className="min-h-screen bg-gray-950 text-white flex items-center justify-center">
      <div className="text-center">
        <div className="text-4xl mb-4">⚠️</div>
        <p className="text-gray-400 mb-2">{message}</p>
        <p className="text-sm text-gray-600 mb-6">{owner}/{repo}</p>
        <a href="/" className="text-blue-400 text-sm hover:underline">← 돌아가기</a>
      </div>
    </main>
  )
}
