import sys
import io

# 出力をファイルにリダイレクト
out = io.open(r"C:\Users\onlyg\AppData\Local\Temp\testout.txt", "w", encoding="utf-8")
sys.stdout = out
sys.stderr = out

try:
    import runpy
    runpy.run_path("test_algorithm.py", run_name="__main__")
except SystemExit as e:
    print(f"\nSysExit: {e.code}")
except Exception as e:
    print(f"\nERROR: {e}")
    import traceback
    traceback.print_exc()
finally:
    out.flush()
    out.close()
