import { classifyDomain, isFixPR, type PR } from './analyzer'

const GH_API = 'https://api.github.com'

export async function fetchMergedPRs(owner: string, repo: string, limit = 200): Promise<PR[]> {
  const prs: PR[] = []
  let page = 1

  while (prs.length < limit) {
    const res = await fetch(
      `${GH_API}/repos/${owner}/${repo}/pulls?state=closed&per_page=100&page=${page}&sort=updated&direction=desc`,
      {
        headers: {
          Accept: 'application/vnd.github.v3+json',
          ...(process.env.GITHUB_TOKEN ? { Authorization: `Bearer ${process.env.GITHUB_TOKEN}` } : {}),
        },
        next: { revalidate: 3600 }, // 1시간 캐시
      }
    )

    if (!res.ok) {
      if (res.status === 404) throw new Error('레포지토리를 찾을 수 없습니다. public 레포인지 확인해주세요.')
      if (res.status === 403) throw new Error('API 요청 한도 초과. 잠시 후 다시 시도해주세요.')
      throw new Error(`GitHub API 오류: ${res.status}`)
    }

    const data: GHPull[] = await res.json()
    const merged = data.filter(pr => pr.merged_at !== null)

    for (const pr of merged) {
      const title = pr.title
      const isFix = isFixPR(title)
      prs.push({
        number: pr.number,
        title,
        mergedAt: pr.merged_at!,
        additions: pr.additions ?? 0,
        deletions: pr.deletions ?? 0,
        isFix,
        domain: classifyDomain(title),
        isAiGenerated: false, // web에서는 커밋 조회 비용이 크므로 생략
      })
    }

    if (data.length < 100 || prs.length >= limit) break
    page++
  }

  return prs.slice(0, limit).sort((a, b) => a.number - b.number)
}

export async function validateRepo(owner: string, repo: string): Promise<{ stars: number; description: string }> {
  const res = await fetch(`${GH_API}/repos/${owner}/${repo}`, {
    headers: {
      Accept: 'application/vnd.github.v3+json',
      ...(process.env.GITHUB_TOKEN ? { Authorization: `Bearer ${process.env.GITHUB_TOKEN}` } : {}),
    },
  })
  if (!res.ok) throw new Error('레포지토리를 찾을 수 없습니다.')
  const data: GHRepo = await res.json()
  return { stars: data.stargazers_count, description: data.description ?? '' }
}

interface GHPull {
  number: number
  title: string
  merged_at: string | null
  additions?: number
  deletions?: number
}

interface GHRepo {
  stargazers_count: number
  description: string | null
}
