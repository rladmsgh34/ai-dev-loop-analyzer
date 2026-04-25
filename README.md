# AI Dev Loop Analyzer

> PR 히스토리에서 회귀 패턴을 감지하고, AI 코딩 어시스턴트(Claude Code 등)의 규칙을 자동으로 제안합니다.

AI-assisted development에서 같은 실수가 반복되는 이유는 **과거 데이터가 피드백 루프에 연결되지 않기** 때문입니다.  
이 도구는 PR 히스토리를 분석해 위험한 도메인과 회귀 클러스터를 감지하고, `CLAUDE.md` 또는 `.github/copilot-instructions.md`에 추가할 규칙을 자동 생성합니다.

---

## 작동 원리

```
merged PR 히스토리
        ↓
fix PR 클러스터 감지 (연속으로 같은 도메인에서 버그 발생)
        ↓
고위험 도메인·파일 순위 산출
        ↓
CLAUDE.md / AI 규칙 추가 제안 생성
        ↓
PR 코멘트 or 주간 이슈로 자동 게시
```

---

## 실제 데이터 예시

165개 PR 분석 결과 (Next.js + Prisma + Docker 커머스 프로젝트):

```
총 PR: 165개  |  fix PR: 26개 (15.8%)

📍 회귀 클러스터
  [ci/cd      ]  #52 → #53 → #54 → #56 → #58 → #59 → #60 → #61
  [ci/cd      ]  #62 → #66 → #68 → #78
  [payment    ]  #140 → #142 → #150
  [external-api]  #308 → #310

💡 CLAUDE.md 추가 규칙 제안
  - CI/CD·Docker 변경 전 verify-build.sh 실행 필수 — 11회 회귀 감지
  - 결제 플로우 변경 시 Opus 모델로 설계 검토 후 구현 — 4회 회귀
  - 외부 API(Kakao·PortOne) 연동은 스테이징 배포 후 검증 — 3회 회귀
```

---

## 사용법

### CLI (로컬)

```bash
# gh CLI 인증 필요
pip install -r requirements.txt  # 없음, 표준 라이브러리만 사용

# 현재 레포 분석
python3 src/analyze.py

# 파일 목록까지 수집 (느리지만 더 정확)
python3 src/analyze.py --fetch-files

# JSON 출력
python3 src/analyze.py --format json > report.json

# 옵션
python3 src/analyze.py --help
```

### GitHub Action

```yaml
# .github/workflows/pr-quality.yml
name: PR Quality Check
on:
  pull_request:
    types: [closed]

jobs:
  analyze:
    if: github.event.pull_request.merged == true
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: your-username/ai-dev-loop-analyzer@main
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          limit: "200"
          post-comment: "true"
```

주간 리포트 예시는 `examples/weekly-report.yml` 참고.

---

## 지원 도메인

| 도메인 | 감지 키워드 |
|--------|-------------|
| ci/cd | deploy, docker, dockerfile, workflow, compose |
| auth | auth, login, session, jwt, credential |
| payment | payment, checkout, order, cart |
| database | prisma, migration, schema |
| security | csp, xss, csrf, rate-limit |
| external-api | kakao, portone, gcs, sentry |
| test/e2e | e2e, playwright, vitest, coverage |
| config | next.config, env.ts, tsconfig |

---

## AI 어시스턴트 통합

### Claude Code (`CLAUDE.md`)
생성된 규칙을 `CLAUDE.md`의 `## 🐛 Claude가 했던 실수` 섹션에 추가하면 다음 세션부터 즉시 적용됩니다.

### GitHub Copilot (`.github/copilot-instructions.md`)
동일한 규칙을 Copilot 지시 파일에도 사용할 수 있습니다.

### Cursor (`.cursorrules`)
Cursor 규칙 파일에도 동일하게 적용 가능합니다.

---

## AI 규칙 생성

별도 API 키 없이 **GitHub Token만으로** AI 규칙 생성이 가능합니다.

| 방식 | 필요한 것 | 모델 |
|------|-----------|------|
| GitHub Models (기본) | `GITHUB_TOKEN` — Actions에서 자동 제공 | gpt-4o-mini |
| Anthropic API (선택) | `ANTHROPIC_API_KEY` | claude-haiku |
| 템플릿 폴백 | 없음 | — |

```bash
# GitHub Models (gh CLI 토큰 자동 사용)
python3 src/analyze.py

# Anthropic API
ANTHROPIC_API_KEY=sk-ant-... python3 src/analyze.py

# AI 없이 템플릿만
python3 src/analyze.py --no-ai

# 모델 지정
python3 src/analyze.py --model gpt-4o
```

## Requirements

- Python 3.10+
- `gh` CLI (인증된 상태)
- 표준 라이브러리만 사용 (추가 패키지 불필요)

---

## License

MIT
