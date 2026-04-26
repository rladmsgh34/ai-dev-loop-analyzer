// Profile loader — Python src/analyze.py와 동일한 분류 정책을 TS로 포팅.
// scope-first 매칭이 핵심 — 같은 매칭 결과를 보장해야 web과 cron 분석이 어긋나지 않음.

import { promises as fs } from 'fs'
import path from 'path'

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

// monorepo root — web/은 ai-dev-loop-analyzer/web, profiles/config는 그 위에.
const MONOREPO_ROOT = path.resolve(process.cwd(), '..')
const CONFIG_PATH = path.join(MONOREPO_ROOT, 'config', 'repos.json')
const DEFAULT_PROFILE_PATH = path.join(MONOREPO_ROOT, 'profiles', 'default.json')

let _configCache: RepoConfig[] | null = null
const _profileCache = new Map<string, Profile>()

async function loadRepoConfig(): Promise<RepoConfig[]> {
  if (_configCache) return _configCache
  try {
    const raw = await fs.readFile(CONFIG_PATH, 'utf-8')
    _configCache = JSON.parse(raw) as RepoConfig[]
    return _configCache
  } catch {
    _configCache = []
    return _configCache
  }
}

async function loadProfileFromPath(profilePath: string): Promise<Profile | null> {
  if (_profileCache.has(profilePath)) {
    return _profileCache.get(profilePath)!
  }
  try {
    const raw = await fs.readFile(profilePath, 'utf-8')
    const parsed = JSON.parse(raw) as RawProfile
    const profile: Profile = {
      name: parsed.name ?? path.basename(profilePath, '.json'),
      fixPrRegex: parsed.fix_pr_regex
        ? new RegExp(parsed.fix_pr_regex, 'i')
        : /^(fix|hotfix|bugfix|patch)\b/i,
      domainPatterns: (parsed.domain_patterns ?? []).map(
        ([name, pat]) => [name, new RegExp(pat, 'i')] as [string, RegExp]
      ),
      scopeToDomain: parsed.scope_to_domain ?? {},
    }
    _profileCache.set(profilePath, profile)
    return profile
  } catch {
    return null
  }
}

/** 특정 repo의 프로파일을 결정. config에 등록 안 됐거나 profile=null이면 default. */
export async function getProfileForRepo(repo: string): Promise<Profile> {
  const config = await loadRepoConfig()
  const entry = config.find(c => c.repo === repo)
  if (entry?.profile) {
    const fullPath = path.join(MONOREPO_ROOT, entry.profile)
    const loaded = await loadProfileFromPath(fullPath)
    if (loaded) return loaded
  }
  const fallback = await loadProfileFromPath(DEFAULT_PROFILE_PATH)
  if (fallback) return fallback
  // 최후 폴백 — profile 파일 자체가 없으면 빈 프로파일 (모두 general로 떨어짐)
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
