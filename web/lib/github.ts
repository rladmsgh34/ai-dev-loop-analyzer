import { classifyDomain, isFixPR, type PR } from './analyzer'

const GH_API = 'https://api.github.com'
const GH_GRAPHQL = 'https://api.github.com/graphql'

// GraphQL 응답 타입
interface GHGraphQLPRNode {
  number: number
  title: string
  mergedAt: string
  additions: number
  deletions: number
  commits: {
    nodes: {
      commit: {
        message: string
      }
    }[]
  }
}

interface GHGraphQLResponse {
  data: {
    repository: {
      pullRequests: {
        nodes: GHGraphQLPRNode[]
        pageInfo: {
          hasNextPage: boolean
          endCursor: string | null
        }
      }
    }
  }
  errors?: { message: string }[]
}

const MERGED_PRS_QUERY = `
  query($owner: String!, $repo: String!, $cursor: String) {
    repository(owner: $owner, name: $repo) {
      pullRequests(first: 100, states: MERGED, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
        nodes {
          number
          title
          mergedAt
          additions
          deletions
          commits(first: 10) {
            nodes {
              commit {
                message
              }
            }
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
`

export async function fetchMergedPRs(owner: string, repo: string, limit = 200): Promise<PR[]> {
  const prs: PR[] = []
  let cursor: string | null = null

  const authHeaders = process.env.GITHUB_TOKEN
    ? { Authorization: `Bearer ${process.env.GITHUB_TOKEN}` }
    : {}

  while (prs.length < limit) {
    const res = await fetch(GH_GRAPHQL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        ...authHeaders,
      },
      body: JSON.stringify({
        query: MERGED_PRS_QUERY,
        variables: { owner, repo, cursor },
      }),
      next: { revalidate: 3600 }, // 1시간 캐시
    })

    if (!res.ok) {
      if (res.status === 404) throw new Error('레포지토리를 찾을 수 없습니다. public 레포인지 확인해주세요.')
      if (res.status === 403) throw new Error('API 요청 한도 초과. 잠시 후 다시 시도해주세요.')
      throw new Error(`GitHub API 오류: ${res.status}`)
    }

    const json: GHGraphQLResponse = await res.json()

    if (json.errors && json.errors.length > 0) {
      const msg = json.errors[0].message
      if (msg.includes('Could not resolve to a Repository')) {
        throw new Error('레포지토리를 찾을 수 없습니다. public 레포인지 확인해주세요.')
      }
      throw new Error(`GitHub GraphQL 오류: ${msg}`)
    }

    const { nodes, pageInfo } = json.data.repository.pullRequests

    for (const pr of nodes) {
      // 커밋 메시지에 "Co-Authored-By: Claude" 포함 여부로 AI 생성 PR 감지
      const isAiGenerated = pr.commits.nodes.some(({ commit }) =>
        commit.message.includes('Co-Authored-By: Claude')
      )

      const title = pr.title
      prs.push({
        number: pr.number,
        title,
        mergedAt: pr.mergedAt,
        additions: pr.additions,
        deletions: pr.deletions,
        isFix: isFixPR(title),
        domain: classifyDomain(title),
        isAiGenerated,
      })

      if (prs.length >= limit) break
    }

    if (!pageInfo.hasNextPage || prs.length >= limit) break
    cursor = pageInfo.endCursor
  }

  return prs.slice(0, limit).sort((a, b) => a.number - b.number)
}

export async function validateRepo(
  owner: string,
  repo: string
): Promise<{ stars: number; description: string; language: string }> {
  const res = await fetch(`${GH_API}/repos/${owner}/${repo}`, {
    headers: {
      Accept: 'application/vnd.github.v3+json',
      ...(process.env.GITHUB_TOKEN ? { Authorization: `Bearer ${process.env.GITHUB_TOKEN}` } : {}),
    },
  })
  if (!res.ok) throw new Error('레포지토리를 찾을 수 없습니다.')
  const data: GHRepo = await res.json()
  return {
    stars: data.stargazers_count,
    description: data.description ?? '',
    language: (data.language ?? '').toLowerCase(),
  }
}

const LANG_PATTERNS_URL =
  'https://raw.githubusercontent.com/rladmsgh34/ai-dev-loop-analyzer/main/data/language-patterns.json'

export async function fetchLanguagePatterns(): Promise<LanguagePatterns | null> {
  try {
    const res = await fetch(LANG_PATTERNS_URL, { next: { revalidate: 3600 } })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}

export interface LangStats {
  repos_analyzed: number
  avg_fix_rate: number
  avg_clusters: number
  domain_avg_fix_rates: Record<string, number>
  top_domains: string[]
  sample_repos: string[]
}

export interface LanguagePatterns {
  updated_at: string
  total_repos_analyzed: number
  languages: Record<string, LangStats>
  repo_results: { owner: string; repo: string; fix_rate: number; language: string }[]
}

interface GHRepo {
  stargazers_count: number
  description: string | null
  language: string | null
}
