# 🛡️ GENTLE IA: AGENT HARNESS MASTER REGISTRY
**Fuente:** [El PADRE de todos los CURSOS de IA - Gentleman Programming]
**Framework:** Gentle IA / Pie Agent

## BLOQUE 1: ORQUESTACIÓN Y CONTEXTO
* **01. SDD Orchestrator Harness:** El orquestador coordina, no ejecuta.
* **02. Delegation Harness:** Define qué tareas justifican un sub-agente.
* **03. SDD Init Harness:** Calibra el proyecto antes de codificar.
* **04. Execution Mode Harness:** Define velocidad vs. control.
* **05. Artifact Store Harness:** El chat no es la verdad. El estado va a artefactos.

## BLOQUE 2: FASES Y ARTEFACTOS
* **06. Phase DAG Harness:** Grafo dirigido: Init -> Proposal -> Spec -> Design -> Task -> Apply -> Verify -> Archive.
* **07. Artifact Dependency Harness:** Entradas obligatorias para cada fase.
* **08. Result Contract Harness:** Contratos JSON entre fases.
* **09. SDD Artifact Grammar Harness:** Gramática compartida del proceso.
* **10. Engram Memory Harness:** Memoria persistente para recuperación.

## BLOQUE 3: CONTINUIDAD Y VERIFICACIÓN
* **11. Strict TDD Harness:** Red -> Green -> Triangulate -> Refactor.
* **12. Verify Harness:** Exige pruebas y outputs antes de terminar.
* **13. Apply Continuity Harness:** Guarda progreso intra-tarea.  
  **DC-EPMS:** OPERATIVO (2026-05-24). Implementado en `backend/agent_continuity.py`
  (`CheckpointStore` JSONL append-only + `Checkpoint` dataclass + phases
  `PHASE_PRE_LLM`/`PHASE_POST_LLM`). Wired into `ProcedureArchitectAgent`
  (`generate()` emite pre/post-LLM; `resume_from_checkpoint()` recupera
  con 3 ramas: ninguno→None, post_llm→reconstrucción sin LLM,
  pre_llm→re-dispatch). Skill: `S-CONTINUITY-01`. Cobertura: 18 tests en
  `tests/test_agent_continuity.py` (10 store primitives + 4 hook
  emission + 3 resume paths + 1 acceptance crash+recovery).

## BLOQUE 4: SKILLS Y SUBAGENTES
* **14. Skill Registry Harness:** Índice de capacidades del proyecto.
* **15. Skill Digestion Harness:** Compila contexto en instrucciones precisas.
* **16. Skill Resolution Feedback Harness:** Auditoría de uso de skills.  
  **DC-EPMS:** OPERATIVO (2026-05-24). Implementado en `backend/skill_audit.py`
  (`SKILL_ID_PATTERN` regex + `parse_commit_citations()` + `load_skill_registry()`
  + `expected_skills_for_files()` heuristic table + `audit_commit()` + CLI
  `python -m backend.skill_audit --since HEAD~N`). Skill: `S-FEEDBACK-01`.
  Cobertura: 22 tests en `tests/test_skill_audit.py`. **Bloque 4 ahora cerrado**
  (H14 ✓ skill-registry.md, H15 ✓ Skill Digestion in CLAUDE.md OPERATIONAL RULE,
  H16 ✓ this commit, H17 ✓ hermetic_prompt / sanitize_history).
* **17. Sub-Agent Isolation Harness:** (CRÍTICO) Aislamiento total de contexto para subagentes.

## BLOQUE 5: ENTREGA Y REVISIÓN
* **18. Review Warlock Harness:** Evalúa riesgo de PRs grandes.
* **19. Delivery Strategy Harness:** Estrategia de entrega de código.
* **20. Chain Strategy Harness:** Geometría de entrega (stacked PRs vs direct).

## ⚡ BLOQUE 6: EXTENSIONES AVANZADAS
* **21-30. (Advanced Harnesses):** Model Routing, Profile Isolation, Permission Security, MCP Injection, Backup/Rollback, Component Dependency, Command Wrapper, Per-Agent Adapter, Session Summary.
