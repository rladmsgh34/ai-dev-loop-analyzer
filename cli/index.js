#!/usr/bin/env node
'use strict'

const https = require('https')
const { execSync } = require('child_process')

// ── ANSI 컬러 ────────────────────────────────────────────────────────────────
const c = {
  reset: '\x1b[0m', bold: '\x1b[1m', dim: '\x1b[2m',
  red: '\x1b[31m', green: '\x1b[32m', yellow: '\x1b[33m',
  blue: '\x1b[34m', cyan: '\x1b[36m', gray: '\x1b[90m',
  bgRed: '\x1b[41m', bgGreen: '\x1b[42m', bgYellow: '\x1b[43m',
}
const bold = s => `${c.bold}${s}${c.reset}`
const dim = s => `${c.dim}${s}${c.reset}`
const red = s => `${c.red}${s}${c.reset}`
const green = s => `${c.green}${s}${c.reset}`
const yellow = s => `${c.yellow}${s}${c.reset}`
const gray = s => `${c.gray}${s}${c.reset}`
const cyan = s => `${c.cyan}${s}${c.reset}`

// ── CLI 인수 파싱 ─────────────────────────────────────────────────────────────
function parseArgs(argv) {
  const args = { repo: null, limit: 200, json: false, noColor: false, help: false }
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i]
    if (a === '--help' || a === '-h') { args.help = true }
    else if (a === '--json') { args.json = true }
    else if (a === '--no-color') { args.noColor = true }
    else if (a === '--limit' && argv[i + 1]) { args.limit = parseInt(argv[++i]) || 200 }
    else if (!a.startsWith('-')) { args.repo = a }
  }
  return args
}

function printHelp() {
  console.log(`
${bold('AI Dev Loop Analyzer')}
${dim('PR 히스토리에서 회귀 패턴을 감지합니다')}

${bold('사용법')}
  npx ai-dev-loop-analyzer <owner/repo> [options]

${bold('옵션')}
  --limit <n>    분석할 PR 수 (기본값: 200)
  --json         JSON 형식으로 출력
  --no-color     색상 없이 출력
  --help         도움말

${bold('예시')}
  npx ai-dev-loop-analyzer vercel/next.js
  npx ai-dev-loop-analyzer facebook/react --limit 100
  npx ai-dev-loop-analyzer vercel/next.js --json > report.json

${bold('환경변수')}
  GITHUB_TOKEN   GitHub API 인증 토큰 (없으면 gh CLI 토큰 자동 사용)

${bold('데모 사이트')}
  https://ai-dev-loop-analyzer.rladmsgh34.org
`)
}

// ── GitHub 토큰 ──────────────────────────────────────────────────────────────
function getToken() {
  if (process.env.GITHUB_TOKEN) return process.env.GITHUB_TOKEN
  try {
    return execSync('gh auth token', { stdio: ['pipe', 'pipe', 'pipe'] }).toString().trim()
  } catch {
    return ''
  }
}

// ── GitHub API fetch ─────────────────────────────────────────────────────────
function ghFetch(path, token) {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: 'api.github.com',
      path,
      headers: {
        'User-Agent': 'ai-dev-loop-analyzer-cli',
        'Accept': 'application/vnd.github.v3+json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    }
    https.get(options, res => {
      let data = ''
      res.on('data', chunk => data += chunk)
      res.on('end', () => {
        if (res.statusCode === 404) return reject(new Error('레포지토리를 찾을 수 없습니다. public 레포인지 확인해주세요.'))
        if (res.statusCode === 403) return reject(new Error('API 요청 한도 초과. GITHUB_TOKEN 환경변수를 설정하거나 잠시 후 다시 시도해주세요.'))
        try { resolve(JSON.parse(data)) }
        catch { reject(new Error('API 응답 파싱 실패')) }
      })
    }).on('error', reject)
  })
}

// ── 도메인 분류 ───────────────────────────────────────────────────────────────
const DOMAIN_PATTERNS = [
  ['ci/cd',        /deploy|docker|dockerfile|ci\b|workflow|buildx|healthcheck|compose|musl|alpine/i],
  ['auth',         /auth|login|signup|session|jwt|credential|signin/i],
  ['payment',      /payment|portone|checkout|order|cart|purchase/i],
  ['database',     /prisma|migration|schema/i],
  ['security',     /csp|xss|csrf|rate.?limit|sanitize|allowlist/i],
  ['external-api', /kakao|postcode|google.?maps|gcs|sentry|daum/i],
  ['test/e2e',     /\.test\.|\.spec\.|e2e|playwright|vitest|coverage/i],
  ['config',       /next\.config|env\.ts|tsconfig|biome|tailwind/i],
]

