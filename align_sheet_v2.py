# align_sheet_v2.py
# -*- coding: utf-8 -*-
"""
MODULE NẮN PHẲNG PHỐI CẢNH ĐA TẦNG OMR CHUẨN BỘ GD&ĐT 2025 (PHIÊN BẢN CAMERA DI ĐỘNG CHUYÊN NGHIỆP)
Tích hợp:
1. Bộ lọc mốc vuông tự thích ứng (Adaptive 4-Corner OMR Quad Finder) cho điện thoại chụp nghiêng, lệch góc.
2. Tự động xoay 4 hướng (0°, 90°, 180°, 270°) dựa trên đặc tính hình học đối xứng và phân bố mực.
3. Tầng dự phòng nhận diện viền giấy A4 (Document Boundary Contour Fallback).
4. Khắc phục triệt để lỗi charmap UnicodeEncodeError trên Windows .exe.
"""
from itertools import combinations
import os
from pathlib import Path
import sys
from typing import List, Optional, Tuple
import cv2
import numpy as np

# Bảo vệ luồng Console stdout chống lỗi charmap trên Windows .exe
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
    """Xoay ma trận ảnh chính xác theo các góc vuông."""
    if angle == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    elif angle == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    elif angle == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return image


def detect_fiducial_squares(gray: np.ndarray) -> List[Tuple[float, float, float, float]]:
    """
    Quét tìm các ứng viên mốc vuông đen trên toàn trang, kể cả khi chụp camera có nền bàn.
    Sử dụng cv2.RETR_LIST để không bị mất các mốc nằm bên trong viền giấy.
    """
    h, w = gray.shape
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    
    # Kết hợp hai ngưỡng thích ứng để bắt mốc trong mọi điều kiện ánh sáng
    thresh1 = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 7)
    thresh2 = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 6)
    thresh = cv2.bitwise_or(thresh1, thresh2)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    cnts, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    cands = []
    min_dim = min(h, w)
    min_side = max(6, int(round(min_dim * 0.005)))
    max_side = max(50, int(round(min_dim * 0.08)))

    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        if cw < min_side or ch < min_side or cw > max_side or ch > max_side:
            continue
        aspect = cw / float(ch)
        if 0.65 <= aspect <= 1.55:
            area = cv2.contourArea(c)
            extent = area / float(cw * ch)
            if extent > 0.45:
                cands.append((float(x + cw / 2.0), float(y + ch / 2.0), float(cw), float(ch)))
    return cands


def find_adaptive_4_corners(cands: List[Tuple[float, ...]], w: int, h: int) -> Optional[np.ndarray]:
    """
    Định vị 4 mốc góc OMR (TL, TR, BR, BL) thích ứng 100% với ảnh chụp điện thoại.
    Không phụ thuộc vào vị trí đặt giấy trên bàn hay khoảng cách cầm máy.
    """
    if len(cands) < 4:
        return None

    pts = np.array([[c[0], c[1]] for c in cands], dtype=np.float32)
    hull_idx = cv2.convexHull(pts, returnPoints=False)
    hull = pts[hull_idx.flatten()]
    if len(hull) < 4:
        return None

    # Tối ưu tốc độ: giữ lại tối đa 18 điểm cực trị ngoài cùng
    if len(hull) > 18:
        ctr = np.mean(hull, axis=0)
        dists = np.linalg.norm(hull - ctr, axis=1)
        hull = hull[np.argsort(dists)[-18:]]

    best_quad = None
    best_score = -1.0

    for comb in combinations(range(len(hull)), 4):
        quad = hull[list(comb)]
        ctr = np.mean(quad, axis=0)
        angles = np.arctan2(quad[:, 1] - ctr[1], quad[:, 0] - ctr[0])
        quad = quad[np.argsort(angles)]

        # Sắp xếp theo thứ tự: TL, TR, BR, BL
        tl_idx = min(range(4), key=lambda i: quad[i][0]**2 + quad[i][1]**2)
        quad = np.roll(quad, -tl_idx, axis=0)
        p_tl, p_tr, p_br, p_bl = quad

        # Kiểm tra tính lồi và chiều không gian
        if p_tr[0] <= p_tl[0] or p_br[1] <= p_tr[1] or p_bl[1] <= p_tl[1] or p_br[0] <= p_bl[0]:
            continue

        w_top = np.linalg.norm(p_tr - p_tl)
        w_bot = np.linalg.norm(p_br - p_bl)
        h_l = np.linalg.norm(p_bl - p_tl)
        h_r = np.linalg.norm(p_br - p_tr)

        avg_w = (w_top + w_bot) / 2.0
        avg_h = (h_l + h_r) / 2.0
        if avg_w < 100 or avg_h < 150:
            continue

        ratio = avg_h / avg_w
        # Tỷ lệ lý tưởng giữa chiều cao và chiều rộng của 4 mốc OMR là ~1.444 (cho phép góc nghiêng điện thoại 1.10 - 1.80)
        if not (1.10 <= ratio <= 1.80):
            continue
        if abs(w_top - w_bot) / avg_w > 0.38 or abs(h_l - h_r) / avg_h > 0.38:
            continue

        area = avg_w * avg_h
        score = area / (1.0 + abs(ratio - 1.444) * 6.0)
        if score > best_score:
            best_score = score
            best_quad = np.array([p_tl, p_tr, p_br, p_bl], dtype=np.float32)

    return best_quad


