import sys, pathlib, asyncio
sys.path.insert(0, 'backend')
from procedure_engine import build_default_orchestrator

orch = build_default_orchestrator(pathlib.Path('.'))
print('Procedures loaded:', orch.registry.list_ids())

ex = asyncio.run(orch.start_procedure('MOP-ATS-MONTHLY-001', 'wilmer.angel'))
print('After start_procedure:', ex.state)
print('Pre-condition results:')
for r in ex.pre_condition_results:
    print(f'  {r["id"]}: passed={r["passed"]} action={r["failure_action"]}')

ex2 = asyncio.run(orch.advance_to_in_progress(ex.execution_id, 'wilmer.angel'))
print('After advance_to_in_progress:', ex2.state)
print(f'Steps executed: {len(ex2.execution_log)}')
for s in ex2.execution_log:
    print(f'  {s.step_id}: {s.status}')
