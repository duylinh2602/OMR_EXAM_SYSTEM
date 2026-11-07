# align_sheet_v2.py
# -*- coding: utf-8 -*-
"""
MODULE NẮN PHẲNG PHỐI CẢNH ĐA TẦNG OMR CHUẨN BỘ GD&ĐT 2025
Tích hợp Auto Cardinal Orientation Rectifier (0°, 90°, 180°, 270°):
- Tự động nhận diện hướng chụp (ngang, dọc, lộn ngược) dựa trên đặc tính
  hình học bất đối xứng của 10 mốc chuẩn OMR hoặc 4 mốc góc.
- Xoay ảnh về đúng chiều chuẩn (0°) trước khi tiến hành nắn phẳng phối cảnh.
- Cấu hình an toàn luồng Console stdout chống lỗi charmap UnicodeEncodeError trên Windows .exe.
"""
from itertools import combinations
import os
from pathlib import Path
import sys
from typing import List, Optional, Tuple
import cv2
import numpy as np

# ==============================================================================
# BẢO VỆ LUỒNG XUẤT STDOUT CHỐNG LỖI CHARMAP TRÊN WINDOWS EXE ĐÓNG GÓI
# ==============================================================================
if sys.platform == "win32":
    try:
        if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

CANONICAL_WIDTH = 1769
CANONICAL_HEIGHT = 2526

# Tọa độ 5 cặp mốc chuẩn trên phôi Master (1769 x 2526)
TPL_LEFT_5 = np.array([
    [56.7, 45.9],      # M0: Góc trên trái
    [58.9, 819.2],     # M1: Đầu Phần I
    [58.9, 1371.1],    # M2: Đầu Phần II
    [55.6, 1723.7],    # M3: Đầu Phần III
    [55.6, 2449.0],    # M4: Góc dưới trái
], dtype=np.float32)

TPL_RIGHT_5 = np.array([
    [1720.9, 44.8],    # M0: Góc trên phải
    [1720.9, 819.2],   # M1: Đầu Phần I
    [1721.5, 1371.1],  # M2: Đầu Phần II
    [1721.5, 1723.7],  # M3: Đầu Phần III
    [1721.5, 2449.0],  # M4: Góc dưới phải
], dtype=np.float32)

# Tỷ lệ khoảng cách bất đối xứng chuẩn theo trục dọc
EXPECTED_Y_RATIOS = (TPL_LEFT_5[:, 1] - TPL_LEFT_5[0, 1]) / (TPL_LEFT_5[4, 1] - TPL_LEFT_5[0, 1])


def rotate_cardinal(image: np.ndarray, angle: int) -> np.ndarray:
    """Xoay ma trận ảnh chính xác theo các góc vuông (không nội suy méo góc)."""
    if angle == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    elif angle == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    elif angle == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image


def detect_fiducial_markers(gray: np.ndarray) -> Tuple[List[Tuple[float, ...]], List[Tuple[float, ...]], List[Tuple[float, float]]]:
    """Quét tìm các mốc vuông đen dọc 2 biên giấy với bộ lọc hình học nghiêm ngặt."""
    h, w = gray.shape
    expected_side = max(9, int(round(0.0183 * w)))

    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    block_size = max(15, (expected_side * 3) | 1)
    thresh = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block_size, 7)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_side = expected_side * 0.55
    max_side = expected_side * 1.85

    left_cands, right_cands, all_cands = [], [], []
    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        if min_side <= cw <= max_side and min_side <= ch <= max_side:
            aspect = cw / float(ch)
            area = cv2.contourArea(c)
            extent = area / float(cw * ch)
            if 0.65 <= aspect <= 1.50 and extent > 0.52:
                cx = x + cw / 2.0
                cy = y + ch / 2.0
                all_cands.append((cx, cy))
                if cx < w * 0.18:
                    left_cands.append((cx, cy, float(cw), float(ch)))
                elif cx > w * 0.82:
                    right_cands.append((cx, cy, float(cw), float(ch)))

    left_cands.sort(key=lambda item: item[1])
    right_cands.sort(key=lambda item: item[1])
    return left_cands, right_cands, all_cands