def _eval_orientation_asymmetry(gray: np.ndarray, corners: np.ndarray) -> float:
    """
    Đo lường độ bất đối xứng của các cặp mốc chuẩn dọc trục Y (chuẩn Bộ GD&ĐT 2025).
    Đặc tính bất biến:
    - M2 (Đầu Phần II) tại Y = 1371.1 (54.3% chiều cao) trên cả 2 lề trái và phải.
    - M1 (Đầu Phần I) tại Y = 819.2 (32.4%).
    - M3 (Đầu Phần III) tại Y = 1723.7 (68.2%).
    Nếu ảnh đúng chiều (0°), toạ độ M1, M2, M3 ánh xạ vào đúng các ô vuông đen.
    Nếu ảnh bị xoay ngược 180°, M2 rơi vào khoảng giấy trắng tinh (Y = 1154.9).
    """
    tpl_corners = np.array([
        TPL_LEFT_5[0], TPL_RIGHT_5[0],
        TPL_RIGHT_5[4], TPL_LEFT_5[4]
    ], dtype=np.float32)

    H = cv2.getPerspectiveTransform(tpl_corners, corners)
    test_pts = np.array([
        TPL_LEFT_5[1],   # M1 Trái
        TPL_RIGHT_5[1],  # M1 Phải
        TPL_LEFT_5[2],   # M2 Trái (Khóa bất đối xứng chính)
        TPL_RIGHT_5[2],  # M2 Phải (Khóa bất đối xứng chính)
        TPL_LEFT_5[3],   # M3 Trái
        TPL_RIGHT_5[3],  # M3 Phải
    ], dtype=np.float32).reshape(1, -1, 2)

    mapped_pts = cv2.perspectiveTransform(test_pts, H)[0]
    h, w = gray.shape
    score = 0.0
    r = max(5, int(round(min(h, w) * 0.012)))

    for i, (mx, my) in enumerate(mapped_pts):
        ix, iy = int(round(mx)), int(round(my))
        if r <= ix < w - r and r <= iy < h - r:
            patch = gray[iy - r : iy + r + 1, ix - r : ix + r + 1]
            if np.min(patch) < 105 and (patch < 115).sum() > (r * r * 0.35):
                weight = 3.0 if (i == 2 or i == 3) else 1.0  # M2 mang trọng số quyết định
                score += weight
    return score


def auto_orient_sheet_robust(image_bgr: np.ndarray) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """
    Tự động phát hiện hướng chụp và xoay đúng chiều đứng (0°).
    Kiểm tra cả 4 góc vuông (0°, 90°, 180°, 270°) và chọn góc có độ tương thích
    mốc bất đối xứng Y cao nhất.
    """
    raw_h, raw_w = image_bgr.shape[:2]
    # Ưu tiên góc dọc tự nhiên trước, sau đó là góc ngang
    test_angles = [0, 180, 90, 270] if raw_h >= raw_w else [90, 270, 0, 180]

    valid_candidates = []
    for angle in test_angles:
        rotated = rotate_cardinal(image_bgr, angle)
        cur_gray = cv2.cvtColor(rotated, cv2.COLOR_BGR2GRAY)
        cur_h, cur_w = cur_gray.shape
        cands = detect_fiducial_squares(cur_gray)
        corners = find_adaptive_4_corners(cands, cur_w, cur_h)

        if corners is not None:
            score = _eval_orientation_asymmetry(cur_gray, corners)
            valid_candidates.append((score, angle, rotated, corners))

    if valid_candidates:
        # Sắp xếp theo điểm bất đối xứng mốc giảm dần
        valid_candidates.sort(key=lambda c: c[0], reverse=True)
        best_score, best_angle, best_rot, best_corners = valid_candidates[0]

        if best_angle != 0:
            print(f"[OK] Phát hiện ảnh xoay {best_angle}° (Điểm mốc M1-M3: {best_score:.1f}) -> Đã xoay về đúng chiều đứng (0°).")
        return best_rot, best_corners

    return image_bgr, None

