import ast
files = [
    "backend/agent_graph_tool.py",
    "backend/main.py",
    "backend/agent_copilot.py",
    "scripts/smoke_graphrag.py",
]
for f in files:
    try:
        ast.parse(open(f, encoding="utf-8").read())
        print(f"  [ok] {f}")
    except SyntaxError as e:
        print(f"  [FAIL] {f}: line {e.lineno}: {e.msg}")
