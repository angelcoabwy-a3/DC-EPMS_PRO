"""
Sprint S2 - Batch 2 Fix: correct the site_model fixture in test_graphrag.py.

The original fixture used SiteModel.load(path) which is wrong because
load() is an instance method, not a classmethod with a path arg.

Correct usage: SiteModel(yaml_path=path); sm.load(); return sm
"""
from pathlib import Path
import sys

TEST_PATH = Path(r"C:\dev\DC-EPMS_PRO\tests\test_graphrag.py")
PYTEST_INI = Path(r"C:\dev\DC-EPMS_PRO\pytest.ini")

if not TEST_PATH.exists():
    print(f"ERROR: not found: {TEST_PATH}")
    sys.exit(1)

content = TEST_PATH.read_text(encoding="utf-8")

# Replace the broken fixture
old_fixture = '''@pytest.fixture(scope="module")
def site_model():
    return SiteModel.load(SITE_MODEL_PATH)'''

new_fixture = '''@pytest.fixture(scope="module")
def site_model():
    sm = SiteModel(yaml_path=SITE_MODEL_PATH)
    sm.load()
    return sm'''

if old_fixture in content:
    content = content.replace(old_fixture, new_fixture)
    TEST_PATH.write_text(content, encoding="utf-8")
    print(f"[ok] Fixture patched in {TEST_PATH.name}")
else:
    print(f"[warn] fixture marker not found in {TEST_PATH.name}")
    print("       Maybe it was already fixed? Check current content:")
    for i, line in enumerate(content.split("\n")[45:55], start=46):
        print(f"   line {i}: {line}")

# Also register the 'slow' marker in pytest.ini to silence warnings
PYTEST_INI_CONTENT = """[pytest]
markers =
    slow: tests that load the embedding model (~90MB download on first run)
"""

if PYTEST_INI.exists():
    existing = PYTEST_INI.read_text(encoding="utf-8")
    if "slow:" not in existing:
        # Append marker if pytest.ini exists but doesn't have it
        if "[pytest]" in existing:
            if "markers =" in existing:
                existing = existing.replace(
                    "markers =",
                    "markers =\n    slow: tests that load the embedding model (~90MB download on first run)\n#"
                )
            else:
                existing += "\nmarkers =\n    slow: tests that load the embedding model (~90MB download on first run)\n"
        else:
            existing += "\n" + PYTEST_INI_CONTENT
        PYTEST_INI.write_text(existing, encoding="utf-8")
        print(f"[ok] Updated existing {PYTEST_INI.name} with slow marker")
    else:
        print(f"[skip] {PYTEST_INI.name} already has slow marker")
else:
    PYTEST_INI.write_text(PYTEST_INI_CONTENT, encoding="utf-8")
    print(f"[ok] Created {PYTEST_INI.name} with slow marker registration")

print()
print("=== Fix applied. Re-run tests. ===")
