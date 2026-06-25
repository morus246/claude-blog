# Deploy Pipeline Audit

**Data:** 2026-06-25
**Escopo:** CI do skill repo (`.github/workflows/ci.yml`) + deploy de blog posts (`scripts/deploy_post.py` → `fabiomorus/deploy.sh` → VPS Hostinger)

---

## Visão geral - 2 fluxos independentes

### Fluxo A - CI do skill repo
`.github/workflows/ci.yml`, trigger push/PR → main/master, 6 jobs paralelos:
- `test` - pytest em py 3.11 + 3.12 (matrix)
- `validate-skills` - frontmatter SKILL.md + plugin.json + `claude plugin validate` (best-effort)
- `lint-markdown` - paths stale `blog/references` / `blog/templates`
- `lint-prose-hygiene` - `scripts/lint_prose.py`
- `version-coherence` - versão igual em pyproject/plugin.json/CITATION/SKILL.md

**Sem deploy automático do skill.** Release é manual: `git tag` + `gh release create` + `/release-blog`.

### Fluxo B - Deploy blog post → fabiomorus.com
`scripts/deploy_post.py` (12 passos):
1-4. Load `.deploy.json` → achar MD → achar hero → converter webp
5. Normaliza frontmatter PT (+ detecta EN em `translations/en/`)
6-9. Escreve `.md` em `src/content/blog/` (+ `blog-en/` se EN)
10. `pnpm run build` (rollback se falhar)
11. `bash deploy.sh` no repo fabiomorus → VPS via rsync over SSH
12. Emite JSON `{pt_url, en_url, hero}`

`deploy.sh` (fabiomorus): `pnpm run validate:deploy` → stop PM2 → rm estáticos → rsync `dist/client` + `dist/server` → `pnpm install --prod` → `pm2 startOrRestart` → IndexNow.

---

## 🔴 P0 - Bugs / correções rápidas

| # | Problema | Local | Esforço |
|---|----------|-------|---------|
| 1 | **`hero_rel` dead variable** - computado, nunca usado | `deploy_post.py:256` | 5 min |
| 2 | **`author` hardcoded "Fabio Morus"** - ignora `config["default_author"]` do `.deploy.json` | `deploy_post.py:130,190` | 10 min |
| 3 | **Domínio `fabiomorus.com` hardcoded em 4 locais** - não usa config; reuso impossível | `deploy_post.py:2,257,321,325` | 15 min |
| 4 | **`subprocess.run` sem timeout** - build/deploy podem hangar indefinidamente | `deploy_post.py:297,307` | 10 min |
| 5 | **`_find_canonical_md` ambíguo** - múltiplos MDs sem match de slug pega `candidates[0]` (não-determinístico) | `deploy_post.py:50` | 15 min |

## 🟠 P1 - Robustez / lacunas reais

| # | Problema | Impacto | Esforço |
|---|----------|---------|---------|
| 6 | **Sem rollback do step 11 (deploy.sh)** - se rsync falhar depois de PM2 stop, VPS fica inconsistente + downtime | Estado quebrado no ar, site offline | 1-2h |
| 7 | **Sem health check pós-deploy** - não verifica 200 no live após PM2 restart | Deploy "sucesso" mas site 500 | 30 min |
| 8 | **PM2 stop → rsync → start = downtime explícito** (minutos) | Indisponibilidade em todo deploy | 2-4h (zero-downtime) |
| 9 | **`.deploy.json` path absoluto** (`/Users/morus/...`) - quebra em CI/outra máquina | Não-portátil, não-testável em CI | 20 min |
| 10 | **Sem preflight SSH** - chave/host só validados no step final | Falha tardia, debug difícil | 30 min |
| 11 | **`_to_webp` fallback silencioso** - sem PIL copia raw; jpg grande vira asset gigante | Performance/LCP | 30 min |
| 12 | **Sem validação de slug URL-safe** - acento/espaço no nome da pasta quebra URL | 404/encoding bugs | 20 min |

## 🟡 P2 - Cobertura de teste / CI

