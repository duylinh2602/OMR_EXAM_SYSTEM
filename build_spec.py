# build_spec.py
# -*- coding: utf-8 -*-
"""
KỊCH BẢN ĐÓNG GÓI PYINSTALLER CHUYÊN NGHIỆP CHO OMR 2026
Tự động dọn tiến trình khóa file, gỡ thuộc tính Read-only, bảo đảm tài nguyên chuẩn.
"""
import os
from pathlib import Path
import subprocess
import sys
import time

print("\n" + "=" * 70)
print("[1/3] DỌN DẸP AN TOÀN VÀ GIẢI PHÓNG TÀI NGUYÊN...")
print("=" * 70)

# Cưỡng chế dừng tiến trình cũ nếu còn đang chạy ngầm
try:
    subprocess.run(["taskkill", "/F", "/IM", "OMR_System.exe", "/T"], capture_output=True, text=True)
    time.sleep(0.3)
except Exception:
    pass

# Xóa bản build cũ bằng lệnh Windows Native (chống dính lỗi WinError 5)
if os.name == "nt":
    for folder in ["dist\\OMR_Desktop_App", "build\\OMR_Desktop_App"]:
        if os.path.exists(folder):
            subprocess.run(f'attrib -r -s -h "{folder}\\*" /s /d', shell=True, capture_output=True)
            subprocess.run(f'cmd /c "rd /s /q {folder}"', shell=True, capture_output=True)
            print(f"[✓] Đã dọn sạch: {folder}")

print("\n" + "=" * 70)
print("[2/3] XÁC THỰC CÁC TỆP TÀI NGUYÊN BẮT BUỘC...")
print("=" * 70)

required_data_files = [
    ("templates", "templates"),
    ("output/header_coordinates.json", "output"),
    ("output/part1_coordinates.json", "output"),
    ("output/part2_coordinates.json", "output"),
    ("output/part3_coordinates.json", "output"),
    ("output/exams_db.json", "output"),
]

missing = [src for src, _ in required_data_files if not Path(src).exists()]
if missing:
    print(f"[!] Thiếu tệp bắt buộc: {missing}")
    if Path("restore_coordinates.py").exists():
        print("[*] Đang tự động chạy restore_coordinates.py...")
        subprocess.run([sys.executable, "restore_coordinates.py"], check=True)
    else:
        print("[!] Không tìm thấy restore_coordinates.py để phục hồi.")
        sys.exit(1)

# Đảm bảo file database mặc định tồn tại
db_file = Path("output/exams_db.json")
if not db_file.exists():
    db_file.parent.mkdir(exist_ok=True, parents=True)
    db_file.write_text('{"active_exam_id": "default_exam", "exams": {}}', encoding="utf-8")

spec_content = f"""# -*- mode: python ; coding: utf-8 -*-
block_cipher = None

added_datas = {required_data_files}

a = Analysis(
    ['main_desktop.py'],
    pathex=[],
    binaries=[],
    datas=added_datas,
    hiddenimports=[
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.lifespans',
        'uvicorn.lifespans.on',
        'fastapi',
        'starlette',
        'pydantic',
        'fitz',
        'openpyxl',
        'cv2',
        'numpy',
        'webview',
        'webview.platforms.winforms',
        'webview.platforms.edgechromium',
        'clr'
    ],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'unittest'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OMR_System',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=None
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='OMR_Desktop_App',
)
"""

Path("app_build.spec").write_text(spec_content, encoding="utf-8")

print("\n" + "=" * 70)
print("[3/3] TIẾN HÀNH BIÊN DỊCH VỚI PYINSTALLER...")
print("=" * 70)

try:
    subprocess.run(["pyinstaller", "--noconfirm", "app_build.spec"], check=True)
    print("\n" + "=" * 70)
    print("[✓] BIÊN DỊCH THÀNH CÔNG RỰC RỠ!")
    print(f"[*] Thư mục sản phẩm: {Path('dist/OMR_Desktop_App').resolve()}")
    print("=" * 70)
except subprocess.CalledProcessError as err:
    print(f"\n[!] BIÊN DỊCH THẤT BẠI: Exit code {err.returncode}")
    sys.exit(err.returncode)