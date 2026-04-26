# 1단계 샘플링 — 도메인 분류 라벨링

도메인 분류기가 `general`로 떨어뜨린 fix PR 샘플. 사람이 직접 보고 진짜 도메인을 라벨링해 ground truth를 만든다.

## 데이터셋 (2026-04-26 기준)

| 파일 | 레포 | 프로파일 | scan | fix PR | general | 수집율 |
|---|---|---|---|---|---|---|
| `vuejs-core-2026-04-26.csv` | vuejs/core | 없음 (default) | 1500 | 684 (45.6%) | **100건** | 14.6% |
| `vercel-nextjs-2026-04-26.csv` | vercel/next.js | 없음 (default) | 1500 | 63 (4.2%) | **8건** | 12.7% |
| `gwangcheon-shop-control-2026-04-26.csv` | rladmsgh34/gwangcheon-shop | korean-nextjs-shop | 178 | 31 (17.4%) | **1건** | 3.2% |

**총 109건** — 사람이 한 시간 안에 라벨링 가능한 분량.

## 라벨링 방법

각 행의 빈 컬럼 3개를 채운다:

| 컬럼 | 입력 예시 |
|---|---|
| `true_domain` | `reactivity`, `compiler`, `routing`, `ssr`, `hmr`, `bundler`, `image`, `runtime`, `i18n`, `cache`, ... 또는 기존 도메인(`auth`, `database` 등) |
| `suggested_pattern` | regex 후보. 예: `reactiv\|signal\|effect\|computed`, `compile\|sfc\|template\|directive` |
| `notes` | 분류가 어려웠던 이유, 모호한 경우 컨텍스트 |

### 새 도메인 vs 기존 도메인

**새 도메인 추가 신호**: 같은 키워드/파일 패턴이 5건 이상 반복되고, 기존 12개 카테고리(ci/cd, auth, payment, database, security, external-api, test/e2e, maintenance, docs, config, api, ui)에 자연스럽게 포함되지 않을 때.

**기존 도메인 확장 신호**: 기존 도메인의 한 변형이지만 키워드만 추가하면 잡힐 때 (예: `reactivity` 같은 SPA 코어는 `runtime`이라는 신규 도메인이 나을 수도 있고, `ui`의 확장으로 볼 수도 있음 — 라벨링하면서 결정).

## 다음 단계 (3단계 프로파일 빌드 입력)

라벨링 완료 후 다음 형태로 집계:

```
도메인별 빈도:
  reactivity      23건  → vue/core 신규 도메인 후보
  compiler        18건  → vue/core 신규 도메인 후보
  ssr             12건  → next.js 신규 도메인 후보
  routing          9건  → 둘 다 해당
  bundler          7건  → 기존 config 확장 가능
  ...
```

이 집계가 `profiles/examples/vuejs-core.json`, `profiles/examples/vercel-nextjs.json` 신규 프로파일의 입력이 된다.

## 별도 발견 — `fix_pr_regex` 개선 필요

`vercel/next.js`는 `[ci]:`, `[turbopack] Fix`, `Patch X`, `Backport` 같은 비표준 prefix를 사용해 현재 정규식 `^(fix|hotfix|bugfix)(\([^)]*\))?:`이 fix PR의 상당수를 놓친다 (1500 PR 중 63개만 매칭).

**해결 후보** (이 PR 범위 밖, 별도 이슈):
- 정규식 확장: `^(\[[\w/-]+\][:\s]*)?(fix|patch|hotfix|bugfix|bug)\b`
- 또는 GitHub 라벨/마일스톤 신호 보조 활용

## 도구 재실행

```bash
python3 src/sample_for_labeling.py \
  --repo owner/repo --target 100 --scan 1500 \
  --output data/sampling/owner-repo-YYYY-MM-DD.csv \
  [--profile profiles/examples/X.json]
```
