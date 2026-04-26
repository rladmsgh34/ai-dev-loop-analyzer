// Profile loader — Python src/analyze.py와 동일한 분류 정책을 TS로 포팅.
// scope-first 매칭이 핵심 — 같은 매칭 결과를 보장해야 web과 cron 분석이 어긋나지 않음.
//
// Vercel serverless에선 web/ 외부 파일을 읽을 수 없어 fs 대신 GitHub raw로 fetch.
// Next의 1시간 revalidate cache가 cold-start만 살짝 느리고 그 외엔 무비용.

export interface Profile {
  name: string
  fixPrRegex: RegExp
  domainPatterns: [string, RegExp][]
  scopeToDomain: Record<string, string>
}

interface RawProfile {
  name?: string
  fix_pr_regex?: string
  domain_patterns?: [string, string][]
  scope_to_domain?: Record<string, string>
}

interface RepoConfig {
  repo: string
  profile: string | null
  schedule: 'daily' | 'weekly'
  post_issues: boolean
  fetch_limit: number
  enabled: boolean
}

const RAW_BASE =
  'https://raw.githubusercontent.com/rladmsgh34/ai-dev-loop-analyzer/main'
const REVALIDATE_SECONDS = 3600

let _configCache: RepoConfig[] | null = null
const _profileCache = new Map<string, Profile>()

async function fetchJson<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url, { next: { revalidate: REVALIDATE_SECONDS } })
    if (!res.ok) return null
    return (await res.json()) as T
  } catch {
    return null
  }
}

async function loadRepoConfig(): Promise<RepoConfig[]> {
  if (_configCache) return _configCache
  const data = await fetchJson<RepoConfig[]>(`${RAW_BASE}/config/repos.json`)
  _configCache = data ?? []
  return _configCache
}

/**
 * Python regex pattern → JS-compatible.
 * Python의 `(?i)` 같은 inline flag는 JS RegExp가 못 읽음 — strip하고 'i' arg로 대체.
 * 다른 Python-only 구문이 추가되면 여기서 함께 처리.
 */
function pythonRegexToJs(pattern: string): string {
  return pattern.replace(/^\(\?[ims]+\)/, '')
}

async function loadProfileByRelPath(relPath: string): Promise<Profile | null> {
  if (_profileCache.has(relPath)) {
    return _profileCache.get(relPath)!
  }
  const parsed = await fetchJson<RawProfile>(`${RAW_BASE}/${relPath}`)
  if (!parsed) return null
  const profile: Profile = {
    name: parsed.name ?? relPath,
    fixPrRegex: parsed.fix_pr_regex
      ? new RegExp(pythonRegexToJs(parsed.fix_pr_regex), 'i')
      : /^(fix|hotfix|bugfix|patch)\b/i,
    domainPatterns: (parsed.domain_patterns ?? []).map(
      ([name, pat]) => [name, new RegExp(pythonRegexToJs(pat), 'i')] as [string, RegExp]
    ),
    scopeToDomain: parsed.scope_to_domain ?? {},
  }
  _profileCache.set(relPath, profile)
  return profile
}

/** 특정 repo의 프로파일을 결정. config에 등록 안 됐거나 profile=null이면 default. */
export async function getProfileForRepo(repo: string): Promise<Profile> {
  const config = await loadRepoConfig()
  const entry = config.find(c => c.repo === repo)
  if (entry?.profile) {
    const loaded = await loadProfileByRelPath(entry.profile)
    if (loaded) return loaded
  }
  const fallback = await loadProfileByRelPath('profiles/default.json')
  if (fallback) return fallback
  // 최후 폴백 — raw fetch까지 실패하면 빈 프로파일 (모두 general로 떨어짐)
  return {
    name: 'empty',
    fixPrRegex: /^(fix|hotfix|bugfix|patch)\b/i,
    domainPatterns: [],
    scopeToDomain: {},
  }
}

/** repo가 tracked 목록(config/repos.json)에 있는지. cache lookup의 게이트. */
export async function isTrackedRepo(repo: string): Promise<boolean> {
  const config = await loadRepoConfig()
  return config.some(c => c.repo === repo && c.enabled)
}