| # | Problema | Esforço |
|---|----------|---------|
| 13 | Sem teste p/ `_load_config` JSON inválido | 10 min |
| 14 | Sem teste p/ falha do deploy.sh (step 11) - porque rollback não existe | 30 min (após #6) |
| 15 | Sem teste p/ `_to_webp` fallback / ambiguous canonical MD | 20 min |
| 16 | CI sem secret scanning (gitleaks/trufflehog) - `.deploy.json` gitignored mas sem guard | 30 min |
| 17 | Mocks de teste frágeis - `mock_run` global, detecção por substring `"build" in cmd` | 1h |

---

## Observações positivas (não mexer)
- IndexNow key file presente no disco (`public/4e5c0542-*.txt`) ✓
- `validate:deploy` = lint + check + build ✓ (gating correto no `deploy.sh`)
- Rollback do step 10 (build) implementado corretamente (`_rollback` + `_fail`) ✓
- `_fail` emite JSON estruturado no stderr ✓
- CI: SHA-pinned actions, least-privilege token, concurrency cancel ✓
- `.deploy.json` gitignored (linha 32) - sem leak git ✓

---

## Recomendações

- **Quick wins** (P0 todos + #9 + #13): ~1h, zero risco, fecha inconsistências (author/domínio ignoram config que existe pra isso).
- **Maior ganho de robustez**: #6 (rollback deploy.sh) + #7 (health check) - evita "deploy sucesso, site quebrado".
- **Maior ganho de disponibilidade**: #8 (zero-downtime via `pm2 reload` ou blue-green) - maior esforço, só se downtime for problema real.

## Status

**Implementado (2026-06-25).** P0 + P1 completos via TDD. 302 testes passando, prose lint OK.

### Resumo do que foi feito

| Item | Onde | Status |
|------|------|--------|
| #1 dead var `hero_rel` | `scripts/deploy_post.py` | feito (refactor) |
| #2 author do config (`default_author`) | `scripts/deploy_post.py` | feito (TDD) |
| #3 domínio do config (`site_url`) | `scripts/deploy_post.py` | feito (TDD) |
| #4 timeout subprocess (build/deploy) + `TimeoutExpired` handling | `scripts/deploy_post.py` | feito (TDD) |
| #5 canonical MD determinístico (fail on ambiguous) | `scripts/deploy_post.py` | feito (TDD) |
| #6 rollback rsync (snapshot/restore + trap) | `fabiomorus/deploy.sh` | feito (bash -n OK) |
| #7 health check pós-deploy (retry+backoff, _fail se quebrado) | `scripts/deploy_post.py` | feito (TDD) |
| #8 zero-downtime | - | **NÃO feito - ver plano abaixo** |
| #9 site path portátil (relativo + env `CLAUDE_BLOG_SITE`) | `scripts/deploy_post.py` | feito (TDD) |
| #10 preflight SSH (BatchMode, antes de destruir) | `fabiomorus/deploy.sh` | feito (bash -n OK) |
| #11 webp fallback warning (stderr) | `scripts/deploy_post.py` | feito (TDD) |
| #12 validação de slug URL-safe | `scripts/deploy_post.py` | feito (TDD) |

Testes: 73 -> 284 `def test_` (suíte total: 302 passing). Coverage nova: canonical MD, timeout, slug, webp, config helpers, health check.

### #8 - Por que não foi implementado

`ecosystem.config.cjs` roda em **fork mode, `instances: 1`**. PM2 `reload` com 1 instância fork = restart completo (não zero-downtime). Além disso, rsync `--delete` muta os dirs `dist/client` + `dist/server` vivos, então qualquer worker ativo durante a transferência serviria chunks quebrados.

Zero-downtime real exige refactor release/symlink-swap (cross-repo, alto risco):
1. Layout VPS: `/var/www/fabiomorus/releases/<ts>/{client,server}` + symlink `current -> releases/<latest>`.
2. `ecosystem.config.cjs`: `cwd: current` (resolve via symlink), `exec_mode: 'cluster'`, `instances: 2+`.
3. `deploy.sh`: rsync p/ `releases/<novo-ts>`, `ln -sfn` swap atômico, `pm2 reload` (rolling), reter últimas 3 releases.
4. nginx: servir `current/client` (static) via symlink.
5. `csp-preload.cjs`: confirmar resolução de path via symlink.

Estimativa: 2-4h, só validável na VPS. Não fazer em sessão sem acesso ao ambiente de produção.

### #2/#3/#9 - Novos campos de config

`.deploy.json` agora suporta (campos novos opcionais, defaults seguros):
- `default_author` - autor no frontmatter (default: `"Fabio Morus"`).
- `site_url` - URL base p/ links absolutos (default: `"https://fabiomorus.com"`).
- `site` - path absoluto OU relativo ao repo root; env `CLAUDE_BLOG_SITE` sobrepõe tudo.

Recomendado adicionar `site_url` explicitamente ao `.deploy.json` local p/ documentar.