def detect_fiducial_markers_legacy(gray: np.ndarray) -> Tuple[List[Tuple[float, ...]], List[Tuple[float, ...]], List[Tuple[float, float]]]:
    """Hàm quét mốc phẳng nguyên bản (dành cho bản scan máy tính)."""
    h, w = gray.shape
    expected_side = max(9, int(round(0.0183 * w)))

    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    block_size = max(15, (expected_side * 3) | 1)
    thresh = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block_size, 7)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    cnts, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    min_side = expected_side * 0.50
    max_side = expected_side * 1.95

    left_cands, right_cands, all_cands = [], [], []
    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        if min_side <= cw <= max_side and min_side <= ch <= max_side:
            aspect = cw / float(ch)
            area = cv2.contourArea(c)
            extent = area / float(cw * ch)
            if 0.60 <= aspect <= 1.55 and extent > 0.45:
                cx = x + cw / 2.0
                cy = y + ch / 2.0
                all_cands.append((cx, cy))
                if cx < w * 0.30:
                    left_cands.append((cx, cy, float(cw), float(ch)))
                elif cx > w * 0.70:
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
        if ratio_err > 0.052:
            continue

        poly = np.polyfit(ys, xs, 1)
        x_pred = np.polyval(poly, ys)
        x_err = float(np.max(np.abs(xs - x_pred)))

        score = ratio_err * 1000.0 + x_err * 2.0
        if score < best_score:
            best_score = score
            best_pts = np.array([[p[0], p[1]] for p in pts], dtype=np.float32)

    return best_pts


def detect_a4_paper_contour(gray: np.ndarray) -> Optional[np.ndarray]:
    """Tầng dự phòng 3: Nhận diện 4 góc của tờ giấy A4 trên nền bàn."""
    h, w = gray.shape
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    cnts, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = sorted(cnts, key=cv2.contourArea, reverse=True)

    min_area = w * h * 0.15
    for c in cnts[:5]:
        if cv2.contourArea(c) < min_area:
            break
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            pts = approx.reshape(4, 2).astype(np.float32)
            ctr = np.mean(pts, axis=0)
            angles = np.arctan2(pts[:, 1] - ctr[1], pts[:, 0] - ctr[0])
            pts = pts[np.argsort(angles)]
            tl_idx = min(range(4), key=lambda i: pts[i][0]**2 + pts[i][1]**2)
            pts = np.roll(pts, -tl_idx, axis=0)
            return pts
    return None


def align_sheet_4band(image_path: Path, output_path: Path) -> np.ndarray:
    """Nắn phẳng phối cảnh đa tầng sau khi đã tự động chuẩn hóa chiều đứng."""
    raw_bgr = cv2.imread(str(image_path))
    if raw_bgr is None:
        raise FileNotFoundError(f"Không tìm thấy file: {image_path}")

    out_w, out_h = CANONICAL_WIDTH, CANONICAL_HEIGHT
    tpl_corners = np.array([
        TPL_LEFT_5[0], TPL_RIGHT_5[0],
        TPL_RIGHT_5[4], TPL_LEFT_5[4]
    ], dtype=np.float32)

    # 1. Tự động xoay và tìm 4 mốc góc OMR thích ứng với camera di động
    image_bgr, corners_4 = auto_orient_sheet_robust(raw_bgr)
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # TẦNG 1: NẮN 4 DẢI KHI ĐỦ 10 MỐC (DÀNH CHO BẢN SCAN PHẲNG)
    lc, rc, _ = detect_fiducial_markers_legacy(gray)
    if len(lc) <= 15 and len(rc) <= 15:
        src_left = select_best_5(lc, min_span=h * 0.50)
        src_right = select_best_5(rc, min_span=h * 0.50)
    else:
        src_left, src_right = None, None

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

    # TẦNG 2: NẮN 4 MỐC GÓC OMR THÍCH ỨNG (DÀNH CHO CAMERA DI ĐỘNG CẦM TAY)
    if corners_4 is not None:
        H_corners = cv2.getPerspectiveTransform(corners_4, tpl_corners)
        canvas = cv2.warpPerspective(image_bgr, H_corners, (out_w, out_h), flags=cv2.INTER_CUBIC)
        output_path.parent.mkdir(exist_ok=True, parents=True)
        cv2.imwrite(str(output_path), canvas)
        return canvas

    # TẦNG 3: DỰ PHÒNG VIỀN GIẤY A4 TRÊN NỀN BÀN
    paper_corners = detect_a4_paper_contour(gray)
    if paper_corners is not None:
        dst_a4 = np.array([
            [0, 0], [out_w, 0],
            [out_w, out_h], [0, out_h]
        ], dtype=np.float32)
        H_paper = cv2.getPerspectiveTransform(paper_corners, dst_a4)
        canvas_a4 = cv2.warpPerspective(image_bgr, H_paper, (out_w, out_h), flags=cv2.INTER_CUBIC)
        output_path.parent.mkdir(exist_ok=True, parents=True)
        cv2.imwrite(str(output_path), canvas_a4)
        return canvas_a4

    raise RuntimeError(
        "ALIGNMENT_FAILED: Không nhận diện được đủ 4 mốc định vị của bài thi. "
        "Hãy giữ điện thoại hướng thẳng vào bài thi và chụp đủ 4 góc phiếu."
    )
