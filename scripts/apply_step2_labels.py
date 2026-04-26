#!/usr/bin/env python3
"""Step 2 — apply AI labels to step 1 sampling CSVs.

This is an *interim* AI labeling pass to unblock step 3 (profile build).
Ground truth quality is lower than human labeling; revisit per-row
decisions when the user has time to review.

Each entry is classified by examining (1) the PR title prefix
(e.g. ``fix(reactivity)``) and (2) the top file paths. When the two
disagree (e.g. ``fix(types)`` touching ``packages/reactivity/*``), we
prefer the package-derived domain so the resulting keyword lists match
file paths the classifier already sees.

Run: ``python3 scripts/apply_step2_labels.py``
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLING = ROOT / "data" / "sampling"

# (domain, suggested_pattern, notes)
# suggested_pattern is a short keyword/path fragment that would classify
# the row. Aggregated in step 3 into profile DOMAIN_PATTERNS regex.
Label = tuple[str, str, str]

VUEJS: dict[int, Label] = {
    14705: ("vapor",       "runtime-vapor", ""),
    14666: ("vapor",       "runtime-vapor", ""),
    14641: ("reactivity",  "packages/reactivity|shallowReactive", "fix(types) but core change in reactivity package"),
    14639: ("reactivity",  "packages/reactivity|customRef", ""),
    14493: ("reactivity",  "packages/reactivity|shallowReactive", ""),
    14492: ("types",       "dts-test|useAttrs", ""),
    14470: ("vapor",       "runtime-vapor|FunctionalVaporComponent", ""),
    14267: ("compiler",    "compiler-sfc|compileScript", ""),
    14184: ("hmr",         "hmr\\.ts|effectScope", ""),
    14133: ("compiler",    "compiler-core|codegen", ""),
    14123: ("vapor",       "runtime-vapor|fragment", ""),
    14118: ("types",       "dts-test|defineComponent", ""),
    14000: ("vapor",       "runtime-vapor|trusted types", ""),
    13997: ("runtime",     "runtime-core|apiAsyncComponent", ""),
    13982: ("compiler",    "compiler-core|transformVBind", ""),
    13915: ("runtime-dom", "runtime-dom|dom stub", ""),
    13825: ("vapor",       "runtime-vapor|trusted types", ""),
    13823: ("vapor",       "vapor component|host node", ""),
    13817: ("hmr",         "hmr\\.ts|VUE_HMR_RUNTIME", ""),
    13806: ("runtime-dom", "runtime-dom|vShow", ""),
    13777: ("hydration",   "hydration|vShow", ""),
    13761: ("reactivity",  "reactivity|arrayInstrumentations", ""),
    13759: ("reactivity",  "reactivity|collectionHandlers", ""),
    13758: ("types",       "dts-test|directives", ""),
    13722: ("vapor",       "runtime-vapor|renderList", ""),
    13701: ("devtools",    "profiling|devtools", ""),
    13654: ("reactivity",  "reactivity|system", ""),
    13652: ("hmr",         "hmr\\.ts", ""),
    13605: ("reactivity",  "reactivity|effect", ""),
    13590: ("compiler",    "compiler-sfc|parse", ""),
    13589: ("types",       "runtime-core|component\\.ts", ""),
    13587: ("scheduler",   "scheduler\\.ts", ""),
    13580: ("devtools",    "devtools\\.ts|createApp", ""),
    13525: ("compiler",    "compiler-sfc|SSR mode", ""),
    13502: ("vapor",       "runtime-vapor|vdomInterop", ""),
    13343: ("types",       "runtime-dom|vOnce|vSlot", ""),
    13223: ("runtime",     "runtime-core|renderer", ""),
    13210: ("runtime",     "runtime-core|setRef", ""),
    13197: ("compiler",    "compiler-sfc|useTemplateRef", ""),
    13119: ("types",       "dts-test|defineComponent generics", ""),
    13078: ("reactivity",  "reactivity|computed", ""),
    13043: ("compiler",    "compiler|domTagConfig", ""),
    13007: ("types",       "dts-test|componentProps", ""),
    13001: ("runtime-dom", "runtime-dom|patchProp", ""),
    12948: ("devtools",    "customFormatter|debugger", ""),
    12870: ("types",       "dts-test|ComponentInstance", ""),
    12820: ("vapor",       "vapor component|host node", ""),
    12605: ("types",       "dts-test|directives", ""),
    12556: ("compiler",    "compiler-core|v-pre", ""),
    12554: ("compiler",    "compiler-core|vBind", ""),
    12553: ("compiler",    "compiler-core|utils", ""),
    12343: ("types",       "dts-test|defineEmits", ""),
    12163: ("runtime",     "runtime-core|component", ""),
    12131: ("compiler",    "compiler-core|vIf", ""),
    12123: ("types",       "dts-test|\\$props", ""),
    12108: ("types",       "dts-test|setupHelpers", ""),
    12094: ("reactivity",  "reactivity|ref|reactive", ""),
    12077: ("types",       "runtime-core|PublicProps", ""),
    12073: ("types",       "runtime-core|TypeProps", ""),
    12062: ("compiler",    "compiler-sfc|definePropsDestructure", ""),
    12049: ("reactivity",  "reactivity|UnwrapRef", ""),
    12022: ("types",       "componentEmits|union", ""),
    12019: ("compiler",    "compiler-sfc|parse", ""),
    12007: ("reactivity",  "reactivity|getDepFromReactive", ""),
    11986: ("reactivity",  "reactivity|triggerRef|ObjectRefImpl", ""),
    11970: ("playground",  "sfc-playground", ""),
    11963: ("compiler",    "compiler-sfc|definePropsDestructure", ""),
    11944: ("reactivity",  "reactivity|computed|chained", ""),
    11935: ("hydration",   "hydrationStrategies|idle callback", ""),
    11840: ("types",       "componentEmits|TypeEmits", ""),
    11826: ("scheduler",   "scheduler\\.ts", ""),
    11825: ("hydration",   "renderer|asyncHydrate", ""),
    11823: ("runtime-dom", "runtime-dom|jsx|details tag", ""),
    11699: ("types",       "useModel|defineModel", ""),
    11644: ("types",       "componentProps|all-optional", ""),
    11608: ("reactivity",  "reactivity|computed|WritableComputedRef", ""),
    11598: ("types",       "runtime-dom|DOM lib", ""),
    11579: ("types",       "componentEmits|PascalCase", ""),
    11578: ("runtime-dom", "apiCustomElement|defineCustomElement", ""),
    11547: ("compiler",    "compiler-core|transformElement", ""),
    11540: ("types",       "directives|DirectiveArguments", ""),
    11538: ("runtime-dom", "useCssVars|cssvars", ""),
    11536: ("reactivity",  "reactivity|nested refs", ""),
    11490: ("types",       "withDefaults|setupHelpers", ""),
    11442: ("reactivity",  "reactivity|ref|getter setter", ""),
    11384: ("runtime-dom", "apiCustomElement|array emits", ""),
    11048: ("ssr",         "server-renderer|ssrRenderSlot", ""),
    11041: ("compiler",    "compiler-sfc|import macro", ""),
    11011: ("compiler",    "compiler-core|ForIteratorExpression", ""),
    10963: ("compiler",    "renderList|v-for key", ""),
    10938: ("runtime-dom", "runtime-dom|jsx|onToggle", ""),
    10825: ("runtime",     "runtime-core|componentSlots", ""),
    10603: ("types",       "apiCreateApp|app.provide", ""),
    10599: ("hydration",   "hydration|mismatch details", ""),
    10482: ("runtime",     "runtime-core|errorHandling", ""),
    10472: ("devtools",    "customFormatter|repl", ""),
    10443: ("runtime-dom", "runtime-dom|jsx|scroll event", ""),
    10414: ("runtime",     "runtime-core|warning", ""),
    10357: ("types",       "runtime-core|apiDefineComponent", ""),
    10311: ("runtime-dom", "runtime-dom|vShow|transition", ""),
}

NEXTJS: dict[int, Label] = {
    93128: ("turbopack",      "turbopack|turbo-tasks", ""),
    92831: ("cli",            "next/src/cli|trace-server", ""),
    92813: ("monorepo",       "pnpm-workspace|postinstall", ""),
    92631: ("turbopack",      "turbopack|turbo-tasks-fs|watcher", ""),
    92588: ("font",           "next_font|NextFontIssue", ""),
    92581: ("turbopack",      "turbopack|turbo-tasks-backend", ""),
    92569: ("turbopack",      "turbopack|persistent cache|chunk", ""),
    92535: ("monorepo",       "pnpm-workspace|minimumReleaseAge", ""),
    92414: ("cli",            "next/src/cli|next-build", ""),
    92210: ("turbopack",     "turbopack|task_cache|deadlock", ""),
    92205: ("scripts",       "scripts/pr-status", ""),
    91640: ("turbopack",     "turbopack|turbo-persistence|mmap", ""),
    91455: ("turbopack",     "turbopack|data_uri_source", ""),
    91454: ("cache",         "use-cache|cache-wrapper", ""),
    91262: ("ts-plugin",     "next/src/server/typescript|editor plugin", ""),
    91210: ("server-actions","server_actions|next-custom-transforms", ""),
    91099: ("scripts",       "scripts/patch-preview-tarball", ""),
    91092: ("scripts",       "scripts/set-preview-version|lerna", ""),
    91087: ("scripts",       "scripts/pr-status", ""),
    90817: ("turbopack",     "turbopack|turbo-persistence|static_sorted_file", ""),
    90700: ("turbopack",     "turbopack|manifest-loader|posix.join", ""),
    90398: ("turbopack",     "turbopack|hot-reloader-turbopack|hmr", ""),
    90312: ("build",         "next/src/build|debug-build-paths", ""),
    90056: ("turbopack",     "turbopack|aggregation_update|task lock", ""),
    89804: ("scripts",       "scripts/devlow-bench", ""),
    89708: ("turbopack",     "turbopack|task_storage_macro", ""),
    89228: ("turbopack",     "turbopack|task_storage_macro|tracking", ""),
    89134: ("cache",         "next/src/server/lib/lru-cache", "backport"),
    89099: ("server-runtime","router-server|zlib", ""),
    89040: ("cache",         "next/src/server/lib/lru-cache", ""),
    88934: ("turbopack",     "turbopack|turbo-tasks-backend", "typo"),
    88757: ("docs",          "AGENTS\\.md", ""),
    88685: ("edge-runtime",  "node-environment-extensions|setImmediate|edge", ""),
    88598: ("turbopack",     "turbopack|turbo-tasks|tokio_tracing", ""),
    88589: ("cli",           "next/src/cli/next-start|start-server", ""),
    88508: ("turbopack",     "turbopack|production chunking", ""),
    88346: ("edge-runtime",  "node-environment-extensions|setImmediate", ""),
    88331: ("turbopack",     "turbopack|TaskDataCategory|is_immutable", ""),
    88309: ("turbopack",     "turbopack|task category|cells", ""),
    88184: ("config",        "conductor\\.json|repo root", ""),
    88126: ("scripts",       "scripts/pack-util|next-swc", ""),
}

# control sample — fits existing `config` domain via .claude/ extension.
GWANGCHEON_SHOP: dict[int, Label] = {
    321: ("config", "\\.claude/settings", "Claude Code config — extends existing config domain"),
}

DATASETS = [
    ("vuejs-core-2026-04-26.csv", VUEJS),
    ("vercel-nextjs-2026-04-26.csv", NEXTJS),
    ("gwangcheon-shop-control-2026-04-26.csv", GWANGCHEON_SHOP),
]


def apply(csv_path: Path, labels: dict[int, Label]) -> tuple[int, int]:
    rows = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            pr = int(row["pr_number"])
            if pr in labels:
                domain, pattern, notes = labels[pr]
                row["true_domain"] = domain
                row["suggested_pattern"] = pattern
                row["notes"] = notes
            rows.append(row)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    labeled = sum(1 for r in rows if r.get("true_domain"))
    return labeled, len(rows)


def main() -> None:
    grand_total = 0
    grand_labeled = 0
    for filename, labels in DATASETS:
        path = SAMPLING / filename
        labeled, total = apply(path, labels)
        grand_total += total
        grand_labeled += labeled
        print(f"  {filename}: {labeled}/{total}")
    print(f"\nTotal: {grand_labeled}/{grand_total}")


if __name__ == "__main__":
    main()