def select_best_5(cands: List[Tuple[float, ...]], min_span: float) -> Optional[np.ndarray]:
    """Khớp tổ hợp 5 mốc theo tỷ lệ khoảng cách bất đối xứng chuẩn."""
    if len(cands) < 5:
        return None
    best_pts = None
    best_score = float("inf")

    for comb in combinations(range(len(cands)), 5):
        pts = [cands[i] for i in comb]
        xs = np.array([p[0] for p in pts], dtype=np.float32)
        ys = np.array([p[1] for p in pts], dtype=np.float32)

        span_y = ys[-1] - ys[0]
        if span_y < min_span:
            continue

        ratios = (ys - ys[0]) / span_y
        ratio_err = float(np.max(np.abs(ratios - EXPECTED_Y_RATIOS)))
        if ratio_err > 0.048:
            continue

        poly = np.polyfit(ys, xs, 1)
        x_pred = np.polyval(poly, ys)
        x_err = float(np.max(np.abs(xs - x_pred)))

        score = ratio_err * 1000.0 + x_err * 2.0
        if score < best_score:
            best_score = score
            best_pts = np.array([[p[0], p[1]] for p in pts], dtype=np.float32)

    return best_pts


def find_4_corner_markers(all_cands: List[Tuple[float, float]], w: int, h: int) -> Optional[np.ndarray]:
    """Định vị 4 mốc góc OMR ngoài cùng (TL, TR, BR, BL)."""
    if len(all_cands) < 4:
        return None

    pts = np.array(all_cands, dtype=np.float32)
    z_tl = [p for p in pts if p[0] < w * 0.28 and p[1] < h * 0.28]
    z_tr = [p for p in pts if p[0] > w * 0.72 and p[1] < h * 0.28]
    z_br = [p for p in pts if p[0] > w * 0.72 and p[1] > h * 0.72]
    z_bl = [p for p in pts if p[0] < w * 0.28 and p[1] > h * 0.72]

    if z_tl and z_tr and z_br and z_bl:
        tl = min(z_tl, key=lambda p: p[0] ** 2 + p[1] ** 2)
        tr = min(z_tr, key=lambda p: (w - p[0]) ** 2 + p[1] ** 2)
        br = min(z_br, key=lambda p: (w - p[0]) ** 2 + (h - p[1]) ** 2)
        bl = min(z_bl, key=lambda p: p[0] ** 2 + (h - p[1]) ** 2)
        return np.array([tl, tr, br, bl], dtype=np.float32)

    return None


def auto_orient_sheet(image_bgr: np.ndarray) -> np.ndarray:
    """
    THUẬT TOÁN TỰ ĐỘNG PHÁT HIỆN HƯỚNG VÀ XOAY ĐÚNG CHIỀU GIẤY (0°, 90°, 180°, 270°)
    Sử dụng định dạng log an toàn tuyệt đối với Windows .exe.
    """
    raw_h, raw_w = image_bgr.shape[:2]

    if raw_w > raw_h:
        test_angles = [90, 270, 0, 180]
    else:
        test_angles = [0, 180, 90, 270]

    # --- TẦNG 1: QUÉT HƯỚNG BẰNG 10 MỐC CHUẨN ---
    for angle in test_angles:
        rotated = rotate_cardinal(image_bgr, angle)
        cur_gray = cv2.cvtColor(rotated, cv2.COLOR_BGR2GRAY)
        cur_h, cur_w = cur_gray.shape

        lc, rc, _ = detect_fiducial_markers(cur_gray)
        src_left = select_best_5(lc, min_span=cur_h * 0.65)
        src_right = select_best_5(rc, min_span=cur_h * 0.65)

        if src_left is not None and src_right is not None:
            if angle != 0:
                print(f"[OK] Tu dong phat hien anh xoay {angle} do -> Da xoay ve chuan dung (0 do).")
            return rotated

    # --- TẦNG 2: DỰ PHÒNG KHI THIẾU MỐC GIỮA (4 GÓC OMR) ---
    for angle in test_angles:
        rotated = rotate_cardinal(image_bgr, angle)
        cur_gray = cv2.cvtColor(rotated, cv2.COLOR_BGR2GRAY)
        cur_h, cur_w = cur_gray.shape

        _, _, all_cands = detect_fiducial_markers(cur_gray)
        corners = find_4_corner_markers(all_cands, cur_w, cur_h)

        if corners is not None:
            tl, tr, br, bl = corners
            dx = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2.0
            dy = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2.0
            aspect = dy / (dx + 1e-6)

            if aspect >= 1.15:
                top_ink = np.sum(cur_gray[: int(cur_h * 0.25), :] < 100)
                bottom_ink = np.sum(cur_gray[int(cur_h * 0.75) :, :] < 100)
                if top_ink >= bottom_ink * 0.8:
                    if angle != 0:
                        print(f"[OK] Dinh vi 4 goc: Phat hien xoay {angle} do -> Da xoay ve chuan dung (0 do).")
                    return rotated

    return image_bgr


