# clean_project.py
# -*- coding: utf-8 -*-
"""
CÔNG CỤ DỌN DẸP VÀ CHUẨN HÓA DỰ ÁN OMR TRƯỚC KHI XUẤT BẢN
Tự động sao lưu file cũ vào archive_backup/ và tinh gọn thư mục làm việc.
"""
import shutil
from pathlib import Path

# 1. Danh sách file code thừa/thử nghiệm ở thư mục gốc cần di dời vào archive
OBSOLETE_ROOT_FILES = [
    "align_sheet.py",
    "benchmark_test.py",
    "bubble_detector.py",
    "detect_markers.py",
    "detect_part1.py",
    "detect_part2.py",
    "detect_part3.py",
    "detect_part3_backup.py",
    "detect_part3_shadowfix.py",
    "render_template.py",
    "test_bubble_detector.py",
    "test_benchmark_clean.py",
    "test_unified_pipeline.py",
]

# 2. Danh sách công cụ hiệu chuẩn (di dời vào tools/calibration/)
CALIBRATION_TOOLS = [
    "calibrate_answers.py",
    "calibrate_header.py",
    "calibrate_part1.py",
    "calibrate_part2.py",
    "calibrate_part3.py",
    "config.py",
    "convert_pdf.py",
]

# 3. Danh sách file cốt lõi BẮT BUỘC PHẢI TỒN TẠI
CRITICAL_FILES = [
    "app.py",
    "full_grading_pipeline.py",
    "align_sheet_v2.py",
    "visual_stamper.py",
    "exam_manager.py",
    "run_app.bat",
    "templates/index.html",
    "output/header_coordinates.json",
    "output/part1_coordinates.json",
    "output/part2_coordinates.json",
    "output/part3_coordinates.json",
    "output/exams_db.json",
]


def clean_project():
    root = Path(".")
    archive_dir = root / "archive_backup"
    tools_dir = root / "tools" / "calibration"

    archive_dir.mkdir(exist_ok=True)
    tools_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 75)
    print("TIẾN TRÌNH TINH GỌN DỰ ÁN OMR EXAM SYSTEM")
    print("=" * 75)

    # 1. Sao lưu & Di dời các script thử nghiệm cũ
    moved_count = 0
    for fname in OBSOLETE_ROOT_FILES:
        fpath = root / fname
        if fpath.exists():
            shutil.move(str(fpath), str(archive_dir / fname))
            print(f"[*] Đã chuyển vào archive: {fname}")
            moved_count += 1

    # 2. Gom các công cụ hiệu chuẩn vào tools/calibration/
    tools_count = 0
    for fname in CALIBRATION_TOOLS:
        fpath = root / fname
        if fpath.exists():
            shutil.move(str(fpath), str(tools_dir / fname))
            print(f"[*] Đã chuyển vào tools/calibration: {fname}")
            tools_count += 1

    # 3. Dọn sạch file rác thử nghiệm trong thư mục output/
    output_dir = root / "output"
    deleted_output_count = 0
    if output_dir.exists():
        # Xóa các file kết quả scan cũ (bai_kiem_tra_*)
        for p in output_dir.glob("bai_kiem_tra_*_part*.*"):
            p.unlink()
            deleted_output_count += 1
        for p in output_dir.glob("bai_kiem_tra_*_debug*.*"):
            p.unlink()
            deleted_output_count += 1
        # Xóa database cũ v4.0 nếu còn
        old_db = output_dir / "submissions_db.json"
        if old_db.exists():
            old_db.unlink()
            print("[*] Đã xóa database cũ: output/submissions_db.json")
            deleted_output_count += 1

    print("-" * 75)
    print(f"[✓] Đã lưu trữ an toàn: {moved_count} file script cũ.")
    print(f"[✓] Đã gom gọn: {tools_count} công cụ hiệu chuẩn vào tools/calibration/.")
    print(f"[✓] Đã dọn dẹp: {deleted_output_count} file rác trong output/.")

    # 4. Kiểm tra tính toàn vẹn hệ thống (Integrity Check)
    print("\nKIỂM TRA TÍNH TOÀN VẸN HỆ THỐNG:")
    all_ok = True
    for cfile in CRITICAL_FILES:
        p = root / cfile
        if p.exists():
            print(f"  [OK] {cfile}")
        else:
            print(f"  [MISSING] {cfile} <-- LỖI: THIẾU TỆP CỐT LÕI!")
            all_ok = False

    print("=" * 75)
    if all_ok:
        print("[SUCCESS] DỰ ÁN ĐÃ ĐƯỢC LÀM SẠCH VÀ SẴN SÀNG CHO PHÁT HÀNH!")
    else:
        print("[WARNING] PHÁT HIỆN THIẾU TỆP, HÃY KIỂM TRA LẠI!")
    print("=" * 75)


if __name__ == "__main__":
    clean_project()