function classifyDomain(title) {
  const t = title.toLowerCase()
  for (const [domain, pattern] of DOMAIN_PATTERNS) {
    if (pattern.test(t)) return domain
  }
  return 'general'
}

function isFixPR(title) {
  return /^(fix|hotfix|bugfix|revert|regression|bug)\b/i.test(title)
}

// ── PR 수집 ──────────────────────────────────────────────────────────────────
async function fetchPRs(owner, repo, limit, token) {
  const prs = []
  let page = 1
  process.stderr.write(`  PR 수집 중`)
  while (prs.length < limit) {
    const data = await ghFetch(
      `/repos/${owner}/${repo}/pulls?state=closed&per_page=100&page=${page}&sort=updated&direction=desc`,
      token
    )
    if (!Array.isArray(data) || data.length === 0) break
    const merged = data.filter(p => p.merged_at)
    for (const p of merged) {
      prs.push({
        number: p.number,
        title: p.title,
        mergedAt: p.merged_at,
        isFix: isFixPR(p.title),
        domain: classifyDomain(p.title),
      })
    }
    process.stderr.write('.')
    if (data.length < 100 || prs.length >= limit) break
    page++
    await new Promise(r => setTimeout(r, 300))
  }
  process.stderr.write(` ${prs.length}개\n`)
  return prs.slice(0, limit).sort((a, b) => a.number - b.number)
}

// ── 분석 ─────────────────────────────────────────────────────────────────────
function detectClusters(prs, windowSize = 8, threshold = 2) {
  const sorted = [...prs].sort((a, b) => a.number - b.number)
  const inCluster = new Set()
  const clusters = []
  for (let i = 0; i < sorted.length; i++) {
    if (!sorted[i].isFix || inCluster.has(i)) continue
    const group = [i]
    for (let j = i + 1; j < sorted.length && sorted[j].number - sorted[i].number < windowSize * 3; j++) {
      if (sorted[j].isFix) group.push(j)
      if (group.length >= 8) break
    }
    if (group.length >= threshold) {
      const groupPRs = group.map(idx => sorted[idx])
      const domainCounts = {}
      for (const pr of groupPRs) domainCounts[pr.domain] = (domainCounts[pr.domain] ?? 0) + 1
      const domain = Object.entries(domainCounts).sort((a, b) => b[1] - a[1])[0][0]
      clusters.push({ prs: groupPRs, domain, start: groupPRs[0].number, end: groupPRs.at(-1).number })
      group.forEach(idx => inCluster.add(idx))
    }
  }
  return clusters
}

function analyzeTrend(prs) {
  const byMonth = {}
  for (const pr of prs) {
    const month = pr.mergedAt.slice(0, 7)
    if (!byMonth[month]) byMonth[month] = { total: 0, fix: 0 }
    byMonth[month].total++
    if (pr.isFix) byMonth[month].fix++
  }
  return Object.entries(byMonth)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([month, { total, fix }]) => ({
      month, total, fixCount: fix,
      fixRate: total > 0 ? Math.round(fix / total * 1000) / 10 : 0,
    }))
    .slice(-12)
}

function analyze(prs) {
  const fixPRs = prs.filter(p => p.isFix)
  const fixRate = prs.length ? Math.round(fixPRs.length / prs.length * 1000) / 10 : 0
  const clusters = detectClusters(prs)
  const domainCounter = {}
  for (const pr of fixPRs) domainCounter[pr.domain] = (domainCounter[pr.domain] ?? 0) + 1
  const domainCounts = Object.entries(domainCounter)
    .map(([domain, fixCount]) => ({ domain, fixCount }))
    .sort((a, b) => b.fixCount - a.fixCount)
  return { summary: { totalPRs: prs.length, fixPRs: fixPRs.length, fixRate }, clusters, domainCounts, trend: analyzeTrend(prs) }
}

