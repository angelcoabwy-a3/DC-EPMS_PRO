from pathlib import Path
p = Path(r"C:\dev\DC-EPMS_PRO\backend\main.py")
data = p.read_text(encoding="utf-8")
broken = '# ==============================================================if __name__ == "__main__":'
fixed = '# ==============================================================\nif __name__ == "__main__":'
if broken in data:
    p.write_text(data.replace(broken, fixed), encoding="utf-8")
    print("Patched: separated header comment from if __name__")
else:
    print("Pattern not found - check manually")
