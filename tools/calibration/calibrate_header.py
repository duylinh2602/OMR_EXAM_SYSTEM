# calibrate_header.py
# -*- coding: utf-8 -*-
"""
HIEU CHUAN SO BAO DANH (8 COT) VA MA DE THI (4 COT)
Theo chuan phoi answer_sheet_master.png (1769 x 2526 px)
"""
import json
from pathlib import Path
import cv2
import numpy as np

IMAGE_PATH = Path("output/answer_sheet_master.png")
OUTPUT_DIR = Path("output")

# Quy cách:
# Số báo danh: 8 cột x 10 hàng (0..9) = 80 ô
# Mã đề thi: 4 cột x 10 hàng (0..9) = 40 ô
# Tổng cộng: 12 cột x 10 hàng = 120 ô

CLICK_LABELS = [
    # 1. Hàng chữ số 0 của SBD (8 điểm: Cột 1 đến Cột 8)
    "SBD - Chu so 0 - Cot 1",
    "SBD - Chu so 0 - Cot 2",
    "SBD - Chu so 0 - Cot 3",
    "SBD - Chu so 0 - Cot 4",
    "SBD - Chu so 0 - Cot 5",
    "SBD - Chu so 0 - Cot 6",
    "SBD - Chu so 0 - Cot 7",
    "SBD - Chu so 0 - Cot 8",
    # 2. Hàng chữ số 0 của Mã đề (4 điểm: Cột 1 đến Cột 4)
    "Ma de - Chu so 0 - Cot 1",
    "Ma de - Chu so 0 - Cot 2",
    "Ma de - Chu so 0 - Cot 3",
    "Ma de - Chu so 0 - Cot 4",
    # 3. Điểm đáy để tính khoảng cách bước nhảy hàng dọc (Hàng số 9)
    "SBD - Chu so 9 - Cot 1"
]

image = cv2.imread(str(IMAGE_PATH))
if image is None:
    raise FileNotFoundError(f"Khong tim thay anh: {IMAGE_PATH}")

height, width = image.shape[:2]

scale = min(1100 / width, 780 / height, 1.0)
display_width = int(width * scale)
display_height = int(height * scale)
scale_x = display_width / width
scale_y = display_height / height

display_original = cv2.resize(image, (display_width, display_height), interpolation=cv2.INTER_AREA)
display_image = display_original.copy()
points = []

WINDOW_NAME = "HIEU CHUAN SO BAO DANH VA MA DE"


