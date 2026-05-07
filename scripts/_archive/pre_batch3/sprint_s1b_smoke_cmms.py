import sys, asyncio, json
sys.path.insert(0, 'backend')
sys.path.insert(0, '.')
from cmms_mcp import tool_draft_cmms_work_order

async def go():
    result = await tool_draft_cmms_work_order({
        'component_id': 'chiller_1',
        'issue_summary': 'Quarterly tube cleaning + refrigerant test',
        'work_class_hint': 'PM',
        'likelihood_idx': 2,
        'consequence_idx': 3,
        'estimated_cost_usd': 4500,
        'requires_loto': False,
    })
    print(json.dumps(result, indent=2, default=str))

asyncio.run(go())