// ── 터미널 출력 ───────────────────────────────────────────────────────────────
function printReport(owner, repo, result) {
  const { summary, clusters, domainCounts, trend } = result
  const fixRateColor = summary.fixRate > 20 ? red : summary.fixRate > 10 ? yellow : green

  console.log()
  console.log(bold(`📊 ${owner}/${repo}`))
  console.log(gray('─'.repeat(50)))

  // 요약
  console.log()
  console.log(`  총 PR    ${bold(summary.totalPRs.toLocaleString())}개`)
  console.log(`  fix PR   ${bold(summary.fixPRs)}개`)
  console.log(`  fix율    ${bold(fixRateColor(`${summary.fixRate}%`))}`)

  // 회귀 클러스터
  if (clusters.length > 0) {
    console.log()
    console.log(bold('📍 회귀 클러스터'))
    for (const cl of clusters) {
      console.log(`  ${cyan(`[${cl.domain.padEnd(12)}]`)}  #${cl.start} → #${cl.end}  ${gray(`(${cl.prs.length}개 연속 fix)`)}`)
    }
  }

  // 도메인별
  if (domainCounts.length > 0) {
    console.log()
    console.log(bold('🏴 도메인별 fix 횟수'))
    const maxCount = domainCounts[0].fixCount
    for (const d of domainCounts) {
      const bar = '█'.repeat(Math.round(d.fixCount / maxCount * 20)).padEnd(20)
      console.log(`  ${d.domain.padEnd(14)} ${yellow(bar)} ${d.fixCount}`)
    }
  }

  // 트렌드
  if (trend.length >= 3) {
    console.log()
    console.log(bold('📈 월별 fix율 트렌드'))
    const maxRate = Math.max(...trend.map(t => t.fixRate), 1)
    for (const t of trend) {
      const barLen = Math.round(t.fixRate / maxRate * 20)
      const barColor = t.fixRate > 20 ? red : t.fixRate > 10 ? yellow : green
      const bar = barColor('█'.repeat(barLen || 1))
      console.log(`  ${gray(t.month)}  ${bar.padEnd(25)}  ${t.fixRate}%`)
    }
    // 트렌드 방향
    const half = Math.floor(trend.length / 2)
    const avg = pts => pts.reduce((s, p) => s + p.fixRate, 0) / pts.length
    const diff = avg(trend.slice(-half)) - avg(trend.slice(0, half))
    if (Math.abs(diff) >= 1) {
      console.log()
      if (diff < 0) console.log(`  ${green(`▼ 전반 대비 fix율 ${Math.abs(diff).toFixed(1)}%p 감소 — 개선 추세`)}`)
      else console.log(`  ${red(`▲ 전반 대비 fix율 ${diff.toFixed(1)}%p 증가 — 주의 필요`)}`)
    }
  }

  console.log()
  console.log(dim(`  🌐 https://ai-dev-loop-analyzer.rladmsgh34.org/r/${owner}/${repo}`))
  console.log()
}

// ── main ──────────────────────────────────────────────────────────────────────
async function main() {
  const args = parseArgs(process.argv)

  if (args.help || !args.repo) {
    printHelp()
    process.exit(args.help ? 0 : 1)
  }

  const repoStr = args.repo.replace(/^https?:\/\/github\.com\//, '').replace(/\/$/, '')
  const match = repoStr.match(/^([^/\s]+)\/([^/\s]+)$/)
  if (!match) {
    console.error(red('오류: owner/repo 또는 https://github.com/owner/repo 형식으로 입력하세요.'))
    process.exit(1)
  }
  const [, owner, repo] = match

  const token = getToken()
  if (!token) {
    console.error(yellow('⚠️  GITHUB_TOKEN이 없습니다. rate limit이 낮을 수 있습니다.'))
    console.error(yellow('   gh auth login 또는 GITHUB_TOKEN 환경변수를 설정하세요.'))
  }

  try {
    if (!args.json) process.stderr.write(`\n  ${bold(owner + '/' + repo)} 분석 중...\n`)
    const prs = await fetchPRs(owner, repo, args.limit, token)
    if (prs.length === 0) {
      console.error(red('오류: 머지된 PR을 찾을 수 없습니다.'))
      process.exit(1)
    }
    const result = analyze(prs)
    if (args.json) {
      console.log(JSON.stringify(result, null, 2))
    } else {
      printReport(owner, repo, result)
    }
  } catch (e) {
    console.error(red(`\n오류: ${e.message}`))
    process.exit(1)
  }
}

main()