def redraw():
    global display_image
    display_image = display_original.copy()
    for index, (x, y) in enumerate(points):
        px = int(round(x * scale_x))
        py = int(round(y * scale_y))
        cv2.circle(display_image, (px, py), 5, (0, 255, 0), 2)
        cv2.putText(
            display_image,
            str(index + 1),
            (px + 6, py - 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (0, 0, 255),
            1
        )
    cv2.imshow(WINDOW_NAME, display_image)


def mouse_callback(event, x, y, flags, param):
    if event != cv2.EVENT_LBUTTONDOWN:
        return

    if len(points) >= len(CLICK_LABELS):
        print("Da chon du 13 diem. Nhan phím S de luu toa do.")
        return

    orig_x = int(round(x / scale_x))
    orig_y = int(round(y / scale_y))
    points.append((orig_x, orig_y))
    idx = len(points) - 1

    print(f"[{idx + 1}/13] {CLICK_LABELS[idx]}: x={orig_x}, y={orig_y}")
    redraw()

    if len(points) < len(CLICK_LABELS):
        print(f"--> Tiep theo: {CLICK_LABELS[len(points)]}")
    else:
        print("\n[✓] DA CHON DU 13 DIEM! Nhan phim S de luu, Backspace de xoa diem vua chon.")


def save_calibration():
    if len(points) != len(CLICK_LABELS):
        print(f"Chua du 13 diem: {len(points)}/13")
        return

    # 8 tọa độ X của SBD (Cột 1 đến 8)
    sbd_xs = [float(points[i][0]) for i in range(8)]
    # 4 tọa độ X của Mã đề (Cột 1 đến 4)
    made_xs = [float(points[i][0]) for i in range(8, 12)]

    # Hàng chữ số 0: lấy trung bình Y của 12 điểm chữ số 0
    row_zero_y = float(np.mean([points[i][1] for i in range(12)]))
    # Điểm chữ số 9 của cột 1
    row_nine_y = float(points[12][1])

    row_step = (row_nine_y - row_zero_y) / 9.0

    if row_step <= 10.0:
        raise ValueError(f"Khoang cach hang khong hop le: {row_step:.2f}")

    # Sinh danh sách tọa độ 10 hàng chữ số
    digits_y = [round(row_zero_y + d * row_step, 2) for d in range(10)]

    sbd_grid = []
    for col_idx, cx in enumerate(sbd_xs, start=1):
        col_data = {"column": col_idx, "x": round(cx, 2), "digits": {}}
        for d in range(10):
            col_data["digits"][str(d)] = [round(cx, 2), digits_y[d]]
        sbd_grid.append(col_data)

    made_grid = []
    for col_idx, cx in enumerate(made_xs, start=1):
        col_data = {"column": col_idx, "x": round(cx, 2), "digits": {}}
        for d in range(10):
            col_data["digits"][str(d)] = [round(cx, 2), digits_y[d]]
        made_grid.append(col_data)

    header_result = {
        "template": "answer_sheet_master",
        "template_width": width,
        "template_height": height,
        "row_step": round(row_step, 3),
        "digits_y_rows": digits_y,
        "sbd_columns": sbd_grid,
        "made_columns": made_grid
    }

    OUTPUT_DIR.mkdir(exist_ok=True)
    json_path = OUTPUT_DIR / "header_coordinates.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(header_result, f, ensure_ascii=False, indent=4)

    # Vẽ kiểm tra 120 ô tròn lên ảnh mẫu
    preview = image.copy()
    for col in sbd_grid:
        for d, (x, y) in col["digits"].items():
            cv2.circle(preview, (int(x), int(y)), 8, (0, 200, 0), 2)
            cv2.putText(preview, d, (int(x) - 4, int(y) + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 255), 1)

    for col in made_grid:
        for d, (x, y) in col["digits"].items():
            cv2.circle(preview, (int(x), int(y)), 8, (255, 100, 0), 2)
            cv2.putText(preview, d, (int(x) - 4, int(y) + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 255), 1)

    preview_path = OUTPUT_DIR / "header_calibration_preview.png"
    cv2.imwrite(str(preview_path), preview)

    print("\n========================================================")
    print("HIEU CHUAN SO BAO DANH & MA DE THANH CONG!")
    print(f"- Khoang cach hang doc (row_step): {row_step:.2f} px")
    print(f"- File toa do da luu: {json_path.resolve()}")
    print(f"- Anh preview kiem tra: {preview_path.resolve()}")
    print("========================================================")


print("========================================================")
print("HUONG DAN HIEU CHUAN HEADER (SO BAO DANH & MA DE THI)")
print("========================================================")
for i, lbl in enumerate(CLICK_LABELS, start=1):
    print(f"{i:2d}. Click vao TAM o: {lbl}")
print("\n- Phim S: Luu toa do sau khi click du 13 diem")
print("- Phim Backspace: Xoa diem vua click nham")
print("- Phim ESC: Huy bo")

cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
cv2.resizeWindow(WINDOW_NAME, display_width, display_height)
cv2.setMouseCallback(WINDOW_NAME, mouse_callback)

while True:
    cv2.imshow(WINDOW_NAME, display_image)
    key = cv2.waitKey(20) & 0xFF
    if key == 27:
        print("Da huy.")
        break
    elif key in (8, 127):  # Backspace / Delete
        if points:
            removed = points.pop()
            print(f"Da xoa diem: {removed}")
            redraw()
    elif key == ord("s"):
        try:
            save_calibration()
            break
        except Exception as err:
            print("LOI:", err)

cv2.destroyAllWindows()