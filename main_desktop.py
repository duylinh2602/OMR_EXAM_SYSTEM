# main_desktop.py
# -*- coding: utf-8 -*-
"""
DESKTOP LAUNCHER CHO HỆ THỐNG OMR 2026 (PRODUCTION DESKTOP CLIENT)
Tích hợp Self-Healing Bootstrapper: Tự động trích xuất tọa độ phôi mẫu, file Excel mẫu và template
từ _internal sang working directory trước khi nạp FastAPI Pipeline.
"""
import sys
import os

# Thiết lập bảng mã UTF-8 cho toàn bộ tiến trình con và Uvicorn
os.environ["PYTHONIOENCODING"] = "utf-8"
if sys.platform == "win32":
    try:
        if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from pathlib import Path
import shutil
import multiprocessing
import threading
import socket
import time

# ==============================================================================
# 1. BOOTSTRAPPER: THIẾT LẬP THƯ MỤC LÀM VIỆC & ĐỒNG BỘ DỮ LIỆU TỰ ĐỘNG
# (BẮT BUỘC CHẠY TRƯỚC KHI IMPORT APP.PY)
# ==============================================================================
def get_base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

BASE_DIR = get_base_dir()
os.chdir(BASE_DIR)

RUNTIME_OUTPUT_DIR = BASE_DIR / "output"
RUNTIME_OUTPUT_DIR.mkdir(exist_ok=True, parents=True)
(RUNTIME_OUTPUT_DIR / "graded_sheets").mkdir(exist_ok=True, parents=True)
(BASE_DIR / "output/web_uploads").mkdir(exist_ok=True, parents=True)
TARGET_TEMPLATES = BASE_DIR / "templates"
TARGET_TEMPLATES.mkdir(exist_ok=True, parents=True)

# Đồng bộ tài nguyên từ gói đóng gói PyInstaller (_internal hoặc _MEIPASS)
if getattr(sys, 'frozen', False):
    internal_dirs = [
        Path(getattr(sys, '_MEIPASS', BASE_DIR / "_internal")),
        BASE_DIR / "_internal"
    ]
    for int_dir in internal_dirs:
        if not int_dir.exists():
            continue
        
        # Sao chép các file tọa độ & template mẫu
        src_output = int_dir / "output"
        if src_output.exists():
            for f in src_output.iterdir():
                if f.is_file():
                    dest_f = RUNTIME_OUTPUT_DIR / f.name
                    if not dest_f.exists() or dest_f.stat().st_size == 0:
                        try:
                            shutil.copy2(f, dest_f)
                        except Exception:
                            pass

        # Sao chép toàn bộ thư mục templates (bao gồm icons, sw.js, manifest.json, các file html)
        src_tpl = int_dir / "templates"
        if src_tpl.exists():
            for item in src_tpl.rglob("*"):
                rel = item.relative_to(src_tpl)
                dest_item = TARGET_TEMPLATES / rel
                if item.is_dir():
                    dest_item.mkdir(parents=True, exist_ok=True)
                elif not dest_item.exists() or dest_item.stat().st_size == 0:
                    dest_item.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copy2(item, dest_item)
                    except Exception:
                        pass

# ==============================================================================
# 2. KHỞI TẠO MÁY CHỦ UVICORN VÀ GIAO DIỆN DESKTOP WEBVIEW
# ==============================================================================
from app import app
import uvicorn
import webview

def check_port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0

def find_available_port(default_port: int = 8000) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("127.0.0.1", default_port)) != 0:
            return default_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]

class ServerWorker(threading.Thread):
    def __init__(self, host="0.0.0.0", port=8000):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.config = uvicorn.Config(
            app=app, 
            host=self.host, 
            port=self.port, 
            log_level="warning"
        )
        self.server = uvicorn.Server(self.config)

    def run(self):
        try:
            self.server.run()
        except Exception as e:
            print(f"[!] Lỗi tiến trình máy chủ: {e}")

    def stop(self):
        self.server.should_exit = True

def main():
    multiprocessing.freeze_support()
    port = find_available_port(8000)
    
    server = ServerWorker(host="0.0.0.0", port=port)
    server.start()

    # Chờ server mở socket hoàn tất để chống lỗi trắng trang
    for _ in range(40):
        if check_port_open("127.0.0.1", port):
            break
        time.sleep(0.1)

    window = webview.create_window(
        title="HỆ THỐNG QUẢN LÝ VÀ CHẤM THI OMR 2026",
        url=f"http://127.0.0.1:{port}",
        width=1440,
        height=900,
        min_size=(1024, 700),
        text_select=True,
        confirm_close=True
    )

    def on_window_closed():
        server.stop()

    window.events.closed += on_window_closed
    webview.start(gui="edgechromium", debug=False)
    sys.exit(0)

if __name__ == "__main__":
    main()
