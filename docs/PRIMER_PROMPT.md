# 🚀 Primer prompt — Claude Code · DC-EPMS PRO

Hola Claude Code. Soy **Wilmer Y. Angel Beltran**, CET y Lead Architect de
a3semi (A-Cubed Semiconductor Systems Inc.). Construyo **DC-EPMS PRO**
targeting el rol CET en **Microsoft CO+I**, ventana de entrevista
**early August 2026**.

Este archivo es el arranque de 30 segundos. Reescrito 2026-05-16 (T1.4)
para reflejar la realidad v0.10.13 — el primer prompt anterior estaba
congelado en v0.7.3 y se borró.

## 📍 Punto de entrada — leé esto primero

1. **`CLAUDE.md`** (raíz, synced 2026-05-16) — memoria persistente:
   estado, bugs registry, vocabulario Path C2, working style, reglas.
2. **`docs/ROADMAP-V11.md`** (locked 2026-05-10) — el **backlog vivo**.
   Cualquier "qué sigue" sale de ahí, no de este archivo.

## ✅ Verificar estado (no asumas — verificá)

```powershell
cd C:\dev\DC-EPMS_PRO
git log --oneline --decorate -n 5
git tag --sort=-creatordate | Select-Object -First 5
git status --short
docker ps --filter name=epms-db
```

Esperado:

- Árbol limpio **salvo** `DEMO_SCRIPT.md` modificado (draft v5 — ver abajo)
  y `.claude/` untracked (settings locales de Claude, intencional).
- `master` puede estar 1+ commits adelante de `origin` si quedó algo sin
  pushear; `git status` lo dice.
- Último tag en la línea `v0.10.x` (`v0.10.13-modal-fix` o descendiente).
- `epms-db` corriendo y `healthy`.

## 🔌 Levantar el stack

```powershell
docker start epms-db
docker inspect --format "{{.State.Health.Status}}" epms-db   # esperá: healthy
& .\.venv\Scripts\python.exe backend\main.py                 # backend nativo :8080
```

`curl http://127.0.0.1:8080/api/health` debe decir `postgres: up` y
`database: dcepms`. **Si dice `down`**: el backend lee `PG_DB`/`PG_USER`/
`PG_PASSWORD` de `config/.env` — el contenedor es `epms`/`dcepms`, NO
`postgres`/`epms` (lección DC-EPMS-DB-001, resuelta 2026-05-16).

## 🗺️ Dónde está el proyecto

- **V9 feature-complete** (v0.10.13). Backlog vivo = `docs/ROADMAP-V11.md`.
- **Frontend test harness existe** (T2.4): Vitest + happy-dom. `npm test`
  corre `tests/frontend/`. `package.json` en la raíz — el proyecto Node
  coexiste con el backend Python; no afecta el serving estático de FastAPI.
- **Grabación de demo (ROADMAP-V11 T1.2/T1.3) EN PAUSA.** `DEMO_SCRIPT.md`
  está en **v5, draft sin stagear** en el working tree — intencional, a la
  espera de los ensayos de grabación OBS. NO lo commitees hasta que Wilmer
  retome esa tarea.
- Última fase: "Cool Down" — T1.6 (cierre de bugs backend DC-EPMS-019/039,
  boot mucho más silencioso) y T1.4 (este archivo). Detalle en `CHANGELOG.md`.

## ⚠️ Reglas operacionales (no negociables)

- **Approve-then-execute**: plan en bullets, esperá "GO" / "luz verde"
  antes de generar código.
- **Atomic batches**: 2-3 por sesión, cada uno validable por separado.
- **Reality check**: si algo no es genuinamente demostrable en una laptop
  RTX 3060 6 GB, decilo y proponé lo que SÍ lo es.
- **Honest scope / honest tech debt**: sin padding; todo fallo se registra.
- **Tag is not closure**: tras taggear, `git log --decorate -n 5` verifica.
- **`--no-verify`**: permitido SOLO en commits que chocan con deuda lint
  legacy pre-existente (DC-EPMS-021), con validación manual (`py_compile` /
  tests) y autorización explícita de Wilmer.
- **PowerShell**: sin `<>` en strings, sin em-dashes, commits ASCII-only,
  validar `$LASTEXITCODE`. Filesystem ops en PowerShell nativo, no Bash.

## 🤝 Cómo trabajamos

Confío en tu disciplina. Si propongo algo que rompe las reglas, hago
pushback y vos re-analizás — no capitulás. Si necesitás ver un archivo
antes de proponer un fix, leélo con tus tools. Empezá leyendo `CLAUDE.md`.
