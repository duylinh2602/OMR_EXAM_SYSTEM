# run_desktop.py
# -*- coding: utf-8 -*-
import multiprocessing
import os
from pathlib import Path
import socket
import sys
import threading
import time
import traceback


def get_base_dir() -> Path:
    """Xác định đúng thư mục gốc dù chạy mã nguồn trực tiếp hay chạy qua file .exe đóng gói"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


# Đặt lại thư mục làm việc về đúng thư mục dự án
os.chdir(get_base_dir())

try:
    from app import app
    import uvicorn
    import webview
except Exception as e:
    print("\n[!] LỖI IMPORT THƯ VIỆN:")
    traceback.print_exc()
    input("\nNhấn Enter để thoát...")
    sys.exit(1)


def find_available_port(default_port: int = 8000) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # Kiểm tra trên 0.0.0.0
        if s.connect_ex(("127.0.0.1", default_port)) != 0:
            return default_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def wait_for_server(host: str, port: int, timeout: float = 8.0) -> bool:
    start_time = time.time()
    while time.time() - start_time < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.1)
    return False


class UvicornServerThread(threading.Thread):

    def __init__(self, host: str, port: int):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.config = uvicorn.Config(
            app=app, host=self.host, port=self.port, log_level="warning"
        )
        self.server = uvicorn.Server(self.config)

    def run(self):
        try:
            self.server.run()
        except Exception as ex:
            print(f"[!] Lỗi máy chủ Uvicorn: {ex}")

    def stop(self):
        self.server.should_exit = True


def start_app():
    # 0.0.0.0 cho phép cả máy tính lẫn điện thoại trong mạng LAN kết nối
    server_host = "0.0.0.0"
    port = find_available_port(8000)
    
    # URL hiển thị trên Desktop nội bộ
    desktop_url = f"http://127.0.0.1:{port}"

    server_thread = UvicornServerThread(server_host, port)
    server_thread.start()

    if not wait_for_server("127.0.0.1", port, timeout=8.0):
        print(f"[!] Lỗi: Máy chủ không thể lắng nghe tại cổng {port}")
        input("\nNhấn Enter để thoát...")
        sys.exit(1)

    print(f"[*] Máy chủ OMR đang mở rộng trên toàn mạng:")
    print(f"    - Truy cập trên máy tính : http://127.0.0.1:{port}")
    print(f"    - Truy cập trên điện thoại: http://192.168.1.48:{port}/scanner")

    window = webview.create_window(
        title="HỆ THỐNG CHẤM PHIẾU TRẮC NGHIỆM - BỘ GD&ĐT 2025",
        url=desktop_url,
        width=1440,
        height=900,
        min_size=(1024, 700),
        resizable=True,
        confirm_close=True,
    )

    def on_closed():
        server_thread.stop()

    window.events.closed += on_closed
    webview.start(gui="edgechromium", debug=False)
    sys.exit(0)

    def on_closed():
        server_thread.stop()

    window.events.closed += on_closed
    webview.start(gui="edgechromium", debug=False)
    sys.exit(0)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    start_app()