"""Sprint 2 E2E: procedure_engine + real HAL adapters with mock backends."""
import asyncio, sys, pathlib
sys.path.insert(0, 'backend')

from procedure_engine import (
    ProcedureRegistry, PreConditionEvaluator, StateProvider,
    AdapterRegistry, StepExecutor, ProcedureOrchestrator, SimulatedAdapter,
)
from hal import (CumminsAdapter, MockModbusBackend,
                 AscoAdapter, MockBACnetBackend)

registry = ProcedureRegistry(pathlib.Path('config/procedures'))
registry.load_all()

adapters = AdapterRegistry()
adapters.register("simulated", SimulatedAdapter())

cummins_backend = MockModbusBackend()
cummins_backend.preload(slave=1, address=0,  value=1)
cummins_backend.preload(slave=1, address=10, value=1500)
cummins_backend.preload(slave=1, address=13, value=6005)
cummins_backend.preload(slave=1, address=14, value=480)
cummins_backend.preload(slave=1, address=19, value=850)
cummins_backend.preload(slave=1, address=20, value=750)
cummins_backend.preload(slave=1, address=23, value=2440)
cummins = CumminsAdapter(cummins_backend, {"genset_a": {"slave_id": 1}})
adapters.register("cummins", cummins)

asco_backend = MockBACnetBackend()
asco_backend.preload("10.5.2.50", "multiStateInput", 1, "presentValue", 0)
asco_backend.preload("10.5.2.50", "binaryInput", 1, "presentValue", 0)
asco_backend.preload("10.5.2.50", "binaryInput", 2, "presentValue", 0)
asco = AscoAdapter(asco_backend, {"ats_a": {"address": "10.5.2.50", "device_id": 1001}})
adapters.register("asco", asco)

original_write = asco_backend.write
async def smart_write(address, object_type, object_id, prop, value):
    result = await original_write(address, object_type, object_id, prop, value)
    if object_type == "binaryOutput" and value:
        if object_id == 1:
            asco_backend._store[(address, "binaryInput", 2, "presentValue")] = 1
        elif object_id == 3:
            asco_backend._store[(address, "multiStateInput", 1, "presentValue")] = 1
            asco_backend._store[(address, "binaryInput", 1, "presentValue")] = 0
        elif object_id == 2:
            asco_backend._store[(address, "multiStateInput", 1, "presentValue")] = 0
            asco_backend._store[(address, "binaryInput", 1, "presentValue")] = 0
    return result
asco_backend.write = smart_write

evaluator = PreConditionEvaluator(StateProvider())
executor = StepExecutor(adapters)
orch = ProcedureOrchestrator(registry, evaluator, executor)

async def main():
    await cummins.connect()
    await asco.connect()
    print("Adapters connected: simulated, cummins, asco")

    ex = await orch.start_procedure('MOP-ATS-MONTHLY-001', 'wilmer.angel')
    print(f"\nstart_procedure: state = {ex.state.value}")

    ex2 = await orch.advance_to_in_progress(ex.execution_id, 'wilmer.angel')
    print(f"advance_to_in_progress: state = {ex2.state.value}")
    print(f"\nSteps executed: {len(ex2.execution_log)}")
    for s in ex2.execution_log:
        marker = "OK" if s.status == "OK" else "FAIL"
        print(f"  [{marker}] {s.step_id}: {s.title}")

    print(f"\nBACnet writes captured:")
    for k, v in sorted(asco_backend._store.items(), key=str):
        if isinstance(k, tuple) and len(k) == 4 and k[1] == "binaryOutput":
            print(f"  obj_id={k[2]:2}  value={v}")

asyncio.run(main())