def align_sheet_4band(image_path: Path, output_path: Path) -> np.ndarray:
    """Nắn phẳng phối cảnh đa tầng sau khi đã tự động chuẩn hóa chiều đứng."""
    raw_bgr = cv2.imread(str(image_path))
    if raw_bgr is None:
        raise FileNotFoundError(f"Không tìm thấy file: {image_path}")

    # 1. Tự động xoay về chiều đứng (0°)
    image_bgr = auto_orient_sheet(raw_bgr)

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    lc, rc, all_cands = detect_fiducial_markers(gray)
    src_left = select_best_5(lc, min_span=h * 0.65)
    src_right = select_best_5(rc, min_span=h * 0.65)

    out_w, out_h = CANONICAL_WIDTH, CANONICAL_HEIGHT

    # TẦNG 1: NẮN 4 DẢI KHI ĐỦ 10 MỐC (BẢN SCAN PHẲNG)
    if src_left is not None and src_right is not None:
        canvas = np.zeros((out_h, out_w, 3), dtype=np.uint8)
        band_bounds = [
            (0, int(round(TPL_LEFT_5[1, 1]))),
            (int(round(TPL_LEFT_5[1, 1])), int(round(TPL_LEFT_5[2, 1]))),
            (int(round(TPL_LEFT_5[2, 1])), int(round(TPL_LEFT_5[3, 1]))),
            (int(round(TPL_LEFT_5[3, 1])), out_h),
        ]
        for b_idx in range(4):
            src_quad = np.array([
                src_left[b_idx], src_right[b_idx],
                src_right[b_idx + 1], src_left[b_idx + 1]
            ], dtype=np.float32)
            dst_quad = np.array([
                TPL_LEFT_5[b_idx], TPL_RIGHT_5[b_idx],
                TPL_RIGHT_5[b_idx + 1], TPL_LEFT_5[b_idx + 1]
            ], dtype=np.float32)
            H = cv2.getPerspectiveTransform(src_quad, dst_quad)
            warped_band = cv2.warpPerspective(image_bgr, H, (out_w, out_h), flags=cv2.INTER_CUBIC)
            y0, y1 = band_bounds[b_idx]
            canvas[y0:y1, :] = warped_band[y0:y1, :]

        output_path.parent.mkdir(exist_ok=True, parents=True)
        cv2.imwrite(str(output_path), canvas)
        return canvas

    # TẦNG 2: NẮN 4 MỐC GÓC OMR (BẢN CHỤP CAMERA DI ĐỘNG)
    corners_4 = find_4_corner_markers(all_cands, w, h)
    if corners_4 is not None:
        tpl_corners = np.array([
            TPL_LEFT_5[0], TPL_RIGHT_5[0],
            TPL_RIGHT_5[4], TPL_LEFT_5[4]
        ], dtype=np.float32)
        H_corners = cv2.getPerspectiveTransform(corners_4, tpl_corners)
        canvas = cv2.warpPerspective(image_bgr, H_corners, (out_w, out_h), flags=cv2.INTER_CUBIC)
        output_path.parent.mkdir(exist_ok=True, parents=True)
        cv2.imwrite(str(output_path), canvas)
        return canvas

    raise RuntimeError(
        "ALIGNMENT_FAILED: Không nhận diện được đủ mốc định vị của bài thi (không đủ 10 mốc và không đủ 4 mốc góc). "
        "Ảnh có thể bị mất góc, quá mờ hoặc bóng che khuất. Vui lòng chụp lại thẳng góc và đủ sáng."
    )