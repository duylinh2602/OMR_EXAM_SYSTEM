# pack_project.py
# -*- coding: utf-8 -*-
"""
CÔNG CỤ ĐÓNG GÓI MÃ NGUỒN DỰ ÁN OMR THÀNH 1 FILE TXT
Tự động lọc bỏ: .venv, __pycache__, ảnh (PNG, JPG), tài liệu (PDF, XLSX).
Chỉ gom: Code Python (.py), Giao diện (.html, .css, .js), Cấu hình tọa độ (.json), File chạy (.bat).
"""
from datetime import datetime
import os
from pathlib import Path

# Thư mục và file cần bỏ qua
EXCLUDE_DIRS = {
    ".venv",
    "venv",
    "env",
    ".git",
    "__pycache__",
    ".vscode",
    ".idea",
    "web_uploads",
    "graded_sheets",
    "dist",
    "build",
}

EXCLUDE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".pdf",
    ".xlsx",
    ".xls",
    ".pyc",
    ".zip",
    ".tar",
    ".gz",
}

# Các đuôi file cần gom nội dung
INCLUDE_EXTENSIONS = {".py", ".html", ".js", ".css", ".bat", ".json", ".md"}

OUTPUT_FILE = "project_context.txt"


def generate_tree(root_dir: Path, prefix: str = "") -> list:
    """Tạo sơ đồ cây thư mục trực quan"""
    lines = []
    items = sorted(
        list(root_dir.iterdir()), key=lambda x: (x.is_file(), x.name.lower())
    )
    items = [
        item
        for item in items
        if item.name not in EXCLUDE_DIRS
        and item.name != OUTPUT_FILE
        and item.suffix.lower() not in EXCLUDE_EXTENSIONS
    ]

    for index, item in enumerate(items):
        is_last = index == len(items) - 1
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{item.name}")

        if item.is_dir():
            sub_prefix = prefix + ("    " if is_last else "│   ")
            lines.extend(generate_tree(item, sub_prefix))
    return lines


def pack_project():
    root_path = Path(".")
    packed_files = []

    # Quét toàn bộ file thỏa điều kiện
    for root, dirs, files in os.walk(root_path):
        # Lọc bỏ thư mục không cần thiết
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        for file in sorted(files):
            if file == OUTPUT_FILE:
                continue
            f_path = Path(root) / file
            if f_path.suffix.lower() in INCLUDE_EXTENSIONS:
                packed_files.append(f_path)

    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        out.write("=" * 80 + "\n")
        out.write("BÁO CÁO TOÀN DIỆN MÃ NGUỒN DỰ ÁN OMR (BỘ GD&ĐT 2025)\n")
        out.write(f"Thời gian tạo: {timestamp}\n")
        out.write(f"Tổng số file mã nguồn & cấu hình: {len(packed_files)}\n")
        out.write("=" * 80 + "\n\n")

        # 1. Ghi cây thư mục
        out.write("SƠ ĐỒ CẤU TRÚC THƯ MỤC:\n")
        out.write("OMR_EXAM_SYSTEM/\n")
        tree_lines = generate_tree(root_path)
        out.write("\n".join(tree_lines))
        out.write("\n\n" + "=" * 80 + "\n\n")

        # 2. Ghi chi tiết nội dung từng file
        for idx, f_path in enumerate(packed_files, start=1):
            rel_path = f_path.relative_to(root_path).as_posix()
            banner = f"[{idx}/{len(packed_files)}] TẬP TIN: {rel_path}"
            out.write("-" * 80 + "\n")
            out.write(banner + "\n")
            out.write("-" * 80 + "\n")

            try:
                content = f_path.read_text(encoding="utf-8")
                out.write(content + "\n\n")
            except Exception as e:
                out.write(f"[!] Không thể đọc tệp này: {e}\n\n")

    file_size_kb = Path(OUTPUT_FILE).stat().st_size / 1024
    print(f"[✓] Đã đóng gói thành công: {OUTPUT_FILE}")
    print(f"[*] Tổng số file: {len(packed_files)}")
    print(f"[*] Dung lượng file xuất: {file_size_kb:.2f} KB")


if __name__ == "__main__":
    pack_project()