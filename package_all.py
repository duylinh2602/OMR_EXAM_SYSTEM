# package_all.py
# -*- coding: utf-8 -*-
"""
KỊCH BẢN ĐÓNG GÓI TOÀN DIỆN CHO HỆ THỐNG CHẤM THI OMR 2026
Thực hiện tuần tự:
1. Kiểm tra môi trường & công cụ biên dịch (PyInstaller, Inno Setup).
2. Tạo icon app_icon.ico chuẩn đa phân giải.
3. Chạy PyInstaller biên dịch ra dist/OMR_Desktop_App.
4. Kiểm tra tính toàn vẹn của tệp thực thi OMR_System.exe.
5. Gọi Inno Setup (iscc.exe) đóng gói thành file cài đặt Setup_OMR_System_2026.exe.
"""
import os
import sys
import shutil
import time
import subprocess
from pathlib import Path

def print_step(step: str, title: str):
    print("\n" + "=" * 75)
    print(f"[{step}] {title}")
    print("=" * 75)

def find_inno_setup_compiler() -> Path:
    candidates = [
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 5\ISCC.exe"),
    ]
    for p in candidates:
        if p.exists():
            return p
    # Kiểm tra trong PATH
    which_iscc = shutil.which("iscc.exe") if "shutil" in globals() else None
    if which_iscc:
        return Path(which_iscc)
    return None

def main():
    start_time = time.time()
    base_dir = Path(__file__).resolve().parent
    os.chdir(base_dir)

    print_step("1/5", "KIỂM TRA CÔNG CỤ VÀ MÔI TRƯỜNG BIÊN DỊCH...")
    iscc_path = find_inno_setup_compiler()
    if not iscc_path or not iscc_path.exists():
        print("[!] Không tìm thấy Inno Setup Compiler (ISCC.exe).")
        print("    Vui lòng cài đặt Inno Setup 6 từ: https://jrsoftware.org/isdl.php")
        sys.exit(1)
    print(f"[✓] Tìm thấy Inno Setup Compiler: {iscc_path}")

    # Đảm bảo thư mục đầu ra tồn tại
    dist_installer = base_dir / "dist_installer"
    dist_installer.mkdir(parents=True, exist_ok=True)

    print_step("2/5", "KHỞI TẠO BIỂU TƯỢNG ỨNG DỤNG (APP_ICON.ICO)...")
    icon_file = base_dir / "app_icon.ico"
    png_icon = base_dir / "templates" / "icons" / "icon-512.png"
    if png_icon.exists():
        try:
            from PIL import Image
            img = Image.open(png_icon)
            img.save(icon_file, format="ICO", sizes=[(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)])
            print(f"[✓] Đã tạo thành công {icon_file.name} ({icon_file.stat().st_size:,} bytes)")
        except Exception as e:
            print(f"[!] Cảnh báo: Không thể tạo icon: {e}")

    print_step("3/5", "BIÊN DỊCH ỨNG DỤNG BẰNG PYINSTALLER (BUILD_SPEC.PY)...")
    build_py = base_dir / "build_spec.py"
    res = subprocess.run([sys.executable, str(build_py)])
    if res.returncode != 0:
        print(f"\n[!] Thất bại tại bước PyInstaller (Exit Code: {res.returncode})")
        sys.exit(res.returncode)

    print_step("4/5", "KIỂM TRA TÍNH TOÀN VẸN CỦA BẢN BIÊN DỊCH...")
    target_exe = base_dir / "dist" / "OMR_Desktop_App" / "OMR_System.exe"
    if not target_exe.exists():
        print(f"[!] Không tìm thấy tệp thực thi: {target_exe}")
        sys.exit(1)
    exe_size_mb = target_exe.stat().st_size / (1024 * 1024)
    print(f"[✓] Tệp thực thi: {target_exe.name} ({exe_size_mb:.2f} MB)")

    print_step("5/5", "ĐÓNG GÓI BỘ CÀI ĐẶT SETUP BẰNG INNO SETUP...")
    iss_file = base_dir / "installer_config.iss"
    if not iss_file.exists():
        print(f"[!] Không tìm thấy kịch bản Inno Setup: {iss_file}")
        sys.exit(1)

    cmd_inno = [str(iscc_path), str(iss_file)]
    res_inno = subprocess.run(cmd_inno)
    if res_inno.returncode != 0:
        print(f"\n[!] Thất bại khi đóng gói Inno Setup (Exit Code: {res_inno.returncode})")
        sys.exit(res_inno.returncode)

    installer_exe = dist_installer / "Setup_OMR_System_2026.exe"
    if not installer_exe.exists():
        print(f"[!] Không tìm thấy bộ cài đặt hoàn tất tại: {installer_exe}")
        sys.exit(1)

    installer_size_mb = installer_exe.stat().st_size / (1024 * 1024)
    elapsed = time.time() - start_time

    print("\n" + "=" * 75)
    print("🎉 ĐÓNG GÓI THÀNH CÔNG RỰC RỠ BỘ CÀI ĐẶT WINDOWS (.EXE)!")
    print("=" * 75)
    print(f"[*] Tên tệp cài đặt : {installer_exe.name}")
    print(f"[*] Đường dẫn đầy đủ: {installer_exe.resolve()}")
    print(f"[*] Dung lượng      : {installer_size_mb:.2f} MB")
    print(f"[*] Thời gian xử lý : {elapsed:.1f} giây")
    print("=" * 75)

if __name__ == "__main__":
    main()
