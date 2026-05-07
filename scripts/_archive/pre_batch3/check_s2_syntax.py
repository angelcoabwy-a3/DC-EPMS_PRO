import ast
files = [
    "backend/knowledge_graph.py",
    "backend/graphrag_index.py",
    "backend/graphrag_service.py",
    "backend/graphrag_routes.py",
    "tests/test_graphrag.py",
]
for f in files:
    try:
        ast.parse(open(f, encoding="utf-8").read())
        print(f"  [ok] {f}")
    except SyntaxError as e:
        print(f"  [FAIL] {f}: {e}")
