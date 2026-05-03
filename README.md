# AI Dev Loop Analyzer

> 본인 레포의 PR 히스토리를 분석해, 코드 작성 시점에 Claude Code/Cursor에 회귀 위험을 띄워주는 도구.

같은 파일에서 같은 실수가 반복되는 이유는 *과거 fix diff가 편집 시점에 보이지 않기 때문*입니다. 이 도구는 본인 레포의 fix PR diff를 누적·임베딩해두고, MCP를 통해 편집 직전에 "이 파일 마지막 fix는 이런 패턴이었다"를 띄워줍니다.

---

## 무엇을 하나

```
본인 레포 PR 히스토리 (fix/hotfix만)
    ↓
fix PR의 변경 파일 + diff snippet 수집
    ↓
data/diff-patterns.json 누적 + ChromaDB 임베딩
    ↓
Claude Code(MCP) — 편집 시점에 유사 fix diff 자동 노출
```

핵심 출력은 *분석 리포트*가 아니라 **편집 시점에 뜨는 경고**입니다.

---

## MCP 서버 (메인 사용처)

Claude Code/Cursor에서 코드 작성 시 회귀 핫존을 자동 경고합니다.

```bash
pip install -r requirements.txt   # chromadb, sentence-transformers, rank-bm25

claude mcp add ai-dev-loop-analyzer -- python3 /path/to/src/mcp_server.py

# 프로파일(도메인 키워드 커스텀) 적용
claude mcp add ai-dev-loop-analyzer \
  -e AI_DEV_LOOP_PROFILE=/path/to/my-project.json \
  -- python3 /path/to/src/mcp_server.py
```

| 도구 | 언제 호출 |
|----|----|
| `check_risk_zones(file_paths)` | 파일을 편집하기 *전*. 회귀 이력 + 마지막 fix diff 표시 |
| `diff_risk_score(diff)` | 커밋 *직전*. `git diff --staged` 결과를 과거 fix 패턴과 비교해 0–10 점수 |
| `suggest_review_checklist(pr_title, file_paths)` | PR 열 때. 변경 파일·도메인 기반 리뷰 체크리스트 |
| `analyze_pr_history(repo)` | 새 레포 등록·캐시 갱신 |
| `list_repos()` | 등록된 레포 확인 |

`check_risk_zones` 출력 예시:

```
🔴 Dockerfile
   회귀 이력: 4회 | 도메인: ci/cd

   📌 마지막 fix (fix: Dockerfile deps 스테이지 수정):
   ```diff
   -COPY package.json pnpm-lock.yaml ./
   +COPY package.json pnpm-lock.yaml .npmrc ./
    RUN pnpm install --frozen-lockfile
   ```
```

---

## CLI

다른 레포를 빠르게 훑어보거나 캐시를 수동 갱신할 때.

```bash
# 현재 디렉토리의 git 레포 분석 (smart-fetch 기본)
python3 src/analyze.py

# 모든 fix PR 정밀 fetch (느림, 더 정확)
python3 src/analyze.py --fetch-files

# JSON 출력
python3 src/analyze.py --format json > report.json
```

---

## 자동 갱신 워크플로우

`config/repos.json`에 본인 레포를 등록하면 매일/매주 cron으로 분석이 돌아 `data/repos/{slug}/analysis-cache.json`과 `data/diff-patterns.json`이 갱신됩니다 — MCP는 이 파일을 직접 읽습니다.

```json
[
  {
    "repo": "owner/your-repo",
    "profile": "profiles/examples/your-profile.json",
    "schedule": "daily",
    "fetch_limit": 200,
    "enabled": true
  }
]
```

| 워크플로우 | 스케줄 | 역할 |
|-----------|--------|------|
| `evolve-rules.yml` | 매일 KST 10:00 / 매주 일 KST 11:00 | enabled 레포 분석 → analysis-cache + diff-patterns 갱신 |
| `lint.yml` | push / PR | `src/**/*.py` 문법 + `.github/workflows/*.yml` YAML 검증 |

`scripts/rag-sync.sh`를 cron에 걸면 갱신된 diff-patterns가 ChromaDB에 자동 인제스트됩니다.

```cron
0 12 * * 0 /path/to/ai-dev-loop-analyzer/scripts/rag-sync.sh
```

---

## 프로파일 시스템

도메인 키워드와 fix PR 패턴을 JSON으로 교체합니다. 엔진 코드는 스택 무관 — 프로젝트별 키워드(예: `kakao`, `portone`, `gcs`)는 프로파일에만 둡니다.

```
profiles/
├── default.json                    # 범용 프리셋 (빌트인)
└── examples/
    ├── nextjs-prisma.json          # Next.js + Prisma
    └── korean-nextjs-shop.json     # 한국 커머스 스택
```

```json
{
  "name": "my-project",
  "fix_pr_regex": "^(fix|hotfix|revert)",
  "domain_patterns": [
    ["payment", "payment|stripe|checkout|order"],
    ["external-api", "stripe|sendgrid|s3"]
  ]
}
```

### 지원 도메인 (default)

| 도메인 | 감지 키워드 |
|--------|-------------|
| ci/cd | deploy, docker, dockerfile, workflow, compose |
| auth | auth, login, session, jwt, credential |
| payment | payment, checkout, order, cart |
| database | migration, schema, migrate |
| security | csp, xss, csrf, rate-limit |
| external-api | stripe, twilio, sendgrid, s3, cloudfront, firebase |
| test/e2e | e2e, playwright, vitest, jest, coverage, flaky |
| config | .config., env.ts, tsconfig, biome, tailwind |

### fix PR 감지 패턴

```
fix / hotfix / revert / regression / bug
수정 / 버그 (한국어 지원)
```

PR 제목 + 변경 파일 경로를 함께 봅니다. smart-fetch로 파일 경로가 수집되면 정확도가 올라갑니다.

---

## AI 규칙 생성 (선택)

CLI 출력 끝에 *제안* 형태로 CLAUDE.md 추가 후보가 나옵니다. 자동으로 PR을 만들거나 CLAUDE.md를 수정하지는 않습니다 — 본인이 읽고 의미 있는 것만 옮기면 됩니다.

| 방식 | 필요한 것 | 모델 |
|------|-----------|------|
| GitHub Models | `GITHUB_TOKEN` (gh CLI 자동) | gpt-4o-mini |
| Anthropic API | `ANTHROPIC_API_KEY` | claude-haiku |
| 템플릿 폴백 | 없음 | — |

```bash
ANTHROPIC_API_KEY=sk-ant-... python3 src/analyze.py
python3 src/analyze.py --no-ai   # 템플릿만
```

---

## Requirements

- Python 3.10+
- `gh` CLI (인증된 상태)
- MCP/RAG 사용 시: `pip install -r requirements.txt`

---

## License

MIT
