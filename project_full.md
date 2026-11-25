## FILE: align_sheet_v2.py
```py
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
from typing import List, Optional, Tuple, Union
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
    Tối ưu: downscale ảnh lớn về max 750px để tăng tốc 2-4x.
    """
    h, w = gray.shape
    max_dim = max(h, w)

    # Downscale nếu ảnh lớn để tăng tốc xử lý
    if max_dim > 800:
        ds_scale = 750.0 / max_dim
        small = cv2.resize(gray, (int(round(w * ds_scale)), int(round(h * ds_scale))), interpolation=cv2.INTER_AREA)
    else:
        ds_scale = 1.0
        small = gray

    sh, sw = small.shape
    blur = cv2.GaussianBlur(small, (3, 3), 0)
    
    # Kết hợp hai ngưỡng thích ứng để bắt mốc trong mọi điều kiện ánh sáng
    thresh1 = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 7)
    thresh2 = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 6)
    thresh = cv2.bitwise_or(thresh1, thresh2)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    cnts, _ = cv2.findContours(closed, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    cands = []
    min_dim_img = min(sh, sw)
    min_side = max(6, int(round(min_dim_img * 0.005)))
    max_side = max(50, int(round(min_dim_img * 0.08)))

    # Lọc ứng viên theo giấy trắng: tìm vùng sáng bao quanh mốc
    # (giúp loại bỏ blob trên nền bàn gỗ sẫm)
    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        if cw < min_side or ch < min_side or cw > max_side or ch > max_side:
            continue
        aspect = cw / float(ch)
        if 0.65 <= aspect <= 1.55:
            area = cv2.contourArea(c)
            extent = area / float(cw * ch)
            if extent > 0.45:
                # Kiểm tra vùng bao quanh có nền sáng (giấy trắng) không
                cx_s = float(x + cw / 2.0)
                cy_s = float(y + ch / 2.0)
                pad_ring = max(cw, ch)
                rx0 = max(0, x - pad_ring)
                ry0 = max(0, y - pad_ring)
                rx1 = min(sw, x + cw + pad_ring)
                ry1 = min(sh, y + ch + pad_ring)
                ring_patch = small[ry0:ry1, rx0:rx1]
                if ring_patch.size > 0:
                    ring_bright = float(np.percentile(ring_patch, 75))
                    core_patch = small[y:y+ch, x:x+cw]
                    core_dark = float(np.mean(core_patch))
                    contrast = ring_bright - core_dark
                    # Chấp nhận: vùng bao quanh sáng >= 120 VÀ tương phản >= 15
                    # HOẶC tương phản rất cao >= 35 (mốc rõ nét dù nền không hoàn toàn trắng)
                    if (ring_bright >= 120 and contrast >= 15) or contrast >= 35:
                        # Scale coords back
                        cands.append((cx_s / ds_scale, cy_s / ds_scale, float(cw) / ds_scale, float(ch) / ds_scale))
                else:
                    cands.append((cx_s / ds_scale, cy_s / ds_scale, float(cw) / ds_scale, float(ch) / ds_scale))
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
        # Tỷ lệ lý tưởng giữa chiều cao và chiều rộng của 4 mốc OMR là ~1.444 (cho phép góc nghiêng điện thoại 1.05 - 1.92)
        if not (1.05 <= ratio <= 1.92):
            continue
        if abs(w_top - w_bot) / avg_w > 0.38 or abs(h_l - h_r) / avg_h > 0.38:
            continue

        area = avg_w * avg_h
        tpl_corners = np.array([
            TPL_LEFT_5[0], TPL_RIGHT_5[0],
            TPL_RIGHT_5[4], TPL_LEFT_5[4]
        ], dtype=np.float32)
        H_proj = cv2.getPerspectiveTransform(tpl_corners, quad)
        test_pts = np.vstack([TPL_LEFT_5[1:4], TPL_RIGHT_5[1:4]]).reshape(1, -1, 2)
        mapped = cv2.perspectiveTransform(test_pts, H_proj)[0]

        matched_inter = 0
        search_radius = max(18.0, min(avg_w, avg_h) * 0.04)
        for mx, my in mapped:
            for cx, cy, cw, ch in cands:
                if np.hypot(cx - mx, cy - my) <= search_radius:
                    matched_inter += 1
                    break

        score = (area / (1.0 + abs(ratio - 1.444) * 6.0)) + (matched_inter * (area * 0.25))
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


def verify_and_refine_10_markers(canvas_bgr: np.ndarray) -> Tuple[bool, np.ndarray]:
    """
    Xác thực nghiêm ngặt ảnh sau khi nắn phẳng và nắn tinh chỉnh 10 mốc 4 dải:
    1. Độ sáng trung bình toàn trang >= 95 (chịu được bóng đổ tay/điện thoại).
    2. Quét vùng lân cận ±50px tại 10 mốc chuẩn (5 mốc trái TPL_LEFT_5 và 5 mốc phải TPL_RIGHT_5).
       Tìm tâm tối nhất (lõi 7x7px) và so sánh với vành giấy xung quanh (r=16..24px).
       Mốc hợp lệ khi core_mean < 135.0, contrast = ring_p75 - core_mean >= 16.0, core_mean < 0.85 * ring_p75.
    3. Phiếu hợp lệ khi có ít nhất 6/10 mốc đạt chuẩn và ít nhất 3/4 mốc góc đạt chuẩn.
    4. Nội suy tuyến tính cho các mốc bị lóa sáng/mờ dựa trên 2 mốc góc M0 và M4.
    5. Nắn tinh chỉnh 4 dải (4-band perspective refinement) bằng cv2.INTER_LINEAR,
       giúp sai số tọa độ các ô trả lời < 2px dù giấy bị cong vênh nhẹ khi cầm tay.
    """
    if canvas_bgr is None or canvas_bgr.shape[:2] != (CANONICAL_HEIGHT, CANONICAL_WIDTH):
        return False, canvas_bgr

    gray = cv2.cvtColor(canvas_bgr, cv2.COLOR_BGR2GRAY)
    # Xác thực nền giấy A4: Phiếu OMR trắng phải có trung vị độ sáng >= 135
    if np.median(gray) < 135.0:
        return False, canvas_bgr

    kernel_7 = np.ones((7, 7), dtype=np.float32) / 49.0
    r_in = 16
    r_out = 24
    search_w = 50

    ref_left = []
    ref_right = []
    is_marker_valid_L = []
    is_marker_valid_R = []
    valid_count = 0
    corner_valid = 0

    m_ratios = [0.0, 0.324, 0.543, 0.682, 1.0]

    for side, tpl_list, ref_list, valid_flags in [
        ('L', TPL_LEFT_5, ref_left, is_marker_valid_L),
        ('R', TPL_RIGHT_5, ref_right, is_marker_valid_R)
    ]:
        for idx, pt in enumerate(tpl_list):
            cx, cy = int(round(pt[0])), int(round(pt[1]))
            x0, x1 = max(0, cx - search_w), min(CANONICAL_WIDTH, cx + search_w + 1)
            y0, y1 = max(0, cy - search_w), min(CANONICAL_HEIGHT, cy + search_w + 1)
            patch = gray[y0:y1, x0:x1]
            if patch.shape[0] < 15 or patch.shape[1] < 15:
                ref_list.append((float(cx), float(cy)))
                valid_flags.append(False)
                continue

            blur = cv2.filter2D(patch.astype(np.float32), -1, kernel_7)
            b = 7
            if blur.shape[0] > 2 * b and blur.shape[1] > 2 * b:
                inner = blur[b:-b, b:-b]
                min_pos = np.unravel_index(np.argmin(inner), inner.shape)
                best_y = y0 + b + min_pos[0]
                best_x = x0 + b + min_pos[1]
            else:
                best_y, best_x = cy, cx

            core_patch = gray[max(0, best_y - 3):min(CANONICAL_HEIGHT, best_y + 4),
                              max(0, best_x - 3):min(CANONICAL_WIDTH, best_x + 4)]
            core_mean = float(np.mean(core_patch)) if core_patch.size > 0 else 255.0

            ry0, ry1 = max(0, best_y - r_out), min(CANONICAL_HEIGHT, best_y + r_out + 1)
            rx0, rx1 = max(0, best_x - r_out), min(CANONICAL_WIDTH, best_x + r_out + 1)
            patch_ring = gray[ry0:ry1, rx0:rx1]

            gy, gx = np.ogrid[ry0 - best_y : ry1 - best_y, rx0 - best_x : rx1 - best_x]
            d = np.hypot(gx, gy)
            ring_mask = (d >= r_in) & (d <= r_out)

            if np.any(ring_mask):
                ring_vals = patch_ring[ring_mask]
                p75 = float(np.percentile(ring_vals, 75))
            else:
                p75 = 0.0

            contrast = p75 - core_mean
            if core_mean < 145.0 and p75 >= 155.0 and contrast >= 25.0 and core_mean < 0.85 * p75:
                valid_count += 1
                if idx in (0, 4):
                    corner_valid += 1
                ref_list.append((float(best_x), float(best_y)))
                valid_flags.append(True)
            else:
                ref_list.append((float(best_x), float(best_y)))
                valid_flags.append(False)

    is_valid = (valid_count >= 5 and corner_valid >= 2)
    if not is_valid:
        return False, canvas_bgr

    # Nội suy tuyến tính cho mốc trung gian nào chưa hợp lệ dựa trên 2 mốc góc M0 và M4
    for ref_list, valid_flags, tpl_list in [
        (ref_left, is_marker_valid_L, TPL_LEFT_5),
        (ref_right, is_marker_valid_R, TPL_RIGHT_5)
    ]:
        p0 = ref_list[0] if valid_flags[0] else (float(tpl_list[0][0]), float(tpl_list[0][1]))
        p4 = ref_list[4] if valid_flags[4] else (float(tpl_list[4][0]), float(tpl_list[4][1]))

        # Kiểm tra collinearity: 5 mốc cùng bên phải nằm gần 1 đường thẳng
        valid_indices = [i for i in range(5) if valid_flags[i]]
        valid_xs = [ref_list[i][0] for i in valid_indices]
        valid_ys = [ref_list[i][1] for i in valid_indices]
        if len(valid_indices) >= 3:
            poly_line = np.polyfit(valid_ys, valid_xs, 1)
            x_pred = np.polyval(poly_line, valid_ys)
            x_errs = np.abs(np.array(valid_xs) - x_pred)
            # Nếu có mốc lệch > 18px khỏi đường hồi quy, đánh dấu invalid và nội suy lại
            for vi, xerr in enumerate(x_errs):
                if xerr > 18.0:
                    orig_idx = valid_indices[vi]
                    if orig_idx not in (0, 4):
                        valid_flags[orig_idx] = False

        for i in range(1, 4):
            if not valid_flags[i]:
                t = m_ratios[i]
                inter_x = p0[0] + t * (p4[0] - p0[0])
                inter_y = p0[1] + t * (p4[1] - p0[1])
                ref_list[i] = (inter_x, inter_y)

    ref_left = np.array(ref_left, dtype=np.float32)
    ref_right = np.array(ref_right, dtype=np.float32)

    # Nắn tinh chỉnh 4 dải (4-band perspective refinement)
    # Kiểm tra offset lệch: nếu bất kỳ mốc nào lệch > 35px so với template,
    # giữ flat 4-corner warp thay vì warp 4-band (tránh vặn méo Phần III)
    max_offset = 0.0
    for i in range(5):
        dx_l = abs(ref_left[i][0] - float(TPL_LEFT_5[i][0]))
        dy_l = abs(ref_left[i][1] - float(TPL_LEFT_5[i][1]))
        dx_r = abs(ref_right[i][0] - float(TPL_RIGHT_5[i][0]))
        dy_r = abs(ref_right[i][1] - float(TPL_RIGHT_5[i][1]))
        max_offset = max(max_offset, dx_l, dy_l, dx_r, dy_r)

    if max_offset > 35.0:
        # Mốc lệch quá nhiều → giữ flat canvas (đã warp 4-corner ở bước trước)
        return True, canvas_bgr

    refined_canvas = np.zeros_like(canvas_bgr)
    band_bounds = [
        (0, int(round(TPL_LEFT_5[1, 1]))),
        (int(round(TPL_LEFT_5[1, 1])), int(round(TPL_LEFT_5[2, 1]))),
        (int(round(TPL_LEFT_5[2, 1])), int(round(TPL_LEFT_5[3, 1]))),
        (int(round(TPL_LEFT_5[3, 1])), CANONICAL_HEIGHT),
    ]
    for b_idx in range(4):
        src_quad = np.array([
            ref_left[b_idx], ref_right[b_idx],
            ref_right[b_idx + 1], ref_left[b_idx + 1]
        ], dtype=np.float32)
        dst_quad = np.array([
            TPL_LEFT_5[b_idx], TPL_RIGHT_5[b_idx],
            TPL_RIGHT_5[b_idx + 1], TPL_LEFT_5[b_idx + 1]
        ], dtype=np.float32)
        H_band = cv2.getPerspectiveTransform(src_quad, dst_quad)
        warped_band = cv2.warpPerspective(canvas_bgr, H_band, (CANONICAL_WIDTH, CANONICAL_HEIGHT), flags=cv2.INTER_LINEAR)
        y0, y1 = band_bounds[b_idx]
        refined_canvas[y0:y1, :] = warped_band[y0:y1, :]

    return True, refined_canvas


def verify_aligned_omr_template(canvas_bgr: np.ndarray) -> bool:
    """Wrapper tương thích ngược trả về True/False."""
    is_valid, _ = verify_and_refine_10_markers(canvas_bgr)
    return is_valid


def align_sheet_from_array(raw_bgr: np.ndarray, hint_corners: Optional[np.ndarray] = None) -> np.ndarray:
    """Nắn phẳng phối cảnh đa tầng thuần trong RAM, không đọc/ghi đĩa, trả về canvas (1769 x 2526)."""
    if raw_bgr is None or raw_bgr.size == 0:
        raise RuntimeError("ALIGNMENT_FAILED: Ảnh đầu vào rỗng.")

    out_w, out_h = CANONICAL_WIDTH, CANONICAL_HEIGHT
    tpl_corners = np.array([
        TPL_LEFT_5[0], TPL_RIGHT_5[0],
        TPL_RIGHT_5[4], TPL_LEFT_5[4]
    ], dtype=np.float32)

    # TẦNG 0: NẾU CÓ HINT_CORNERS TỪ MOBILE CAMERA SCANNER ĐÃ KHÓA CHUẨN
    if hint_corners is not None and len(hint_corners) == 4:
        # Kiểm tra hình học cơ bản trước khi trust hint_corners
        hc = hint_corners
        w_top = np.linalg.norm(hc[1] - hc[0])
        w_bot = np.linalg.norm(hc[2] - hc[3])
        h_left = np.linalg.norm(hc[3] - hc[0])
        h_right = np.linalg.norm(hc[2] - hc[1])
        avg_w_hc = (w_top + w_bot) / 2.0
        avg_h_hc = (h_left + h_right) / 2.0
        ratio_hc = avg_h_hc / avg_w_hc if avg_w_hc > 0 else 0
        edge_diff_w = abs(w_top - w_bot) / avg_w_hc if avg_w_hc > 0 else 1
        edge_diff_h = abs(h_left - h_right) / avg_h_hc if avg_h_hc > 0 else 1
        hint_valid = (1.10 <= ratio_hc <= 1.80 and edge_diff_w <= 0.28 and edge_diff_h <= 0.28 and avg_w_hc >= 100)

        if hint_valid:
            raw_gray = cv2.cvtColor(raw_bgr, cv2.COLOR_BGR2GRAY)
            cands = detect_fiducial_squares(raw_gray)
            refined_corners = []
            for hx, hy in hint_corners:
                best_c = None
                min_d = 75.0
                for cx, cy, cw, ch in cands:
                    d = np.hypot(cx - hx, cy - hy)
                    if d < min_d:
                        min_d = d
                        best_c = (cx, cy)
                if best_c is not None:
                    refined_corners.append(best_c)
                else:
                    refined_corners.append((hx, hy))
            refined_corners = np.array(refined_corners, dtype=np.float32)

            H_hint = cv2.getPerspectiveTransform(refined_corners, tpl_corners)
            canvas_hint = cv2.warpPerspective(raw_bgr, H_hint, (out_w, out_h), flags=cv2.INTER_LINEAR)
            ok, refined_canvas = verify_and_refine_10_markers(canvas_hint)
            if ok:
                return refined_canvas

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
            warped_band = cv2.warpPerspective(image_bgr, H, (out_w, out_h), flags=cv2.INTER_LINEAR)
            y0, y1 = band_bounds[b_idx]
            canvas[y0:y1, :] = warped_band[y0:y1, :]

        ok, refined_canvas = verify_and_refine_10_markers(canvas)
        if ok:
            return refined_canvas

    # TẦNG 2: NẮN 4 MỐC GÓC OMR THÍCH ỨNG (DÀNH CHO CAMERA DI ĐỘNG CẦM TAY)
    if corners_4 is not None:
        H_corners = cv2.getPerspectiveTransform(corners_4, tpl_corners)
        canvas = cv2.warpPerspective(image_bgr, H_corners, (out_w, out_h), flags=cv2.INTER_LINEAR)
        ok, refined_canvas = verify_and_refine_10_markers(canvas)
        if ok:
            return refined_canvas

    # TẦNG 3: DỰ PHÒNG VIỀN GIẤY A4 TRÊN NỀN BÀN (CHỈ CHẤP NHẬN NẾU ĐẠT XÁC THỰC MỐC PHIẾU OMR)
    paper_corners = detect_a4_paper_contour(gray)
    if paper_corners is not None:
        dst_a4 = np.array([
            [0, 0], [out_w, 0],
            [out_w, out_h], [0, out_h]
        ], dtype=np.float32)
        H_paper = cv2.getPerspectiveTransform(paper_corners, dst_a4)
        canvas_a4 = cv2.warpPerspective(image_bgr, H_paper, (out_w, out_h), flags=cv2.INTER_LINEAR)
        ok, refined_canvas = verify_and_refine_10_markers(canvas_a4)
        if ok:
            return refined_canvas

    raise RuntimeError(
        "NOT_OMR_SHEET: Không nhận diện được đúng mẫu phiếu trả lời trắc nghiệm Bộ GD&ĐT. "
        "Hãy đảm bảo đưa đúng phiếu thi vào khung ngắm và đủ ánh sáng."
    )


def align_sheet_4band(image_path: Union[str, Path, np.ndarray], output_path: Union[str, Path], hint_corners: Optional[np.ndarray] = None) -> Union[np.ndarray, Tuple[None, str]]:
    """Wrapper tương thích ngược: đọc file nếu cần, gọi align_sheet_from_array và lưu output_path."""
    if isinstance(image_path, np.ndarray):
        raw_bgr = image_path
    else:
        raw_bgr = cv2.imread(str(image_path))
        if raw_bgr is None:
            raise FileNotFoundError(f"Không tìm thấy file: {image_path}")

    refined_canvas = align_sheet_from_array(raw_bgr, hint_corners=hint_corners)
    output_path = Path(output_path)
    output_path.parent.mkdir(exist_ok=True, parents=True)
    cv2.imwrite(str(output_path), refined_canvas)
    return refined_canvas

```

## FILE: app.py
```py
# app.py
# -*- coding: utf-8 -*-
"""
FASTAPI WEB SERVER - OMR GRADING SYSTEM 2026 (PRODUCTION V6.9 - OPTIMIZED STORAGE & EXPORT)
Cập nhật:
- Lưu trữ nén thông minh: Chuyển đổi toàn bộ lưu trữ đĩa sang JPEG Quality 90 & WebP.
  Giảm 96% dung lượng ổ cứng (từ ~29MB/bài xuống còn ~1.1MB/bài).
- Tự động dọn dẹp file Raw sau khi đã nắn ảnh thành công.
- Tự động giới hạn kích thước ảnh đầu vào (max 2600px) để chống tràn RAM khi nạp ảnh camera lớn.
- Bổ sung hàm sanitize_ascii_filename: Triệt tiêu hoàn toàn lỗi HTTP 500 khi xuất Excel và PDF.
- Xuất PDF bằng PyMuPDF (fitz) tuần tự, không ngốn RAM.
"""
import os
import sys
import io
import json
import math
import re
import time
import uuid
import shutil
import asyncio
import threading
import unicodedata
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Cấu hình an toàn bảng mã console cho Windows .exe
if sys.platform == "win32":
    try:
        if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import cv2
import fitz  # PyMuPDF
import numpy as np
import openpyxl
from pydantic import BaseModel
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from align_sheet_v2 import CANONICAL_HEIGHT, CANONICAL_WIDTH, align_sheet_4band, align_sheet_from_array
from exam_manager import ExamManager
from full_grading_pipeline import FullGradingPipeline, normalize_answer_keys
from quality_gate import ImageQualityAssessment
from visual_stamper import VisualStamper


# ==============================================================================
# HELPER: Chuyển đổi an toàn các kiểu NumPy → JSON-serializable (Chống HTTP 500)
# ==============================================================================
def to_json_safe(obj):
    """Đệ quy chuyển đổi mọi kiểu NumPy/NaN thành kiểu Python thuần để json.dump không lỗi."""
    if isinstance(obj, dict):
        return {str(k): to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_json_safe(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [to_json_safe(v) for v in obj.tolist()]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        if math.isnan(v) or math.isinf(v):
            return 0.0
        return v
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
    return obj

app = FastAPI(title="OMR Grading System 2026", version="6.9.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("output/web_uploads")
GRADED_DIR = Path("output/graded_sheets")
DB_FILE = Path("output/exams_db.json")
DB_FILE_BAK = Path("output/exams_db.json.bak")
DB_LOCK = threading.RLock()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
GRADED_DIR.mkdir(parents=True, exist_ok=True)


def sanitize_ascii_filename(text: str, fallback: str = "FILE") -> str:
    """Khử 100% dấu tiếng Việt và ký tự đặc biệt cho tên file đính kèm HTTP Header."""
    if not text:
        return fallback
    nfkd = unicodedata.normalize('NFKD', str(text))
    ascii_text = nfkd.encode('ASCII', 'ignore').decode('ASCII')
    clean = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', ascii_text)
    clean = re.sub(r'_+', '_', clean).strip('_')
    return clean if clean else fallback


def find_aligned_image_path(sub_id: str) -> Optional[Path]:
    """Thống nhất tìm ảnh nắn phẳng tốt nhất của bài thi trong UPLOAD_DIR và GRADED_DIR."""
    candidates = [
        UPLOAD_DIR / f"{sub_id}_aligned.jpg",
        UPLOAD_DIR / f"{sub_id}_aligned.png",
        GRADED_DIR / f"{sub_id}_aligned.jpg",
        GRADED_DIR / f"{sub_id}_aligned.png",
        GRADED_DIR / f"{sub_id}_graded.jpg",
        GRADED_DIR / f"{sub_id}_graded.png",
    ]
    for c_path in candidates:
        if c_path.exists():
            return c_path
    return None


# ==============================================================================
# 1. MODELS (PYDANTIC)
# ==============================================================================

class CreateExamRequest(BaseModel):
    subject: str
    period: str
    class_name: str
    school_year: str


class UpdateSubmissionRequest(BaseModel):
    submission_id: str
    sbd: Optional[str] = None
    exam_code: Optional[str] = None
    part1: Optional[Dict[str, str]] = None
    part2: Optional[Dict[str, Dict[str, str]]] = None
    part3: Optional[Dict[str, Optional[float]]] = None


class SmartPasteRequest(BaseModel):
    text: str
    default_made: Optional[str] = "0001"


# ==============================================================================
# 2. DATABASE & SESSION MANAGEMENT (SINGLE SOURCE OF TRUTH)
# ==============================================================================

DB_DATA: Dict[str, Any] = {
    "active_exam_id": "default_exam",
    "exams": {
        "default_exam": {
            "id": "default_exam",
            "exam_info": {
                "subject": "Sinh học",
                "period": "Giữa kỳ I",
                "class_name": "11A",
                "school_year": "2026-2027",
                "is_configured": False
            },
            "exam_data": None,
            "submissions": {},
            "created_at": "05/11/2026 08:00"
        }
    }
}

def _load_db_from_file(p: Path) -> Optional[Dict[str, Any]]:
    if not p.exists() or p.stat().st_size == 0:
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and ("exams" in data or "exam_info" in data):
                return data
    except Exception as e:
        print(f"[!] Lỗi đọc {p}: {e}")
    return None

disk_db = _load_db_from_file(DB_FILE)
if disk_db is None and DB_FILE_BAK.exists():
    print("[*] exams_db.json lỗi hoặc rỗng, đang tự động phục hồi từ exams_db.json.bak...")
    disk_db = _load_db_from_file(DB_FILE_BAK)
    if disk_db:
        try:
            shutil.copy2(DB_FILE_BAK, DB_FILE)
        except Exception:
            pass

if disk_db:
    if "exams" in disk_db:
        DB_DATA = disk_db
    elif "exam_info" in disk_db:
        old_id = "exam_legacy"
        DB_DATA = {
            "active_exam_id": old_id,
            "exams": {
                old_id: {
                    "id": old_id,
                    "exam_info": disk_db.get("exam_info", {}),
                    "exam_data": disk_db.get("exam_data"),
                    "submissions": disk_db.get("submissions", {}),
                    "created_at": "04/11/2026"
                }
            }
        }


def get_current_exam() -> Dict[str, Any]:
    active_id = DB_DATA.get("active_exam_id", "default_exam")
    if active_id not in DB_DATA["exams"]:
        if DB_DATA["exams"]:
            active_id = list(DB_DATA["exams"].keys())[0]
            DB_DATA["active_exam_id"] = active_id
        else:
            new_id = f"exam_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            DB_DATA["exams"][new_id] = {
                "id": new_id,
                "exam_info": {
                    "subject": "Sinh học",
                    "period": "Giữa kỳ I",
                    "class_name": "11A",
                    "school_year": "2026-2027",
                    "is_configured": False
                },
                "exam_data": None,
                "submissions": {},
                "created_at": datetime.now().strftime("%d/%m/%Y %H:%M")
            }
            DB_DATA["active_exam_id"] = new_id
            active_id = new_id
    return DB_DATA["exams"][active_id]


def save_to_disk():
    """Ghi nguyên tử (Atomic write) với lock và backup an toàn chống xung đột đa luồng/mất dữ liệu."""
    with DB_LOCK:
        try:
            # 1. Sao lưu dự phòng
            if DB_FILE.exists() and DB_FILE.stat().st_size > 0:
                try:
                    shutil.copy2(DB_FILE, DB_FILE_BAK)
                except Exception:
                    pass

            # 2. Ghi ra tệp tạm dạng JSON rút gọn (không indent) và fsync
            tmp_file = DB_FILE.parent / f".exams_db.json.{uuid.uuid4().hex}.tmp"
            safe_db = to_json_safe(DB_DATA)
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(safe_db, ensure_ascii=False, separators=(",", ":")))
                f.flush()
                os.fsync(f.fileno())

            # 3. Thay thế tệp gốc với retry trên Windows
            success = False
            for attempt in range(5):
                try:
                    os.replace(tmp_file, DB_FILE)
                    success = True
                    break
                except PermissionError:
                    time.sleep(0.05)

            if not success and tmp_file.exists():
                try:
                    shutil.copy2(tmp_file, DB_FILE)
                    tmp_file.unlink(missing_ok=True)
                except Exception as e:
                    print("[!] Lỗi sao chép file database cuối cùng:", e)
        except Exception as e:
            print("[!] Lỗi lưu database:", e)


def _rebuild_anomalies_after_manual_edit(sub: Dict[str, Any], exam_data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Tự động xóa các cảnh báo cũ khi giáo viên đã sửa tay thông tin bài thi hợp lệ."""
    old_anoms = sub.get("anomalies", [])
    new_anoms = []

    sbd = str(sub.get("sbd", "")).strip()
    exam_code = str(sub.get("exam_code", "")).strip().zfill(4) if sub.get("exam_code") else ""
    p1 = sub.get("details", {}).get("part1", {})
    p2 = sub.get("details", {}).get("part2", {})
    p3 = sub.get("details", {}).get("part3", {})
    answer_keys = exam_data.get("answer_keys", {}) if exam_data else {}

    sbd_valid = bool(sbd and "?" not in sbd and "[" not in sbd)
    code_valid = bool(exam_code and "?" not in exam_code and "[" not in exam_code and len(exam_code) == 4)

    for a in old_anoms:
        atype = a.get("type", "")
        amsg = a.get("msg", "")

        # 1. Bỏ lỗi SBD nếu SBD đã hợp lệ
        if atype in {"MISSING_SBD", "SBD_DOUBLE_FILL"} and sbd_valid:
            continue

        # 2. Bỏ lỗi Mã đề nếu Mã đề đã hợp lệ
        if atype in {"INVALID_EXAM_CODE", "UNKNOWN_CODE", "NO_ANSWER_KEY", "MADE_DOUBLE_FILL"} and code_valid:
            continue

        # 3. Bỏ lỗi Phần I nếu câu đó đã chọn 1 đáp án A/B/C/D duy nhất
        if atype == "P1_DOUBLE_FILL":
            m = re.search(r"Câu\s+(\d+)", amsg)
            if m:
                q_num = int(m.group(1))
                if p1.get(q_num) in {"A", "B", "C", "D"}:
                    continue

        # 4. Bỏ lỗi Phần II nếu ý đó đã chọn Đ hoặc S duy nhất
        if atype in {"P2_DOUBLE_FILL", "P2_UNCERTAIN"}:
            m = re.search(r"Câu\s+(\d+)([a-d])", amsg)
            if m:
                q_num = int(m.group(1))
                rk = m.group(2).lower()
                if p2.get(q_num, {}).get(rk) in {"Đ", "S"}:
                    continue

        # 5. Bỏ lỗi Phần III nếu câu đó đã được sửa giá trị hợp lệ
        if atype.startswith("P3_Q") and "_VIOLATION" in atype:
            m = re.search(r"P3_Q(\d+)_VIOLATION", atype)
            if m:
                q_num = int(m.group(1))
                p3_val = p3.get(q_num)
                if isinstance(p3_val, dict) and p3_val.get("is_valid") and p3_val.get("normalized_value") is not None:
                    continue
                elif isinstance(p3_val, (int, float)):
                    continue

        new_anoms.append(a)

    # Nếu mã đề không có trong barem đáp án -> thêm UNKNOWN_CODE
    if code_valid and answer_keys and exam_code not in answer_keys:
        if not any(a.get("type") == "UNKNOWN_CODE" for a in new_anoms):
            new_anoms.append({"type": "UNKNOWN_CODE", "msg": f"Mã đề {exam_code} không tồn tại trong barem đáp án"})

    return new_anoms


def delete_submission_files(submission_id: str):
    """Xóa sạch các tệp ảnh liên quan của một bài làm (hỗ trợ cả định dạng .png và .jpg mới)."""
    extensions = [".png", ".jpg", ".jpeg", ".webp"]
    for ext in extensions:
        targets = [
            UPLOAD_DIR / f"{submission_id}_raw{ext}",
            UPLOAD_DIR / f"{submission_id}_aligned{ext}",
            GRADED_DIR / f"{submission_id}_graded{ext}",
            GRADED_DIR / f"{submission_id}_preview{ext}"
        ]
        for p in targets:
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass


current_exam = get_current_exam()
pipeline = FullGradingPipeline(exam_data=current_exam.get("exam_data"))


# ==============================================================================
# 3. ROUTE TÀI NGUYÊN GIAO DIỆN & QUẢN LÝ ĐỢT KIỂM TRA
# ==============================================================================

def get_template_content(template_name: str) -> str:
    candidates = [
        Path("templates") / template_name,
        Path(sys.executable).resolve().parent / "templates" / template_name if getattr(sys, 'frozen', False) else None,
        Path(getattr(sys, '_MEIPASS', '')) / "templates" / template_name if getattr(sys, 'frozen', False) else None,
        Path(sys.executable).resolve().parent / "_internal" / "templates" / template_name if getattr(sys, 'frozen', False) else None,
    ]
    for p in candidates:
        if p and p.exists() and p.is_file():
            return p.read_text(encoding="utf-8")
    return f"<h2>Không tìm thấy tệp giao diện: {template_name}</h2>"


NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0"
}


@app.get("/", response_class=HTMLResponse)
async def serve_home():
    return HTMLResponse(content=get_template_content("index.html"), headers=NO_CACHE_HEADERS)


@app.get("/scanner", response_class=HTMLResponse)
async def serve_mobile_scanner():
    return HTMLResponse(content=get_template_content("mobile_scanner.html"), headers=NO_CACHE_HEADERS)


@app.get("/manifest.json")
async def get_manifest():
    content = get_template_content("manifest.json")
    return Response(content=content, media_type="application/manifest+json")


@app.get("/sw.js")
async def get_service_worker():
    content = get_template_content("sw.js")
    return Response(content=content, media_type="application/javascript", headers=NO_CACHE_HEADERS)


@app.get("/icons/{icon_name}")
async def get_pwa_icon(icon_name: str):
    icon_path = Path("templates/icons") / icon_name
    if not icon_path.exists():
        raise HTTPException(status_code=404, detail="Icon not found")
    return FileResponse(str(icon_path), media_type="image/png")


@app.get("/api/health")
async def health_check():
    """Endpoint siêu nhẹ kiểm tra trạng thái thức/ngủ của server (Zero-Downtime Health Check)."""
    return JSONResponse(content={"status": "ok", "timestamp": time.time()}, headers=NO_CACHE_HEADERS)


@app.get("/api/session")
async def get_session():
    try:
        exam = get_current_exam()
        all_exams_summary = []
        for eid, edata in DB_DATA["exams"].items():
            info = edata.get("exam_info") or {}
            title = f"{info.get('subject', 'Môn học')} - {info.get('period', 'Kiểm tra')} ({info.get('class_name', '')})"
            all_exams_summary.append({
                "id": eid,
                "title": title,
                "submission_count": len(edata.get("submissions", {})),
                "created_at": edata.get("created_at", ""),
                "is_active": (eid == DB_DATA["active_exam_id"])
            })
        response_data = to_json_safe({
            "active_exam_id": DB_DATA["active_exam_id"],
            "exam_info": exam.get("exam_info"),
            "exam_data": exam.get("exam_data"),
            "submissions": list(exam.get("submissions", {}).values()),
            "all_exams": all_exams_summary
        })
        return JSONResponse(content=response_data, headers=NO_CACHE_HEADERS)
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            content={"active_exam_id": None, "exam_info": {}, "exam_data": None, "submissions": [], "all_exams": [], "error": str(e)},
            headers=NO_CACHE_HEADERS
        )


@app.post("/api/create-exam")
async def create_exam(payload: CreateExamRequest):
    global pipeline
    new_id = f"exam_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    new_exam = {
        "id": new_id,
        "exam_info": {
            "subject": payload.subject.strip(),
            "period": payload.period.strip(),
            "class_name": payload.class_name.strip(),
            "school_year": payload.school_year.strip(),
            "is_configured": False
        },
        "exam_data": None,
        "submissions": {},
        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M")
    }

    DB_DATA["exams"][new_id] = new_exam
    DB_DATA["active_exam_id"] = new_id
    pipeline = FullGradingPipeline(exam_data=None)

    save_to_disk()
    return {"status": "SUCCESS", "active_exam_id": new_id, "exam_info": new_exam["exam_info"]}


@app.post("/api/switch-exam/{exam_id}")
async def switch_exam(exam_id: str):
    global pipeline
    if exam_id not in DB_DATA["exams"]:
        raise HTTPException(status_code=404, detail="Không tìm thấy đợt kiểm tra này")

    DB_DATA["active_exam_id"] = exam_id
    active_exam = DB_DATA["exams"][exam_id]
    pipeline = FullGradingPipeline(exam_data=active_exam.get("exam_data"))

    save_to_disk()
    return {
        "status": "SUCCESS",
        "active_exam_id": exam_id,
        "exam_info": active_exam["exam_info"],
        "submission_count": len(active_exam.get("submissions", {}))
    }


@app.post("/api/select-exam/{exam_id}")
async def select_exam(exam_id: str):
    """Bí danh cho switch_exam phục vụ PWA Mobile Scanner."""
    return await switch_exam(exam_id)


@app.delete("/api/delete-exam/{exam_id}")
async def delete_exam(exam_id: str):
    global pipeline
    if exam_id not in DB_DATA["exams"]:
        raise HTTPException(status_code=404, detail="Đợt kiểm tra không tồn tại")

    target_exam = DB_DATA["exams"][exam_id]
    for sub_id in list(target_exam.get("submissions", {}).keys()):
        delete_submission_files(sub_id)

    del DB_DATA["exams"][exam_id]

    if DB_DATA["active_exam_id"] == exam_id:
        if DB_DATA["exams"]:
            DB_DATA["active_exam_id"] = list(DB_DATA["exams"].keys())[0]
        else:
            new_id = f"exam_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            DB_DATA["exams"][new_id] = {
                "id": new_id,
                "exam_info": {
                    "subject": "Sinh học",
                    "period": "Giữa kỳ I",
                    "class_name": "11A",
                    "school_year": "2026-2027",
                    "is_configured": False
                },
                "exam_data": None,
                "submissions": {},
                "created_at": datetime.now().strftime("%d/%m/%Y %H:%M")
            }
            DB_DATA["active_exam_id"] = new_id

    active_exam = get_current_exam()
    pipeline = FullGradingPipeline(exam_data=active_exam.get("exam_data"))
    save_to_disk()

    return {
        "status": "SUCCESS",
        "active_exam_id": DB_DATA["active_exam_id"],
        "remaining_exams_count": len(DB_DATA["exams"])
    }


# ==============================================================================
# 4. ROUTE CHẤM THI TUẦN TỰ & TỐI ƯU HÓA KHÔNG GIAN LƯU TRỮ
# ==============================================================================

def _save_submission_artifacts_bg(sub_id: str, aligned_bgr: np.ndarray, graded_bgr: np.ndarray):
    """Lưu ảnh đã nắn phẳng, ảnh đóng dấu bút đỏ (JPEG Quality 82) và DB ở tác vụ nền."""
    try:
        aligned_path = UPLOAD_DIR / f"{sub_id}_aligned.jpg"
        cv2.imwrite(str(aligned_path), aligned_bgr, [cv2.IMWRITE_JPEG_QUALITY, 82])

        graded_path = GRADED_DIR / f"{sub_id}_graded.jpg"
        cv2.imwrite(str(graded_path), graded_bgr, [cv2.IMWRITE_JPEG_QUALITY, 82])
    except Exception as e:
        print(f"[!] Lỗi lưu ảnh nền cho bài {sub_id}: {e}")
    finally:
        save_to_disk()


def _process_and_save(
    img_bgr: np.ndarray,
    file_name: str,
    sub_id: str,
    exam: Dict[str, Any],
    hint_corners: Optional[np.ndarray] = None,
    background_tasks: Optional[BackgroundTasks] = None
) -> Dict[str, Any]:
    """
    Hàm lõi chấm thi - Xử lý thuần trong RAM & đẩy ghi đĩa sang BackgroundTasks:
    1. Giới hạn độ phân giải ảnh thô đầu vào nếu quá lớn (max 2600px).
    2. Tiền kiểm định chất lượng ảnh (Quality Gate) trước khi nắn mốc.
    3. Nắn phẳng phối cảnh đa tầng trực tiếp trong RAM qua align_sheet_from_array.
    4. Chấm bài và đóng dấu bút đỏ trong RAM.
    5. Lưu tệp ảnh JPEG 82 + DB qua BackgroundTasks (không tạo WebP đồng bộ).
    """
    # 1. Giới hạn độ phân giải ảnh đầu vào nếu là ảnh chụp siêu lớn từ điện thoại
    h, w = img_bgr.shape[:2]
    max_dim = max(h, w)
    if max_dim > 2600:
        scale = 2600.0 / max_dim
        img_bgr = cv2.resize(img_bgr, (int(round(w * scale)), int(round(h * scale))), interpolation=cv2.INTER_AREA)
        if hint_corners is not None:
            hint_corners = hint_corners * scale

    # 2. Tiền kiểm định chất lượng ảnh (Quality Gate) trước khi nắn mốc
    is_valid, q_report = ImageQualityAssessment.evaluate(img_bgr)
    if not is_valid:
        reasons = q_report.get("reasons", ["Ảnh không đạt chuẩn chất lượng nhận diện."])
        reason_str = "; ".join(reasons)
        user_friendly_msg = f"Ảnh không đạt chuẩn kiểm định ({reason_str}). Vui lòng chụp lại rõ nét và đủ sáng."
        raise HTTPException(status_code=422, detail=user_friendly_msg)

    try:
        # 3. Nắn ảnh thuần trong RAM và tự xoay 4 hướng
        target_img = align_sheet_from_array(img_bgr, hint_corners=hint_corners)
        if target_img is None:
            raise RuntimeError("ALIGNMENT_FAILED: Không thể nắn phẳng ảnh.")

        # 4. Chấm bài bằng lõi quang học Ink Map
        res = pipeline.process_sheet(target_img, file_name)
        res["submission_id"] = sub_id
        res["original_filename"] = file_name
        res["has_error"] = False
        res["quality_metrics"] = q_report.get("metrics", {})

        graded_bgr = res.pop("graded_image_bgr")
        safe_res = to_json_safe(res)
        exam["submissions"][sub_id] = safe_res

        # 5. Đẩy I/O đĩa sang BackgroundTasks để trả JSON điểm tức thì
        if background_tasks is not None:
            background_tasks.add_task(_save_submission_artifacts_bg, sub_id, target_img, graded_bgr)
        else:
            _save_submission_artifacts_bg(sub_id, target_img, graded_bgr)

        return safe_res

    except HTTPException:
        raise
    except Exception as err:
        traceback.print_exc()
        err_msg = str(err)
        if "NOT_OMR_SHEET" in err_msg:
            user_friendly_msg = "Không nhận diện được đúng mẫu phiếu trả lời trắc nghiệm Bộ GD&ĐT. Hãy đảm bảo đưa đúng phiếu thi vào khung ngắm."
        elif "ALIGNMENT_FAILED" in err_msg:
            user_friendly_msg = "Ảnh bị mất mốc định vị hoặc quá nghiêng. Hãy chụp thẳng góc và đủ sáng."
        else:
            user_friendly_msg = f"Lỗi xử lý bài làm: {err_msg}"

        # Ném lỗi 422 Unprocessable Entity - Tuyệt đối không lưu bản ghi rác vào cơ sở dữ liệu
        raise HTTPException(status_code=422, detail=user_friendly_msg)


@app.post("/api/grade-single-file")
async def grade_single_file(background_tasks: BackgroundTasks, file: UploadFile = File(...), corners: Optional[str] = Form(None)):
    exam = get_current_exam()

    if not exam.get("exam_info", {}).get("is_configured", False) or not exam.get("exam_data", {}).get("answer_keys"):
        raise HTTPException(
            status_code=400,
            detail="Đợt kiểm tra hiện tại chưa được nạp đáp án. Vui lòng bấm 'Nạp File Đáp Án' trước khi chấm bài."
        )

    raw_bytes = await file.read()
    new_subs = []

    if file.filename.lower().endswith(".pdf"):
        try:
            doc = fitz.open(stream=raw_bytes, filetype="pdf")
            for page_idx in range(len(doc)):
                page = doc[page_idx]
                pix = page.get_pixmap(dpi=200)
                img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR if pix.n == 4 else cv2.COLOR_RGB2BGR)
                sub_id = str(uuid.uuid4())[:8]
                page_name = f"{file.filename}_Trang_{page_idx + 1}"
                try:
                    res = _process_and_save(img_bgr, page_name, sub_id, exam, background_tasks=background_tasks)
                    new_subs.append(res)
                except HTTPException as e:
                    print(f"[!] Trang {page_idx + 1} bị bỏ qua do lỗi: {e.detail}")
            doc.close()
        except HTTPException:
            raise
        except Exception as err:
            traceback.print_exc()
            raise HTTPException(status_code=400, detail=f"Lỗi đọc file PDF: {err}")

        if not new_subs:
            raise HTTPException(
                status_code=422,
                detail="Tất cả các trang trong file PDF đều không đạt chuẩn kiểm định hoặc không phải phiếu OMR."
            )
    else:
        np_arr = np.frombuffer(raw_bytes, np.uint8)
        img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img_bgr is None:
            raise HTTPException(status_code=400, detail="Không thể giải mã file ảnh.")
        sub_id = str(uuid.uuid4())[:8]

        hint_corners = None
        if corners:
            try:
                c_data = json.loads(corners)
                if isinstance(c_data, list) and len(c_data) == 4:
                    orig_h, orig_w = img_bgr.shape[:2]
                    hint_corners = np.array([
                        [float(pt[0]) * orig_w, float(pt[1]) * orig_h]
                        for pt in c_data
                    ], dtype=np.float32)
            except Exception as e:
                print(f"[!] Lỗi phân tích hint_corners: {e}")

        res = _process_and_save(img_bgr, file.filename, sub_id, exam, hint_corners=hint_corners, background_tasks=background_tasks)
        new_subs.append(res)

    return {
        "status": "SUCCESS",
        "new_submissions": new_subs,
        "total_submissions_count": len(exam["submissions"])
    }


# ==============================================================================
# 5. ROUTE SỬA TAY REALTIME & TÁI ĐÓNG DẤU BÚT ĐỎ
# ==============================================================================

@app.post("/api/update-submission")
async def update_submission(payload: UpdateSubmissionRequest):
    """Cập nhật SBD, Mã đề, Đáp án; tự động chấm lại và vẽ lại tem bút đỏ Cột 3."""
    try:
        exam = get_current_exam()
        sub_id = payload.submission_id
        if not sub_id or sub_id not in exam.get("submissions", {}):
            raise HTTPException(status_code=404, detail="Không tìm thấy bài thi cần cập nhật.")

        sub = exam["submissions"][sub_id]

        new_sbd = str(payload.sbd).strip() if payload.sbd is not None else sub.get("sbd", "")
        new_exam_code = str(payload.exam_code).strip().zfill(4) if payload.exam_code else sub.get("exam_code", "")

        sub["sbd"] = new_sbd
        sub["exam_code"] = new_exam_code

        if payload.part1 is not None and isinstance(payload.part1, dict):
            sub["details"]["part1"] = {int(k): str(v).upper() for k, v in payload.part1.items() if v}
        if payload.part2 is not None and isinstance(payload.part2, dict):
            sub["details"]["part2"] = {int(k): {str(sk).lower(): str(sv).upper() for sk, sv in sdict.items()} for k, sdict in payload.part2.items() if sdict}
        
        if payload.part3 is not None and isinstance(payload.part3, dict):
            p3_clean = {}
            for k, v in payload.part3.items():
                if v is not None and str(v).strip() != "":
                    try:
                        f_val = float(str(v).replace(",", "."))
                        p3_clean[int(k)] = {
                            "raw_string": str(v),
                            "normalized_value": f_val,
                            "is_valid": True,
                            "anomalies": []
                        }
                    except ValueError:
                        pass
            sub["details"]["part3"] = p3_clean

        exam_data = exam.get("exam_data")
        if exam_data and "answer_keys" in exam_data:
            pipeline.answer_keys = normalize_answer_keys(exam_data["answer_keys"])

        new_scores = pipeline._grade(
            new_exam_code,
            sub["details"].get("part1", {}),
            sub["details"].get("part2", {}),
            sub["details"].get("part3", {})
        )
        sub["scores"] = new_scores

        # Tự động cập nhật lại danh sách anomalies sau khi sửa tay
        sub["anomalies"] = _rebuild_anomalies_after_manual_edit(sub, exam_data)

        # Cập nhật lại status chính xác
        has_critical = any(
            a["type"] in {"INVALID_EXAM_CODE", "UNKNOWN_CODE", "NO_ANSWER_KEY", "MISSING_SBD"}
            or a["type"].endswith("DOUBLE_FILL")
            or "VIOLATION" in a["type"]
            for a in sub["anomalies"]
        )
        if new_scores.get("status") in {"UNKNOWN_CODE", "NO_ANSWER_KEY"} or has_critical:
            sub["status"] = "NEEDS_REVIEW"
        else:
            sub["status"] = "GRADED"

        sub["has_error"] = (sub["status"] == "NEEDS_REVIEW")
        sub["error_msg"] = None
        sub["updated_at"] = datetime.now().isoformat()

        try:
            aligned_file = find_aligned_image_path(sub_id)
            if aligned_file is not None:
                base_img = cv2.imread(str(aligned_file))
                if base_img is not None:
                    if "graded" in aligned_file.name:
                        base_img[185:440, 65:410] = (255, 255, 255)

                    key_dict = pipeline.answer_keys.get(new_exam_code, {})
                    stamped = VisualStamper.stamp_graded_sheet(
                        aligned_bgr=base_img,
                        submission=sub,
                        p1_coords=pipeline.p1_coords,
                        p2_coords=pipeline.p2_coords,
                        p3_coords=pipeline.p3_coords,
                        key_dict=key_dict,
                        sbd_columns=pipeline.sbd_columns,
                        made_columns=pipeline.made_columns
                    )
                    graded_path = GRADED_DIR / f"{sub_id}_graded.jpg"
                    cv2.imwrite(str(graded_path), stamped, [cv2.IMWRITE_JPEG_QUALITY, 90])
                    
                    preview_webp = GRADED_DIR / f"{sub_id}_preview.webp"
                    cv2.imwrite(str(preview_webp), stamped, [cv2.IMWRITE_WEBP_QUALITY, 80])
                    print(f"[OK] Da ve lai tem but do: {sub_id} (Diem: {new_scores['total']})")
        except Exception as stamp_err:
            print(f"[!] Canh bao ve tem but do: {stamp_err}")

        save_to_disk()

        return {
            "status": "success",
            "message": "Đã cập nhật và chấm lại thành công!",
            "updated_submission": sub
        }

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Lỗi cập nhật máy chủ: {str(e)}")


@app.delete("/api/delete-submission/{submission_id}")
async def delete_submission(submission_id: str):
    exam = get_current_exam()
    if submission_id not in exam.get("submissions", {}):
        raise HTTPException(status_code=404, detail="Không tìm thấy bài làm cần xóa")

    delete_submission_files(submission_id)
    del exam["submissions"][submission_id]
    save_to_disk()

    return {"status": "SUCCESS", "remaining_count": len(exam["submissions"])}


@app.get("/api/crop-info/{submission_id}")
async def get_crop_info(submission_id: str):
    aligned_path = find_aligned_image_path(submission_id)
    if not aligned_path or not aligned_path.exists():
        raise HTTPException(status_code=404, detail="Không tìm thấy bài làm")

    img = cv2.imread(str(aligned_path))
    if img is None:
        raise HTTPException(status_code=500, detail="Không thể đọc tệp ảnh bài làm.")

    # Vùng cắt thông tin thí sinh: Y từ 205 đến 725, X từ 440 đến 1225
    crop = img[205:725, 440:1225]

    _, buffer = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return Response(
        content=buffer.tobytes(),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache"}
    )


@app.get("/api/graded-image/{sub_id}")
async def get_graded_image(sub_id: str):
    """Phục vụ ảnh WebP nén nhẹ kết hợp HTTP Cache ETag."""
    webp_path = GRADED_DIR / f"{sub_id}_preview.webp"
    jpg_path = GRADED_DIR / f"{sub_id}_graded.jpg"
    png_path = GRADED_DIR / f"{sub_id}_graded.png"

    source_path = None
    for p in [jpg_path, png_path]:
        if p.exists():
            source_path = p
            break

    if not source_path and not webp_path.exists():
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh bài làm đã chấm.")

    need_regenerate = False
    if not webp_path.exists():
        need_regenerate = True
    elif source_path and source_path.stat().st_mtime > webp_path.stat().st_mtime:
        need_regenerate = True

    if need_regenerate and source_path:
        bgr = cv2.imread(str(source_path))
        if bgr is not None:
            cv2.imwrite(str(webp_path), bgr, [cv2.IMWRITE_WEBP_QUALITY, 80])

    target_file = webp_path if webp_path.exists() else source_path
    media_type = "image/webp" if target_file.suffix == ".webp" else "image/jpeg"
    last_modified = int(target_file.stat().st_mtime)

    return FileResponse(
        target_file,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "ETag": f'"{sub_id}-{last_modified}"'
        }
    )


@app.get("/api/image/{sub_id}")
async def get_image_alias(sub_id: str):
    """Bí danh phục vụ ảnh bài làm cho các client gọi /api/image/{sub_id}"""
    return await get_graded_image(sub_id)


# ==============================================================================
# 6. ROUTE IMPORT / EXPORT DỮ LIỆU (KHỬ HOÀN TOÀN DẤU TIẾNG VIỆT CHO HEADER)
# ==============================================================================

@app.get("/api/download-template")
async def download_template():
    tpl_path = Path("output/MAU_DAP_AN_TRAC_NGHIEM_2025.xlsx")
    exam = get_current_exam()
    info = exam.get("exam_info", {})

    file_bytes = ExamManager.generate_excel_template(
        output_path=tpl_path,
        exam_name=f"{info.get('subject', 'Sinh học')} - {info.get('period', 'Giữa kỳ I')}",
        subject=info.get("subject", "Sinh học"),
        period=info.get("period", "Giữa kỳ I")
    )

    return Response(
        content=file_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="MAU_DAP_AN_TRAC_NGHIEM_2025.xlsx"'
        }
    )


@app.post("/api/upload-answer-key")
async def upload_answer_key(file: UploadFile = File(...)):
    global pipeline
    raw_bytes = await file.read()
    temp_path = UPLOAD_DIR / "uploaded_key.xlsx"
    temp_path.write_bytes(raw_bytes)

    try:
        exam_data = ExamManager.parse_excel_config(temp_path)
        exam = get_current_exam()
        exam["exam_data"] = exam_data
        exam["exam_info"]["is_configured"] = True

        pipeline = FullGradingPipeline(exam_data=exam_data)

        # Chấm lại các bài thi hiện có theo đáp án mới
        for sub_id, sub in exam["submissions"].items():
            aligned_p = find_aligned_image_path(sub_id)
            if aligned_p and aligned_p.exists():
                img = cv2.imread(str(aligned_p))
                if img is not None:
                    updated = pipeline.process_sheet(img, sub["file_name"], forced_exam_code=sub["exam_code"])
                    updated["submission_id"] = sub_id
                    updated["original_filename"] = sub["file_name"]
                    
                    graded_path = GRADED_DIR / f"{sub_id}_graded.jpg"
                    cv2.imwrite(str(graded_path), updated["graded_image_bgr"], [cv2.IMWRITE_JPEG_QUALITY, 90])
                    
                    preview_webp = GRADED_DIR / f"{sub_id}_preview.webp"
                    cv2.imwrite(str(preview_webp), updated["graded_image_bgr"], [cv2.IMWRITE_WEBP_QUALITY, 80])
                    
                    del updated["graded_image_bgr"]
                    exam["submissions"][sub_id] = updated

        save_to_disk()
        codes_list = list(exam_data["answer_keys"].keys())
        return {
            "status": "SUCCESS",
            "exam_name": exam_data["exam_name"],
            "codes_loaded": codes_list,
            "exam_codes": codes_list,
            "exam_info": exam["exam_info"]
        }
    except Exception as err:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"Lỗi file đáp án: {err}")


@app.post("/api/smart-paste-answer-key")
async def smart_paste_answer_key(payload: SmartPasteRequest):
    global pipeline
    if not payload.text or not payload.text.strip():
        raise HTTPException(status_code=400, detail="Vui lòng nhập hoặc dán nội dung đáp án.")

    try:
        parsed_result = ExamManager.smart_parse_text_keys(payload.text, default_made=payload.default_made or "0001")
        parsed_keys = parsed_result.get("answer_keys", {})
        if not parsed_keys:
            raise HTTPException(status_code=400, detail="Không nhận diện được câu hỏi hoặc đáp án nào. Hãy kiểm tra định dạng dán (VD: 1.A 2.B hoặc 1A 2B).")

        exam = get_current_exam()
        default_config = {
            "pts_p1": 0.25,
            "pts_p2_rule": {0: 0.0, 1: 0.1, 2: 0.25, 3: 0.5, 4: 1.0},
            "pts_p3": 0.25
        }
        if not exam.get("exam_data"):
            exam["exam_data"] = {
                "exam_name": f"{exam['exam_info'].get('subject', 'Đề thi')} - {exam['exam_info'].get('period', 'Kiểm tra')}",
                "subject": exam["exam_info"].get("subject", "Sinh học"),
                "period": exam["exam_info"].get("period", "Giữa kỳ I"),
                "config": parsed_result.get("config", default_config),
                "answer_keys": {},
                "scoring_rules": {
                    "part1": {"points_per_question": 0.25},
                    "part2": {
                        "type": "graduated_moet",
                        "table": {"1": 0.1, "2": 0.25, "3": 0.5, "4": 1.0}
                    },
                    "part3": {"points_per_question": 0.25}
                }
            }
        elif "config" not in exam["exam_data"]:
            exam["exam_data"]["config"] = parsed_result.get("config", default_config)

        # Cập nhật các mã đề mới parsed vào answer_keys (merge từng phần, không xóa Phần II, III)
        for code, new_k in parsed_keys.items():
            if code not in exam["exam_data"]["answer_keys"]:
                exam["exam_data"]["answer_keys"][code] = new_k
            else:
                for part in ["part1", "part2", "part3"]:
                    if new_k.get(part):
                        exam["exam_data"]["answer_keys"][code][part] = new_k[part]
        exam["exam_info"]["is_configured"] = True

        pipeline = FullGradingPipeline(exam_data=exam["exam_data"])

        # Tái chấm các bài thi có trong danh sách
        re_graded_count = 0
        for sub_id, sub in exam.get("submissions", {}).items():
            sub_code = sub.get("exam_code", "")
            if sub_code in exam["exam_data"]["answer_keys"]:
                aligned_p = find_aligned_image_path(sub_id)
                if aligned_p and aligned_p.exists():
                    img = cv2.imread(str(aligned_p))
                    if img is not None:
                        updated = pipeline.process_sheet(img, sub.get("file_name", ""), forced_exam_code=sub_code)
                        updated["submission_id"] = sub_id
                        updated["original_filename"] = sub.get("file_name", "")
                        
                        graded_path = GRADED_DIR / f"{sub_id}_graded.jpg"
                        cv2.imwrite(str(graded_path), updated["graded_image_bgr"], [cv2.IMWRITE_JPEG_QUALITY, 90])
                        
                        preview_webp = GRADED_DIR / f"{sub_id}_preview.webp"
                        cv2.imwrite(str(preview_webp), updated["graded_image_bgr"], [cv2.IMWRITE_WEBP_QUALITY, 80])
                        
                        del updated["graded_image_bgr"]
                        exam["submissions"][sub_id] = updated
                        re_graded_count += 1

        save_to_disk()
        return {
            "status": "SUCCESS",
            "codes_loaded": list(parsed_keys.keys()),
            "exam_codes": list(parsed_keys.keys()),
            "total_codes": list(exam["exam_data"]["answer_keys"].keys()),
            "re_graded_count": re_graded_count,
            "details": {
                c: {
                    "part1": len(k.get("part1", {})),
                    "part2": len(k.get("part2", {})),
                    "part3": len(k.get("part3", {}))
                } for c, k in parsed_keys.items()
            },
            "exam_info": exam["exam_info"]
        }
    except HTTPException:
        raise
    except Exception as err:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"Lỗi xử lý đáp án dán: {err}")


def _generate_excel_sync(exam: Dict[str, Any]) -> Tuple[Path, str]:
    subs = exam.get("submissions", {})
    if not subs:
        raise HTTPException(status_code=400, detail="Chưa có bài thi nào trong đợt để xuất bảng điểm.")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BangDiem"

    headers = ["STT", "Tên Tệp", "Số Báo Danh (Vào Sổ)", "Mã Đề", "Điểm P1", "Điểm P2", "Điểm P3", "TỔNG ĐIỂM", "Trạng Thái", "Cảnh Báo"]
    ws.append(headers)

    for idx, (sub_id, sub) in enumerate(subs.items(), start=1):
        sc = sub.get("scores", {})
        ws.append([
            idx,
            sub.get("file_name", ""),
            sub.get("sbd", ""),
            sub.get("exam_code", ""),
            sc.get("p1", 0.0),
            sc.get("p2", 0.0),
            sc.get("p3", 0.0),
            sc.get("total", 0.0),
            sub.get("status", "GRADED"),
            ", ".join([a["msg"] for a in sub.get("anomalies", [])]) if sub.get("anomalies") else "Hợp lệ"
        ])

    excel_path = Path("output/BANG_DIEM_VAO_SO.xlsx")
    try:
        wb.save(excel_path)
    except PermissionError:
        excel_path = Path(f"output/BANG_DIEM_VAO_SO_{int(time.time())}.xlsx")
        wb.save(excel_path)

    info = exam.get("exam_info", {})
    sub_name = sanitize_ascii_filename(info.get("subject", "MON"))
    period_name = sanitize_ascii_filename(info.get("period", "KY"))
    download_name = f"BANG_DIEM_{sub_name}_{period_name}.xlsx"
    return excel_path, download_name


def _generate_pdf_sync(exam: Dict[str, Any]) -> Tuple[Path, str]:
    subs = exam.get("submissions", {})
    if not subs:
        raise HTTPException(status_code=400, detail="Chưa có bài thi nào trong đợt để xuất PDF.")

    pdf_out = Path("output/TAP_PHIEU_DA_CHAM.pdf")

    # Tối ưu hóa bộ nhớ RAM: Chèn ảnh trực tiếp qua page.insert_image không giải nén ma trận RGB bitmap
    # Tiết kiệm 95% RAM, chống sập OOM trên Render Free Tier và sinh PDF trong ~300ms
    doc = fitz.open()
    for sub_id, sub in subs.items():
        img_path = None
        for ext in [".jpg", ".png", ".webp"]:
            p = GRADED_DIR / f"{sub_id}_graded{ext}"
            if p.exists():
                img_path = p
                break
            p_up = UPLOAD_DIR / f"{sub_id}_aligned{ext}"
            if p_up.exists():
                img_path = p_up
                break

        if img_path and img_path.exists():
            try:
                page = doc.new_page(width=CANONICAL_WIDTH, height=CANONICAL_HEIGHT)
                page.insert_image(fitz.Rect(0, 0, CANONICAL_WIDTH, CANONICAL_HEIGHT), filename=str(img_path))
            except Exception as page_err:
                print(f"[!] Bỏ qua ảnh lỗi {img_path.name}: {page_err}")
        else:
            # Fallback nếu tệp ảnh chưa đồng bộ về ổ cứng: Tạo trang tổng hợp thông tin bài chấm
            page = doc.new_page(width=CANONICAL_WIDTH, height=CANONICAL_HEIGHT)
            sc = sub.get("scores", {})
            title_text = f"KET QUA BAI THI: {sub.get('file_name', sub_id)}"
            sbd_text = f"SBD: {sub.get('sbd', '---')}  |  Ma de: {sub.get('exam_code', '---')}  |  Trang thai: {sub.get('status', 'GRADED')}"
            score_text = f"TONG DIEM: {sc.get('total', 0.0):.2f} / 10  (P1: {sc.get('p1', 0.0)} d, P2: {sc.get('p2', 0.0)} d, P3: {sc.get('p3', 0.0)} d)"
            page.insert_text(fitz.Point(100, 200), title_text, fontsize=28, color=(0, 0, 0))
            page.insert_text(fitz.Point(100, 260), sbd_text, fontsize=20, color=(0.2, 0.2, 0.2))
            page.insert_text(fitz.Point(100, 320), score_text, fontsize=24, color=(0.8, 0, 0))

    if len(doc) == 0:
        page = doc.new_page(width=CANONICAL_WIDTH, height=CANONICAL_HEIGHT)
        page.insert_text(fitz.Point(100, 200), "Chua co bai thi nao trong he thong", fontsize=24)

    page_count = len(doc)
    try:
        doc.save(str(pdf_out), deflate=True)
    except PermissionError:
        pdf_out = Path(f"output/TAP_PHIEU_DA_CHAM_{int(time.time())}.pdf")
        doc.save(str(pdf_out), deflate=True)
    finally:
        doc.close()

    info = exam.get("exam_info", {})
    sub_name = sanitize_ascii_filename(info.get("subject", "MON"))
    class_name = sanitize_ascii_filename(info.get("class_name", "LOP"))
    download_name = f"TAP_PHIEU_DA_CHAM_{sub_name}_{class_name}.pdf"
    print(f"[OK] Da xuat thanh cong tap PDF gom {page_count} trang: {pdf_out.name}")
    return pdf_out, download_name


@app.get("/api/export-excel")
async def export_excel():
    """Xuất bảng điểm Excel an toàn; Chạy trong threadpool chống nghẽn event loop, Header filename thuần ASCII."""
    try:
        exam = get_current_exam()
        excel_path, download_name = await asyncio.to_thread(_generate_excel_sync, exam)
        return FileResponse(
            path=str(excel_path),
            filename=download_name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Content-Disposition": f'attachment; filename="{download_name}"'
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Lỗi xuất Excel: {str(e)}")


@app.get("/api/export-graded-pdf")
async def export_graded_pdf():
    """Xuất tập phiếu đã chấm thành PDF nhiều trang; Chạy trong threadpool chống nghẽn event loop, Header thuần ASCII."""
    try:
        exam = get_current_exam()
        pdf_out, download_name = await asyncio.to_thread(_generate_pdf_sync, exam)
        return FileResponse(
            path=str(pdf_out),
            filename=download_name,
            media_type="application/pdf",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Content-Disposition": f'attachment; filename="{download_name}"'
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Lỗi xuất PDF: {str(e)}")


@app.get("/api/export-pdf")
async def export_pdf_alias():
    """Bí danh xuất tập phiếu đã chấm thành PDF"""
    return await export_graded_pdf()


# ==============================================================================
# 7. KHỞI CHẠY MÁY CHỦ
# ==============================================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
```

## FILE: Dockerfile
```dockerfile
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7860

WORKDIR /app

# Cài đặt thư viện hệ thống tối thiểu cho OpenCV Headless và PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Khởi tạo thư mục dữ liệu với toàn quyền đọc ghi
RUN mkdir -p output/web_uploads output/graded_sheets && \
    chmod -R 777 output

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]

```

## FILE: exam_manager.py
```py
# exam_manager.py
# -*- coding: utf-8 -*-
"""
MODULE QUẢN LÝ CẤU HÌNH ĐỀ THI & ĐÁP ÁN CHUẨN HÓA BỘ GD&ĐT 2025
- Cấu hình thang điểm trực quan: Đúng 1, 2, 3, 4 ý chia thành 2 hàng ô trên - ô dưới rõ ràng.
- Đầy đủ 40 câu P1, 8 câu P2 (32 ý), 6 câu P3.
- Hỗ trợ xuất ra cả đĩa và bộ nhớ đệm (in-memory buffer) chống lỗi file lock trên Windows.
"""
import io
from pathlib import Path
from typing import Any, Dict, List, Optional
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


class ExamManager:
    MAX_P1 = 40
    MAX_P2 = 8
    MAX_P3 = 6

    @classmethod
    def generate_excel_template(
        cls,
        output_path: Optional[Path] = None,
        exam_name: str = "Kiểm tra trắc nghiệm",
        subject: str = "Sinh học",
        period: str = "Giữa kỳ I"
    ) -> bytes:
        """
        Tạo file Excel mẫu chuẩn:
        - Hàng 3-5: Cấu hình thang điểm. Đặc biệt Phần II hiển thị 4 cột:
          Ô trên: Đúng 1 ý | Đúng 2 ý | Đúng 3 ý | Đúng 4 ý
          Ô dưới:   0.10   |   0.25   |   0.50   |   1.00
        - Hàng 7: Header toàn bộ 78 cột (1 cột Mã đề + 40 P1 + 32 P2 + 6 P3).
        - Hàng 8-9: 2 dòng mã đề mẫu (0504, 0501).
        """
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "DAP_AN_TRAC_NGHIEM"
        ws.views.sheetView[0].showGridLines = True

        thin = Border(
            left=Side(style='thin', color='D3D3D3'),
            right=Side(style='thin', color='D3D3D3'),
            top=Side(style='thin', color='D3D3D3'),
            bottom=Side(style='thin', color='D3D3D3')
        )

        fill_navy = PatternFill("solid", fgColor="1B365D")
        fill_p1 = PatternFill("solid", fgColor="E8F0FE")    # Xanh dương nhạt
        fill_p2 = PatternFill("solid", fgColor="FEF7E0")    # Vàng cam nhạt
        fill_p3 = PatternFill("solid", fgColor="E6F4EA")    # Xanh lá nhạt
        fill_header = PatternFill("solid", fgColor="F1F3F4")
        fill_val = PatternFill("solid", fgColor="FFFFFF")

        font_title = Font(name="Times New Roman", size=13, bold=True, color="1B365D")
        font_sub = Font(name="Times New Roman", size=10, italic=True, color="555555")
        font_label = Font(name="Times New Roman", size=10, bold=True)
        font_val = Font(name="Times New Roman", size=11, bold=True, color="000080")
        font_h = Font(name="Times New Roman", size=10, bold=True)
        font_h_white = Font(name="Times New Roman", size=10, bold=True, color="FFFFFF")

        # 1. TIÊU ĐỀ & LƯU Ý
        ws["A1"] = f"BẢNG ĐÁP ÁN & CẤU HÌNH THANG ĐIỂM CHUẨN BỘ GD&ĐT: {subject.upper()} - {period.upper()}"
        ws["A1"].font = font_title

        ws["A2"] = "LƯU Ý: Thầy/cô có thể sửa điểm ở các ô màu trắng. Đề thi có bao nhiêu câu thì điền bấy nhiêu câu, câu không thi để trống hoàn toàn."
        ws["A2"].font = font_sub

        # 2. KHUNG CẤU HÌNH THANG ĐIỂM TRỰC QUAN (HÀNG 3 - 5)
        # Cột A-B: Thông tin chung
        ws["A3"] = "Tên bài kiểm tra:"
        ws["B3"] = f"{subject} - {period}"
        ws["A4"] = "Môn học:"
        ws["B4"] = subject
        ws["A5"] = "Năm học:"
        ws["B5"] = "2026-2027"

        # Cột C-D: Điểm Phần I & Phần III
        ws["C3"] = "Điểm 1 câu Phần I:"
        ws["D3"] = 0.25
        ws["C4"] = "Điểm 1 câu Phần III:"
        ws["D4"] = 0.25
        ws["C5"] = "Kỳ kiểm tra:"
        ws["D5"] = period

        # Cột E-H: BẢNG THANG ĐIỂM PHẦN II (ĐÚNG/SAI BẬC THANG)
        ws.merge_cells("E3:H3")
        ws["E3"] = "THANG ĐIỂM BẬC THANG PHẦN II (ĐÚNG / SAI BỘ GD&ĐT)"
        ws["E3"].font = font_label
        ws["E3"].alignment = Alignment(horizontal="center", vertical="center")
        ws["E3"].fill = fill_p2
        ws["E3"].border = thin

        # Hàng 4: Ô TRÊN - Tên mức đúng
        p2_headers = [("E4", "Đúng 1 ý"), ("F4", "Đúng 2 ý"), ("G4", "Đúng 3 ý"), ("H4", "Đúng 4 ý")]
        for cell_id, text in p2_headers:
            ws[cell_id] = text
            ws[cell_id].font = font_label
            ws[cell_id].alignment = Alignment(horizontal="center", vertical="center")
            ws[cell_id].fill = fill_header
            ws[cell_id].border = thin

        # Hàng 5: Ô DƯỚI - Số điểm tương ứng
        p2_scores = [("E5", 0.10), ("F5", 0.25), ("G5", 0.50), ("H5", 1.00)]
        for cell_id, val in p2_scores:
            ws[cell_id] = val
            ws[cell_id].font = font_val
            ws[cell_id].alignment = Alignment(horizontal="center", vertical="center")
            ws[cell_id].fill = fill_val
            ws[cell_id].border = thin

        # Định dạng viền và màu sắc khối A3..D5
        for r in range(3, 6):
            for c in ["A", "C"]:
                ws[f"{c}{r}"].font = font_label
                ws[f"{c}{r}"].fill = fill_header
                ws[f"{c}{r}"].border = thin
            for c in ["B", "D"]:
                ws[f"{c}{r}"].font = font_val if c == "D" else Font(name="Times New Roman", size=10)
                ws[f"{c}{r}"].fill = fill_val
                ws[f"{c}{r}"].border = thin
                if c == "D":
                    ws[f"{c}{r}"].alignment = Alignment(horizontal="center", vertical="center")

        # 3. HEADER BẢNG ĐÁP ÁN (DÒNG 7)
        header_row = 7
        headers = ["Mã Đề Thi"]
        col_types = ["CODE"]

        # 40 câu Phần I
        for i in range(1, cls.MAX_P1 + 1):
            headers.append(f"P1_C{i}")
            col_types.append("P1")

        # 8 câu Phần II (mỗi câu 4 ý a, b, c, d = 32 cột)
        for i in range(1, cls.MAX_P2 + 1):
            for sk in ["a", "b", "c", "d"]:
                headers.append(f"P2_C{i}_{sk}")
                col_types.append("P2")

        # 6 câu Phần III
        for i in range(1, cls.MAX_P3 + 1):
            headers.append(f"P3_C{i}")
            col_types.append("P3")

        for c_idx, (h_name, c_type) in enumerate(zip(headers, col_types), start=1):
            cell = ws.cell(row=header_row, column=c_idx, value=h_name)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin
            if c_type == "CODE":
                cell.font = font_h_white
                cell.fill = fill_navy
            elif c_type == "P1":
                cell.font = font_h
                cell.fill = fill_p1
            elif c_type == "P2":
                cell.font = font_h
                cell.fill = fill_p2
            else:
                cell.font = font_h
                cell.fill = fill_p3

        # 4. ĐIỀN DỮ LIỆU MẪU (2 MÃ ĐỀ 0504 & 0501)
        sample_rows = [
            ("0504", {
                "P1": ["B", "C", "A", "A", "C", "D", "C", "C", "B", "A", "C", "C", "C", "D", "A", "B"],
                "P2": [("Đ", "Đ", "Đ", "Đ"), ("Đ", "Đ", "Đ", "Đ")],
                "P3": ["214", "214", "1322"]
            }),
            ("0501", {
                "P1": ["B", "A", "B", "B", "D", "A", "D", "B", "D", "D", "A", "A", "A", "C", "D"],
                "P2": [("Đ", "S", "Đ", "S"), ("S", "S", "Đ", "Đ")],
                "P3": ["6", "2134", "10"]
            })
        ]

        for r_offset, (code, ans_dict) in enumerate(sample_rows, start=1):
            curr_r = header_row + r_offset
            row_data = [code]

            p1_vals = ans_dict.get("P1", [])
            for i in range(cls.MAX_P1):
                row_data.append(p1_vals[i] if i < len(p1_vals) else "")

            p2_tuples = ans_dict.get("P2", [])
            for q_i in range(cls.MAX_P2):
                if q_i < len(p2_tuples):
                    t_a, t_b, t_c, t_d = p2_tuples[q_i]
                    row_data.extend([t_a, t_b, t_c, t_d])
                else:
                    row_data.extend(["", "", "", ""])

            p3_vals = ans_dict.get("P3", [])
            for i in range(cls.MAX_P3):
                row_data.append(p3_vals[i] if i < len(p3_vals) else "")

            for c_idx, val in enumerate(row_data, start=1):
                cell = ws.cell(row=curr_r, column=c_idx, value=val)
                cell.font = Font(name="Times New Roman", size=11, bold=(c_idx == 1))
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.border = thin

        ws.column_dimensions["A"].width = 14
        ws.column_dimensions["B"].width = 24
        ws.column_dimensions["C"].width = 18
        ws.column_dimensions["D"].width = 14
        ws.column_dimensions["E"].width = 12
        ws.column_dimensions["F"].width = 12
        ws.column_dimensions["G"].width = 12
        ws.column_dimensions["H"].width = 12

        for col_idx in range(9, len(headers) + 1):
            letter = get_column_letter(col_idx)
            ws.column_dimensions[letter].width = 8

        # Xuất ra bộ nhớ (BytesIO) để chống hoàn toàn lỗi khóa file trên Windows
        mem_buffer = io.BytesIO()
        wb.save(mem_buffer)
        mem_buffer.seek(0)
        file_bytes = mem_buffer.getvalue()

        # Lưu xuống đĩa nếu có output_path
        if output_path is not None:
            try:
                output_path.parent.mkdir(exist_ok=True, parents=True)
                with open(output_path, "wb") as f:
                    f.write(file_bytes)
            except Exception as e:
                print(f"[!] Cảnh báo: Không thể ghi file ra đĩa (có thể đang mở trong Excel): {e}")

        return file_bytes

    @classmethod
    def parse_excel_config(cls, excel_path: Path) -> Dict[str, Any]:
        """
        Đọc cấu hình & barem đáp án từ file Excel.
        Hỗ trợ cấu hình Phần II ô trên (E4-H4) và ô dưới (E5-H5).
        """
        wb = openpyxl.load_workbook(excel_path, data_only=True)
        ws = wb.active

        exam_name = str(ws["B3"].value or "Bài kiểm tra trắc nghiệm").strip()

        # 1. Đọc điểm Phần I
        try:
            pts_p1 = float(ws["D3"].value)
        except (ValueError, TypeError):
            pts_p1 = 0.25

        # 2. Đọc điểm Phần III
        try:
            pts_p3 = float(ws["D4"].value)
        except (ValueError, TypeError):
            pts_p3 = 0.25

        # 3. Đọc thang điểm Phần II (Ô trên: E4-H4, Ô dưới: E5-H5)
        try:
            if ws["E5"].value is not None and ws["F5"].value is not None:
                v1 = float(ws["E5"].value)
                v2 = float(ws["F5"].value)
                v3 = float(ws["G5"].value) if ws["G5"].value is not None else 0.50
                v4 = float(ws["H5"].value) if ws["H5"].value is not None else 1.00
                p2_rule = {0: 0.0, 1: v1, 2: v2, 3: v3, 4: v4}
            else:
                raise ValueError("Use fallback")
        except Exception:
            raw_p2_rule = str(ws["D4"].value or "0.1, 0.25, 0.5, 1.0").strip()
            try:
                p2_list = [float(x.strip()) for x in raw_p2_rule.split(",")]
                p2_rule = {0: 0.0, 1: p2_list[0], 2: p2_list[1], 3: p2_list[2], 4: p2_list[3]}
            except Exception:
                p2_rule = {0: 0.0, 1: 0.1, 2: 0.25, 3: 0.5, 4: 1.0}

        # 4. Đọc Header ở dòng 7
        header_row = 7
        col_map = {}
        for c in range(1, ws.max_column + 1):
            v = ws.cell(row=header_row, column=c).value
            if v:
                col_map[c] = str(v).strip()

        # 5. Đọc Đáp án từng Mã đề
        answer_keys = {}
        for r in range(header_row + 1, ws.max_row + 1):
            code_v = ws.cell(row=r, column=1).value
            if not code_v:
                continue
            exam_code = str(code_v).strip().zfill(4)

            p1_dict = {}
            p2_dict = {}
            p3_dict = {}

            for c, h_name in col_map.items():
                if c == 1:
                    continue
                raw_cell = ws.cell(row=r, column=c).value
                if raw_cell is None:
                    continue
                ans_str = str(raw_cell).strip().upper()
                if not ans_str:
                    continue

                if h_name.startswith("P1_C"):
                    q_num = int(h_name.split("_C")[1])
                    p1_dict[q_num] = ans_str

                elif h_name.startswith("P2_C"):
                    parts = h_name.split("_")
                    q_num = int(parts[1][1:])
                    sub_k = parts[2].lower()
                    if q_num not in p2_dict:
                        p2_dict[q_num] = {}
                    p2_dict[q_num][sub_k] = ans_str

                elif h_name.startswith("P3_C"):
                    q_num = int(h_name.split("_C")[1])
                    try:
                        p3_dict[q_num] = float(ans_str.replace(",", "."))
                    except ValueError:
                        pass

            answer_keys[exam_code] = {
                "part1": p1_dict,
                "part2": p2_dict,
                "part3": p3_dict
            }

        return {
            "exam_name": exam_name,
            "config": {
                "pts_p1": pts_p1,
                "pts_p2_rule": p2_rule,
                "pts_p3": pts_p3
            },
            "answer_keys": answer_keys
        }

    @classmethod
    def smart_parse_text_keys(cls, text: str, default_made: str = "0001") -> Dict[str, Any]:
        """
        Bộ bóc tách đáp án thông minh từ văn bản thô (Word, Zalo, SMS, Excel copy-paste).
        Hỗ trợ dán đồng thời nhiều mã đề hoặc một mã đề đơn lẻ.
        """
        import re
        raw = str(text or "").replace("\r", "\n")
        made_blocks = re.split(r'(?i)(?:^|\n)\s*(?:MÃ ĐỀ|MÃ DE|MA DE|ĐỀ|DE)\s*[:#\s]*(\d+)', raw)
        
        answer_keys = {}
        if len(made_blocks) > 1 and made_blocks[1].isdigit():
            i = 1
            while i < len(made_blocks):
                code = made_blocks[i].strip().zfill(4)
                content = made_blocks[i+1] if i+1 < len(made_blocks) else ""
                answer_keys[code] = cls._parse_single_key_block(content)
                i += 2
        else:
            lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
            first_line = lines[0] if lines else ""
            code = default_made.zfill(4)
            body = raw
            if re.match(r'^\d{3,4}$', first_line):
                code = first_line.zfill(4)
                body = "\n".join(lines[1:])
            answer_keys[code] = cls._parse_single_key_block(body)
            
        return {
            "exam_name": "Nhập đáp án thông minh (Smart Paste)",
            "config": {
                "pts_p1": 0.25,
                "pts_p2_rule": {0: 0.0, 1: 0.1, 2: 0.25, 3: 0.5, 4: 1.0},
                "pts_p3": 0.25
            },
            "answer_keys": answer_keys
        }

    @classmethod
    def _parse_single_key_block(cls, text: str) -> Dict[str, Any]:
        import re
        p1, p2, p3 = {}, {}, {}
        norm = text.upper().replace("Ð", "Đ")
        
        # Sắp xếp các cụm từ dài trước (III rồi II rồi I) để tránh khớp tiền tố nhầm lẫn
        sec_regex = r'(?i)(?:^|\n)\s*(PHẦN\s*III\b|PHAN\s*3\b|TLN\b|PHẦN\s*II\b|PHAN\s*2\b|DS\b|ĐS\b|PHẦN\s*I\b|PHAN\s*1\b|TN\b)\s*[:\-\.]?'
        matches = list(re.finditer(sec_regex, norm))
        
        p1_text, p2_text, p3_text = "", "", ""
        if matches:
            for idx, m in enumerate(matches):
                label = m.group(1).upper()
                start = m.end()
                end = matches[idx+1].start() if idx+1 < len(matches) else len(norm)
                chunk = norm[start:end]
                if any(k in label for k in ["III", "3", "TLN"]):
                    p3_text += "\n" + chunk
                elif any(k in label for k in ["II", "2", "DS", "ĐS"]):
                    p2_text += "\n" + chunk
                elif any(k in label for k in ["I", "1", "TN"]):
                    p1_text += "\n" + chunk
        else:
            lines_text = [l.strip() for l in norm.split("\n") if l.strip()]
            for line in lines_text:
                if re.search(r'[ĐS]', line) and not re.search(r'[A-D]', line):
                    p2_text += "\n" + line
                elif re.search(r'\d+(?:[.,]\d+)?', line) and not re.search(r'[A-DĐS]', line):
                    p3_text += "\n" + line
                else:
                    p1_text += "\n" + line

        # 1. Phần I
        p1_items = re.findall(r'(?:^|[\s;,]|câu\s*)(\d{1,2})[\.:\)\-\s]*([ABCD])\b', p1_text, re.IGNORECASE)
        if p1_items:
            for q_str, ans in p1_items:
                q_num = int(q_str)
                if 1 <= q_num <= cls.MAX_P1:
                    p1[q_num] = ans.upper()
        else:
            tokens = re.findall(r'\b[ABCD]+\b', p1_text)
            flat_chars = "".join(tokens)
            for idx, char in enumerate(flat_chars[:cls.MAX_P1], start=1):
                p1[idx] = char

        # 2. Phần II: Hỗ trợ linh hoạt cả khối câu 'Câu 1: a) Đ, b) S...' và dạng lặp '1a: Đ, 1b: S...'
        q_blocks = re.split(r'(?i)(?:^|\n)\s*(?:câu\s*)?(\d{1,2})\s*[:\.\)]', p2_text)
        if len(q_blocks) > 1:
            for i in range(1, len(q_blocks), 2):
                try:
                    q_num = int(q_blocks[i])
                    if 1 <= q_num <= cls.MAX_P2:
                        block = q_blocks[i+1]
                        subs = re.findall(r'([ABCDa-d])[\.:\)\-\s]*([ĐS])', block)
                        if subs:
                            p2[q_num] = {k.lower(): v for k, v in subs}
                except (ValueError, IndexError):
                    pass

        if not p2:
            p2_sub_items = re.findall(r'(?:^|[\s;,]|câu\s*)(\d{1,2})\s*([ABCDa-d])[\.:\)\-\s]*([ĐS])\b', p2_text, re.IGNORECASE)
            if p2_sub_items:
                for q_str, sub_key, val in p2_sub_items:
                    q_num = int(q_str)
                    if 1 <= q_num <= cls.MAX_P2:
                        if q_num not in p2:
                            p2[q_num] = {}
                        p2[q_num][sub_key.lower()] = val.upper()

        if not p2:
            for line in p2_text.split('\n'):
                line = line.strip()
                m = re.match(r'^(?:câu\s*)?(\d{1,2})[\.:\)\-\s]*([ĐS\s]{4,})', line, re.IGNORECASE)
                if m:
                    q_num = int(m.group(1))
                    chars = [c for c in m.group(2) if c in "ĐS"]
                    if len(chars) == 4 and 1 <= q_num <= cls.MAX_P2:
                        p2[q_num] = {"a": chars[0], "b": chars[1], "c": chars[2], "d": chars[3]}
            if not p2:
                all_ds = [c for c in p2_text if c in "ĐS"]
                num_rows = min(len(all_ds) // 4, cls.MAX_P2)
                for r_idx in range(num_rows):
                    chunk = all_ds[r_idx*4 : (r_idx+1)*4]
                    p2[r_idx + 1] = {"a": chunk[0], "b": chunk[1], "c": chunk[2], "d": chunk[3]}

        # 3. Phần III
        p3_items = re.findall(r'(?:^|[\s;,]|câu\s*)(\d{1,2})[:\)\.\s]+(-?\d+(?:[.,]\d+)?)\b', p3_text, re.IGNORECASE)
        if p3_items:
            for q_str, val_str in p3_items:
                q_num = int(q_str)
                if 1 <= q_num <= cls.MAX_P3:
                    try:
                        p3[q_num] = float(val_str.replace(",", "."))
                    except ValueError:
                        pass
        else:
            num_tokens = re.findall(r'-?\d+(?:[.,]\d+)?', p3_text)
            for idx, val_str in enumerate(num_tokens[:cls.MAX_P3], start=1):
                try:
                    p3[idx] = float(val_str.replace(",", "."))
                except ValueError:
                    pass

        return {"part1": p1, "part2": p2, "part3": p3}

```

## FILE: full_grading_pipeline.py
```py
# full_grading_pipeline.py
# -*- coding: utf-8 -*-
"""
HỆ THỐNG CHẤM THI OMR TOÀN DIỆN - PRODUCTION V6.5 (STRICT AUDIT & FAIL-SAFE CORE)
Chuẩn hóa Giai đoạn 1:
- Khử hoàn toàn cơ chế Fuzzy Matching mã đề (chống chấm nhầm đề).
- Xử lý tô đúp Phần I và Phần II chuẩn quy chế thi: Gán MULTIPLE / ĐS -> 0 điểm.
- Khóa toàn bộ đáp án mẫu ngầm: Chỉ chấm khi đợt thi đã nạp đáp án hợp lệ.
- Chuẩn hóa dữ liệu Phần III: Hỗ trợ linh hoạt cả Object OMR lẫn giá trị số Float từ giao diện sửa tay.
- Tương thích 100% với VisualStamper và cơ chế giải quyết đường dẫn Runtime.
"""
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from visual_stamper import VisualStamper

CANONICAL_WIDTH = 1769
CANONICAL_HEIGHT = 2526


def resolve_data_path(rel_path: str) -> Path:
    """Tự động tìm kiếm đường dẫn tệp tài nguyên an toàn trên mọi môi trường."""
    p_rel = Path(rel_path)
    candidates = [
        p_rel,
        Path(sys.executable).resolve().parent / p_rel if getattr(sys, "frozen", False) else None,
        Path(getattr(sys, "_MEIPASS", "")) / p_rel if getattr(sys, "frozen", False) else None,
        Path(sys.executable).resolve().parent / "_internal" / p_rel if getattr(sys, "frozen", False) else None,
        Path(__file__).resolve().parent / p_rel,
    ]
    for cand in candidates:
        if cand is not None and cand.exists():
            return cand
    return p_rel


def normalize_answer_keys(raw_keys: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Chuẩn hóa toàn bộ số thứ tự câu hỏi và giá trị barem đáp án."""
    normalized = {}
    for code, data in (raw_keys or {}).items():
        code_str = str(code).strip().zfill(4)
        data = data or {}

        p1 = {int(q): str(ans).strip().upper() for q, ans in data.get("part1", {}).items() if str(ans).strip()}
        p2 = {
            int(q): {str(sk).strip().lower(): str(sv).strip().upper() for sk, sv in sdict.items() if str(sv).strip()}
            for q, sdict in data.get("part2", {}).items() if sdict
        }
        p3 = {}
        for q, val in data.get("part3", {}).items():
            if val is not None and str(val).strip() != "":
                try:
                    p3[int(q)] = float(str(val).replace(",", "."))
                except ValueError:
                    pass
        normalized[code_str] = {"part1": p1, "part2": p2, "part3": p3}
    return normalized


class Part3ShadowfixReader:
    def __init__(self, p3_coords: List[Dict[str, Any]], scale: float, template_ink_map: Optional[np.ndarray] = None):
        self.coords = p3_coords
        self.scale = scale
        self.core_r = 4.5 * scale
        self.search_r = int(round(4.5 * scale))
        self.ring_in = 7.2 * scale
        self.ring_out = 10.8 * scale
        self.template_ink_map = template_ink_map

    def _build_gradient_response(self, gray: np.ndarray) -> np.ndarray:
        smoothed = cv2.GaussianBlur(gray, (0, 0), sigmaX=max(0.8, 1.0 * self.scale), sigmaY=max(0.8, 1.0 * self.scale))
        gx = cv2.Sobel(smoothed, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(smoothed, cv2.CV_32F, 0, 1, ksize=3)
        mag = cv2.magnitude(gx, gy)
        r = int(np.ceil(self.ring_out))
        yy, xx = np.ogrid[-r:r+1, -r:r+1]
        dist = np.sqrt(xx * xx + yy * yy)
        mask = ((dist >= self.ring_in) & (dist <= self.ring_out)).astype(np.float32)
        kernel = mask / float(mask.sum()) if mask.sum() > 0 else mask
        return cv2.filter2D(mag, cv2.CV_32F, kernel, borderType=cv2.BORDER_REFLECT)

    def _refine_and_score(self, ink_map: np.ndarray, resp: np.ndarray, x: float, y: float) -> Tuple[float, Tuple[int, int]]:
        xi, yi = int(round(x)), int(round(y))
        h, w = resp.shape
        x1, x2 = max(0, xi - self.search_r), min(w, xi + self.search_r + 1)
        y1, y2 = max(0, yi - self.search_r), min(h, yi + self.search_r + 1)
        patch = resp[y1:y2, x1:x2]
        yy, xx = np.mgrid[y1:y2, x1:x2]
        adjusted = patch - 0.4 * np.sqrt((xx - x) ** 2 + (yy - y) ** 2)
        iy, ix = np.unravel_index(np.argmax(adjusted), adjusted.shape)
        cx, cy = int(x1 + ix), int(y1 + iy)

        r = max(1, int(round(self.core_r)))
        if cx - r < 0 or cy - r < 0 or cx + r >= w or cy + r >= h:
            return 0.0, (cx, cy)
        yy, xx = np.ogrid[-r:r+1, -r:r+1]
        val = float(np.mean(ink_map[cy - r:cy + r + 1, cx - r:cx + r + 1][xx * xx + yy * yy <= r * r]))

        # Trừ nền mực từ phôi gốc nếu có (chỉ trừ mực in sẵn > 0, không trừ số âm)
        if self.template_ink_map is not None:
            th, tw = self.template_ink_map.shape
            if cx - r >= 0 and cy - r >= 0 and cx + r < tw and cy + r < th:
                tpl_val = max(0.0, float(np.mean(self.template_ink_map[cy - r:cy + r + 1, cx - r:cx + r + 1][xx * xx + yy * yy <= r * r])))
            else:
                tpl_val = 0.0
            net_val = max(0.0, val - tpl_val * 0.90)
        else:
            net_val = max(0.0, val)

        return net_val, (cx, cy)

    def read_filtered(self, gray: np.ndarray, ink_map: np.ndarray, active_q_nums: List[int]) -> Tuple[Dict[int, Dict[str, Any]], List[Dict[str, str]]]:
        # Tối ưu: Chỉ tính gradient response cho vùng Phần III (Y từ 1680 trở đi)
        y_start = 1680
        h_full, w_full = gray.shape[:2]
        gray_p3 = gray[y_start:h_full, :]
        resp_p3 = self._build_gradient_response(gray_p3)
        resp = np.zeros((h_full, w_full), dtype=np.float32)
        resp[y_start:h_full, :] = resp_p3

        results = {}
        anomalies = []
        active_set = {int(q) for q in active_q_nums}

        for q in self.coords:
            q_num = int(q["question"])
            if q_num not in active_set:
                continue

            q_errors = []

            # Đọc dấu âm (-)
            s_val, _ = self._refine_and_score(ink_map, resp, q["sign"][0], q["sign"][1])
            has_minus = s_val >= 14.5

            # Đọc dấu phẩy (,)
            comma_hits = []
            for idx, cpos in enumerate(q["comma_positions"]):
                c_val, _ = self._refine_and_score(ink_map, resp, cpos[0], cpos[1])
                if c_val >= 14.5:
                    comma_hits.append(idx + 1)

            if len(comma_hits) > 1:
                q_errors.append("Tô đúp dấu phẩy")
                comma_opt = None
            elif len(comma_hits) == 1:
                comma_opt = comma_hits[0]
            else:
                comma_opt = None

            # Đọc 4 cột chữ số (0..9)
            col_digits: List[List[str]] = [[] for _ in range(4)]
            for col in range(4):
                net_scores = []
                for d in range(10):
                    val, _ = self._refine_and_score(ink_map, resp, q["digits"][str(d)][col][0], q["digits"][str(d)][col][1])
                    net_scores.append(val)

                # Nền động cột = phân vị 60%
                col_bg = float(np.percentile(net_scores, 60))
                rel_scores = [max(0.0, s - col_bg) for s in net_scores]

                ranked = sorted(enumerate(rel_scores), key=lambda x: x[1], reverse=True)
                top_d, top_rel = ranked[0]
                sec_d, sec_rel = ranked[1]

                # Kết luận tô đúp
                if top_rel >= 15.5 and sec_rel >= 14.5 and (top_rel - sec_rel) < 8.0:
                    col_digits[col] = [str(top_d), str(sec_d)]
                # Kết luận tô hợp lệ 1 chữ số (bắt trọn nét chì nhạt, không bỏ sót)
                elif top_rel >= 11.5 and (top_rel - sec_rel) >= 6.5:
                    col_digits[col] = [str(top_d)]
                else:
                    col_digits[col] = []

            col_filled = [len(digits) > 0 for digits in col_digits]

            for c_i, hits in enumerate(col_digits):
                if len(hits) > 1:
                    q_errors.append(f"Cột {c_i + 1} tô đúp ({', '.join(hits)})")

            if any(col_filled):
                first_idx = col_filled.index(True)
                seen_empty = False
                for c_i in range(first_idx, 4):
                    if not col_filled[c_i]:
                        seen_empty = True
                    elif seen_empty:
                        q_errors.append(f"Cột {c_i + 1} bị bỏ cách quãng")
                        break

            raw_tokens = []
            if has_minus:
                raw_tokens.append("-")
            for c_i, hits in enumerate(col_digits):
                if not hits:
                    raw_tokens.append("_")
                elif len(hits) == 1:
                    raw_tokens.append(hits[0])
                else:
                    raw_tokens.append(f"[{''.join(hits)}]")
                if comma_opt == (c_i + 1):
                    raw_tokens.append(",")

            raw_str = "".join(raw_tokens)
            norm_val = None
            is_valid = (len(q_errors) == 0 and any(col_filled))

            if is_valid:
                num_str = ("-" if has_minus else "")
                for c_i in range(4):
                    if not col_digits[c_i]:
                        break
                    num_str += col_digits[c_i][0]
                    if comma_opt == (c_i + 1):
                        num_str += "."
                try:
                    norm_val = float(num_str)
                except ValueError:
                    is_valid = False
                    norm_val = None

            if q_errors:
                anomalies.append({
                    "type": f"P3_Q{q_num}_VIOLATION",
                    "msg": f"Phần III Câu {q_num} phạm quy chế: " + "; ".join(q_errors)
                })

            results[q_num] = {
                "raw_string": raw_str,
                "normalized_value": norm_val,
                "is_valid": is_valid,
                "anomalies": q_errors
            }

        return results, anomalies


class FullGradingPipeline:
    def __init__(self, exam_data: Optional[Dict[str, Any]] = None):
        header_coord_path = resolve_data_path("output/header_coordinates.json")
        p1_path = resolve_data_path("output/part1_coordinates.json")
        p2_path = resolve_data_path("output/part2_coordinates.json")
        p3_path = resolve_data_path("output/part3_coordinates.json")

        # Tự phục hồi tọa độ nếu thiếu bất kỳ tệp nào, chống sập server lúc khởi động (Zero-Downtime Boot)
        if not (header_coord_path.exists() and p1_path.exists() and p2_path.exists() and p3_path.exists()):
            try:
                from restore_coordinates import restore_all_coordinates
                restore_all_coordinates(output_dir_param=header_coord_path.parent)
                print("[INFO] Đã tự động khôi phục toàn bộ tệp tọa độ OMR.")
            except Exception as e:
                print(f"[WARN] Không thể tự phục hồi tọa độ OMR: {e}")

        if not header_coord_path.exists():
            raise FileNotFoundError(f"Chưa tìm thấy tệp tọa độ: {header_coord_path}")

        with open(header_coord_path, "r", encoding="utf-8") as f:
            header_data = json.load(f)
            self.sbd_columns = header_data["sbd_columns"]
            self.made_columns = header_data["made_columns"]

        with open(p1_path, "r", encoding="utf-8") as f:
            self.p1_coords = json.load(f)["questions"]
        with open(p2_path, "r", encoding="utf-8") as f:
            self.p2_coords = json.load(f)["questions"]
        with open(p3_path, "r", encoding="utf-8") as f:
            self.p3_coords = json.load(f)["questions"]

        # Nạp bản đồ mực phôi gốc dùng chung cho mọi phần
        self.template_ink_map = None
        tpl_path = resolve_data_path("output/answer_sheet_master.png")
        if tpl_path.exists():
            tpl_bgr = cv2.imread(str(tpl_path))
            if tpl_bgr is not None and tpl_bgr.shape[:2] == (CANONICAL_HEIGHT, CANONICAL_WIDTH):
                tpl_gray = cv2.cvtColor(tpl_bgr, cv2.COLOR_BGR2GRAY)
                th, tw = tpl_gray.shape[:2]
                st_w, st_h = max(100, tw // 4), max(100, th // 4)
                s_tpl = cv2.resize(tpl_gray, (st_w, st_h), interpolation=cv2.INTER_AREA)
                s_bg = cv2.GaussianBlur(s_tpl, (0, 0), sigmaX=5.5, sigmaY=5.5, borderType=cv2.BORDER_REFLECT)
                tpl_bg = cv2.resize(s_bg, (tw, th), interpolation=cv2.INTER_LINEAR)
                self.template_ink_map = tpl_bg.astype(np.float32) - tpl_gray.astype(np.float32)

        scale = CANONICAL_WIDTH / 1434.0
        self.p3_reader = Part3ShadowfixReader(self.p3_coords, scale, template_ink_map=self.template_ink_map)
        self.stamper = VisualStamper

        # Precompute kernel và penalty grid cho dò tâm nhanh
        self._kernel_cache = {}
        for rc in [7, 8]:
            yy_c, xx_c = np.ogrid[-rc : rc + 1, -rc : rc + 1]
            c_mask = (xx_c * xx_c + yy_c * yy_c <= rc * rc).astype(np.float32)
            c_mask /= float(c_mask.sum())
            self._kernel_cache[rc] = c_mask

        yy_p, xx_p = np.mgrid[-8:9:2, -8:9:2]
        self._penalty_grid_8 = (0.2 * np.hypot(xx_p, yy_p)).astype(np.float32)

        # KHÓA BỘ ĐÁP ÁN: Tuyệt đối không nạp ngầm đáp án mẫu khi đợt thi chưa cấu hình
        if exam_data and exam_data.get("answer_keys"):
            self.exam_name = exam_data.get("exam_name", "Kiểm tra trắc nghiệm")
            self.config = exam_data.get("config", {
                "pts_p1": 0.25,
                "pts_p2_rule": {0: 0.0, 1: 0.1, 2: 0.25, 3: 0.5, 4: 1.0},
                "pts_p3": 0.25
            })
            self.answer_keys = normalize_answer_keys(exam_data.get("answer_keys", {}))
            self.is_configured = True
        else:
            self.exam_name = "Chưa nạp đáp án"
            self.config = {
                "pts_p1": 0.25,
                "pts_p2_rule": {0: 0.0, 1: 0.1, 2: 0.25, 3: 0.5, 4: 1.0},
                "pts_p3": 0.25
            }
            self.answer_keys = {}
            self.is_configured = False

    @staticmethod
    def _eval_bubble_ink(
        ink_map: np.ndarray,
        cx: float,
        cy: float,
        r_core: int = 8,
        template_ink_map: Optional[np.ndarray] = None,
        tpl_coeff: float = 0.85
    ) -> float:
        xi, yi = int(round(cx)), int(round(cy))
        h, w = ink_map.shape
        if xi - r_core < 0 or yi - r_core < 0 or xi + r_core >= w or yi + r_core >= h:
            return 0.0
        patch = ink_map[yi - r_core : yi + r_core + 1, xi - r_core : xi + r_core + 1]
        yy, xx = np.ogrid[-r_core : r_core + 1, -r_core : r_core + 1]
        mask = (xx * xx + yy * yy) <= (r_core * r_core)
        raw_val = float(np.mean(patch[mask]))

        if template_ink_map is not None:
            th, tw = template_ink_map.shape
            if xi - r_core >= 0 and yi - r_core >= 0 and xi + r_core < tw and yi + r_core < th:
                tpl_patch = template_ink_map[yi - r_core : yi + r_core + 1, xi - r_core : xi + r_core + 1]
                tpl_val = max(0.0, float(np.mean(tpl_patch[mask])))
                return max(0.0, raw_val - tpl_val * tpl_coeff)
        return raw_val

    def _eval_bubble_ink_refined(
        self,
        ink_map: np.ndarray,
        cx: float,
        cy: float,
        r_core: int = 7,
        search_r: int = 8
    ) -> float:
        """
        Dò tâm ô tròn bán kính rộng (Bubble Center Snapping):
        Vectorized 2D grid lookup không dùng vòng lặp Python, tăng tốc 5-10x.
        """
        xi0, yi0 = int(round(cx)), int(round(cy))
        h, w = ink_map.shape
        pad = search_r + r_core
        if xi0 - pad < 0 or yi0 - pad < 0 or xi0 + pad >= w or yi0 + pad >= h:
            return self._eval_bubble_ink(ink_map, cx, cy, r_core, self.template_ink_map, 0.85)

        patch_ink = ink_map[yi0 - pad : yi0 + pad + 1, xi0 - pad : xi0 + pad + 1]
        if self.template_ink_map is not None:
            th, tw = self.template_ink_map.shape
            if yi0 - pad >= 0 and xi0 - pad >= 0 and yi0 + pad + 1 <= th and xi0 + pad + 1 <= tw:
                patch_tpl = self.template_ink_map[yi0 - pad : yi0 + pad + 1, xi0 - pad : xi0 + pad + 1]
                patch_net = np.maximum(0.0, patch_ink - patch_tpl * 0.85)
            else:
                patch_net = np.maximum(0.0, patch_ink)
        else:
            patch_net = np.maximum(0.0, patch_ink)

        core_mask = self._kernel_cache.get(r_core)
        if core_mask is None:
            yy, xx = np.ogrid[-r_core : r_core + 1, -r_core : r_core + 1]
            core_mask = (xx * xx + yy * yy <= r_core * r_core).astype(np.float32)
            c_sum = float(core_mask.sum())
            if c_sum > 0:
                core_mask /= c_sum
            self._kernel_cache[r_core] = core_mask

        core_resp = cv2.filter2D(patch_net, -1, core_mask)

        # Lấy lưới mẫu với bước nhảy 2px xung quanh tâm pad
        sample_grid = core_resp[pad - search_r : pad + search_r + 1 : 2, pad - search_r : pad + search_r + 1 : 2]
        if search_r == 8 and hasattr(self, "_penalty_grid_8"):
            penalties = self._penalty_grid_8
        else:
            yy_p, xx_p = np.mgrid[-search_r : search_r + 1 : 2, -search_r : search_r + 1 : 2]
            penalties = 0.2 * np.hypot(xx_p, yy_p).astype(np.float32)

        adjusted = np.maximum(0.0, sample_grid - penalties)
        return float(np.max(adjusted))

    def _read_header_ink(self, ink_map: np.ndarray) -> Tuple[str, str, str, List[Dict[str, str]]]:
        """Đọc Số báo danh và Mã đề với Bubble Center Snapping và thích ứng phân vị động."""
        anomalies = []

        def decode_grid(cols, grid_name="SBD"):
            res = []
            for col_idx, col in enumerate(cols, start=1):
                raw_scores = [
                    self._eval_bubble_ink_refined(
                        ink_map,
                        col["digits"][str(d)][0],
                        col["digits"][str(d)][1],
                        r_core=7,
                        search_r=8
                    )
                    for d in range(10)
                ]
                col_baseline = float(np.percentile(raw_scores, 50))
                net_scores = [max(0.0, s - col_baseline) for s in raw_scores]

                ranked = sorted(enumerate(net_scores), key=lambda x: x[1], reverse=True)
                top_d, top_net = ranked[0]
                sec_d, sec_net = ranked[1]
                top_raw = raw_scores[top_d]

                if sec_net >= 13.5 and (top_net - sec_net) < 8.5:
                    res.append(f"[{top_d}{sec_d}]")
                    anomalies.append({
                        "type": f"{grid_name}_DOUBLE_FILL",
                        "msg": f"{grid_name} Cột {col_idx} tô đúp ({top_d} và {sec_d})"
                    })
                elif top_net >= 12.0 and top_raw >= 15.5:
                    res.append(str(top_d))
                else:
                    res.append("?")
            return "".join(res)

        sbd = decode_grid(self.sbd_columns, "SBD")
        raw_made = decode_grid(self.made_columns, "MADE")

        if "?" in sbd or "[" in sbd:
            anomalies.append({"type": "MISSING_SBD", "msg": f"Số báo danh chưa rõ ràng ({sbd})"})

        final_made = ""
        if raw_made.isdigit() and len(raw_made) == 4:
            if not self.answer_keys:
                final_made = raw_made
                anomalies.append({"type": "NO_ANSWER_KEY", "msg": "Đợt thi chưa nạp đáp án để đối chiếu mã đề"})
            elif raw_made in self.answer_keys:
                final_made = raw_made
            else:
                final_made = raw_made
                anomalies.append({"type": "UNKNOWN_CODE", "msg": f"Mã đề {raw_made} không tồn tại trong barem đáp án"})
        else:
            final_made = ""
            anomalies.append({"type": "INVALID_EXAM_CODE", "msg": f"Mã đề thi chưa rõ ràng hoặc tô lỗi ({raw_made})"})

        return sbd, raw_made, final_made, anomalies

    def process_sheet(self, image_bgr: np.ndarray, file_name: str, forced_exam_code: Optional[str] = None) -> Dict[str, Any]:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

        # 0. KHỬ MỜ VI RUNG TAY BẰNG UNSHARP MASK NẾU ẢNH HƠI MỀM NÉT
        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if lap_var < 28.0:
            blurred_sharp = cv2.GaussianBlur(gray, (0, 0), sigmaX=1.5, sigmaY=1.5)
            gray = cv2.addWeighted(gray, 1.55, blurred_sharp, -0.55, 0)

        # 1. TẠO INK MAP TOÀN CỤC (Kỹ thuật Downscale-Blur-Upscale tăng tốc 15-20 lần)
        h_g, w_g = gray.shape[:2]
        small_w, small_h = max(100, w_g // 4), max(100, h_g // 4)
        small_gray = cv2.resize(gray, (small_w, small_h), interpolation=cv2.INTER_AREA)
        small_bg = cv2.GaussianBlur(small_gray, (0, 0), sigmaX=5.5, sigmaY=5.5, borderType=cv2.BORDER_REFLECT)
        bg = cv2.resize(small_bg, (w_g, h_g), interpolation=cv2.INTER_LINEAR)
        ink_map = bg.astype(np.float32) - gray.astype(np.float32)

        # 2. ĐỌC HEADER
        sbd, raw_made, detected_made, h_anom = self._read_header_ink(ink_map)
        
        # Nếu giáo viên cưỡng chế mã đề (sửa tay), sử dụng forced_exam_code
        if forced_exam_code and str(forced_exam_code).strip():
            exam_code = str(forced_exam_code).strip().zfill(4)
            h_anom = [
                a for a in h_anom
                if not a.get("type", "").startswith("MADE_")
                and a.get("type") not in {"INVALID_EXAM_CODE", "UNKNOWN_CODE", "NO_ANSWER_KEY"}
            ]
            if self.answer_keys and exam_code not in self.answer_keys:
                h_anom.append({"type": "UNKNOWN_CODE", "msg": f"Mã đề {exam_code} không tồn tại trong barem đáp án"})
        else:
            exam_code = detected_made

        # 3. XÁC ĐỊNH PHẠM VI CÂU HỎI (KẾ THỪA CẤU TRÚC ĐỢT THI, KHÔNG BAO GIỜ BỎ SÓT PHẦN II, III)
        key_dict = self.answer_keys.get(exam_code, {}) if exam_code else {}
        global_p1 = set().union(*[{int(q) for q in k.get("part1", {}).keys()} for k in self.answer_keys.values()]) if self.answer_keys else set()
        global_p2 = set().union(*[{int(q) for q in k.get("part2", {}).keys()} for k in self.answer_keys.values()]) if self.answer_keys else set()
        global_p3 = set().union(*[{int(q) for q in k.get("part3", {}).keys()} for k in self.answer_keys.values()]) if self.answer_keys else set()

        active_p1 = {int(q) for q in key_dict.get("part1", {}).keys()} if key_dict.get("part1") else (global_p1 or set(range(1, 17)))
        active_p2 = {int(q) for q in key_dict.get("part2", {}).keys()} if key_dict.get("part2") else (global_p2 or set(range(1, 3)))
        active_p3 = {int(q) for q in key_dict.get("part3", {}).keys()} if key_dict.get("part3") else (global_p3 or set(range(1, 5)))

        # 4. QUÉT PHẦN I (TRẮC NGHIỆM 4 LỰA CHỌN)
        p1_res = {}
        p1_anom = []

        for q in self.p1_coords:
            q_num = int(q["question"])
            if q_num not in active_p1:
                continue
            scores = {
                opt: self._eval_bubble_ink_refined(
                    ink_map,
                    q["choices"][opt][0],
                    q["choices"][opt][1],
                    r_core=8,
                    search_r=8
                )
                for opt in ["A", "B", "C", "D"]
            }
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            top_opt, top_val = ranked[0]
            sec_opt, sec_val = ranked[1]
            row_bg = float(np.percentile(list(scores.values()), 50))
            top_rel = top_val - row_bg

            if sec_val >= 15.0 and (top_val - sec_val) < 8.0:
                p1_res[q_num] = "MULTIPLE"
                p1_anom.append({"type": "P1_DOUBLE_FILL", "msg": f"Phần I Câu {q_num} tô đúp ({top_opt} và {sec_opt})"})
            elif top_val >= 14.0 or (top_rel >= 10.0 and (top_val - sec_val) >= 6.8):
                p1_res[q_num] = top_opt
            else:
                p1_res[q_num] = ""

        # 5. QUÉT PHẦN II (ĐÚNG / SAI BẬC THANG)
        p2_res = {}
        p2_anom = []

        for q in self.p2_coords:
            q_num = int(q["question"])
            if q_num not in active_p2:
                continue
            row_dict = {}
            for rk in ["a", "b", "c", "d"]:
                tx, ty = q["rows"][rk]["true"]
                fx, fy = q["rows"][rk]["false"]
                st = self._eval_bubble_ink_refined(ink_map, tx, ty, r_core=8, search_r=8)
                sf = self._eval_bubble_ink_refined(ink_map, fx, fy, r_core=8, search_r=8)

                if st >= 18.0 and sf >= 18.0 and abs(st - sf) < 8.5:
                    row_dict[rk] = "ĐS"
                    p2_anom.append({"type": "P2_DOUBLE_FILL", "msg": f"Phần II Câu {q_num}{rk} tô cả Đúng và Sai"})
                elif max(st, sf) >= 11.0 and abs(st - sf) >= 6.8:
                    row_dict[rk] = "Đ" if st > sf else "S"
                else:
                    row_dict[rk] = ""
            p2_res[q_num] = row_dict

        # 6. QUÉT PHẦN III (TRẢ LỜI NGẮN)
        p3_res, p3_anom = self.p3_reader.read_filtered(gray, ink_map, list(active_p3))

        all_anom = h_anom + p1_anom + p2_anom + p3_anom
        score_res = self._grade(exam_code, p1_res, p2_res, p3_res)

        # PHÂN TÁCH TRẠNG THÁI NGHIỆP VỤ BÀI THI
        has_critical_error = any(
            a["type"] in {"INVALID_EXAM_CODE", "UNKNOWN_CODE", "NO_ANSWER_KEY", "MISSING_SBD"}
            or a["type"].endswith("DOUBLE_FILL")
            or "VIOLATION" in a["type"]
            for a in all_anom
        )

        if score_res.get("status") in {"UNKNOWN_CODE", "NO_ANSWER_KEY"}:
            status_flag = "NEEDS_REVIEW"
        elif has_critical_error:
            status_flag = "NEEDS_REVIEW"
            score_res["status"] = "NEEDS_REVIEW"
        else:
            status_flag = "GRADED"

        sub_res = {
            "file_name": file_name,
            "sbd": sbd,
            "exam_code": exam_code if exam_code else "CHƯA RÕ",
            "raw_exam_code": raw_made,
            "status": status_flag,
            "anomalies": all_anom,
            "scores": score_res,
            "details": {
                "part1": p1_res,
                "part2": p2_res,
                "part3": p3_res
            }
        }

        # 7. ĐÓNG TEM BÚT ĐỎ
        graded_bgr = VisualStamper.stamp_graded_sheet(
            image_bgr,
            sub_res,
            self.p1_coords,
            self.p2_coords,
            self.p3_coords,
            key_dict,
            sbd_columns=self.sbd_columns,
            made_columns=self.made_columns
        )
        sub_res["graded_image_bgr"] = graded_bgr

        return sub_res

    def _grade(self, code: str, p1: dict, p2: dict, p3: dict) -> Dict[str, Any]:
        if not self.answer_keys:
            return {"status": "NO_ANSWER_KEY", "p1": 0.0, "p2": 0.0, "p3": 0.0, "total": 0.0}

        code_str = str(code).strip().zfill(4) if code else ""
        if not code_str or code_str not in self.answer_keys:
            return {"status": "UNKNOWN_CODE", "p1": 0.0, "p2": 0.0, "p3": 0.0, "total": 0.0}

        key = self.answer_keys[code_str]
        pts_p1 = float(self.config.get("pts_p1", 0.25))
        raw_p2_rule = self.config.get("pts_p2_rule", {0: 0.0, 1: 0.1, 2: 0.25, 3: 0.5, 4: 1.0})
        if isinstance(raw_p2_rule, str):
            parts = [float(p.strip()) for p in raw_p2_rule.split(",") if p.strip()]
            if len(parts) == 4:
                p2_rule = {0: 0.0, 1: parts[0], 2: parts[1], 3: parts[2], 4: parts[3]}
            else:
                p2_rule = {0: 0.0, 1: 0.1, 2: 0.25, 3: 0.5, 4: 1.0}
        elif isinstance(raw_p2_rule, dict):
            p2_rule = {int(k): float(v) for k, v in raw_p2_rule.items()}
        else:
            p2_rule = {0: 0.0, 1: 0.1, 2: 0.25, 3: 0.5, 4: 1.0}
        pts_p3 = float(self.config.get("pts_p3", 0.25))

        p1_clean = {int(k): str(v).upper() for k, v in p1.items() if v}
        p2_clean = {int(k): {str(sk).lower(): str(sv).upper() for sk, sv in sdict.items()} for k, sdict in p2.items() if sdict}
        p3_clean = {int(k): v for k, v in p3.items() if v is not None}

        # Chấm Phần I (chỉ khớp các phương án hợp lệ; "MULTIPLE" tự động nhận 0đ)
        s_p1 = sum(pts_p1 for q, ans in key.get("part1", {}).items() if p1_clean.get(q) == ans and ans in ["A", "B", "C", "D"])

        # Chấm Phần II (chỉ khớp phương án Đ hoặc S duy nhất)
        s_p2 = 0.0
        for q, sub_map in key.get("part2", {}).items():
            correct_sub = sum(
                1 for sk, tf in sub_map.items()
                if p2_clean.get(q, {}).get(sk) == tf and p2_clean.get(q, {}).get(sk) in ["Đ", "S"]
            )
            s_p2 += p2_rule.get(correct_sub, 0.0)

        # SỬA LỖI 8: Chấm Phần III hỗ trợ cả Dict OMR lẫn số thực Float sửa tay
        s_p3 = 0.0
        for q, exp_v in key.get("part3", {}).items():
            val_item = p3_clean.get(q)
            if val_item is None:
                continue

            stu_val = None
            if isinstance(val_item, dict):
                if val_item.get("is_valid") and val_item.get("normalized_value") is not None:
                    stu_val = val_item["normalized_value"]
            elif isinstance(val_item, (int, float)):
                stu_val = float(val_item)

            if stu_val is not None and abs(stu_val - float(exp_v)) <= 1e-4:
                s_p3 += pts_p3

        total = round(s_p1 + s_p2 + s_p3, 2)
        return {
            "status": "GRADED",
            "p1": round(s_p1, 2),
            "p2": round(s_p2, 2),
            "p3": round(s_p3, 2),
            "total": total
        }
```

## FILE: main_desktop.py
```py
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

```

## FILE: package_all.py
```py
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

```

## FILE: quality_gate.py
```py
# quality_gate.py
# -*- coding: utf-8 -*-
"""
MODULE TIỀN KIỂM ĐỊNH CHẤT LƯỢNG ẢNH ĐẦU VÀO (INPUT QUALITY GATE)
Kiểm tra độ nét và ánh sáng trước khi đưa vào pipeline nhận diện OMR.
"""
from typing import Dict, Any, Tuple
import cv2
import numpy as np


class ImageQualityAssessment:
    # Ngưỡng Laplacian Variance tối thiểu để không bị mờ nhòe nát (Handheld Motion Blur Gate)
    BLUR_THRESHOLD: float = 6.0
    # Độ tương phản tối thiểu (độ lệch chuẩn độ xám toàn trang)
    CONTRAST_MIN_STD: float = 18.0
    # Độ sáng trung bình tối thiểu và tối đa [40, 248]
    MIN_MEAN_BRIGHTNESS: float = 40.0
    MAX_MEAN_BRIGHTNESS: float = 248.0
    # Tỷ lệ pixel quá tối (underexposed) hoặc quá sáng (burned out) tối đa (cho phép bàn tối màu 65%)
    MAX_EXTREME_PIXELS_RATIO: float = 0.65

    @classmethod
    def evaluate(cls, image_bgr: np.ndarray) -> Tuple[bool, Dict[str, Any]]:
        """
        Đánh giá chất lượng ảnh chụp bài thi.
        Trả về: (is_valid, metrics_dict)
        """
        if image_bgr is None or image_bgr.size == 0:
            return False, {"error": "Ảnh rỗng hoặc không thể giải mã."}

        h, w = image_bgr.shape[:2]
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

        # 1. Đánh giá độ nét (Sharpness) trên vùng trung tâm 75% (loại bỏ nền bàn trơn kéo tụt điểm)
        y0, y1 = int(round(0.12 * h)), int(round(0.88 * h))
        x0, x1 = int(round(0.12 * w)), int(round(0.88 * w))
        center_gray = gray[y0:y1, x0:x1] if (y1 > y0 and x1 > x0) else gray
        laplacian_var = float(cv2.Laplacian(center_gray, cv2.CV_64F).var())
        is_sharp = laplacian_var >= cls.BLUR_THRESHOLD

        # 2. Đánh giá dải tương phản (Dynamic Range / Contrast)
        std_dev = float(np.std(gray))
        mean_val = float(np.mean(gray))
        is_contrast_ok = std_dev >= cls.CONTRAST_MIN_STD

        # 3. Đánh giá độ sáng trung bình (Mean Brightness)
        is_brightness_ok = cls.MIN_MEAN_BRIGHTNESS <= mean_val <= cls.MAX_MEAN_BRIGHTNESS

        # 4. Đánh giá tỷ lệ bóng đen gắt và cháy sáng gắt
        dark_pixels = np.sum(gray < 35)
        bright_pixels = np.sum(gray > 252)
        extreme_ratio = float((dark_pixels + bright_pixels) / (h * w))
        is_lighting_acceptable = extreme_ratio <= cls.MAX_EXTREME_PIXELS_RATIO

        # Tổng hợp kết quả
        reasons = []
        if not is_sharp:
            reasons.append(f"Ảnh bị mờ nhòe/rung tay (Độ nét Laplacian: {laplacian_var:.1f} < {cls.BLUR_THRESHOLD})")
        if not is_contrast_ok:
            reasons.append(f"Độ tương phản quá yếu, ảnh bị xỉn hoặc mờ nhạt (Std: {std_dev:.1f} < {cls.CONTRAST_MIN_STD})")
        if not is_brightness_ok:
            if mean_val < cls.MIN_MEAN_BRIGHTNESS:
                reasons.append(f"Ảnh quá tối/thiếu sáng nghiêm trọng (Độ sáng TB: {mean_val:.1f} < {cls.MIN_MEAN_BRIGHTNESS})")
            else:
                reasons.append(f"Ảnh bị chói lóa/cháy sáng toàn trang (Độ sáng TB: {mean_val:.1f} > {cls.MAX_MEAN_BRIGHTNESS})")
        if not is_lighting_acceptable:
            reasons.append(f"Vùng bóng đen hoặc cháy sáng quá lớn ({extreme_ratio * 100:.1f}% diện tích)")

        is_passed = len(reasons) == 0

        return is_passed, {
            "is_passed": is_passed,
            "reasons": reasons,
            "metrics": {
                "sharpness_laplacian": round(laplacian_var, 1),
                "contrast_std": round(std_dev, 1),
                "mean_brightness": round(mean_val, 1),
                "extreme_lighting_ratio": round(extreme_ratio, 3),
                "resolution": f"{w}x{h}"
            }
        }

```

## FILE: README.md
```md
---
title: Cham Trac Nghiem
emoji: 📝
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
---

# OMR_EXAM_SYSTEM - Ứng Dụng Chấm Thi Trắc Nghiệm Di Động
Hệ thống chấm thi trắc nghiệm theo chuẩn Bộ GD&ĐT 2025 dành cho thiết bị di động.

```

## FILE: requirements.txt
```txt
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
python-multipart>=0.0.9
opencv-python-headless>=4.10.0
numpy>=1.26.0,<3.0.0
openpyxl>=3.1.2
pymupdf>=1.24.0
pydantic>=2.0.0

```

## FILE: run_desktop.py
```py
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


if __name__ == "__main__":
    multiprocessing.freeze_support()
    start_app()
```

## FILE: TASK.md
```md
# OMR EXAM SYSTEM 2026 - TASK TRACKER

## ĐÃ HOÀN THÀNH (STABLE)
- [x] Lõi nắn phẳng đa tầng: 4 dải (scan phẳng) & 4 mốc góc OMR (mobile).
- [x] Tự động phát hiện góc xoay (0°, 90°, 180°, 270°) và xoay thẳng đứng.
- [x] Quy chuẩn tem bút đỏ: Đúng = Xanh lá, Sai = Đỏ, Bỏ trống = Vàng hổ phách.
- [x] Tối ưu hóa dung lượng lưu trữ: JPEG Quality 90 + WebP (giảm 96% dung lượng đĩa).
- [x] Khử dấu tiếng Việt trong HTTP Header, sửa triệt để lỗi HTTP 500 khi xuất file.
- [x] Xuất PDF nhiều trang bằng PyMuPDF (fitz) tiết kiệm RAM, chống khóa file.
- [x] Xuất Excel bảng điểm an toàn, bắt ngoại lệ PermissionError.
- [x] Hộp thoại Save As chọn nơi lưu tệp cho PDF và Excel.
- [x] Loại bỏ ký tự Unicode lạ tránh lỗi charmap trên Windows .exe.

## BACKLOG TIẾP THEO (GIAI ĐOẠN 2 & 3)
- [x] Task 1: Tích hợp `quality_gate.py` vào luồng `_process_and_save` trong `app.py` (cảnh báo ảnh nhòe, rung tay hoặc lóa sáng trước khi nắn mốc).
- [ ] Task 2: Chuyển đổi nhãn điểm trên tem bút đỏ từ cố định "/ 10" sang thang điểm OMR động theo cấu hình thực tế của từng đề thi.
- [ ] Task 3: Bổ sung trường nhập điểm Tự luận thủ công ở Cột 2 và tính tổng điểm toàn bài (OMR + Tự luận).
```

## FILE: visual_stamper.py
```py
# visual_stamper.py
# -*- coding: utf-8 -*-
"""
MODULE VẼ OVERLAY CHẤM BÚT ĐỎ TRỰC TIẾP LÊN PHIẾU BÀI LÀM (PRODUCTION V6.9)
Quy chuẩn màu sắc trực quan:
- XANH LÁ (COLOR_GREEN)       : Câu/ý học sinh TÔ ĐÚNG.
- ĐỎ (COLOR_RED)              : Ô học sinh TÔ SAI hoặc TÔ ĐÚP vi phạm.
- VÀNG HỔ PHÁCH (COLOR_YELLOW): Đáp án đúng của các câu BỎ TRỐNG (KHÔNG TÔ).
"""
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import cv2
import re
import numpy as np


class VisualStamper:
    COLOR_GREEN = (0, 180, 0)     # Xanh lá (Học sinh làm ĐÚNG)
    COLOR_RED = (0, 0, 220)       # Đỏ (Học sinh làm SAI / Tô đúp)
    COLOR_YELLOW = (0, 190, 245)  # Vàng hổ phách (BỎ TRỐNG)

    @staticmethod
    def _draw_centered_text(img: np.ndarray, text: str, cx: int, cy: int, font: int, scale: float, color: tuple, thickness: int):
        (tw, th), _ = cv2.getTextSize(text, font, scale, thickness)
        tx = int(round(cx - tw / 2.0))
        ty = int(round(cy + th / 2.0))
        cv2.putText(img, text, (tx, ty), font, scale, color, thickness, cv2.LINE_AA)

    @classmethod
    def _highlight_bubble(cls, canvas: np.ndarray, center: Tuple[int, int], color: tuple, radius: int = 13, alpha: float = 0.35):
        cx, cy = center
        h, w = canvas.shape[:2]
        if cx - radius < 0 or cy - radius < 0 or cx + radius >= w or cy + radius >= h:
            return

        # Tối ưu: Chỉ copy ROI nhỏ thay vì toàn bộ canvas (~13MB/lần → ~2KB/lần)
        pad = radius + 3
        x1 = max(0, cx - pad)
        y1 = max(0, cy - pad)
        x2 = min(w, cx + pad + 1)
        y2 = min(h, cy + pad + 1)
        roi = canvas[y1:y2, x1:x2]
        overlay_roi = roi.copy()
        cv2.circle(overlay_roi, (cx - x1, cy - y1), radius, color, -1, cv2.LINE_AA)
        cv2.addWeighted(overlay_roi, alpha, roi, 1.0 - alpha, 0, roi)
        cv2.circle(canvas, (cx, cy), radius, color, 2, cv2.LINE_AA)

    @classmethod
    def stamp_graded_sheet(
        cls,
        aligned_bgr: np.ndarray,
        submission: Dict[str, Any],
        p1_coords: List[Dict[str, Any]],
        p2_coords: List[Dict[str, Any]],
        p3_coords: List[Dict[str, Any]],
        key_dict: Dict[str, Any],
        sbd_columns: Optional[List[Dict[str, Any]]] = None,
        made_columns: Optional[List[Dict[str, Any]]] = None
    ) -> np.ndarray:
        canvas = aligned_bgr.copy()
        sc = submission.get("scores", {"total": 0.0, "p1": 0.0, "p2": 0.0, "p3": 0.0})
        details = submission.get("details", {})
        exam_code = str(submission.get("exam_code", "")).strip().zfill(4)
        raw_exam_code = str(submission.get("raw_exam_code", exam_code)).strip()
        sbd_str = str(submission.get("sbd", "????????")).strip()

        RADIUS = 13

        p1_stu = {int(k): str(v).upper() for k, v in details.get("part1", {}).items() if v}
        p2_stu = {int(k): {str(sk).lower(): str(sv).upper() for sk, sv in sdict.items()} for k, sdict in details.get("part2", {}).items() if sdict}
        p3_stu = {int(k): v for k, v in details.get("part3", {}).items() if v is not None}

        p1_keys = {int(k): str(v).upper() for k, v in key_dict.get("part1", {}).items() if str(v).strip()}
        p2_keys = {int(k): {str(sk).lower(): str(sv).upper() for sk, sv in sdict.items()} for k, sdict in key_dict.get("part2", {}).items() if sdict}
        p3_keys = {}
        for k, v in key_dict.get("part3", {}).items():
            if v is not None and str(v).strip() != "":
                try:
                    p3_keys[int(k)] = float(v)
                except ValueError:
                    pass

        # 1. ĐÓNG KHUNG ĐIỂM
        box_tl, box_br = (65, 185), (410, 440)
        cv2.rectangle(canvas, box_tl, box_br, (255, 255, 255), -1)
        cv2.rectangle(canvas, box_tl, box_br, cls.COLOR_RED, 3)

        cv2.putText(canvas, f"DIEM: {sc.get('total', 0.0):.2f} / 10", (85, 245), cv2.FONT_HERSHEY_DUPLEX, 1.15, cls.COLOR_RED, 3, cv2.LINE_AA)
        cv2.putText(canvas, f"P.I   : {sc.get('p1', 0.0):.2f} d", (85, 295), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 180), 2, cv2.LINE_AA)
        cv2.putText(canvas, f"P.II  : {sc.get('p2', 0.0):.2f} d", (85, 345), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 180), 2, cv2.LINE_AA)
        cv2.putText(canvas, f"P.III : {sc.get('p3', 0.0):.2f} d", (85, 395), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 180), 2, cv2.LINE_AA)
        cv2.putText(canvas, f"Ma de: {exam_code}", (260, 295), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 100, 0), 2, cv2.LINE_AA)

        # 2. CHẤM SỐ BÁO DANH
        if sbd_columns:
            for col_idx, col_data in enumerate(sbd_columns):
                char_digit = sbd_str[col_idx] if col_idx < len(sbd_str) else "?"
                if char_digit == "?" or not char_digit.isdigit():
                    pos_0 = col_data["digits"]["0"]
                    cls._highlight_bubble(canvas, (int(round(pos_0[0])), int(round(pos_0[1]))), cls.COLOR_RED, RADIUS)
                else:
                    if char_digit in col_data["digits"]:
                        pos_d = col_data["digits"][char_digit]
                        cls._highlight_bubble(canvas, (int(round(pos_d[0])), int(round(pos_d[1]))), cls.COLOR_GREEN, RADIUS)

        # 3. CHẤM MÃ ĐỀ
        if made_columns:
            is_all_correct = (raw_exam_code == exam_code and "?" not in raw_exam_code and len(raw_exam_code) == 4)
            for col_idx, col_data in enumerate(made_columns):
                raw_char = raw_exam_code[col_idx] if col_idx < len(raw_exam_code) else "?"
                target_char = exam_code[col_idx] if col_idx < len(exam_code) else "?"

                if is_all_correct:
                    if target_char in col_data["digits"]:
                        pos = col_data["digits"][target_char]
                        cls._highlight_bubble(canvas, (int(round(pos[0])), int(round(pos[1]))), cls.COLOR_GREEN, RADIUS)
                else:
                    if raw_char.isdigit() and raw_char in col_data["digits"]:
                        if raw_char != target_char:
                            pos_wrong = col_data["digits"][raw_char]
                            cls._highlight_bubble(canvas, (int(round(pos_wrong[0])), int(round(pos_wrong[1]))), cls.COLOR_RED, RADIUS)
                        else:
                            pos_right = col_data["digits"][raw_char]
                            cls._highlight_bubble(canvas, (int(round(pos_right[0])), int(round(pos_right[1]))), cls.COLOR_GREEN, RADIUS)
                    elif raw_char == "?":
                        pos_0 = col_data["digits"]["0"]
                        cls._highlight_bubble(canvas, (int(round(pos_0[0])), int(round(pos_0[1]))), cls.COLOR_RED, RADIUS)

                    if target_char.isdigit() and target_char in col_data["digits"] and target_char != raw_char:
                        pos_target = col_data["digits"][target_char]
                        cls._highlight_bubble(canvas, (int(round(pos_target[0])), int(round(pos_target[1]))), cls.COLOR_GREEN, RADIUS)

        # 4. CHẤM PHẦN I (TRẮC NGHIỆM): ĐÚNG = XANH | SAI = ĐỎ | KHÔNG TÔ = VÀNG
        for q_item in p1_coords:
            q_num = int(q_item["question"])
            if q_num not in p1_keys:
                continue

            correct_ans = p1_keys[q_num]
            stu_ans = p1_stu.get(q_num, "").strip()
            cx, cy = map(int, map(round, q_item["choices"][correct_ans]))

            if not stu_ans or stu_ans == "":
                cls._highlight_bubble(canvas, (cx, cy), cls.COLOR_YELLOW, RADIUS)
            elif stu_ans == correct_ans:
                cls._highlight_bubble(canvas, (cx, cy), cls.COLOR_GREEN, RADIUS)
            elif stu_ans == "MULTIPLE":
                # TÔ ĐÚP: Học sinh tô 2 ô trở lên -> Bị phạt 0 ĐIỂM câu này!
                # Khoanh ĐỎ vào các ô học sinh đã tô vi phạm
                double_opts = []
                for a in submission.get("anomalies", []):
                    if a.get("type") == "P1_DOUBLE_FILL" and f"Câu {q_num} " in a.get("msg", ""):
                        m = re.findall(r'\b([A-D])\b', a.get("msg", ""))
                        if m:
                            double_opts = m
                        break
                if not double_opts:
                    double_opts = ["A", "B", "C", "D"]

                for opt in double_opts:
                    if opt in q_item["choices"]:
                        ox, oy = map(int, map(round, q_item["choices"][opt]))
                        cls._highlight_bubble(canvas, (ox, oy), cls.COLOR_RED, RADIUS)
                # Đánh dấu đáp án chuẩn của barem
                cls._highlight_bubble(canvas, (cx, cy), cls.COLOR_GREEN, RADIUS - 4 if correct_ans in double_opts else RADIUS)
            else:
                if stu_ans in q_item["choices"]:
                    wx, wy = map(int, map(round, q_item["choices"][stu_ans]))
                    cls._highlight_bubble(canvas, (wx, wy), cls.COLOR_RED, RADIUS)
                cls._highlight_bubble(canvas, (cx, cy), cls.COLOR_GREEN, RADIUS)

        # 5. CHẤM PHẦN II (ĐÚNG/SAI): ĐÚNG = XANH | SAI = ĐỎ | KHÔNG TÔ = VÀNG
        for q_item in p2_coords:
            q_num = int(q_item["question"])
            if q_num not in p2_keys:
                continue

            sub_map = p2_keys[q_num]
            stu_sub_map = p2_stu.get(q_num, {})

            for rk in ["a", "b", "c", "d"]:
                if rk not in sub_map:
                    continue
                exp_tf = sub_map[rk]
                stu_tf = stu_sub_map.get(rk, "").strip()

                tx, ty = map(int, map(round, q_item["rows"][rk]["true"]))
                fx, fy = map(int, map(round, q_item["rows"][rk]["false"]))

                correct_pos = (tx, ty) if exp_tf == "Đ" else (fx, fy)
                wrong_pos = (fx, fy) if exp_tf == "Đ" else (tx, ty)

                if not stu_tf or stu_tf == "":
                    cls._highlight_bubble(canvas, correct_pos, cls.COLOR_YELLOW, RADIUS)
                elif stu_tf == exp_tf:
                    cls._highlight_bubble(canvas, correct_pos, cls.COLOR_GREEN, RADIUS)
                else:
                    if stu_tf in ["Đ", "S"]:
                        cls._highlight_bubble(canvas, wrong_pos, cls.COLOR_RED, RADIUS)
                    elif stu_tf == "ĐS":
                        cls._highlight_bubble(canvas, (tx, ty), cls.COLOR_RED, RADIUS)
                        cls._highlight_bubble(canvas, (fx, fy), cls.COLOR_RED, RADIUS)
                    cls._highlight_bubble(canvas, correct_pos, cls.COLOR_GREEN, RADIUS)

        # 6. CHẤM PHẦN III (TRẢ LỜI NGẮN): ĐÚNG = XANH | SAI = ĐỎ | KHÔNG TÔ = VÀNG
        for q_item in p3_coords:
            q_num = int(q_item["question"])
            if q_num not in p3_keys:
                continue

            exp_v = p3_keys[q_num]
            stu_item = p3_stu.get(q_num)

            is_valid = False
            stu_v = None
            raw_str = ""
            stu_digits_list = []

            if isinstance(stu_item, dict):
                is_valid = stu_item.get("is_valid", False)
                stu_v = stu_item.get("normalized_value")
                raw_str = stu_item.get("raw_string", "")
                stu_digits_list = stu_item.get("digits")
                if not stu_digits_list and raw_str:
                    # Khôi phục danh sách ô đã tô từ raw_string (VD: "-1,2[34]_") để chấm đỏ chuẩn xác
                    s_clean = raw_str.lstrip("-").replace(",", "")
                    stu_digits_list = []
                    idx_s = 0
                    while idx_s < len(s_clean) and len(stu_digits_list) < 4:
                        ch = s_clean[idx_s]
                        if ch == "[":
                            end_b = s_clean.find("]", idx_s)
                            if end_b != -1:
                                stu_digits_list.append(list(s_clean[idx_s + 1:end_b]))
                                idx_s = end_b + 1
                                continue
                        elif ch == "_":
                            stu_digits_list.append([])
                        elif ch.isdigit():
                            stu_digits_list.append([ch])
                        idx_s += 1
                elif not stu_digits_list:
                    stu_digits_list = [[], [], [], []]
            elif isinstance(stu_item, (int, float)):
                stu_v = float(stu_item)
                is_valid = True
                raw_str = str(stu_item)

            is_correct = (is_valid and stu_v is not None and abs(stu_v - exp_v) <= 1e-4)
            is_blank = (not raw_str or raw_str.replace("_", "").strip() == "") and not is_correct

            col_xs = [q_item["digits"]["0"][c][0] for c in range(4)]
            box_cx = int(round(np.mean(col_xs)))
            score_y = int(round(q_item["sign"][1])) - 40

            if abs(exp_v - round(exp_v)) < 1e-6:
                exp_str = str(int(round(exp_v)))
            else:
                exp_str = f"{exp_v:.4f}".rstrip('0').rstrip('.')

            has_exp_minus = exp_v < 0
            val_part = exp_str.lstrip("-")
            comma_idx = val_part.find(".") if "." in val_part else -1
            clean_digits = val_part.replace(".", "")

            if is_correct:
                cls._draw_centered_text(canvas, "+0.25d", box_cx, score_y, cv2.FONT_HERSHEY_DUPLEX, 0.65, cls.COLOR_GREEN, 2)
                if has_exp_minus:
                    sx, sy = map(int, map(round, q_item["sign"]))
                    cls._highlight_bubble(canvas, (sx, sy), cls.COLOR_GREEN, RADIUS)
                if comma_idx in [1, 2]:
                    cpos = q_item["comma_positions"][comma_idx - 1]
                    cls._highlight_bubble(canvas, (int(cpos[0]), int(cpos[1])), cls.COLOR_GREEN, RADIUS)
                for c_i in range(min(4, len(clean_digits))):
                    d_char = clean_digits[c_i]
                    if d_char in q_item["digits"]:
                        pos = q_item["digits"][d_char][c_i]
                        cls._highlight_bubble(canvas, (int(pos[0]), int(pos[1])), cls.COLOR_GREEN, RADIUS)

            elif is_blank:
                cls._draw_centered_text(canvas, f"0d [DA: {exp_str}]", box_cx, score_y, cv2.FONT_HERSHEY_DUPLEX, 0.50, cls.COLOR_YELLOW, 2)
                if has_exp_minus:
                    sx, sy = map(int, map(round, q_item["sign"]))
                    cls._highlight_bubble(canvas, (sx, sy), cls.COLOR_YELLOW, RADIUS)
                if comma_idx in [1, 2]:
                    cpos = q_item["comma_positions"][comma_idx - 1]
                    cls._highlight_bubble(canvas, (int(cpos[0]), int(cpos[1])), cls.COLOR_YELLOW, RADIUS)
                for c_i in range(min(4, len(clean_digits))):
                    d_char = clean_digits[c_i]
                    if d_char in q_item["digits"]:
                        pos = q_item["digits"][d_char][c_i]
                        cls._highlight_bubble(canvas, (int(pos[0]), int(pos[1])), cls.COLOR_YELLOW, RADIUS)

            else:
                doc_str = raw_str if raw_str else "Trống"
                cls._draw_centered_text(canvas, f"0d [Doc: {doc_str}]", box_cx, score_y, cv2.FONT_HERSHEY_DUPLEX, 0.50, cls.COLOR_RED, 2)
                for c_i, hits in enumerate(stu_digits_list):
                    for d_char in hits:
                        if d_char in q_item["digits"]:
                            pos = q_item["digits"][d_char][c_i]
                            cls._highlight_bubble(canvas, (int(pos[0]), int(pos[1])), cls.COLOR_RED, RADIUS)
                if has_exp_minus:
                    sx, sy = map(int, map(round, q_item["sign"]))
                    cls._highlight_bubble(canvas, (sx, sy), cls.COLOR_GREEN, RADIUS)
                if comma_idx in [1, 2]:
                    cpos = q_item["comma_positions"][comma_idx - 1]
                    cls._highlight_bubble(canvas, (int(cpos[0]), int(cpos[1])), cls.COLOR_GREEN, RADIUS)
                for c_i in range(min(4, len(clean_digits))):
                    d_char = clean_digits[c_i]
                    if d_char in q_item["digits"]:
                        pos = q_item["digits"][d_char][c_i]
                        cls._highlight_bubble(canvas, (int(pos[0]), int(pos[1])), cls.COLOR_GREEN, RADIUS)

        return canvas

    @staticmethod
    def export_all_to_pdf(graded_bgr_list: List[np.ndarray], output_pdf_path: Path):
        """Hàm dự phòng xuất PDF - Tuyệt đối không dùng ký tự Unicode lạ để tránh charmap crash."""
        from PIL import Image

        pil_images = []
        for bgr in graded_bgr_list:
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            pil_images.append(Image.fromarray(rgb))

        if pil_images:
            output_pdf_path.parent.mkdir(exist_ok=True, parents=True)
            pil_images[0].save(output_pdf_path, save_all=True, append_images=pil_images[1:], resolution=200.0)
            print(f"[OK] Da xuat thanh cong tep PDF: {output_pdf_path.name}")
```

## FILE: templates\index.html
```html
<!-- templates/index.html -->
<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Hệ Thống Chấm Thi Trắc Nghiệm Chuẩn Bộ GD&ĐT</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    ::-webkit-scrollbar { width: 5px; height: 5px; }
    ::-webkit-scrollbar-track { background: #f1f5f9; }
    ::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
    ::-webkit-scrollbar-thumb:hover { background: #94a3b8; }
  </style>
</head>
<body class="bg-slate-100 text-slate-800 h-screen flex flex-col font-sans overflow-hidden">

  <!-- MODAL 1: TẠO ĐỢT KIỂM TRA MỚI -->
  <div id="createExamModal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center hidden">
    <div class="bg-white rounded-2xl shadow-2xl border border-slate-200 max-w-md w-full p-6 m-4">
      <div class="flex items-center gap-3 border-b pb-3 mb-4">
        <div class="p-2.5 bg-indigo-950 text-amber-400 font-black rounded-xl text-lg tracking-wider">OMR</div>
        <div>
          <h2 class="text-sm font-bold text-slate-900 uppercase">Khởi Tạo Đợt Kiểm Tra</h2>
          <p class="text-[11px] text-slate-500">Thiết lập thông tin đợt đánh giá định kỳ</p>
        </div>
      </div>

      <div class="space-y-3 text-xs">
        <div>
          <label class="block font-bold text-slate-700 mb-1">Môn Học (*):</label>
          <input type="text" id="inpSubject" value="Sinh học" placeholder="Ví dụ: Sinh học, Toán, Hóa học..." class="w-full border rounded-lg px-3 py-1.5 text-xs font-semibold focus:ring-2 focus:ring-indigo-600 outline-none" />
        </div>
        <div>
          <label class="block font-bold text-slate-700 mb-1">Kỳ Kiểm Tra (*):</label>
          <input type="text" id="inpPeriod" value="Giữa kỳ I" placeholder="Ví dụ: Giữa kỳ I, Định kỳ, Cuối kỳ..." class="w-full border rounded-lg px-3 py-1.5 text-xs font-semibold focus:ring-2 focus:ring-indigo-600 outline-none" />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <label class="block font-bold text-slate-700 mb-1">Lớp (*):</label>
            <input type="text" id="inpClass" value="11A" class="w-full border rounded-lg px-3 py-1.5 text-xs font-semibold focus:ring-2 focus:ring-indigo-600 outline-none" />
          </div>
          <div>
            <label class="block font-bold text-slate-700 mb-1">Năm Học:</label>
            <input type="text" id="inpYear" value="2026-2027" class="w-full border rounded-lg px-3 py-1.5 text-xs font-semibold focus:ring-2 focus:ring-indigo-600 outline-none" />
          </div>
        </div>
      </div>

      <div class="mt-5 flex justify-end gap-2">
        <button onclick="closeModal('createExamModal')" class="px-3.5 py-1.5 text-xs font-semibold text-slate-500 hover:bg-slate-100 rounded-lg">Đóng</button>
        <button onclick="submitCreateExam()" class="px-4 py-1.5 bg-indigo-900 hover:bg-indigo-800 text-white text-xs font-bold rounded-lg shadow">Khởi Tạo</button>
      </div>
    </div>
  </div>

  <!-- MODAL 2: QUẢN LÝ DANH SÁCH ĐỢT KIỂM TRA -->
  <div id="examHistoryModal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center hidden">
    <div class="bg-white rounded-2xl shadow-2xl border border-slate-200 max-w-xl w-full p-6 m-4 flex flex-col max-h-[85vh]">
      <div class="flex justify-between items-center border-b pb-3 mb-4 shrink-0">
        <div>
          <h2 class="text-sm font-bold text-slate-900 uppercase">Danh Sách Đợt Kiểm Tra</h2>
          <p class="text-[11px] text-slate-500">Lựa chọn đợt làm việc hoặc xóa các đợt không sử dụng</p>
        </div>
        <button onclick="closeModal('examHistoryModal')" class="text-slate-400 hover:text-slate-600 font-bold text-xl leading-none">&times;</button>
      </div>

      <div id="examHistoryList" class="space-y-2 overflow-y-auto flex-1 pr-1"></div>

      <div class="mt-4 pt-3 border-t flex justify-between items-center shrink-0">
        <button onclick="closeModal('examHistoryModal'); openModal('createExamModal');" class="text-xs bg-indigo-50 text-indigo-700 hover:bg-indigo-100 font-bold px-3 py-1.5 rounded-lg border border-indigo-200">
          + Khởi Tạo Đợt Mới
        </button>
        <button onclick="closeModal('examHistoryModal')" class="px-4 py-1.5 bg-slate-200 hover:bg-slate-300 text-slate-700 text-xs font-semibold rounded-lg">
          Đóng
        </button>
      </div>
    </div>
  </div>

  <!-- MODAL 3: DÁN ĐÁP ÁN NHANH (SMART PASTE) -->
  <div id="smartPasteModal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center hidden">
    <div class="bg-white rounded-2xl shadow-2xl border border-slate-200 max-w-xl w-full p-6 m-4 flex flex-col max-h-[90vh]">
      <div class="flex justify-between items-center border-b pb-3 mb-3 shrink-0">
        <div>
          <h2 class="text-sm font-bold text-slate-900 uppercase flex items-center gap-1.5">
            <span>📋 Dán Đáp Án Nhanh (Smart Paste)</span>
          </h2>
          <p class="text-[11px] text-slate-500">Tự động nhận diện từ Zalo, Word, SMS (Phần I, II, III). Không cần tạo file Excel!</p>
        </div>
        <button onclick="closeModal('smartPasteModal')" class="text-slate-400 hover:text-slate-600 font-bold text-xl leading-none">&times;</button>
      </div>

      <div class="space-y-3 overflow-y-auto flex-1 pr-1">
        <div class="grid grid-cols-2 gap-2 bg-slate-50 p-2.5 rounded-xl border border-slate-200">
          <div>
            <label class="block text-[10px] font-bold text-slate-700 uppercase mb-1">Mã đề mặc định:</label>
            <input type="text" id="smartPasteDefaultMade" value="0001" maxlength="4" placeholder="VD: 0001 hoặc 0102" class="w-full border rounded-lg px-2.5 py-1.5 text-xs font-mono font-bold text-indigo-950 outline-none focus:ring-2 focus:ring-indigo-600 bg-white" />
          </div>
          <div class="text-[10px] text-slate-500 flex items-center leading-relaxed">
            💡 Nếu nội dung dán có chứa dòng như <code class="bg-white px-1 py-0.5 rounded border border-slate-300 text-indigo-700 font-bold">Mã đề: 0102</code>, hệ thống sẽ tự nạp đúng mã đề đó.
          </div>
        </div>

        <div>
          <label class="block text-[10px] font-bold text-slate-700 uppercase mb-1">Dán văn bản đáp án vào đây:</label>
          <textarea id="smartPasteText" rows="11" placeholder="Dán văn bản đáp án từ Zalo, Word...
Ví dụ:
Mã đề: 0102
PHẦN I:
1.A 2.B 3.C 4.D 5.A 6.B 7.C 8.D 9.A 10.B
11.C 12.D 13.A 14.B 15.C 16.D 17.A 18.B
PHẦN II:
Câu 1: a) Đ, b) S, c) Đ, d) S
Câu 2: a) S, b) Đ, c) S, d) Đ
Câu 3: a) Đ, b) Đ, c) S, d) S
Câu 4: a) S, b) S, c) Đ, d) Đ
PHẦN III:
Câu 1: -14
Câu 2: 3,14
Câu 3: 42" class="w-full border rounded-xl p-3 text-xs font-mono text-slate-800 outline-none focus:ring-2 focus:ring-indigo-600 bg-slate-50 focus:bg-white resize-y shadow-inner leading-relaxed"></textarea>
        </div>

        <div id="smartPasteFeedback" class="text-xs p-2.5 rounded-lg hidden transition-all"></div>
      </div>

      <div class="mt-4 pt-3 border-t flex justify-end gap-2 shrink-0">
        <button onclick="closeModal('smartPasteModal')" class="px-3.5 py-1.5 text-xs font-semibold text-slate-500 hover:bg-slate-100 rounded-lg">Đóng</button>
        <button onclick="submitSmartPaste()" id="btnSubmitSmartPaste" class="px-4 py-1.5 bg-violet-700 hover:bg-violet-600 text-white text-xs font-bold rounded-lg shadow flex items-center gap-1.5">
          <span>Nhận Diện & Nạp Đáp Án</span>
        </button>
      </div>
    </div>
  </div>

  <!-- HEADER THANH CÔNG CỤ -->
  <header class="bg-indigo-950 text-white shadow-md px-4 py-2.5 flex justify-between items-center z-40 shrink-0">
    <div class="flex items-center gap-3">
      <div class="px-2 py-1 bg-indigo-900 rounded font-black text-sm text-amber-400 tracking-wider">OMR</div>
      <div>
        <div class="flex items-center gap-2">
          <h1 class="text-xs font-bold tracking-wide" id="examHeaderTitle">ĐANG TẢI THÔNG TIN...</h1>
          <button onclick="openModal('examHistoryModal')" class="text-[9px] bg-slate-800 hover:bg-slate-700 text-indigo-200 px-2 py-0.5 rounded font-semibold border border-indigo-700">Quản Lý Đợt Chấm ▾</button>
          <button onclick="openModal('createExamModal')" class="text-[9px] bg-indigo-800 hover:bg-indigo-700 text-amber-300 px-2 py-0.5 rounded font-semibold border border-indigo-700">+ Đợt Mới</button>
        </div>
        <div class="flex items-center gap-2 mt-0.5">
          <p class="text-[10px] text-indigo-300" id="examHeaderSub">Năm học: 2026-2027</p>
          <span id="examStatusBadge" class="text-[9px] px-1.5 py-0.2 rounded font-bold bg-emerald-900 text-emerald-300">Đã sẵn sàng</span>
        </div>
      </div>
    </div>
    
    <div class="flex items-center gap-2">
      <a href="/scanner" target="_blank" class="bg-amber-500 hover:bg-amber-400 text-slate-950 px-2.5 py-1.5 rounded-lg text-xs font-bold shadow flex items-center gap-1 transition">
        <span>📱 Quét Điện Thoại</span>
      </a>
      <button onclick="downloadTemplate()" class="bg-indigo-900 hover:bg-indigo-800 border border-indigo-700 text-indigo-200 px-2.5 py-1.5 rounded-lg text-xs font-semibold">
        Tải Mẫu Đáp Án
      </button>
      <button onclick="openSmartPasteModal()" class="bg-violet-700 hover:bg-violet-600 text-white px-2.5 py-1.5 rounded-lg text-xs font-bold shadow flex items-center gap-1 transition">
        <span>📋 Dán Đáp Án Nhanh</span>
      </button>
      <label class="bg-indigo-700 hover:bg-indigo-600 text-white px-2.5 py-1.5 rounded-lg text-xs font-semibold cursor-pointer border border-indigo-500 shadow">
        Nạp File Đáp Án
        <input type="file" id="keyPicker" accept=".xlsx,.xls" class="hidden">
      </label>

      <div class="h-5 w-px bg-indigo-800 mx-1"></div>

      <!-- NÚT NẠP HÀNG LOẠT -->
      <label class="bg-emerald-600 hover:bg-emerald-500 text-white px-3 py-1.5 rounded-lg text-xs font-bold cursor-pointer shadow flex items-center gap-1.5">
        <span>+ Nạp Bài Thi (Nhiều Bài / PDF)</span>
        <input type="file" id="filePicker" multiple accept="image/*,.pdf" class="hidden">
      </label>

      <!-- NÚT XUẤT FILE TÍCH HỢP HỘP THOẠI CHỌN NƠI LƯU (SAVE AS) -->
      <button onclick="saveFileWithPicker('pdf')" id="btnExportPdf" class="bg-rose-700 hover:bg-rose-600 text-white px-2.5 py-1.5 rounded-lg text-xs font-bold shadow flex items-center gap-1 transition">
        Xuất Phiếu Đã Chấm (PDF)
      </button>
      <button onclick="saveFileWithPicker('excel')" id="btnExportExcel" class="bg-white text-indigo-950 hover:bg-slate-100 px-2.5 py-1.5 rounded-lg text-xs font-bold shadow flex items-center gap-1 transition">
        Xuất Bảng Điểm (Excel)
      </button>
    </div>
  </header>

  <!-- BỐ CỤC 3 CỘT ĐỐI SOÁT TRỰC QUAN -->
  <main class="w-full flex-1 grid grid-cols-12 gap-3 p-3 min-h-0">

    <!-- CỘT 1: DANH SÁCH BÀI THI -->
    <aside class="col-span-12 md:col-span-3 lg:col-span-2 bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden flex flex-col h-full">
      <div class="p-2.5 border-b bg-slate-50 flex justify-between items-center shrink-0">
        <h2 class="font-bold text-[11px] text-slate-700 uppercase tracking-wider">Danh Sách Bài Thi</h2>
        <span id="badgeCount" class="text-[10px] bg-indigo-100 text-indigo-800 font-bold px-2 py-0.5 rounded-full">0 bài</span>
      </div>

      <!-- KHUNG TIẾN TRÌNH CHẤM HÀNG LOẠT -->
      <div id="batchProgressContainer" class="p-2.5 bg-indigo-50 border-b border-indigo-100 shrink-0 hidden">
        <div class="flex justify-between items-center text-[10px] font-bold text-indigo-950 mb-1">
          <span id="batchProgressText">Tiến độ: 0/0 (0%)</span>
          <button onclick="cancelBatchGrading()" class="text-[9px] text-rose-600 hover:text-rose-800 font-bold bg-white px-1.5 py-0.5 rounded border border-rose-200 shadow-xs">
            Dừng lại
          </button>
        </div>
        <div class="w-full bg-slate-200 rounded-full h-1.5 overflow-hidden">
          <div id="batchProgressBar" class="bg-indigo-600 h-1.5 rounded-full transition-all duration-150" style="width: 0%"></div>
        </div>
        <div id="batchCurrentFile" class="text-[9px] text-indigo-600 mt-1 truncate">Đang xử lý: ...</div>
      </div>

      <div id="submissionList" class="divide-y divide-slate-100 overflow-y-auto flex-1 p-1.5 space-y-1">
        <div class="text-center text-slate-400 py-20 text-[11px]">
          Chưa có dữ liệu bài thi.
        </div>
      </div>
    </aside>

    <!-- CỘT 2: BẢNG ĐỐI SOÁT & ĐIỀU CHỈNH ĐIỂM -->
    <section class="col-span-12 md:col-span-5 lg:col-span-5 bg-white rounded-xl shadow-sm border border-slate-200 flex flex-col h-full overflow-hidden">
      <div id="reviewContainer" class="p-4 overflow-y-auto flex-1">
        <div class="text-center text-slate-400 py-36 text-xs">
          Chọn bài thi từ danh sách bên trái để kiểm tra chi tiết.
        </div>
      </div>
    </section>

    <!-- CỘT 3: BẢN QUÉT PHIẾU BÀI LÀM ĐÃ CHẤM -->
    <section class="col-span-12 md:col-span-4 lg:col-span-5 bg-slate-900 rounded-xl shadow-sm border border-slate-800 flex flex-col h-full overflow-hidden">
      <div class="p-2.5 border-b border-slate-800 bg-slate-950 flex justify-between items-center text-white shrink-0">
        <div class="flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
          <span class="text-xs font-bold uppercase tracking-wider text-slate-200">Phiếu Trả Lời Đã Chấm</span>
        </div>
        <div class="flex items-center gap-2">
          <button onclick="zoomSheet(-0.15)" class="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs font-bold" title="Thu nhỏ">-</button>
          <button onclick="resetZoomSheet()" class="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs font-bold" title="Vừa khung">100%</button>
          <button onclick="zoomSheet(0.15)" class="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs font-bold" title="Phóng to">+</button>
          <button onclick="openGradedTab()" class="px-2 py-0.5 bg-indigo-700 hover:bg-indigo-600 text-white rounded text-[11px] font-semibold" title="Mở tab mới">
            Xem Ảnh Gốc ↗
          </button>
        </div>
      </div>

      <div id="sheetViewer" class="flex-1 overflow-auto p-3 flex justify-center items-start bg-slate-900">
        <div id="sheetEmptyNotice" class="text-slate-500 text-xs text-center py-40">
          Chưa chọn bài thi.
        </div>
        <img id="gradedSheetImg" src="" alt="Bản quét phiếu bài làm đã chấm" class="hidden transition-transform origin-top duration-150 rounded shadow-2xl max-w-full" />
      </div>
    </section>

  </main>

  <script>
    let currentSession = null;
    let currentSubmissions = [];
    let selectedSubId = null;
    let currentSheetZoom = 1.0;
    let isBatchCancelled = false;

    window.addEventListener("DOMContentLoaded", async () => {
      await refreshSession();

      const savedSubId = localStorage.getItem("omr_active_sub_id");
      if (savedSubId && currentSubmissions.some(s => s.submission_id === savedSubId)) {
        selectSubmission(savedSubId);
      } else if (currentSubmissions.length > 0) {
        selectSubmission(currentSubmissions[0].submission_id);
      }
    });

    async function refreshSession() {
      try {
        const res = await fetch("/api/session");
        currentSession = await res.json();
        currentSubmissions = currentSession.submissions || [];

        const info = currentSession.exam_info;
        if (info) {
          document.getElementById("examHeaderTitle").innerText = `${info.subject.toUpperCase()} - ${info.period.toUpperCase()} (${info.class_name})`;
          document.getElementById("examHeaderSub").innerText = `Năm học: ${info.school_year}`;

          const badge = document.getElementById("examStatusBadge");
          if (info.is_configured) {
            badge.className = "text-[9px] px-1.5 py-0.2 rounded font-bold bg-emerald-900 text-emerald-300";
            badge.innerText = "Đã sẵn sàng chấm";
          } else {
            badge.className = "text-[9px] px-1.5 py-0.2 rounded font-bold bg-amber-900 text-amber-300";
            badge.innerText = "Chưa cấu hình đáp án";
          }
        }

        renderExamHistory(currentSession.all_exams || []);
        renderList();

        if (selectedSubId) {
          const stillExists = currentSubmissions.find(s => s.submission_id === selectedSubId);
          if (stillExists) selectSubmission(selectedSubId);
          else {
            selectedSubId = null;
            clearReviewViews();
          }
        } else if (currentSubmissions.length > 0) {
          selectSubmission(currentSubmissions[0].submission_id);
        } else {
          clearReviewViews();
        }
      } catch (e) {
        console.error("Lỗi đồng bộ dữ liệu phiên:", e);
      }
    }

    function clearReviewViews() {
      document.getElementById("reviewContainer").innerHTML = `
        <div class="text-center text-slate-400 py-36 text-xs">
          Chưa chọn bài thi.<br>Nhấn <b>+ Nạp Bài Thi</b> để bắt đầu.
        </div>`;
      const sheetImg = document.getElementById("gradedSheetImg");
      const emptyNotice = document.getElementById("sheetEmptyNotice");
      sheetImg.classList.add("hidden");
      emptyNotice.classList.remove("hidden");
      localStorage.removeItem("omr_active_sub_id");
    }

    function openModal(id) { document.getElementById(id).classList.remove("hidden"); }
    function closeModal(id) { document.getElementById(id).classList.add("hidden"); }

    function openSmartPasteModal() {
      document.getElementById("smartPasteText").value = "";
      const fb = document.getElementById("smartPasteFeedback");
      fb.className = "hidden";
      fb.innerText = "";
      openModal("smartPasteModal");
    }

    async function submitSmartPaste() {
      const text = document.getElementById("smartPasteText").value.trim();
      const defaultMade = document.getElementById("smartPasteDefaultMade").value.trim() || "0001";
      const fb = document.getElementById("smartPasteFeedback");
      const btn = document.getElementById("btnSubmitSmartPaste");

      if (!text) {
        fb.className = "text-xs p-2.5 rounded-lg bg-rose-50 text-rose-700 border border-rose-200 block";
        fb.innerText = "Vui lòng nhập hoặc dán nội dung đáp án.";
        return;
      }

      btn.disabled = true;
      btn.innerText = "Đang phân tích...";
      fb.className = "text-xs p-2.5 rounded-lg bg-indigo-50 text-indigo-700 border border-indigo-200 block";
      fb.innerText = "Đang nhận diện cú pháp và nạp đáp án...";

      try {
        const res = await fetch("/api/smart-paste-answer-key", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: text, default_made: defaultMade })
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || "Lỗi nạp đáp án dán");
        }

        fb.className = "text-xs p-2.5 rounded-lg bg-emerald-50 text-emerald-700 border border-emerald-200 block";
        fb.innerHTML = `<b>Thành công!</b> Đã nạp mã đề: <b>${data.codes_loaded.join(", ")}</b>. Đã tự động chấm lại <b>${data.re_graded_count}</b> bài thi.`;

        setTimeout(async () => {
          closeModal("smartPasteModal");
          await refreshSession();
        }, 1200);
      } catch (err) {
        fb.className = "text-xs p-2.5 rounded-lg bg-rose-50 text-rose-700 border border-rose-200 block";
        fb.innerText = `Lỗi: ${err.message}`;
      } finally {
        btn.disabled = false;
        btn.innerHTML = `<span>Nhận Diện & Nạp Đáp Án</span>`;
      }
    }

    function previewBubbleCrop(src, msg) {
      const modal = document.createElement("div");
      modal.className = "fixed inset-0 bg-slate-900/80 backdrop-blur-sm z-50 flex items-center justify-center p-4";
      modal.onclick = () => modal.remove();
      modal.innerHTML = `
        <div class="bg-white rounded-2xl p-5 max-w-xs w-full shadow-2xl text-center" onclick="event.stopPropagation()">
          <h3 class="font-bold text-xs text-slate-800 uppercase mb-2">Chi Tiết Ô Bất Thường</h3>
          <img src="${src}" class="w-44 h-44 mx-auto object-cover rounded-xl border-2 border-rose-400 shadow-md mb-2" />
          <p class="text-xs text-slate-700 font-bold mb-3">${msg}</p>
          <button onclick="this.closest('.fixed').remove()" class="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 text-white text-xs font-bold rounded-lg shadow">Đóng</button>
        </div>
      `;
      document.body.appendChild(modal);
    }

    function renderExamHistory(allExams) {
      const container = document.getElementById("examHistoryList");
      if (!allExams || allExams.length === 0) {
        container.innerHTML = `<div class="text-center py-8 text-xs text-slate-400">Chưa có đợt kiểm tra nào.</div>`;
        return;
      }

      container.innerHTML = allExams.map(ex => `
        <div class="p-3 rounded-xl border transition flex justify-between items-center ${ex.is_active ? 'bg-indigo-50 border-indigo-500 ring-1 ring-indigo-500' : 'bg-white hover:bg-slate-50 border-slate-200'}">
          <div>
            <div class="flex items-center gap-2">
              <span class="font-bold text-xs text-slate-900">${ex.title}</span>
              ${ex.is_active ? `<span class="bg-indigo-600 text-white text-[9px] px-2 py-0.2 rounded-full font-bold">Hiện tại</span>` : ''}
            </div>
            <div class="text-[11px] text-slate-500 mt-0.5">
              Khởi tạo: <b>${ex.created_at || 'Mặc định'}</b> | Đã chấm: <b class="text-emerald-700">${ex.submission_count} bài</b>
            </div>
          </div>
          <div class="flex items-center gap-1.5">
            ${!ex.is_active ? `
              <button onclick="switchExamSession('${ex.id}')" class="px-2.5 py-1 bg-indigo-900 hover:bg-indigo-800 text-white rounded-lg text-xs font-semibold shadow">
                Mở Đợt
              </button>
            ` : ''}
            <button onclick="deleteExamSession('${ex.id}', '${ex.title}')" class="px-2.5 py-1 bg-rose-100 hover:bg-rose-200 text-rose-700 rounded-lg text-xs font-bold transition" title="Xóa đợt kiểm tra này">
              Xóa
            </button>
          </div>
        </div>
      `).join("");
    }

    async function deleteExamSession(examId, examTitle) {
      if (!confirm(`Xác nhận xóa đợt kiểm tra: "${examTitle}"?\nDữ liệu bài làm trong đợt này sẽ bị xóa khỏi hệ thống.`)) {
        return;
      }

      try {
        const res = await fetch(`/api/delete-exam/${examId}`, { method: "DELETE" });
        if (res.ok) {
          selectedSubId = null;
          localStorage.removeItem("omr_active_sub_id");
          await refreshSession();
        } else {
          const err = await res.json();
          alert("Lỗi: " + (err.detail || "Không thể xóa đợt này"));
        }
      } catch (e) {
        alert("Lỗi kết nối: " + e.message);
      }
    }

    async function switchExamSession(examId) {
      try {
        const res = await fetch(`/api/switch-exam/${examId}`, { method: "POST" });
        if (res.ok) {
          closeModal("examHistoryModal");
          selectedSubId = null;
          localStorage.removeItem("omr_active_sub_id");
          await refreshSession();
        }
      } catch (err) {
        alert("Lỗi chuyển đợt kiểm tra: " + err.message);
      }
    }

    async function submitCreateExam() {
      const payload = {
        subject: document.getElementById("inpSubject").value,
        period: document.getElementById("inpPeriod").value,
        class_name: document.getElementById("inpClass").value,
        school_year: document.getElementById("inpYear").value
      };
      await fetch("/api/create-exam", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      closeModal("createExamModal");
      selectedSubId = null;
      localStorage.removeItem("omr_active_sub_id");
      await refreshSession();
    }

    document.getElementById("keyPicker").addEventListener("change", async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const fd = new FormData();
      fd.append("file", file);

      try {
        const res = await fetch("/api/upload-answer-key", { method: "POST", body: fd });
        const data = await res.json();
        alert(`Đã nạp đáp án thành công cho các mã đề: ${data.codes_loaded.join(", ")}.`);
        await refreshSession();
      } catch (err) {
        alert("Lỗi nạp file đáp án: " + err.message);
      }
    });

    // CHẤM HÀNG LOẠT TUẦN TỰ
    document.getElementById("filePicker").addEventListener("change", async (e) => {
      const files = Array.from(e.target.files);
      if (!files.length) return;

      e.target.value = "";

      const progressContainer = document.getElementById("batchProgressContainer");
      const progressBar = document.getElementById("batchProgressBar");
      const progressText = document.getElementById("batchProgressText");
      const currentFileText = document.getElementById("batchCurrentFile");

      progressContainer.classList.remove("hidden");
      isBatchCancelled = false;

      const totalFiles = files.length;
      let processedFiles = 0;
      let successCount = 0;
      let errorCount = 0;

      for (let i = 0; i < totalFiles; i++) {
        if (isBatchCancelled) {
          alert(`Đã dừng tiến trình chấm hàng loạt. Đã xử lý ${processedFiles}/${totalFiles} tệp.`);
          break;
        }

        const file = files[i];
        currentFileText.innerText = `Đang xử lý (${i + 1}/${totalFiles}): ${file.name}`;

        const fd = new FormData();
        fd.append("file", file);

        try {
          const res = await fetch("/api/grade-single-file", {
            method: "POST",
            body: fd
          });

          if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || `HTTP Error: ${res.status}`);
          }

          const data = await res.json();
          if (data.new_submissions && data.new_submissions.length > 0) {
            for (let newSub of data.new_submissions) {
              const existingIdx = currentSubmissions.findIndex(s => s.submission_id === newSub.submission_id);
              if (existingIdx >= 0) {
                currentSubmissions[existingIdx] = newSub;
              } else {
                currentSubmissions.push(newSub);
              }
              if (newSub.has_error) errorCount++;
              else successCount++;
            }

            renderList();

            if (!selectedSubId && currentSubmissions.length > 0) {
              selectSubmission(currentSubmissions[currentSubmissions.length - 1].submission_id);
            }
          }
        } catch (err) {
          console.error(`Lỗi chấm file ${file.name}:`, err);
          errorCount++;
        }

        processedFiles++;
        const percent = Math.round((processedFiles / totalFiles) * 100);
        progressBar.style.width = `${percent}%`;
        progressText.innerText = `Tiến độ: ${processedFiles}/${totalFiles} (${percent}%)`;
      }

      setTimeout(() => {
        progressContainer.classList.add("hidden");
        progressBar.style.width = "0%";
        if (!isBatchCancelled) {
          alert(`Đã hoàn tất chấm hàng loạt!\n- Thành công: ${successCount} bài\n- Lỗi nhận diện: ${errorCount} bài`);
        }
        refreshSession();
      }, 800);
    });

    function cancelBatchGrading() {
      isBatchCancelled = true;
    }

    function renderList() {
      const el = document.getElementById("submissionList");
      document.getElementById("badgeCount").innerText = `${currentSubmissions.length} bài`;

      if (currentSubmissions.length === 0) {
        el.innerHTML = `<div class="text-center text-slate-400 py-24 text-[11px]">Chưa có dữ liệu bài thi.</div>`;
        return;
      }

      el.innerHTML = currentSubmissions.map(sub => {
        const isSelected = sub.submission_id === selectedSubId;
        const hasWarning = sub.anomalies && sub.anomalies.length > 0;
        const hasErr = sub.has_error;

        return `
          <div onclick="selectSubmission('${sub.submission_id}')"
               class="group relative p-2 rounded-lg cursor-pointer transition border text-left ${isSelected ? 'bg-indigo-50 border-indigo-500 shadow-sm' : 'hover:bg-slate-50 border-slate-200'}">
            <div class="flex justify-between items-start">
              <span class="font-bold text-[11px] text-slate-800 truncate max-w-[120px]" title="${sub.file_name}">${sub.file_name}</span>
              <span class="font-bold text-[11px] ${hasErr ? 'text-rose-600' : (hasWarning ? 'text-amber-600' : 'text-emerald-600')}">
                ${hasErr ? 'LỖI' : (sub.scores ? sub.scores.total + ' đ' : '0 đ')}
              </span>
            </div>
            <div class="flex justify-between items-center text-[10px] text-slate-500 mt-0.5">
              <span>SBD: <b>${sub.sbd}</b> | Đề: <b>${sub.exam_code}</b></span>
              ${hasErr ? `<span class="bg-rose-100 text-rose-800 px-1 py-0.2 rounded font-semibold text-[8px]">Lỗi</span>` :
                (hasWarning ? `<span class="bg-amber-100 text-amber-800 px-1 py-0.2 rounded font-semibold text-[8px]">${sub.anomalies.length} cờ</span>` : `<span class="text-emerald-600 font-semibold text-[8px]">Hợp lệ</span>`)}
            </div>
            <button onclick="event.stopPropagation(); deleteSubmission('${sub.submission_id}', '${sub.file_name}');"
                    class="opacity-0 group-hover:opacity-100 absolute top-1 right-1 bg-white hover:bg-rose-100 text-rose-600 p-1 rounded border border-slate-200 shadow-sm transition"
                    title="Xóa bài thi này">
              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
            </button>
          </div>`;
      }).join("");
    }

    function selectSubmission(subId) {
      selectedSubId = subId;
      localStorage.setItem("omr_active_sub_id", subId);
      renderList();
      const sub = currentSubmissions.find(s => s.submission_id === subId);
      if (!sub) return;

      const sheetImg = document.getElementById("gradedSheetImg");
      const emptyNotice = document.getElementById("sheetEmptyNotice");
      const versionTag = sub.updated_at ? `?v=${encodeURIComponent(sub.updated_at)}` : '';
      sheetImg.src = `/api/graded-image/${sub.submission_id}${versionTag}`;
      sheetImg.classList.remove("hidden");
      emptyNotice.classList.add("hidden");
      resetZoomSheet();

      const container = document.getElementById("reviewContainer");
      if (sub.has_error) {
        container.innerHTML = `
          <div class="p-6 bg-rose-50 border border-rose-200 rounded-xl text-center">
            <h3 class="text-sm font-bold text-rose-800 mb-1">Không thể nhận diện bài làm</h3>
            <p class="text-xs text-rose-600 mb-4">${sub.error_msg || 'Ảnh bài thi bị mất góc mốc định vị.'}</p>
            <button onclick="deleteSubmission('${sub.submission_id}', '${sub.file_name}')" class="px-3.5 py-1.5 bg-rose-600 hover:bg-rose-700 text-white rounded-lg text-xs font-bold">
              Xóa Bản Ghi Này
            </button>
          </div>`;
        return;
      }

      const p1 = sub.details?.part1 || {};
      const p2 = sub.details?.part2 || {};
      const p3 = sub.details?.part3 || {};

      container.innerHTML = `
        <div class="flex justify-between items-center border-b pb-2.5 mb-3">
          <div>
            <h3 class="text-xs font-bold text-slate-900 truncate max-w-[200px]">${sub.file_name}</h3>
            <p class="text-[10px] text-slate-400">Mã bài: ${sub.submission_id}</p>
          </div>
          <div class="flex items-center gap-2">
            <div class="text-right mr-1">
              <span class="text-[9px] text-slate-400 block font-bold leading-tight">TỔNG ĐIỂM</span>
              <span class="text-xl font-black text-rose-600" id="liveTotal">${sub.scores ? sub.scores.total : 0} <span class="text-[10px] font-normal text-slate-400">/ 10</span></span>
            </div>
            <button onclick="triggerInstantRegrade('${sub.submission_id}')" class="bg-indigo-900 hover:bg-indigo-800 text-white font-semibold text-xs px-2.5 py-1.5 rounded-lg shadow">
              Cập Nhật Kết Quả
            </button>
            <button onclick="deleteSubmission('${sub.submission_id}', '${sub.file_name}')" class="bg-rose-100 hover:bg-rose-200 text-rose-700 font-bold text-xs px-2.5 py-1.5 rounded-lg transition" title="Xóa bài thi này">
              Xóa
            </button>
          </div>
        </div>

        ${sub.anomalies && sub.anomalies.length > 0 ? `
          <div class="mb-3 bg-amber-50 border border-amber-300 rounded-xl p-2.5 shadow-xs">
            <h4 class="text-[10px] font-bold text-amber-900 uppercase mb-1.5 flex items-center gap-1">
              <span>🔍 Lưu ý đối soát & ô bất thường (${sub.anomalies.length}):</span>
            </h4>
            <div class="space-y-1.5">
              ${sub.anomalies.map(a => `
                <div class="flex items-center gap-2.5 bg-white p-2 rounded-lg border border-amber-200 shadow-xs">
                  ${a.crop_b64 ? `
                    <div class="shrink-0 relative group">
                      <img src="${a.crop_b64}" class="w-12 h-12 object-cover rounded-md border border-rose-300 shadow-xs cursor-pointer hover:border-rose-600 transition" title="Nhấp để phóng to" onclick="previewBubbleCrop('${a.crop_b64}', '${(a.msg || '').replace(/'/g, "\\'")}')" />
                      <span class="absolute bottom-0 right-0 bg-rose-600 text-white text-[7px] px-0.5 font-bold rounded-tl">Zoom</span>
                    </div>
                  ` : ''}
                  <div class="flex-1 min-w-0">
                    <p class="text-[11px] font-bold text-amber-950">${a.msg}</p>
                    <p class="text-[9px] text-slate-500 font-mono">${a.type}</p>
                  </div>
                </div>
              `).join("")}
            </div>
          </div>` : ""}

        <div class="mb-3 bg-slate-50 border rounded-lg p-2">
          <label class="block text-[10px] font-bold text-slate-700 uppercase mb-1">
            Thông tin thí sinh (Đối soát viết tay)
          </label>
          <img src="/api/crop-info/${sub.submission_id}?t=${Date.now()}" 
               class="w-full max-h-40 object-contain rounded border border-slate-300 bg-white shadow-xs mb-2 transition-all hover:scale-105 origin-top" 
               alt="Thông tin viết tay thí sinh" />
          <div class="grid grid-cols-2 gap-2">
            <div>
              <label class="block text-[10px] font-bold text-slate-600 mb-0.5">Số báo danh / Mã thí sinh:</label>
              <input type="text" id="editSbd" value="${sub.sbd}" class="w-full border rounded px-2 py-1 text-xs font-mono font-bold text-indigo-950 focus:ring-1 focus:ring-indigo-600 outline-none" />
            </div>
            <div>
              <div class="flex justify-between items-center mb-0.5">
                <label class="text-[10px] font-bold text-slate-600">Mã đề thi:</label>
                <button onclick="triggerInstantRegrade('${sub.submission_id}')" class="text-[9px] bg-indigo-600 hover:bg-indigo-700 text-white font-bold px-1.5 py-0.5 rounded shadow">
                  Chấm Lại Điểm ↻
                </button>
              </div>
              <input type="text" id="editMade" value="${sub.exam_code}" 
                onchange="triggerInstantRegrade('${sub.submission_id}')"
                placeholder="Nhập 4 số mã đề..."
                class="w-full border-2 border-indigo-400 rounded px-2 py-1 text-xs font-mono font-bold text-indigo-950 bg-amber-50 focus:bg-white focus:ring-2 focus:ring-indigo-600 outline-none" />
            </div>
          </div>
        </div>

        <div class="space-y-2.5">
          <!-- Phần I -->
          <div class="border rounded-lg p-2 bg-white">
            <div class="flex justify-between items-center mb-1">
              <span class="text-[11px] font-bold text-slate-700">Phần I: Trắc nghiệm 4 lựa chọn (${Object.keys(p1).length} câu)</span>
              <span class="text-[11px] font-bold text-emerald-700" id="liveP1">${sub.scores ? sub.scores.p1 : 0} đ</span>
            </div>
            <div class="grid grid-cols-8 gap-1 text-xs">
              ${Object.entries(p1).map(([q, ans]) => `
                <div class="p-1 rounded border text-center ${ans ? 'bg-indigo-50 border-indigo-200' : 'bg-slate-50 text-slate-400'}">
                  <div class="text-[8px] text-slate-400 font-mono">C${q}</div>
                  <input type="text" id="p1_q${q}" value="${ans}" maxlength="1" class="w-full text-center font-bold text-xs uppercase bg-transparent outline-none focus:bg-amber-100" />
                </div>`).join("")}
            </div>
          </div>

          <!-- Phần II -->
          <div class="border rounded-lg p-2 bg-white">
            <div class="flex justify-between items-center mb-1">
              <span class="text-[11px] font-bold text-slate-700">Phần II: Đúng / Sai (${Object.keys(p2).length} câu)</span>
              <span class="text-[11px] font-bold text-emerald-700" id="liveP2">${sub.scores ? sub.scores.p2 : 0} đ</span>
            </div>
            <div class="grid grid-cols-4 gap-2 text-xs">
              ${Object.entries(p2).map(([q, rows]) => `
                <div class="border rounded p-1 bg-slate-50">
                  <div class="font-bold text-slate-700 mb-0.5 text-[10px]">Câu ${q}</div>
                  <div class="grid grid-cols-4 gap-1 text-center font-mono">
                    ${['a', 'b', 'c', 'd'].map(k => `
                      <div>
                        <div class="text-[8px] text-slate-400">${k}</div>
                        <input type="text" id="p2_q${q}_${k}" value="${rows[k] || ''}" maxlength="1" class="w-full text-center font-bold border rounded bg-white text-[10px] focus:bg-amber-100" />
                      </div>`).join("")}
                  </div>
                </div>`).join("")}
            </div>
          </div>

          <!-- Phần III -->
          <div class="border rounded-lg p-2 bg-white">
            <div class="flex justify-between items-center mb-1">
              <span class="text-[11px] font-bold text-slate-700">Phần III: Trả lời ngắn (${Object.keys(p3).length} câu)</span>
              <span class="text-[11px] font-bold text-emerald-700" id="liveP3">${sub.scores ? sub.scores.p3 : 0} đ</span>
            </div>
            <div class="grid grid-cols-4 gap-1.5 text-xs">
              ${Object.entries(p3).map(([q, item]) => {
                const isErr = !item.is_valid && item.raw_string && item.raw_string !== "____";
                return `
                <div class="border rounded p-1 text-center ${isErr ? 'bg-rose-50 border-rose-300' : 'bg-slate-50'}">
                  <div class="font-bold text-slate-600 mb-0.5 text-[10px]">Câu ${q}</div>
                  <input type="number" step="any" id="p3_q${q}"
                         value="${item.is_valid && item.normalized_value !== null ? item.normalized_value : ''}"
                         placeholder="${isErr ? 'LỖI (0đ)' : ''}"
                         class="w-full border rounded text-center font-bold px-1 py-0.5 text-xs ${isErr ? 'border-rose-400 bg-white text-rose-700 placeholder-rose-500' : 'bg-white'} focus:bg-amber-100" />
                  <span class="text-[9px] block mt-0.5 font-mono ${isErr ? 'text-rose-600 font-bold' : 'text-slate-400'}">
                    Đọc: ${item.raw_string || '-'}
                  </span>
                </div>`;
              }).join("")}
            </div>
          </div>
        </div>
      `;
    }

    async function deleteSubmission(subId, fileName) {
      if (!confirm(`Xác nhận xóa bài thi: "${fileName}" khỏi đợt chấm?`)) {
        return;
      }

      try {
        const res = await fetch(`/api/delete-submission/${subId}`, { method: "DELETE" });
        if (res.ok) {
          if (selectedSubId === subId) {
            selectedSubId = null;
            localStorage.removeItem("omr_active_sub_id");
          }
          await refreshSession();
        } else {
          alert("Lỗi: Không thể xóa bài thi này.");
        }
      } catch (e) {
        alert("Lỗi kết nối: " + e.message);
      }
    }

    async function triggerInstantRegrade(subId) {
      const sub = currentSubmissions.find(s => s.submission_id === subId);
      if (!sub) return;

      const editMadeInput = document.getElementById("editMade");
      const editSbdInput = document.getElementById("editSbd");

      const newExamCode = editMadeInput ? editMadeInput.value.trim().padStart(4, '0') : sub.exam_code;
      const newSbd = editSbdInput ? editSbdInput.value.trim() : sub.sbd;

      const p1Data = {};
      for (let q in (sub.details?.part1 || {})) {
        const inp = document.getElementById(`p1_q${q}`);
        p1Data[q] = inp ? inp.value.trim().toUpperCase() : sub.details.part1[q];
      }

      const p2Data = {};
      for (let q in (sub.details?.part2 || {})) {
        p2Data[q] = {};
        for (let k of ['a', 'b', 'c', 'd']) {
          const inp = document.getElementById(`p2_q${q}_${k}`);
          p2Data[q][k] = inp ? inp.value.trim().toUpperCase() : (sub.details.part2[q] ? sub.details.part2[q][k] : "");
        }
      }

      const p3Data = {};
      for (let q in (sub.details?.part3 || {})) {
        const inp = document.getElementById(`p3_q${q}`);
        p3Data[q] = inp ? (inp.value.trim() !== "" ? parseFloat(inp.value) : null) : (sub.details.part3[q] ? sub.details.part3[q].normalized_value : null);
      }

      const payload = {
        submission_id: subId,
        sbd: newSbd,
        exam_code: newExamCode,
        part1: p1Data,
        part2: p2Data,
        part3: p3Data
      };

      try {
        const res = await fetch("/api/update-submission", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (!res.ok) throw new Error("Máy chủ phản hồi lỗi khi cập nhật.");

        const data = await res.json();
        const updated = data.updated_submission;

        const idx = currentSubmissions.findIndex(s => s.submission_id === subId);
        if (idx >= 0) {
          currentSubmissions[idx] = updated;
        }

        renderList();
        selectSubmission(subId);

        const sheetImg = document.getElementById("gradedSheetImg");
        if (sheetImg) {
          sheetImg.src = `/api/graded-image/${subId}?t=${Date.now()}`;
        }
      } catch (err) {
        alert("Lỗi khi chấm lại điểm: " + err.message);
      }
    }

    function zoomSheet(delta) {
      currentSheetZoom = Math.max(0.5, Math.min(2.5, currentSheetZoom + delta));
      document.getElementById("gradedSheetImg").style.transform = `scale(${currentSheetZoom})`;
    }
    function resetZoomSheet() {
      currentSheetZoom = 1.0;
      document.getElementById("gradedSheetImg").style.transform = "scale(1.0)";
    }
    function openGradedTab() {
      if (selectedSubId) {
        window.open(`/api/graded-image/${selectedSubId}`, "_blank");
      }
    }

    function downloadTemplate() { window.location.href = "/api/download-template"; }

    // =========================================================================
    // HỘP THOẠI CHỌN NƠI LƯU (SAVE AS DIALOG) TÍCH HỢP CHO PDF VÀ EXCEL
    // =========================================================================
    async function saveFileWithPicker(fileType) {
      const isPdf = fileType === 'pdf';
      const btn = document.getElementById(isPdf ? "btnExportPdf" : "btnExportExcel");
      const oldHtml = btn.innerHTML;
      btn.innerHTML = `<span class="inline-block animate-spin mr-1">⏳</span> Đang tạo...`;
      btn.disabled = true;

      const endpoint = isPdf ? "/api/export-graded-pdf" : "/api/export-excel";
      const mimeType = isPdf 
        ? "application/pdf" 
        : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
      const ext = isPdf ? ".pdf" : ".xlsx";
      const desc = isPdf ? "Tập phiếu đã chấm PDF" : "Bảng điểm Excel";

      try {
        const res = await fetch(endpoint);
        if (!res.ok) {
          const errData = await res.json().catch(() => ({ detail: "Mã lỗi HTTP: " + res.status }));
          throw new Error(errData.detail || "Không thể xuất tệp dữ liệu.");
        }

        // Lấy tên tệp gợi ý từ header Content-Disposition
        let suggestedName = isPdf ? `TAP_PHIEU_DA_CHAM_${Date.now()}.pdf` : `BANG_DIEM_${Date.now()}.xlsx`;
        const disposition = res.headers.get("content-disposition");
        if (disposition && disposition.indexOf("filename=") !== -1) {
          const matches = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/.exec(disposition);
          if (matches != null && matches[1]) {
            suggestedName = matches[1].replace(/['"]/g, '');
          }
        }

        const blob = await res.blob();

        // 1. NẾU TRÌNH DUYỆT HỖ TRỢ FILE SYSTEM ACCESS API: MỞ CỬA SỔ CHỌN NƠI LƯU (SAVE AS)
        if ('showSaveFilePicker' in window) {
          try {
            const handle = await window.showSaveFilePicker({
              suggestedName: suggestedName,
              types: [{
                description: desc,
                accept: { [mimeType]: [ext] }
              }]
            });
            const writable = await handle.createWritable();
            await writable.write(blob);
            await writable.close();
            alert(`[✓] Đã lưu tệp thành công vào vị trí bạn đã chọn!`);
            return;
          } catch (pickerErr) {
            // Nếu người dùng chủ động nhấn 'Cancel' trên cửa sổ Save As
            if (pickerErr.name === 'AbortError') {
              return;
            }
            console.warn("showSaveFilePicker thất bại, chuyển sang chế độ tải trực tiếp:", pickerErr);
          }
        }

        // 2. PHƯƠNG ÁN DỰ PHÒNG AN TOÀN (FALLBACK)
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.style.display = "none";
        a.href = url;
        a.download = suggestedName;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);

      } catch (err) {
        alert("Thông báo xuất tệp: " + err.message);
      } finally {
        btn.innerHTML = oldHtml;
        btn.disabled = false;
      }
    }

    // SMART AUTO-POLLING TỪ THIẾT BỊ DI ĐỘNG (DUY NHẤT 1 VÒNG LẶP)
    setInterval(async () => {
      const activeEl = document.activeElement;
      if (activeEl && (activeEl.tagName === "INPUT" || activeEl.tagName === "TEXTAREA")) {
        return;
      }

      try {
        const res = await fetch("/api/session");
        if (!res.ok) return;
        const data = await res.json();
        const serverSubs = data.submissions || [];

        if (serverSubs.length !== currentSubmissions.length) {
          const isNewAdded = serverSubs.length > currentSubmissions.length;
          currentSubmissions = serverSubs;
          renderList();

          if (isNewAdded && currentSubmissions.length > 0) {
            const newestSub = currentSubmissions[currentSubmissions.length - 1];
            selectSubmission(newestSub.submission_id);

            const badge = document.getElementById("badgeCount");
            badge.className = "text-[10px] bg-emerald-500 text-white font-bold px-2.5 py-0.5 rounded-full animate-bounce";
            setTimeout(() => {
              badge.className = "text-[10px] bg-indigo-100 text-indigo-800 font-bold px-2 py-0.5 rounded-full";
            }, 1800);
          }
        }
      } catch (e) {
        // Bỏ qua lỗi ngắt quãng mạng
      }
    }, 2000);
  </script>
</body>
</html>
```

## FILE: templates\manifest.json
```json
{
  "name": "OMR Chấm Thi Di Động",
  "short_name": "OMR Chấm Thi",
  "description": "Hệ thống chấm thi trắc nghiệm OMR chuẩn Bộ GD&ĐT 2025 trên điện thoại",
  "start_url": "/scanner",
  "scope": "/",
  "display": "standalone",
  "background_color": "#020617",
  "theme_color": "#0f172a",
  "orientation": "portrait",
  "icons": [
    {
      "src": "/icons/icon-192.png",
      "sizes": "192x192",
      "type": "image/png",
      "purpose": "any maskable"
    },
    {
      "src": "/icons/icon-512.png",
      "sizes": "512x512",
      "type": "image/png",
      "purpose": "any maskable"
    }
  ]
}

```

## FILE: templates\mobile_scanner.html
```html
<!-- templates/mobile_scanner.html -->
<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
  <title>OMR Chấm Thi Di Động</title>
  
  <!-- PWA Meta Tags -->
  <link rel="manifest" href="/manifest.json">
  <meta name="theme-color" content="#0f172a">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="OMR Chấm Thi">
  <link rel="apple-touch-icon" href="/icons/icon-192.png">

  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body {
      touch-action: pan-y;
      background-color: #020617;
      padding-top: env(safe-area-inset-top);
      padding-bottom: env(safe-area-inset-bottom);
    }
    .viewfinder-mask { box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.70); }
    
    /* Khung ngắm góc quang học kiểu bracket mở (rộng 58px, tâm trong suốt không che mốc đen) */
    .target-corner {
      position: absolute;
      width: 58px;
      height: 58px;
      transition: all 0.12s ease-out;
      display: flex;
      align-items: center;
      justify-content: center;
      pointer-events: none;
      z-index: 20;
    }
    .corner-tl { top: -2px; left: -2px; border-top: 4px solid #ef4444; border-left: 4px solid #ef4444; border-top-left-radius: 16px; }
    .corner-tr { top: -2px; right: -2px; border-top: 4px solid #ef4444; border-right: 4px solid #ef4444; border-top-right-radius: 16px; }
    .corner-bl { bottom: -2px; left: -2px; border-bottom: 4px solid #ef4444; border-left: 4px solid #ef4444; border-bottom-left-radius: 16px; }
    .corner-br { bottom: -2px; right: -2px; border-bottom: 4px solid #ef4444; border-right: 4px solid #ef4444; border-bottom-right-radius: 16px; }

    .target-corner.unmatched {
      border-color: #ef4444 !important;
      background-color: rgba(239, 68, 68, 0.08) !important;
    }
    .target-corner.matched {
      border-color: #10b981 !important;
      background-color: rgba(16, 185, 129, 0.28) !important;
      box-shadow: 0 0 16px rgba(16, 185, 129, 0.85);
      transform: scale(1.05);
    }
    .target-corner.matched::after {
      content: '✓';
      color: #10b981;
      font-size: 16px;
      font-weight: 900;
      background: rgba(0, 0, 0, 0.6);
      border-radius: 50%;
      width: 20px;
      height: 20px;
      display: flex;
      align-items: center;
      justify-content: center;
      position: absolute;
    }
    
    .tab-content { display: none; }
    .tab-content.active { display: flex; }
    
    /* Tùy chỉnh thanh cuộn */
    ::-webkit-scrollbar { width: 4px; }
    ::-webkit-scrollbar-track { background: #0f172a; }
    ::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
  </style>
</head>
<body class="h-screen w-screen flex flex-col justify-between text-white font-sans select-none overflow-hidden">

  <!-- CẢNH BÁO KHI MỞ TRONG TRÌNH DUYỆT NHÚNG (ZALO / MESSENGER) -->
  <div id="inAppBrowserAlert" class="hidden bg-amber-500 text-slate-950 px-3 py-1.5 text-[11px] font-bold flex justify-between items-center z-50 shrink-0">
    <span>💡 Nếu camera không hiện: Bấm dấu (⋮) góc trên chọn <b>"Mở bằng trình duyệt" (Chrome/Safari)</b></span>
    <button onclick="this.parentElement.remove()" class="px-1.5 py-0.5 bg-black/20 rounded font-bold">✕</button>
  </div>

  <!-- FLOATING TOAST NOTIFICATION (THAY THẾ WINDOW.ALERT ĐỂ KHÔNG ĐƠ CAMERA) -->
  <div id="floatingToast" class="fixed top-14 left-4 right-4 z-50 pointer-events-none transition-all duration-300 transform -translate-y-12 opacity-0 flex justify-center">
    <div id="floatingToastContent" class="bg-rose-950/95 border border-rose-500 text-rose-200 px-4 py-2.5 rounded-2xl shadow-2xl backdrop-blur text-xs font-semibold flex items-center gap-2 max-w-sm text-center">
      <span id="toastIcon">⚠️</span>
      <span id="toastMsg">Thông báo</span>
    </div>
  </div>

  <!-- ========================================================================= -->
  <!-- TOP HEADER (DÙNG CHUNG) -->
  <!-- ========================================================================= -->
  <header class="w-full px-4 py-2 bg-slate-900/95 backdrop-blur z-30 flex justify-between items-center shrink-0 border-b border-slate-800">
    <div class="flex items-center gap-2">
      <div class="w-7 h-7 bg-amber-500 text-slate-950 font-black rounded-lg flex items-center justify-center text-xs tracking-wider shadow">
        OMR
      </div>
      <div>
        <h1 class="text-xs font-bold text-amber-400 uppercase tracking-wide truncate max-w-[170px]" id="headerExamTitle">
          ĐANG TẢI...
        </h1>
        <p class="text-[10px] text-slate-400 flex items-center gap-1" id="headerExamSubtitle">
          <span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" id="serverStatusDot"></span>
          <span id="serverStatusText">Đang kết nối máy chủ...</span>
        </p>
      </div>
    </div>

    <div class="flex items-center gap-1.5">
      <span id="badgeSubCount" class="px-2 py-0.5 rounded text-[10px] font-bold bg-indigo-950 text-indigo-300 border border-indigo-800">
        0 bài
      </span>
      <button id="btnPwaInstall" onclick="promptPwaInstall()" class="hidden px-2 py-0.5 rounded text-[10px] font-bold bg-amber-600 text-white animate-pulse">
        + Cài App
      </button>
    </div>
  </header>

  <!-- ========================================================================= -->
  <!-- MAIN TABS CONTAINER -->
  <!-- ========================================================================= -->
  <div class="flex-1 w-full relative overflow-hidden flex flex-col">

    <!-- ----------------------------------------------------------------------- -->
    <!-- TAB 1: CAMERA SCANNER -->
    <!-- ----------------------------------------------------------------------- -->
    <div id="tabScanner" class="tab-content active relative flex-1 w-full flex-col items-center justify-between overflow-hidden">
      <!-- Thẻ video với muted playsinline bắt buộc để autoplay trên mobile -->
      <video id="videoElement" autoplay playsinline muted class="absolute inset-0 w-full h-full object-cover bg-black z-0"></video>

      <!-- SUB-HEADER HƯỚNG DẪN QUÉT (ĐỎ KHI CHƯA KHÓA PHIẾU, XANH LÁ KHI ĐÃ KHÓA) -->
      <div class="w-full bg-slate-950/80 backdrop-blur px-4 py-2 border-b border-slate-800 shrink-0 text-center z-20">
        <div class="text-xs font-bold text-rose-400 flex items-center justify-center gap-1.5" id="scanStatusTitle">
          <span class="w-2 h-2 rounded-full bg-rose-500 animate-ping" id="scanPingDot"></span>
          <span id="scanStatusText">Đang tìm phiếu trả lời OMR...</span>
        </div>
        <p id="guideText" class="text-[11px] text-slate-300 mt-0.5 leading-tight">
          Căn 4 mốc đen góc vào 4 khung ngắm. Đúng phiếu OMR máy sẽ tự chụp.
        </p>
      </div>

      <!-- KHUNG NGẮM TỶ LỆ CHUẨN 4 MỐC M0 - M4 (1:1.444) - ĐỎ TUYỆT ĐỐI KHI CHƯA ĐỦ MỐC -->
      <div class="flex-1 w-full flex items-center justify-center relative pointer-events-none my-1">
        <div id="viewfinder" class="relative w-[92%] max-w-[380px] aspect-[1/1.444] border-2 border-dashed border-rose-500/80 rounded-2xl viewfinder-mask transition-all duration-150 flex flex-col justify-between p-1 overflow-hidden">
          <!-- Canvas AR Overlay bám mục tiêu thời gian thực đè khít bên trong viewfinder -->
          <canvas id="overlayCanvas" class="absolute inset-0 w-full h-full pointer-events-none rounded-2xl" style="background: transparent; pointer-events: none; z-index: 15;"></canvas>

          <!-- NÚT MỞ KHÓA CAMERA NẾU BỊ TRÌNH DUYỆT CHẶN AUTOPLAY HOẶC ĐEN MÀN HÌNH -->
          <div id="cameraUnblockBtn" class="hidden absolute inset-0 z-30 flex items-center justify-center bg-black/60 backdrop-blur-xs pointer-events-auto">
            <button onclick="userActivateCamera()" class="px-5 py-3 bg-amber-500 hover:bg-amber-400 active:scale-95 text-slate-950 font-black rounded-2xl shadow-2xl flex items-center gap-2 border-2 border-white animate-bounce text-xs">
              <span class="text-lg">📷</span>
              <span>Bấm để bật Camera</span>
            </button>
          </div>

          <!-- 4 Khung ngắm góc Bracket -->
          <div id="reticle-tl" class="target-corner corner-tl unmatched"></div>
          <div id="reticle-tr" class="target-corner corner-tr unmatched"></div>
          <div id="reticle-bl" class="target-corner corner-bl unmatched"></div>
          <div id="reticle-br" class="target-corner corner-br unmatched"></div>

          <div id="labelM0" class="w-full text-center text-[9px] text-rose-400/80 font-mono tracking-widest mt-1">MỐC ĐẦU ĐỀ (M0)</div>
          
          <!-- HỘP TRẠNG THÁI KHÓA MỤC TIÊU (MÀU ĐỎ MẶC ĐỊNH KHI CHƯA ĐỦ MỐC) -->
          <div id="guidanceBox" class="text-center text-[11px] font-bold text-rose-200 bg-rose-950/90 px-3.5 py-1.5 rounded-full mx-auto shadow-xl border border-rose-500/60 transition-all flex items-center gap-1.5 pointer-events-auto">
            <span id="guideIcon">🎯</span>
            <span id="guideBoxText">Không phải phiếu OMR - Đưa phiếu vào khung</span>
          </div>

          <div id="labelM4" class="w-full text-center text-[9px] text-rose-400/80 font-mono tracking-widest mb-1">MỐC CUỐI ĐỀ (M4)</div>
        </div>
      </div>

      <!-- THANH ĐIỀU KHIỂN HÀNH ĐỘNG CAMERA -->
      <div class="w-full z-20 flex flex-col items-center gap-2 pb-2 shrink-0 bg-gradient-to-t from-slate-950 via-slate-950/80 to-transparent pt-3 px-4">
        
        <!-- HÀNG NÚT CHÍNH: CHỤP VÀ CHẤM NGAY + ĐÈN FLASH -->
        <div class="w-full flex justify-center items-center gap-2 max-w-sm">
          <!-- NÚT CHỤP VÀ CHẤM NGAY NỔI BẬT TO RÕ RÀNG -->
          <button id="btnSnapInstant" onclick="triggerManualCapture()" class="flex-1 py-3 bg-white hover:bg-slate-100 active:scale-95 text-slate-950 rounded-full font-black text-xs shadow-2xl flex items-center justify-center gap-2 border-2 border-emerald-400 transition">
            <svg class="w-4 h-4 text-emerald-600" fill="currentColor" viewBox="0 0 20 20">
              <path fill-rule="evenodd" d="M4 5a2 2 0 00-2 2v8a2 2 0 002 2h12a2 2 0 002-2V7a2 2 0 00-2-2h-1.586a1 1 0 01-.707-.293l-1.121-1.121A2 2 0 0011.172 3H8.828a2 2 0 00-1.414.586L6.293 4.707A1 1 0 015.586 5H4zm6 9a3 3 0 100-6 3 3 0 000 6z" clip-rule="evenodd"></path>
            </svg>
            <span>Chụp và chấm ngay</span>
          </button>

          <!-- NÚT BẬT ĐÈN FLASH HỖ TRỢ -->
          <button id="btnTorchToggle" onclick="toggleTorch()" class="px-4 py-3 bg-slate-900/90 text-amber-300 hover:text-white rounded-full font-bold text-xs border border-slate-700 shadow-xl flex items-center justify-center gap-1.5 active:scale-95 transition">
            <span>⚡</span>
            <span id="torchLabel">Bật đèn</span>
          </button>
        </div>

        <!-- HÀNG NÚT PHỤ: ĐỔI CAMERA + CHỤP BẰNG APP GỐC -->
        <div class="w-full flex justify-between items-center max-w-sm px-2 text-slate-400">
          <button onclick="switchCamera()" class="p-2 bg-slate-900/80 rounded-full border border-slate-700 active:scale-95 transition text-xs flex items-center gap-1">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
            <span>Đổi cam</span>
          </button>

          <!-- Nút Chụp bằng camera gốc máy (Luôn hoạt động 100% khi trình duyệt chặn WebRTC) -->
          <button onclick="document.getElementById('nativeCameraInput').click()" class="px-3 py-1.5 bg-indigo-600/90 hover:bg-indigo-500 text-white rounded-full text-[11px] font-bold shadow flex items-center gap-1.5 border border-indigo-400 active:scale-95 transition">
            <svg class="w-3.5 h-3.5 text-amber-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"></path></svg>
            <span>Chụp máy gốc</span>
          </button>
        </div>

      </div>

      <!-- TOAST THÔNG BÁO KẾT QUẢ VỪA CHẤM XONG -->
      <div id="recentResultDrawer" class="absolute bottom-28 left-4 right-4 z-30 bg-slate-900/95 border border-emerald-500/60 rounded-2xl p-3.5 shadow-2xl backdrop-blur hidden flex items-center justify-between transition-all">
        <div class="flex items-center gap-3">
          <div class="w-12 h-12 bg-emerald-600/30 border border-emerald-500 rounded-xl flex flex-col items-center justify-center shrink-0">
            <span class="text-[9px] text-emerald-300 font-bold uppercase">Điểm</span>
            <span id="toastTotalScore" class="text-base font-black text-white leading-none">0.0</span>
          </div>
          <div>
            <div class="flex items-center gap-2">
              <span class="text-xs font-bold text-white">SBD: <span id="toastSbd" class="text-amber-400">---</span></span>
              <span class="text-[10px] bg-slate-800 text-slate-300 px-1.5 py-0.2 rounded font-mono">Đề: <span id="toastExamCode">---</span></span>
            </div>
            <p class="text-[10px] text-emerald-400 mt-0.5" id="toastBreakdown">P1: 0.0 | P2: 0.0 | P3: 0.0</p>
          </div>
        </div>
        <div class="flex flex-col gap-1.5 shrink-0">
          <button onclick="viewLatestGradedImage()" class="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-bold flex items-center gap-1 shadow">
            <span>🔍 Xem ảnh</span>
          </button>
          <button onclick="closeResultToast()" class="px-2.5 py-1 bg-slate-800 text-slate-400 rounded-lg text-[10px]">Đóng</button>
        </div>
      </div>
    </div>

    <!-- ----------------------------------------------------------------------- -->
    <!-- TAB 2: BẢNG ĐIỂM & DANH SÁCH BÀI CHẤM -->
    <!-- ----------------------------------------------------------------------- -->
    <div id="tabResults" class="tab-content w-full h-full flex-col bg-slate-950 overflow-hidden">
      <!-- Search Bar -->
      <div class="p-3 border-b border-slate-800 bg-slate-900/70 flex gap-2 items-center shrink-0">
        <div class="relative flex-1">
          <input type="text" id="searchSbdInput" oninput="renderSubmissionsList()" placeholder="Tìm số báo danh, mã đề..." class="w-full bg-slate-800 border border-slate-700 rounded-xl px-3 py-1.5 text-xs text-white placeholder-slate-500 outline-none focus:border-indigo-500" />
        </div>
        <button onclick="refreshSubmissions()" class="p-1.5 bg-slate-800 text-slate-300 rounded-xl border border-slate-700 text-xs">
          🔄
        </button>
      </div>

      <!-- Danh sách bài thi -->
      <div id="resultsListContainer" class="flex-1 overflow-y-auto p-3 space-y-2">
        <div class="text-center text-slate-500 py-20 text-xs">
          Đang tải danh sách bài làm...
        </div>
      </div>
    </div>

    <!-- ----------------------------------------------------------------------- -->
    <!-- TAB 3: QUẢN LÝ ĐỀ & XUẤT FILE -->
    <!-- ----------------------------------------------------------------------- -->
    <div id="tabExam" class="tab-content w-full h-full flex-col bg-slate-950 overflow-y-auto p-4 space-y-4">
      
      <!-- Card: Thông tin đợt kiểm tra -->
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-4">
        <div class="flex justify-between items-start mb-2">
          <div>
            <span class="text-[10px] text-indigo-400 font-bold uppercase tracking-wider">Đợt kiểm tra hiện tại</span>
            <h2 class="text-base font-bold text-white mt-0.5" id="cardExamSubject">---</h2>
            <p class="text-xs text-slate-400" id="cardExamDetails">---</p>
          </div>
          <span id="cardAnswerStatus" class="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-950 text-amber-300 border border-amber-800">
            Chưa có đáp án
          </span>
        </div>

        <div class="mt-3 pt-3 border-t border-slate-800/80 flex flex-col gap-2">
          <!-- Nạp file đáp án -->
          <label class="w-full py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-bold flex items-center justify-center gap-1.5 cursor-pointer shadow">
            <span>📄 Nạp File Đáp Án (Excel)</span>
            <input type="file" id="mobileKeyPicker" accept=".xlsx,.xls" class="hidden" onchange="uploadAnswerKeyMobile(event)">
          </label>
          <!-- Dán đáp án nhanh -->
          <button onclick="openSmartPasteMobile()" class="w-full py-2 bg-violet-600 hover:bg-violet-500 text-white rounded-xl text-xs font-bold flex items-center justify-center gap-1.5 shadow">
            <span>📋 Dán Đáp Án Nhanh (Smart Paste)</span>
          </button>
        </div>
      </div>

      <!-- Card: Xuất Báo Cáo & Bảng Điểm -->
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-4 space-y-2.5">
        <h3 class="text-xs font-bold text-slate-300 uppercase tracking-wider">Xuất Dữ Liệu Chấm Thi</h3>
        
        <button id="btnMobExportExcel" onclick="exportExcelMobile(event)" class="w-full py-2.5 bg-emerald-600 hover:bg-emerald-500 active:scale-95 text-white rounded-xl text-xs font-bold flex items-center justify-center gap-2 shadow transition">
          <span>📊 Tải Bảng Điểm Excel (.xlsx)</span>
        </button>

        <button id="btnMobExportPdf" onclick="exportPdfMobile(event)" class="w-full py-2.5 bg-rose-700 hover:bg-rose-600 active:scale-95 text-white rounded-xl text-xs font-bold flex items-center justify-center gap-2 shadow transition">
          <span>📑 Tải Toàn Bộ Bài Chấm PDF</span>
        </button>

        <div class="flex justify-between items-center text-[10px] text-slate-400 pt-1 border-t border-slate-800/60 px-1">
          <span>Link tải trực tiếp máy:</span>
          <div class="flex gap-3">
            <a href="/api/export-excel" download class="text-emerald-400 font-bold hover:underline">Tải Excel ↗</a>
            <a href="/api/export-pdf" download class="text-rose-400 font-bold hover:underline">Tải PDF ↗</a>
          </div>
        </div>
      </div>

      <!-- Card: Chuyển đổi / Tạo đợt thi mới -->
      <div class="bg-slate-900 border border-slate-800 rounded-2xl p-4 space-y-3">
        <div class="flex justify-between items-center">
          <h3 class="text-xs font-bold text-slate-300 uppercase tracking-wider">Danh Sách Các Đợt Thi</h3>
          <button onclick="toggleCreateExamForm()" class="text-[11px] text-amber-400 font-bold">+ Tạo đợt mới</button>
        </div>

        <!-- Form tạo đợt mới (ẩn/hiện) -->
        <div id="formCreateExamMobile" class="hidden bg-slate-950 border border-slate-800 rounded-xl p-3 space-y-2 text-xs">
          <div>
            <label class="block text-slate-400 text-[10px] mb-0.5">Môn Học:</label>
            <input type="text" id="mobInpSubject" value="Sinh học" class="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1 text-white text-xs">
          </div>
          <div class="grid grid-cols-2 gap-2">
            <div>
              <label class="block text-slate-400 text-[10px] mb-0.5">Kỳ Thi:</label>
              <input type="text" id="mobInpPeriod" value="Giữa kỳ I" class="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1 text-white text-xs">
            </div>
            <div>
              <label class="block text-slate-400 text-[10px] mb-0.5">Lớp:</label>
              <input type="text" id="mobInpClass" value="11A" class="w-full bg-slate-900 border border-slate-700 rounded px-2.5 py-1 text-white text-xs">
            </div>
          </div>
          <button onclick="submitCreateExamMobile()" class="w-full py-1.5 bg-indigo-600 text-white font-bold rounded text-xs mt-1">Lưu & Kích Hoạt</button>
        </div>

        <div id="mobileExamsList" class="space-y-1.5 max-h-48 overflow-y-auto"></div>
      </div>

    </div>

  </div>

  <!-- INPUT FILE ẨN ĐỂ MỞ CAMERA GỐC ĐIỆN THOẠI (DỰ PHÒNG KHI CẦN) -->
  <input type="file" id="nativeCameraInput" accept="image/*" capture="environment" class="hidden" onchange="handleNativeCameraCapture(event)">

  <!-- MODAL DÁN ĐÁP ÁN NHANH TRÊN MOBILE -->
  <div id="mobileSmartPasteModal" class="fixed inset-0 z-50 bg-black/90 flex flex-col justify-center hidden p-4">
    <div class="bg-slate-900 border border-slate-800 rounded-2xl p-4 flex flex-col max-h-[85vh]">
      <div class="flex justify-between items-center border-b border-slate-800 pb-2.5 mb-3">
        <div>
          <h3 class="text-xs font-bold text-violet-400 uppercase flex items-center gap-1">
            <span>📋 Dán Đáp Án Nhanh</span>
          </h3>
          <p class="text-[10px] text-slate-400">Dán từ Zalo, SMS, Word (P1, P2, P3)</p>
        </div>
        <button onclick="closeSmartPasteMobile()" class="px-2 py-1 text-slate-400 text-xs font-bold">✕</button>
      </div>
      <div class="space-y-2.5 overflow-y-auto flex-1">
        <div>
          <label class="block text-[10px] text-slate-400 mb-0.5">Mã đề mặc định:</label>
          <input type="text" id="mobDefaultMade" value="0001" maxlength="4" class="w-full bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs font-mono font-bold text-white">
        </div>
        <div>
          <label class="block text-[10px] text-slate-400 mb-0.5">Văn bản đáp án:</label>
          <textarea id="mobSmartPasteText" rows="9" placeholder="Dán nội dung từ Zalo/Word...
VD:
Mã đề: 0504
PHẦN I:
1.A 2.B 3.C
PHẦN II:
Câu 1: a) Đ, b) S, c) Đ, d) S
PHẦN III:
Câu 1: -14
Câu 2: 3,14" class="w-full bg-slate-950 border border-slate-700 rounded-lg p-2.5 text-xs font-mono text-slate-200 outline-none focus:border-violet-500 shadow-inner"></textarea>
        </div>
        <div id="mobSmartPasteFeedback" class="text-xs p-2 rounded hidden"></div>
      </div>
      <div class="mt-3 pt-2.5 border-t border-slate-800 flex justify-end gap-2">
        <button onclick="closeSmartPasteMobile()" class="px-3 py-1.5 bg-slate-800 text-slate-300 rounded-lg text-xs font-semibold">Đóng</button>
        <button onclick="submitSmartPasteMobile()" id="btnMobSubmitSmartPaste" class="px-3.5 py-1.5 bg-violet-600 hover:bg-violet-500 text-white rounded-lg text-xs font-bold shadow">
          Nạp Đáp Án
        </button>
      </div>
    </div>
  </div>

  <!-- ========================================================================= -->
  <!-- MODAL XEM CHI TIẾT ẢNH BÀI CHẤM BÚT ĐỎ (CÓ SPINNER VÀ TỰ SỬA ROUTE) -->
  <!-- ========================================================================= -->
  <div id="imageViewerModal" class="fixed inset-0 z-50 bg-black/95 flex flex-col justify-between hidden">
    <div class="p-3 bg-slate-900/90 backdrop-blur flex justify-between items-center z-10 border-b border-slate-800">
      <div>
        <h4 class="text-xs font-bold text-amber-400" id="viewerTitle">Bài làm</h4>
        <p class="text-[10px] text-slate-400" id="viewerSubtitle">Chi tiết tem bút đỏ</p>
      </div>
      <button onclick="closeImageViewer()" class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-white rounded-lg text-xs font-bold active:scale-95 transition">Đóng ✕</button>
    </div>
    <div class="flex-1 overflow-auto flex items-center justify-center p-2 relative">
      <div id="viewerLoading" class="text-slate-400 text-xs flex items-center gap-2">
        <svg class="animate-spin w-4 h-4 text-emerald-400" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path></svg>
        <span>Đang tải ảnh bài chấm...</span>
      </div>
      <img id="viewerImage" src="" alt="Bài làm" class="max-w-full max-h-full object-contain rounded-lg shadow-2xl hidden">
    </div>
  </div>

  <!-- ========================================================================= -->
  <!-- BOTTOM NAVIGATION BAR (CHO ĐIỆN THOẠI) -->
  <!-- ========================================================================= -->
  <nav class="w-full bg-slate-900/95 backdrop-blur border-t border-slate-800 flex justify-around items-center z-40 py-2 shrink-0">
    <button onclick="switchTab('tabScanner')" id="navScanner" class="flex flex-col items-center gap-0.5 text-emerald-400 font-bold text-[10px]">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
      <span>Quét Bài</span>
    </button>

    <button onclick="switchTab('tabResults')" id="navResults" class="flex flex-col items-center gap-0.5 text-slate-400 font-semibold text-[10px]">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"></path></svg>
      <span>Bảng Điểm</span>
    </button>

    <button onclick="switchTab('tabExam')" id="navExam" class="flex flex-col items-center gap-0.5 text-slate-400 font-semibold text-[10px]">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path></svg>
      <span>Đề & Xuất File</span>
    </button>
  </nav>

  <canvas id="analysisCanvas" class="hidden"></canvas>
  <canvas id="captureCanvas" class="hidden"></canvas>

  <script>
    // =========================================================================
    // KHỞI TẠO BIẾN TRẠNG THÁI TOÀN CỤC
    // =========================================================================
    let currentStream = null;
    let videoTrack = null;
    let facingMode = "environment";
    let isGrading = false;
    let opticalInterval = null;
    let lock4Frames = 0;
    let lastScanCooldownUntil = 0;
    let lastValidCornersNorm = null;
    let lastCornersPos = null;
    let deferredPrompt = null;
    let latestSubId = null;
    let isTorchOn = false;
    let toastTimer = null;
    let sessionRetryTimer = null;
    let sessionRetryCount = 0;
    let cameraWatchdogTimer = null;

    let sessionData = {
      active_exam_id: null,
      exam_info: null,
      exam_data: null,
      submissions: [],
      all_exams: []
    };

    const RETICLES = [
      { id: "reticle-tl", name: "Trên-Trái", matched: false },
      { id: "reticle-tr", name: "Trên-Phải", matched: false },
      { id: "reticle-bl", name: "Dưới-Trái", matched: false },
      { id: "reticle-br", name: "Dưới-Phải", matched: false }
    ];

    // Phát âm thanh phản hồi bằng Web Audio API
    function playBeep(isSuccess = true) {
      try {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) return;
        const ctx = new AudioContext();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        
        if (isSuccess) {
          osc.type = "sine";
          osc.frequency.setValueAtTime(587.33, ctx.currentTime); // D5
          osc.frequency.setValueAtTime(880, ctx.currentTime + 0.08); // A5
          gain.gain.setValueAtTime(0.25, ctx.currentTime);
          gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.25);
          osc.start(ctx.currentTime);
          osc.stop(ctx.currentTime + 0.25);
        } else {
          osc.type = "triangle";
          osc.frequency.setValueAtTime(220, ctx.currentTime);
          gain.gain.setValueAtTime(0.2, ctx.currentTime);
          gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.2);
          osc.start(ctx.currentTime);
          osc.stop(ctx.currentTime + 0.2);
        }
      } catch (e) {}
    }

    // Hiển thị thông báo Toast không gây đơ camera
    function showNotificationToast(msg, isError = true) {
      const toast = document.getElementById("floatingToast");
      const content = document.getElementById("floatingToastContent");
      const icon = document.getElementById("toastIcon");
      const text = document.getElementById("toastMsg");

      if (isError) {
        content.className = "bg-rose-950/95 border border-rose-500 text-rose-200 px-4 py-2.5 rounded-2xl shadow-2xl backdrop-blur text-xs font-semibold flex items-center gap-2 max-w-sm text-center";
        icon.innerText = "⚠️";
      } else {
        content.className = "bg-emerald-950/95 border border-emerald-500 text-emerald-200 px-4 py-2.5 rounded-2xl shadow-2xl backdrop-blur text-xs font-semibold flex items-center gap-2 max-w-sm text-center";
        icon.innerText = "✓";
      }
      text.innerText = msg;

      toast.classList.remove("-translate-y-12", "opacity-0");
      toast.classList.add("translate-y-0", "opacity-100");

      if (toastTimer) clearTimeout(toastTimer);
      toastTimer = setTimeout(() => {
        toast.classList.remove("translate-y-0", "opacity-100");
        toast.classList.add("-translate-y-12", "opacity-0");
      }, 3500);
    }

    // Kiểm tra nếu đang mở trong trình duyệt nhúng của ứng dụng (Zalo / FB / Messenger)
    const ua = navigator.userAgent || "";
    if (/Zalo|FBAN|FBAV|Instagram|Messenger|Line/i.test(ua)) {
      const alertEl = document.getElementById("inAppBrowserAlert");
      if (alertEl) alertEl.classList.remove("hidden");
    }

    // =========================================================================
    // PWA & SERVICE WORKER REGISTRATION (v9)
    // =========================================================================
    window.addEventListener('error', (event) => {
      console.error("Global JS Error:", event.error || event.message);
      const dot = document.getElementById("serverStatusDot");
      const statusText = document.getElementById("serverStatusText");
      if (dot && statusText && statusText.innerText.includes("Đang kết nối")) {
        dot.className = "w-1.5 h-1.5 rounded-full bg-rose-500 inline-block";
        statusText.innerHTML = `Lỗi script: ${(event.message || "Lỗi").slice(0, 30)}... <button onclick="window.location.reload(true)" class="underline font-bold text-amber-300 ml-1">Tải lại</button>`;
      }
    });

    if ('serviceWorker' in navigator) {
      window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js?v=9').then((reg) => {
          reg.update();
        }).catch(err => console.log('SW Fail:', err));
      });
    }

    window.addEventListener('beforeinstallprompt', (e) => {
      e.preventDefault();
      deferredPrompt = e;
      const btn = document.getElementById("btnPwaInstall");
      if (btn) btn.classList.remove("hidden");
    });

    function promptPwaInstall() {
      if (deferredPrompt) {
        deferredPrompt.prompt();
        deferredPrompt.userChoice.then(() => {
          deferredPrompt = null;
          document.getElementById("btnPwaInstall").classList.add("hidden");
        });
      } else {
        alert("Để cài App:\n- Trên iPhone (Safari): Bấm nút Chia Sẻ (Share ⬆️) -> Chọn 'Thêm vào MH chính'.\n- Trên Android: Bấm menu 3 chấm (⋮) -> Chọn 'Cài đặt ứng dụng'.");
      }
    }

    // =========================================================================
    // KHỞI ĐỘNG ỨNG DỤNG (BẬT CAMERA NGAY LẬP TỨC TRONG 200MS, KHÔNG CHỜ SERVER)
    // =========================================================================
    function initApp() {
      // 1. Mở Camera tức thì, không bị chặn bởi mạng
      startCamera();

      // 2. Tải dữ liệu đợt thi ngầm với cơ chế tự động thử lại khi máy chủ Render khởi động
      fetchSessionWithRetry();

      // 3. Khởi động vòng lặp kiểm tra mốc quang học 90ms/chu kỳ
      if (!opticalInterval) opticalInterval = setInterval(runOpticalMarkerDetection, 90);

      // Chạm màn hình để bật video nếu bị chặn autoplay
      document.body.addEventListener("click", () => {
        const video = document.getElementById("videoElement");
        if (video && video.paused) {
          video.play().catch(e => {});
        }
      }, { once: true });
    }

    if (document.readyState === "loading") {
      window.addEventListener("DOMContentLoaded", initApp);
    } else {
      initApp();
    }

    // =========================================================================
    // ĐIỀU HƯỚNG TABS
    // =========================================================================
    function switchTab(tabId) {
      document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
      document.getElementById(tabId).classList.add("active");

      const navs = {
        tabScanner: document.getElementById("navScanner"),
        tabResults: document.getElementById("navResults"),
        tabExam: document.getElementById("navExam")
      };

      Object.keys(navs).forEach(k => {
        if (k === tabId) {
          navs[k].className = "flex flex-col items-center gap-0.5 text-emerald-400 font-bold text-[10px]";
        } else {
          navs[k].className = "flex flex-col items-center gap-0.5 text-slate-400 font-semibold text-[10px]";
        }
      });

      if (tabId === "tabScanner") {
        if (!currentStream) startCamera();
        if (!opticalInterval) opticalInterval = setInterval(runOpticalMarkerDetection, 90);
      } else {
        if (opticalInterval) { clearInterval(opticalInterval); opticalInterval = null; }
        if (tabId === "tabResults") renderSubmissionsList();
        if (tabId === "tabExam") renderExamsList();
      }
    }

    // =========================================================================
    // ĐỒNG BỘ DỮ LIỆU PHIÊN CHẤM VỚI CƠ CHẾ AUTO-RETRY KHI SERVER COLD-START
    // =========================================================================
    async function fetchSessionWithRetry() {
      const dot = document.getElementById("serverStatusDot");
      const statusText = document.getElementById("serverStatusText");

      if (sessionRetryTimer) {
        clearTimeout(sessionRetryTimer);
        sessionRetryTimer = null;
      }

      // Timeout 8 giây với AbortController chống treo request khi Render cold-start
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 8000);

      try {
        const res = await fetch("/api/session", { signal: controller.signal, cache: "no-store" });
        clearTimeout(timeoutId);
        if (!res.ok) throw new Error("HTTP " + res.status);
        
        sessionData = await res.json();
        sessionRetryCount = 0;
        
        const count = sessionData.submissions ? sessionData.submissions.length : 0;
        document.getElementById("badgeSubCount").innerText = `${count} bài`;

        if (sessionData.exam_info) {
          const title = `${sessionData.exam_info.subject} - LỚP ${sessionData.exam_info.class_name}`;
          document.getElementById("headerExamTitle").innerText = title;
          document.getElementById("headerExamSubtitle").innerHTML = `
            <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block"></span>
            <span>Học kỳ: ${sessionData.exam_info.period}</span>
          `;

          document.getElementById("cardExamSubject").innerText = `${sessionData.exam_info.subject} (${sessionData.exam_info.class_name})`;
          document.getElementById("cardExamDetails").innerText = `Kỳ thi: ${sessionData.exam_info.period} | Năm học: ${sessionData.exam_info.school_year}`;
        }

        const hasKeys = sessionData.exam_info && sessionData.exam_info.is_configured;
        const statusBadge = document.getElementById("cardAnswerStatus");
        if (hasKeys) {
          statusBadge.innerText = "✓ Đã nạp đáp án";
          statusBadge.className = "px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950 text-emerald-300 border border-emerald-800";
        } else {
          statusBadge.innerText = "Chưa có đáp án";
          statusBadge.className = "px-2 py-0.5 rounded text-[10px] font-bold bg-amber-950 text-amber-300 border border-amber-800";
        }

      } catch (err) {
        clearTimeout(timeoutId);
        sessionRetryCount++;

        if (dot && statusText) {
          if (err.name === "AbortError") {
            // Timeout do server Render đang thức dậy (cold-start)
            dot.className = "w-1.5 h-1.5 rounded-full bg-amber-500 animate-ping inline-block";
            statusText.innerHTML = `⏳ Máy chủ đang khởi động (~30-50s)... Lần ${sessionRetryCount} <button onclick="fetchSessionWithRetry()" class="underline font-bold text-amber-300 ml-1">Thử lại</button>`;
          } else if (err.message && err.message.startsWith("HTTP")) {
            // Lỗi HTTP 500/502
            dot.className = "w-1.5 h-1.5 rounded-full bg-rose-500 inline-block";
            statusText.innerHTML = `Lỗi máy chủ (${err.message}) <button onclick="fetchSessionWithRetry()" class="underline font-bold text-rose-300 ml-1">Thử lại</button>`;
          } else {
            // Lỗi mạng chung
            if (sessionRetryCount >= 3) {
              dot.className = "w-1.5 h-1.5 rounded-full bg-amber-500 animate-ping inline-block";
              statusText.innerHTML = `⏳ Máy chủ đang khởi động (~30-50s)... Lần ${sessionRetryCount} <button onclick="fetchSessionWithRetry()" class="underline font-bold text-amber-300 ml-1">Thử lại</button>`;
            } else {
              dot.className = "w-1.5 h-1.5 rounded-full bg-amber-400 animate-ping inline-block";
              statusText.innerHTML = `Đang kết nối máy chủ... (Lần ${sessionRetryCount})`;
            }
          }
        }
        sessionRetryTimer = setTimeout(fetchSessionWithRetry, 3500);
      }
    }

    async function refreshSessionData() {
      await fetchSessionWithRetry();
    }

    // =========================================================================
    // CAMERA & NHẬN DIỆN MỐC QUANG HỌC CHUẨN XÁC
    // =========================================================================
    async function startCamera() {
      if (currentStream) {
        try {
          currentStream.getTracks().forEach(t => t.stop());
        } catch(e) {}
        currentStream = null;
      }

      const video = document.getElementById("videoElement");
      if (!video) return;

      video.muted = true;
      video.setAttribute("autoplay", "");
      video.setAttribute("playsinline", "");
      video.setAttribute("muted", "");

      // Cấu hình camera tối ưu, tương thích 100% Android Chrome & Xiaomi
      const constraintCandidates = [
        { video: { facingMode: { ideal: facingMode }, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false },
        { video: { facingMode: { ideal: facingMode } }, audio: false },
        { video: true, audio: false }
      ];

      let stream = null;
      let lastErr = null;

      for (const c of constraintCandidates) {
        try {
          stream = await navigator.mediaDevices.getUserMedia(c);
          if (stream) break;
        } catch (e) {
          lastErr = e;
        }
      }

      if (!stream) {
        console.warn("Camera getUserMedia failed:", lastErr);
        const unblockBtn = document.getElementById("cameraUnblockBtn");
        if (unblockBtn) unblockBtn.classList.remove("hidden");
        showNotificationToast("Không mở được camera trực tiếp. Hãy bấm 'Bật Camera' hoặc 'Chụp máy gốc'!", true);
        return;
      }

      try {
        currentStream = stream;
        video.srcObject = stream;
        videoTrack = stream.getVideoTracks()[0];

        // TUYỆT ĐỐI KHÔNG GỌI videoTrack.applyConstraints({ advanced: [focusMode, exposureMode] })
        // vì gây đen camera trên phần cứng Chrome Android / Xiaomi

        video.onloadedmetadata = async () => {
          try {
            await video.play();
            const unblockBtn = document.getElementById("cameraUnblockBtn");
            if (unblockBtn && video.videoWidth > 0 && !video.paused) {
              unblockBtn.classList.add("hidden");
            }
          } catch (e) {
            console.warn("Video play error on loadedmetadata:", e);
          }
        };

        await video.play();
      } catch (e) {
        console.warn("Video play initial warning:", e);
      }

      // CAMERA WATCHDOG (2.5 giây): Kiểm tra nếu thẻ video chưa phát hình hoặc bị chặn autoplay
      if (cameraWatchdogTimer) clearTimeout(cameraWatchdogTimer);
      cameraWatchdogTimer = setTimeout(async () => {
        const unblockBtn = document.getElementById("cameraUnblockBtn");
        if (!video || video.videoWidth === 0 || video.paused) {
          try {
            await video.play();
          } catch (e) {
            console.warn("Autoplay policy blocked video, showing tap button:", e);
          }
          if (!video || video.videoWidth === 0 || video.paused) {
            if (unblockBtn) unblockBtn.classList.remove("hidden");
          } else {
            if (unblockBtn) unblockBtn.classList.add("hidden");
          }
        } else {
          if (unblockBtn) unblockBtn.classList.add("hidden");
        }
      }, 2500);
    }

    async function userActivateCamera() {
      const video = document.getElementById("videoElement");
      const unblockBtn = document.getElementById("cameraUnblockBtn");
      if (unblockBtn) unblockBtn.classList.add("hidden");
      if (video) {
        try {
          await video.play();
          if (video.videoWidth > 0 && !video.paused) {
            return;
          }
        } catch (e) {
          console.warn("userActivateCamera play failed, re-running startCamera():", e);
        }
      }
      await startCamera();
    }

    function switchCamera() {
      facingMode = (facingMode === "environment") ? "user" : "environment";
      startCamera();
    }

    async function toggleTorch() {
      if (videoTrack && videoTrack.getCapabilities && videoTrack.getCapabilities().torch) {
        try {
          isTorchOn = !isTorchOn;
          await videoTrack.applyConstraints({ advanced: [{ torch: isTorchOn }] });
          document.getElementById("torchLabel").innerText = isTorchOn ? "Tắt đèn" : "Bật đèn";
        } catch (e) {
          showNotificationToast("Không thể điều khiển đèn Flash: " + e.message, true);
        }
      } else {
        showNotificationToast("Thiết bị không hỗ trợ bật đèn Flash trực tiếp.", true);
      }
    }

    // =========================================================================
    // THUẬT TOÁN "OMR SHEET FIDUCIAL DETECTOR" THỜI GIAN THỰC TRÊN VÙNG CROP VIEWFINDER (480 x 693)
    // Quy trình 6 bước:
    // 1. Cắt đúng vùng viewfinder từ video theo tỷ lệ object-cover sang canvas chuẩn 480x693
    // 2. Nhị phân hóa thích nghi cục bộ bằng Integral Image (35x35 px, chống bóng đổ tay/điện thoại)
    // 3. Gom vùng liên thông (Connected Components) & Lọc mốc vuông đen chuẩn (vành giấy trắng ringLum >= 90)
    // 4. Tìm 4 mốc góc (TL, TR, BR, BL) linh hoạt theo 4 góc mở rộng
    // 5. Xác thực mốc trung gian bất đối xứng M1, M2, M3 (t=0.324, 0.543, 0.682)
    // 6. Vẽ AR Overlay đè khít bên trong viewfinder & Tự động chụp khi khóa đủ điều kiện
    // =========================================================================
    function runOpticalMarkerDetection() {
      if (isGrading) return;
      const video = document.getElementById("videoElement");
      if (!video || video.readyState < 2 || video.paused || video.videoWidth === 0 || video.videoHeight === 0) return;

      const vw = video.videoWidth;
      const vh = video.videoHeight;
      const vfEl = document.getElementById("viewfinder");
      if (!vfEl) return;

      const vRect = video.getBoundingClientRect();
      const fRect = vfEl.getBoundingClientRect();
      if (!fRect || fRect.width === 0 || fRect.height === 0 || !vRect || vRect.width === 0 || vRect.height === 0) return;

      // 1. Tỷ lệ object-cover của video và tọa độ crop chuẩn xác của viewfinder
      const scale = Math.max(vRect.width / vw, vRect.height / vh);
      const offsetX = (vRect.width - vw * scale) / 2;
      const offsetY = (vRect.height - vh * scale) / 2;

      const sx = Math.max(0, (fRect.left - vRect.left - offsetX) / scale);
      const sy = Math.max(0, (fRect.top - vRect.top - offsetY) / scale);
      const sw = Math.min(vw - sx, fRect.width / scale);
      const sh = Math.min(vh - sy, fRect.height / scale);
      if (sw <= 10 || sh <= 10) return;

      const W = 480;
      const H = 693; // 480 * 1.44375

      const overlayCanvas = document.getElementById("overlayCanvas");
      if (overlayCanvas) {
        if (overlayCanvas.width !== W || overlayCanvas.height !== H) {
          overlayCanvas.width = W;
          overlayCanvas.height = H;
        }
      }
      const overlayCtx = overlayCanvas ? overlayCanvas.getContext("2d") : null;
      if (overlayCtx) {
        overlayCtx.clearRect(0, 0, W, H);
      }

      let canvas = document.getElementById("analysisCanvas");
      if (!canvas) {
        canvas = document.createElement("canvas");
        canvas.id = "analysisCanvas";
        canvas.style.display = "none";
        document.body.appendChild(canvas);
      }
      if (canvas.width !== W || canvas.height !== H) {
        canvas.width = W;
        canvas.height = H;
      }
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(video, sx, sy, sw, sh, 0, 0, W, H);
      const imgData = ctx.getImageData(0, 0, W, H);
      const data = imgData.data;

      // 2. Grayscale & Integral Image để nhị phân hóa thích nghi cục bộ (cửa sổ 35x35 px)
      const totalPixels = W * H;
      const gray = new Uint8Array(totalPixels);
      const binary = new Uint8Array(totalPixels);
      const intW = W + 1;
      const integral = new Int32Array((W + 1) * (H + 1));

      let ptr = 0;
      for (let y = 0; y < H; y++) {
        let rowSum = 0;
        const intRowPtr = (y + 1) * intW + 1;
        const prevIntRowPtr = y * intW + 1;
        for (let x = 0; x < W; x++) {
          const r = data[ptr];
          const g = data[ptr + 1];
          const b = data[ptr + 2];
          ptr += 4;

          const lum = Math.round(0.299 * r + 0.587 * g + 0.114 * b);
          gray[y * W + x] = lum;
          rowSum += lum;
          integral[intRowPtr + x] = integral[prevIntRowPtr + x] + rowSum;
        }
      }

      // Nhị phân hóa cục bộ cửa sổ 35x35 (bán kính R = 17 px)
      const blockR = 17;
      for (let y = 0; y < H; y++) {
        const y0 = Math.max(0, y - blockR);
        const y1 = Math.min(H - 1, y + blockR);
        for (let x = 0; x < W; x++) {
          const x0 = Math.max(0, x - blockR);
          const x1 = Math.min(W - 1, x + blockR);
          const count = (x1 - x0 + 1) * (y1 - y0 + 1);

          const A = integral[y0 * intW + x0];
          const B = integral[y0 * intW + (x1 + 1)];
          const C = integral[(y1 + 1) * intW + x0];
          const D = integral[(y1 + 1) * intW + (x1 + 1)];
          const localMean = (D - B - C + A) / count;

          const pIdx = y * W + x;
          const gVal = gray[pIdx];

          // Điểm tối thích nghi: tối hơn trung bình cục bộ 22 đơn vị và không quá sáng (gVal < 165)
          if (gVal < (localMean - 22) && gVal < 165) {
            binary[pIdx] = 1;
          }
        }
      }

      // 3. Connected Components & Lọc mốc vuông đen chuẩn
      const visited = new Uint8Array(totalPixels);
      const candidates = [];
      const qX = new Int32Array(1500);
      const qY = new Int32Array(1500);

      for (let y = 3; y < H - 3; y++) {
        for (let x = 3; x < W - 3; x++) {
          const idx = y * W + x;
          if (!binary[idx] || visited[idx]) continue;

          let qHead = 0, qTail = 0;
          qX[qTail] = x; qY[qTail] = y; qTail++;
          visited[idx] = 1;

          let minX = x, maxX = x, minY = y, maxY = y;
          let pCount = 0;

          while (qHead < qTail) {
            const cx = qX[qHead];
            const cy = qY[qHead];
            qHead++;
            pCount++;

            if (cx < minX) minX = cx;
            if (cx > maxX) maxX = cx;
            if (cy < minY) minY = cy;
            if (cy > maxY) maxY = cy;

            const neighbors = [
              (cy - 1) * W + cx,
              (cy + 1) * W + cx,
              cy * W + (cx - 1),
              cy * W + (cx + 1)
            ];
            const nCoords = [[cx, cy - 1], [cx, cy + 1], [cx - 1, cy], [cx + 1, cy]];

            for (let ni = 0; ni < 4; ni++) {
              const nIdx = neighbors[ni];
              const nx = nCoords[ni][0];
              const ny = nCoords[ni][1];
              if (nx >= 0 && nx < W && ny >= 0 && ny < H) {
                if (binary[nIdx] && !visited[nIdx]) {
                  visited[nIdx] = 1;
                  if (qTail < 1490) {
                    qX[qTail] = nx; qY[qTail] = ny; qTail++;
                  }
                }
              }
            }
          }

          const bw = maxX - minX + 1;
          const bh = maxY - minY + 1;

          // Lọc kích thước mốc vuông [5px, 28px] trên khung 480x693
          if (bw >= 5 && bw <= 28 && bh >= 5 && bh <= 28) {
            const aspect = bw / bh;
            if (aspect >= 0.55 && aspect <= 1.80) {
              const fillDensity = pCount / (bw * bh);
              if (fillDensity >= 0.48) {
                // Kiểm tra vành giấy bao quanh (mở rộng quanh bounding box)
                let coreSum = 0, coreCount = 0;
                const ringLums = [];
                let paperCount = 0;
                const midX = (minX + maxX) / 2;
                const midY = (minY + maxY) / 2;
                const rCore = Math.max(bw, bh) * 0.35;
                const rIn = Math.max(bw, bh) * 0.65;
                const rOut = Math.max(bw, bh) * 1.15;

                for (let dy = -Math.round(rOut); dy <= Math.round(rOut); dy++) {
                  const py = Math.round(midY + dy);
                  if (py < 0 || py >= H) continue;
                  for (let dx = -Math.round(rOut); dx <= Math.round(rOut); dx++) {
                    const px = Math.round(midX + dx);
                    if (px < 0 || px >= W) continue;
                    const d = Math.hypot(dx, dy);
                    const pI = py * W + px;
                    const gVal = gray[pI];

                    if (d <= rCore) {
                      coreSum += gVal; coreCount++;
                    } else if (d >= rIn && d <= rOut) {
                      const dI = pI * 4;
                      const r = data[dI], g = data[dI + 1], b = data[dI + 2];
                      const sat = Math.max(r, g, b) - Math.min(r, g, b);
                      ringLums.push(gVal);
                      if (gVal >= 85 && sat <= 65) {
                        paperCount++;
                      }
                    }
                  }
                }

                if (coreCount > 0 && ringLums.length > 0) {
                  const coreLum = coreSum / coreCount;
                  const paperRatio = paperCount / ringLums.length;
                  // Ít nhất 45% số pixel vùng bao quanh là giấy sáng (lum >= 85, sat <= 65)
                  if (paperRatio >= 0.45) {
                    ringLums.sort((a, b) => a - b);
                    const p75Idx = Math.floor(ringLums.length * 0.75);
                    const ringP75 = ringLums[p75Idx];
                    const contrast = ringP75 - coreLum;
                    // Hiệu tương phản giữa nhóm pixel sáng nhất (percentile 75) với lõi đen >= 22
                    if (contrast >= 22) {
                      candidates.push({
                        x: midX,
                        y: midY,
                        bw: bw,
                        bh: bh,
                        score: contrast
                      });
                    }
                  }
                }
              }
            }
          }
        }
      }

      // Vẽ chấm vàng cho các ứng viên mốc tìm thấy
      if (overlayCtx) {
        overlayCtx.fillStyle = "rgba(251, 191, 36, 0.45)";
        candidates.forEach(c => {
          overlayCtx.beginPath();
          overlayCtx.arc(c.x, c.y, 3.5, 0, Math.PI * 2);
          overlayCtx.fill();
        });
      }

      // 4. Tìm 4 mốc góc (TL, TR, BR, BL) linh hoạt theo 4 góc mở rộng
      let TL = null, TR = null, BR = null, BL = null;
      let minSumTL = Infinity, minSumTR = Infinity, minSumBR = Infinity, minSumBL = Infinity;

      for (const c of candidates) {
        // qBonus giảm ảnh hưởng điểm tương phản để tọa độ góc thực sự chiếm ưu thế (tránh ô đen Phần III cướp góc BL)
        const qBonus = Math.min(15, c.score * 0.1);
        // Góc trên-trái: x < 0.42*W, y < 0.35*H
        if (c.x < 0.42 * W && c.y < 0.35 * H) {
          const s = (c.x + c.y) - qBonus;
          if (s < minSumTL) { minSumTL = s; TL = c; }
        }
        // Góc trên-phải: x > 0.58*W, y < 0.35*H
        if (c.x > 0.58 * W && c.y < 0.35 * H) {
          const s = ((W - c.x) + c.y) - qBonus;
          if (s < minSumTR) { minSumTR = s; TR = c; }
        }
        // Góc dưới-phải: x > 0.58*W, y > 0.65*H
        if (c.x > 0.58 * W && c.y > 0.65 * H) {
          const s = ((W - c.x) + (H - c.y)) - qBonus;
          if (s < minSumBR) { minSumBR = s; BR = c; }
        }
        // Góc dưới-trái: x < 0.42*W, y > 0.65*H
        if (c.x < 0.42 * W && c.y > 0.65 * H) {
          const s = (c.x + (H - c.y)) - qBonus;
          if (s < minSumBL) { minSumBL = s; BL = c; }
        }
      }

      const cornersCount = (TL ? 1 : 0) + (TR ? 1 : 0) + (BR ? 1 : 0) + (BL ? 1 : 0);
      let isValidSheet = false;
      let matchedIntermediates = [];
      let quadValid = false;

      // 5. Kiểm tra hình học tứ giác và xác thực mốc bất đối xứng trung gian M1, M2, M3
      if (cornersCount === 4) {
        const wTop = Math.hypot(TR.x - TL.x, TR.y - TL.y);
        const wBot = Math.hypot(BR.x - BL.x, BR.y - BL.y);
        const hLeft = Math.hypot(BL.x - TL.x, BL.y - TL.y);
        const hRight = Math.hypot(BR.x - TR.x, BR.y - TR.y);

        const avgW = (wTop + wBot) / 2;
        const avgH = (hLeft + hRight) / 2;

        if (avgW >= 0.42 * W && avgH >= 0.42 * H) {
          const ratio = avgH / avgW;
          if (ratio >= 1.05 && ratio <= 1.92) {
            // Chênh lệch chiều dài 2 cạnh đối diện cho phép tối đa 30% (chịu góc nghiêng tay)
            const maxW = Math.max(wTop, wBot);
            const maxH = Math.max(hLeft, hRight);
            if ((Math.abs(wTop - wBot) / maxW <= 0.30) && (Math.abs(hLeft - hRight) / maxH <= 0.30)) {
              // Kiểm tra tất cả 4 góc trong của tứ giác nằm trong khoảng [58°, 122°]
              const getAngleDeg = (p1, pCenter, p2) => {
                const v1x = p1.x - pCenter.x, v1y = p1.y - pCenter.y;
                const v2x = p2.x - pCenter.x, v2y = p2.y - pCenter.y;
                const dot = v1x * v2x + v1y * v2y;
                const m1 = Math.hypot(v1x, v1y), m2 = Math.hypot(v2x, v2y);
                if (m1 === 0 || m2 === 0) return 0;
                const cosVal = Math.max(-1, Math.min(1, dot / (m1 * m2)));
                return Math.acos(cosVal) * (180 / Math.PI);
              };

              const angTL = getAngleDeg(TR, TL, BL);
              const angTR = getAngleDeg(TL, TR, BR);
              const angBR = getAngleDeg(TR, BR, BL);
              const angBL = getAngleDeg(BR, BL, TL);

              if (angTL >= 58 && angTL <= 122 &&
                  angTR >= 58 && angTR <= 122 &&
                  angBR >= 58 && angBR <= 122 &&
                  angBL >= 58 && angBL <= 122) {
                quadValid = true;

                // Xác thực 3 cặp mốc trung gian: t = 0.324 (M1), 0.543 (M2), 0.682 (M3)
                const m_ratios = [0.324, 0.543, 0.682];
                let hasM2 = false;
                let matchedLeft = 0;
                let matchedRight = 0;

                m_ratios.forEach((t, mIdx) => {
                  const predX_L = TL.x + t * (BL.x - TL.x);
                  const predY_L = TL.y + t * (BL.y - TL.y);
                  for (const cand of candidates) {
                    if (cand === TL || cand === BL || cand === TR || cand === BR) continue;
                    if (Math.hypot(cand.x - predX_L, cand.y - predY_L) <= 18.0) {
                      matchedIntermediates.push({ x: cand.x, y: cand.y, isM2: (mIdx === 1) });
                      matchedLeft++;
                      if (mIdx === 1) hasM2 = true;
                      break;
                    }
                  }
                });

                m_ratios.forEach((t, mIdx) => {
                  const predX_R = TR.x + t * (BR.x - TR.x);
                  const predY_R = TR.y + t * (BR.y - TR.y);
                  for (const cand of candidates) {
                    if (cand === TL || cand === BL || cand === TR || cand === BR) continue;
                    if (Math.hypot(cand.x - predX_R, cand.y - predY_R) <= 18.0) {
                      matchedIntermediates.push({ x: cand.x, y: cand.y, isM2: (mIdx === 1) });
                      matchedRight++;
                      if (mIdx === 1) hasM2 = true;
                      break;
                    }
                  }
                });

                // Điều kiện công nhận: khóa đủ 4 mốc góc + ít nhất 3/6 mốc cạnh (bắt buộc có mốc M2 và có mốc ở cả 2 bên lề trái & phải)
                if (matchedIntermediates.length >= 3 && hasM2 && matchedLeft >= 1 && matchedRight >= 1) {
                  isValidSheet = true;
                  // Chuẩn hóa tọa độ 4 góc hợp lệ theo kích thước video gốc (0.0 -> 1.0)
                  const normPt = (pt) => {
                    const vx = sx + (pt.x / W) * sw;
                    const vy = sy + (pt.y / H) * sh;
                    return [
                      Math.max(0, Math.min(1, vx / vw)),
                      Math.max(0, Math.min(1, vy / vh))
                    ];
                  };
                  lastValidCornersNorm = [normPt(TL), normPt(TR), normPt(BR), normPt(BL)];
                }
              }
            }
          }
        }
      }

      // Kiểm tra độ ổn định góc giữa 2 frame liên tiếp (độ dịch chuyển < 16px)
      let isStable = false;
      if (lastCornersPos && TL && TR && BR && BL) {
        const dTL = Math.hypot(TL.x - lastCornersPos.TL.x, TL.y - lastCornersPos.TL.y);
        const dTR = Math.hypot(TR.x - lastCornersPos.TR.x, TR.y - lastCornersPos.TR.y);
        const dBR = Math.hypot(BR.x - lastCornersPos.BR.x, BR.y - lastCornersPos.BR.y);
        const dBL = Math.hypot(BL.x - lastCornersPos.BL.x, BL.y - lastCornersPos.BL.y);
        if (Math.max(dTL, dTR, dBR, dBL) < 16.0) {
          isStable = true;
        }
      }
      if (TL && TR && BR && BL) {
        lastCornersPos = {
          TL: { x: TL.x, y: TL.y },
          TR: { x: TR.x, y: TR.y },
          BR: { x: BR.x, y: BR.y },
          BL: { x: BL.x, y: BL.y }
        };
      } else {
        lastCornersPos = null;
      }

      // 6. Vẽ AR Overlay Canvas trực tiếp đè khít bên trong viewfinder
      if (overlayCtx) {
        if (TL && TR && BR && BL) {
          overlayCtx.save();
          overlayCtx.beginPath();
          overlayCtx.moveTo(TL.x, TL.y);
          overlayCtx.lineTo(TR.x, TR.y);
          overlayCtx.lineTo(BR.x, BR.y);
          overlayCtx.lineTo(BL.x, BL.y);
          overlayCtx.closePath();

          if (isValidSheet) {
            overlayCtx.strokeStyle = "#10b981";
            overlayCtx.lineWidth = 3.5;
            overlayCtx.fillStyle = "rgba(16, 185, 129, 0.12)";
            overlayCtx.shadowColor = "#10b981";
            overlayCtx.shadowBlur = 12;
          } else {
            overlayCtx.strokeStyle = "#ef4444";
            overlayCtx.lineWidth = 2.5;
            overlayCtx.setLineDash([8, 6]);
            overlayCtx.fillStyle = "rgba(239, 68, 68, 0.05)";
          }
          overlayCtx.fill();
          overlayCtx.stroke();
          overlayCtx.restore();

          // Vẽ 4 góc tròn
          [TL, TR, BR, BL].forEach(pt => {
            overlayCtx.beginPath();
            overlayCtx.arc(pt.x, pt.y, 9.5, 0, Math.PI * 2);
            overlayCtx.fillStyle = isValidSheet ? "#10b981" : "#ef4444";
            overlayCtx.fill();
            overlayCtx.lineWidth = 2;
            overlayCtx.strokeStyle = "#ffffff";
            overlayCtx.stroke();
          });

          // Vẽ các mốc trung gian đã khớp
          matchedIntermediates.forEach(m => {
            overlayCtx.beginPath();
            overlayCtx.arc(m.x, m.y, m.isM2 ? 7 : 5.5, 0, Math.PI * 2);
            overlayCtx.fillStyle = isValidSheet ? "#10b981" : "#fbbf24";
            overlayCtx.fill();
            overlayCtx.lineWidth = 1.5;
            overlayCtx.strokeStyle = "#ffffff";
            overlayCtx.stroke();
          });
        }
      }

      // Cập nhật trạng thái giao diện UI & Tự động chụp
      updateGuidanceState(isValidSheet, cornersCount, matchedIntermediates.length, TL, TR, BR, BL, isStable);
    }

    function updateGuidanceState(isValidSheet, cornersCount, intermediatesCount, TL, TR, BR, BL, isStable) {
      if (isGrading) return;

      const guideBox = document.getElementById("guidanceBox");
      const guideBoxText = document.getElementById("guideBoxText");
      const guideIcon = document.getElementById("guideIcon");
      const guideSubText = document.getElementById("guideText");
      const viewfinder = document.getElementById("viewfinder");
      const scanStatusTitle = document.getElementById("scanStatusTitle");
      const scanStatusText = document.getElementById("scanStatusText");
      const scanPingDot = document.getElementById("scanPingDot");
      const labelM0 = document.getElementById("labelM0");
      const labelM4 = document.getElementById("labelM4");

      const reticleMap = {
        "reticle-tl": !!TL,
        "reticle-tr": !!TR,
        "reticle-bl": !!BL,
        "reticle-br": !!BR
      };

      if (isValidSheet) {
        if (isStable) {
          lock4Frames++;
        } else {
          lock4Frames = 1;
        }

        if (viewfinder) viewfinder.className = "relative w-[92%] max-w-[380px] aspect-[1/1.444] border-2 border-emerald-400 rounded-2xl viewfinder-mask shadow-[0_0_28px_rgba(16,185,129,0.9)] transition-all flex flex-col justify-between p-1 overflow-hidden";
        if (guideBox) guideBox.className = "text-center text-[11px] font-bold text-emerald-200 bg-emerald-950/95 px-4 py-1.5 rounded-full mx-auto shadow-xl border border-emerald-500 animate-pulse flex items-center gap-1.5 pointer-events-auto";
        if (guideIcon) guideIcon.innerText = "✓";
        if (guideBoxText) guideBoxText.innerText = "ĐÃ KHÓA ĐỦ HỆ THỐNG MỐC! ĐANG CHỤP...";
        if (guideSubText) guideSubText.innerText = "Giữ chắc tay, hệ thống đang chụp chớp nhoáng và chấm bài...";

        if (scanStatusTitle) scanStatusTitle.className = "text-xs font-bold text-emerald-400 flex items-center justify-center gap-1.5";
        if (scanPingDot) scanPingDot.className = "w-2 h-2 rounded-full bg-emerald-400 animate-ping";
        if (scanStatusText) scanStatusText.innerText = "Đã khớp chuẩn phiếu OMR Bộ GD&ĐT 2025!";
        if (labelM0) labelM0.className = "w-full text-center text-[9px] text-emerald-300/80 font-mono tracking-widest mt-1";
        if (labelM4) labelM4.className = "w-full text-center text-[9px] text-emerald-300/80 font-mono tracking-widest mb-1";

        Object.keys(reticleMap).forEach(id => {
          const el = document.getElementById(id);
          if (el) { el.classList.remove("unmatched"); el.classList.add("matched"); }
        });

        // Tự động kích hoạt chụp chớp nhoáng ngay sau 2 chu kỳ ổn định (~150ms), có cooldown 0.8s giữa các bài
        if (lock4Frames >= 2 && Date.now() >= lastScanCooldownUntil) {
          playBeep(true);
          if (navigator.vibrate) navigator.vibrate([40, 60, 40]);
          executeGradingProcess();
        }
        return;
      }

      // NẾU CHƯA ĐỦ ĐIỀU KIỆN: GIỮ MÀU ĐỎ TUYỆT ĐỐI!
      lock4Frames = 0;
      if (viewfinder) viewfinder.className = "relative w-[92%] max-w-[380px] aspect-[1/1.444] border-2 border-dashed border-rose-500/80 rounded-2xl viewfinder-mask transition-all flex flex-col justify-between p-1 overflow-hidden";
      if (guideBox) guideBox.className = "text-center text-[11px] font-bold text-rose-200 bg-rose-950/90 px-3.5 py-1.5 rounded-full mx-auto shadow-xl border border-rose-500/60 transition-all flex items-center gap-1.5 pointer-events-auto";
      if (guideIcon) guideIcon.innerText = "🎯";

      if (cornersCount < 4) {
        if (guideBoxText) guideBoxText.innerText = `Đang tìm mốc góc (${cornersCount}/4 góc)...`;
      } else {
        if (guideBoxText) guideBoxText.innerText = `Đã thấy 4 góc, đang khớp mốc cạnh (${intermediatesCount}/6)...`;
      }
      if (guideSubText) guideSubText.innerText = "Căn 4 mốc đen góc vào 4 khung ngắm. Đúng phiếu OMR máy sẽ tự chụp.";

      if (scanStatusTitle) scanStatusTitle.className = "text-xs font-bold text-rose-400 flex items-center justify-center gap-1.5";
      if (scanPingDot) scanPingDot.className = "w-2 h-2 rounded-full bg-rose-500 animate-ping";
      if (scanStatusText) scanStatusText.innerText = "Đang tìm phiếu trả lời OMR...";
      if (labelM0) labelM0.className = "w-full text-center text-[9px] text-rose-400/80 font-mono tracking-widest mt-1";
      if (labelM4) labelM4.className = "w-full text-center text-[9px] text-rose-400/80 font-mono tracking-widest mb-1";

      // Khi chưa đủ mốc hoặc chưa hợp lệ: 4 góc reticle giữ màu đỏ tuyệt đối (unmatched)
      Object.keys(reticleMap).forEach(id => {
        const el = document.getElementById(id);
        if (el) {
          el.classList.remove("matched");
          el.classList.add("unmatched");
        }
      });
    }

    function triggerManualCapture() {
      if (!isGrading) executeGradingProcess();
    }

    // =========================================================================
    // CHỤP CHỚP NHOÁNG CHỌN KHUNG NÉT NHẤT (BEST-FRAME BURST CAPTURE CHỐNG RUNG TAY)
    // =========================================================================
    async function executeGradingProcess() {
      if (isGrading) return;
      isGrading = true;
      if (navigator.vibrate) navigator.vibrate(60);

      const guideBox = document.getElementById("guidanceBox");
      const guideBoxText = document.getElementById("guideBoxText");
      const guideIcon = document.getElementById("guideIcon");
      const guideSubText = document.getElementById("guideText");
      
      guideIcon.innerText = "⏳";
      guideBoxText.innerText = "Đang nắn phẳng & chấm điểm...";
      guideSubText.innerText = "Hệ thống đang đối chiếu đáp án với mã đề bài thi...";
      guideBox.className = "text-center text-[11px] font-bold text-amber-200 bg-amber-950/95 px-4 py-1.5 rounded-full mx-auto shadow-xl border border-amber-500 animate-pulse flex items-center gap-1.5 pointer-events-auto";

      const video = document.getElementById("videoElement");
      const vw = video.videoWidth || 1920;
      const vh = video.videoHeight || 1080;

      // 1. Chụp nhanh 2 frame liên tiếp (cách nhau 35ms) và chọn frame sắc nét nhất (chống rung tay tức thời)
      let bestCanvas = null;
      let maxSharpness = -1;

      for (let burstIdx = 0; burstIdx < 2; burstIdx++) {
        const tempCanvas = document.createElement("canvas");
        tempCanvas.width = vw;
        tempCanvas.height = vh;
        const tempCtx = tempCanvas.getContext("2d", { willReadFrequently: true });
        tempCtx.drawImage(video, 0, 0, vw, vh);

        // Tính nhanh chỉ số độ nét vi sai trên vùng trung tâm (bước nhảy step = 4 pixel -> < 3ms)
        let sharpness = 0;
        try {
          const sampleW = 140, sampleH = 140;
          const sampleX = Math.round(vw * 0.5 - sampleW / 2);
          const sampleY = Math.round(vh * 0.5 - sampleH / 2);
          const sampleData = tempCtx.getImageData(sampleX, sampleY, sampleW, sampleH).data;
          const byteStep = 4 * 4; // step = 4 pixels * 4 RGBA bytes
          for (let i = 0; i < sampleData.length - 8; i += byteStep) {
            sharpness += Math.abs(sampleData[i] - sampleData[i + 4]);
          }
        } catch (e) {
          sharpness = burstIdx;
        }

        if (sharpness > maxSharpness || bestCanvas === null) {
          maxSharpness = sharpness;
          bestCanvas = tempCanvas;
        }

        if (burstIdx < 1) {
          await new Promise(r => setTimeout(r, 35));
        }
      }

      // 2. Crop sát vùng 4 góc phiếu mở rộng 4.5% lề an toàn, thu phóng cạnh dài nhất về max 1150px
      const finalCanvas = document.getElementById("captureCanvas");
      let cornersToSend = null;

      if (lastValidCornersNorm && lastValidCornersNorm.length === 4) {
        const xs = lastValidCornersNorm.map(p => p[0] * vw);
        const ys = lastValidCornersNorm.map(p => p[1] * vh);
        const minX = Math.min(...xs), maxX = Math.max(...xs);
        const minY = Math.min(...ys), maxY = Math.max(...ys);
        const bw = maxX - minX, bh = maxY - minY;
        const padX = bw * 0.045;
        const padY = bh * 0.045;

        const cropX = Math.max(0, Math.floor(minX - padX));
        const cropY = Math.max(0, Math.floor(minY - padY));
        const cropW = Math.min(vw - cropX, Math.ceil(bw + 2 * padX));
        const cropH = Math.min(vh - cropY, Math.ceil(bh + 2 * padY));

        const maxDim = Math.max(cropW, cropH);
        const scale = maxDim > 1150 ? (1150.0 / maxDim) : 1.0;
        const targetW = Math.round(cropW * scale);
        const targetH = Math.round(cropH * scale);

        finalCanvas.width = targetW;
        finalCanvas.height = targetH;
        const fCtx = finalCanvas.getContext("2d");
        fCtx.drawImage(bestCanvas, cropX, cropY, cropW, cropH, 0, 0, targetW, targetH);

        // Quy đổi lại tọa độ cornersToSend tương ứng với ảnh đã crop (0.0 -> 1.0)
        cornersToSend = lastValidCornersNorm.map(p => [
          Math.max(0, Math.min(1, (p[0] * vw - cropX) / cropW)),
          Math.max(0, Math.min(1, (p[1] * vh - cropY) / cropH))
        ]);
      } else {
        const maxDim = Math.max(vw, vh);
        const scale = maxDim > 1150 ? (1150.0 / maxDim) : 1.0;
        finalCanvas.width = Math.round(vw * scale);
        finalCanvas.height = Math.round(vh * scale);
        const fCtx = finalCanvas.getContext("2d");
        fCtx.drawImage(bestCanvas, 0, 0, finalCanvas.width, finalCanvas.height);
        cornersToSend = null;
      }

      finalCanvas.toBlob(async (blob) => {
        if (!blob) {
          isGrading = false;
          resetGuidanceHUD();
          return;
        }
        await postGradeImageBlob(blob, `Mobile_${Date.now()}.jpg`, cornersToSend);
      }, "image/jpeg", 0.78);
    }

    // =========================================================================
    // CHỤP BẰNG CAMERA MÁY NATIVE (FAIL-SAFE 100% HOẠT ĐỘNG MỌI ỨNG DỤNG)
    // =========================================================================
    async function handleNativeCameraCapture(event) {
      const file = event.target.files[0];
      if (!file) return;

      isGrading = true;
      if (navigator.vibrate) navigator.vibrate(60);

      const guideBoxText = document.getElementById("guideBoxText");
      const guideIcon = document.getElementById("guideIcon");
      guideIcon.innerText = "⏳";
      guideBoxText.innerText = "Đang nắn phẳng & chấm điểm...";

      await postGradeImageBlob(file, file.name || `Native_${Date.now()}.jpg`);
      event.target.value = ""; // Reset file input
    }

    async function postGradeImageBlob(blobOrFile, filename, customCorners = null) {
      const fd = new FormData();
      fd.append("file", blobOrFile, filename);
      const corners = customCorners || lastValidCornersNorm;
      if (corners) {
        fd.append("corners", JSON.stringify(corners));
      }
      lastValidCornersNorm = null;

      try {
        const res = await fetch("/api/grade-single-file", { method: "POST", body: fd });
        
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          const errDetail = errData.detail || `Lỗi máy chủ (${res.status})`;
          playBeep(false);
          if (navigator.vibrate) navigator.vibrate([100, 60, 100]);
          showNotificationToast(errDetail, true);
          return;
        }

        const data = await res.json();
        if (data.new_submissions && data.new_submissions.length > 0) {
          const sub = data.new_submissions[0];
          latestSubId = sub.submission_id;
          if (sub.has_error) {
            playBeep(false);
            if (navigator.vibrate) navigator.vibrate([100, 60, 100]);
            showNotificationToast(sub.error_msg || "Ảnh chụp không đạt chuẩn. Vui lòng chụp thẳng và đủ sáng.", true);
            refreshSessionData().then(() => renderSubmissionsList());
          } else {
            // 1. Phản hồi âm thanh, rung & hiển thị điểm tức thì
            playBeep(true);
            if (navigator.vibrate) navigator.vibrate([60, 40, 120]);
            showResultToast(sub);

            // 2. Cập nhật nhanh số đếm (+1 bài) ngay lập tức không đợi tải lại session
            const badgeEl = document.getElementById("badgeSubCount");
            if (badgeEl) {
              const nextCount = data.total_submissions_count || ((sessionData.submissions ? sessionData.submissions.length : 0) + 1);
              badgeEl.innerText = `${nextCount} bài`;
            }

            // 3. Đồng bộ lại danh sách ngầm (non-blocking) để mở khóa quét ngay sau 0.8s cooldown
            refreshSessionData().then(() => renderSubmissionsList());
          }
        }
      } catch (err) {
        playBeep(false);
        showNotificationToast("Lỗi kết nối máy chủ: " + err.message, true);
      } finally {
        lastScanCooldownUntil = Date.now() + 800;
        isGrading = false;
        lock4Frames = 0;
        resetGuidanceHUD();
      }
    }

    function resetGuidanceHUD() {
      const guideBox = document.getElementById("guidanceBox");
      const guideBoxText = document.getElementById("guideBoxText");
      const guideIcon = document.getElementById("guideIcon");
      const guideSubText = document.getElementById("guideText");
      if (guideBox && guideBoxText && guideIcon && guideSubText) {
        guideIcon.innerText = "🎯";
        guideBoxText.innerText = "Không phải phiếu OMR - Đưa phiếu vào khung";
        guideSubText.innerText = "Căn 4 mốc đen góc vào 4 khung ngắm. Đúng phiếu OMR máy sẽ tự chụp.";
        guideBox.className = "text-center text-[11px] font-bold text-rose-200 bg-rose-950/90 px-3.5 py-1.5 rounded-full mx-auto shadow-xl border border-rose-500/60 transition-all flex items-center gap-1.5 pointer-events-auto";
      }
    }

    function showResultToast(sub) {
      latestSubId = sub.submission_id;
      document.getElementById("toastTotalScore").innerText = sub.scores ? sub.scores.total : "0.0";
      document.getElementById("toastSbd").innerText = sub.sbd || "---";
      document.getElementById("toastExamCode").innerText = sub.exam_code || "---";
      
      const s = sub.scores || {};
      document.getElementById("toastBreakdown").innerText = `P1: ${s.p1 || 0} | P2: ${s.p2 || 0} | P3: ${s.p3 || 0}`;

      const drawer = document.getElementById("recentResultDrawer");
      drawer.classList.remove("hidden");
    }

    function closeResultToast() {
      document.getElementById("recentResultDrawer").classList.add("hidden");
    }

    function viewLatestGradedImage() {
      if (latestSubId) {
        openImageViewer(latestSubId, `SBD: ${document.getElementById("toastSbd").innerText}`);
      }
    }

    // =========================================================================
    // HIỂN THỊ DANH SÁCH BÀI LÀM (TAB 2)
    // =========================================================================
    function renderSubmissionsList() {
      const container = document.getElementById("resultsListContainer");
      const subs = sessionData.submissions || [];
      const query = (document.getElementById("searchSbdInput").value || "").trim().toLowerCase();

      const filtered = subs.filter(s => {
        const sbd = (s.sbd || "").toLowerCase();
        const code = (s.exam_code || "").toLowerCase();
        return !query || sbd.includes(query) || code.includes(query);
      });

      if (filtered.length === 0) {
        container.innerHTML = `
          <div class="text-center text-slate-500 py-16 text-xs">
            ${query ? "Không tìm thấy bài thi khớp số báo danh này." : "Chưa có bài thi nào được chấm trong đợt này."}
          </div>
        `;
        return;
      }

      container.innerHTML = filtered.map(sub => {
        const isErr = sub.has_error;
        const total = sub.scores ? sub.scores.total : 0.0;
        return `
          <div onclick="openImageViewer('${sub.submission_id}', 'SBD: ${sub.sbd || 'Chưa rõ'} - Đề: ${sub.exam_code || '---'}')" class="bg-slate-900 border border-slate-800 rounded-xl p-3 flex justify-between items-center active:scale-[0.99] transition cursor-pointer">
            <div class="flex items-center gap-3">
              <div class="w-10 h-10 ${isErr ? 'bg-rose-950 border-rose-800 text-rose-300' : 'bg-indigo-950 border-indigo-800 text-emerald-400'} border rounded-xl flex items-center justify-center font-black text-sm">
                ${isErr ? '!' : total}
              </div>
              <div>
                <div class="flex items-center gap-2">
                  <span class="text-xs font-bold text-white">SBD: ${sub.sbd || 'Chưa rõ'}</span>
                  <span class="text-[9px] bg-slate-800 text-slate-400 px-1.5 py-0.2 rounded font-mono">Đề: ${sub.exam_code || '---'}</span>
                </div>
                <p class="text-[10px] text-slate-400 mt-0.5 truncate max-w-[180px]">
                  ${isErr ? (sub.error_msg || 'Lỗi nhận diện') : `P1: ${sub.scores.p1} | P2: ${sub.scores.p2} | P3: ${sub.scores.p3}`}
                </p>
              </div>
            </div>
            <div class="flex items-center gap-2" onclick="event.stopPropagation()">
              <button onclick="openImageViewer('${sub.submission_id}', 'SBD: ${sub.sbd || 'Chưa rõ'}')" class="p-1.5 text-indigo-400 hover:text-indigo-300 text-xs" title="Xem chi tiết">
                🔍
              </button>
              <button onclick="deleteSubmissionMobile('${sub.submission_id}')" class="p-1.5 text-slate-500 hover:text-rose-400 text-xs" title="Xóa bài">
                🗑️
              </button>
            </div>
          </div>
        `;
      }).join("");
    }

    async function refreshSubmissions() {
      await refreshSessionData();
      renderSubmissionsList();
    }

    async function deleteSubmissionMobile(subId) {
      if (!confirm("Bạn có chắc chắn muốn xóa bài thi này?")) return;
      try {
        const res = await fetch(`/api/delete-submission/${subId}`, { method: "DELETE" });
        if (res.ok) {
          await refreshSessionData();
          renderSubmissionsList();
        }
      } catch (e) {
        showNotificationToast("Lỗi khi xóa bài: " + e.message, true);
      }
    }

    // =========================================================================
    // XEM ẢNH BÀI CHẤM TOÀN MÀN HÌNH (TỰ ĐỘNG FALLBACK CẢ 2 ROUTE)
    // =========================================================================
    function openImageViewer(subId, title) {
      document.getElementById("viewerTitle").innerText = title;
      document.getElementById("viewerSubtitle").innerText = `Mã bài: ${subId}`;
      const img = document.getElementById("viewerImage");
      const loading = document.getElementById("viewerLoading");
      
      if (loading) {
        loading.classList.remove("hidden");
        loading.innerHTML = `
          <svg class="animate-spin w-4 h-4 text-emerald-400 inline" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path></svg>
          <span>Đang tải ảnh bài chấm...</span>
        `;
      }
      img.classList.add("hidden");

      img.onload = () => {
        if (loading) loading.classList.add("hidden");
        img.classList.remove("hidden");
      };

      img.onerror = () => {
        if (!img.src.includes("/api/image/")) {
          img.src = `/api/image/${subId}?t=${Date.now()}`;
        } else {
          if (loading) loading.innerHTML = "⚠️ Không tìm thấy ảnh bài thi đã chấm.";
        }
      };

      img.src = `/api/graded-image/${subId}?t=${Date.now()}`;
      document.getElementById("imageViewerModal").classList.remove("hidden");
    }

    function closeImageViewer() {
      document.getElementById("imageViewerModal").classList.add("hidden");
    }

    // =========================================================================
    // QUẢN LÝ ĐỢT THI & NẠP ĐÁP ÁN (TAB 3)
    // =========================================================================
    function renderExamsList() {
      const container = document.getElementById("mobileExamsList");
      const allExams = sessionData.all_exams || [];
      const activeId = sessionData.active_exam_id;

      container.innerHTML = allExams.map(ex => {
        const isActive = (ex.id === activeId);
        return `
          <div onclick="selectExamMobile('${ex.id}')" class="p-2.5 rounded-xl border ${isActive ? 'bg-indigo-950/70 border-indigo-500 text-white' : 'bg-slate-900 border-slate-800 text-slate-300'} flex justify-between items-center text-xs">
            <div>
              <span class="font-bold">${ex.title}</span>
              <p class="text-[9px] text-slate-400">Đã chấm: ${ex.submission_count} bài</p>
            </div>
            ${isActive ? '<span class="text-[9px] bg-emerald-600 text-white px-2 py-0.5 rounded-full font-bold">Đang chọn</span>' : ''}
          </div>
        `;
      }).join("");
    }

    async function selectExamMobile(examId) {
      try {
        const res = await fetch(`/api/switch-exam/${examId}`, { method: "POST" });
        if (res.ok) {
          await refreshSessionData();
          renderExamsList();
          showNotificationToast("Đã chuyển sang đợt thi đã chọn.", false);
        }
      } catch (e) {
        showNotificationToast("Lỗi chuyển đợt thi: " + e.message, true);
      }
    }

    function toggleCreateExamForm() {
      const form = document.getElementById("formCreateExamMobile");
      form.classList.toggle("hidden");
    }

    async function submitCreateExamMobile() {
      const subject = document.getElementById("mobInpSubject").value.trim();
      const period = document.getElementById("mobInpPeriod").value.trim();
      const className = document.getElementById("mobInpClass").value.trim();

      if (!subject || !period || !className) {
        showNotificationToast("Vui lòng điền đủ Môn học, Kỳ thi và Lớp.", true);
        return;
      }

      try {
        const res = await fetch("/api/create-exam", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            subject: subject,
            period: period,
            class_name: className,
            school_year: "2026-2027"
          })
        });
        if (res.ok) {
          toggleCreateExamForm();
          await refreshSessionData();
          renderExamsList();
          showNotificationToast("Khởi tạo đợt thi mới thành công!", false);
        }
      } catch (e) {
        showNotificationToast("Lỗi khởi tạo đợt thi: " + e.message, true);
      }
    }

    async function uploadAnswerKeyMobile(e) {
      const file = e.target.files[0];
      if (!file) return;

      const fd = new FormData();
      fd.append("file", file);

      try {
        const res = await fetch("/api/upload-answer-key", { method: "POST", body: fd });
        const data = await res.json();
        if (data.status === "SUCCESS") {
          const count = (data.codes_loaded || data.exam_codes || []).length;
          showNotificationToast(`✓ Đã nạp thành công ${count} mã đề!`, false);
          await refreshSessionData();
        } else {
          showNotificationToast("Lỗi nạp đáp án: " + (data.detail || "Không rõ"), true);
        }
      } catch (err) {
        showNotificationToast("Lỗi kết nối khi nạp đáp án: " + err.message, true);
      }
    }

    // =========================================================================
    // XUẤT FILE EXCEL & PDF TẢI VỀ HOẶC CHIA SẺ TRỰC TIẾP TỪ ĐIỆN THOẠI
    // Tương thích 100% Mobile Safari, Chrome Android, Zalo Webview, PWA
    // =========================================================================
    async function exportExcelMobile(evt) {
      let subs = sessionData.submissions || [];
      if (subs.length === 0) {
        await fetchSessionWithRetry();
        subs = sessionData.submissions || [];
        if (subs.length === 0) {
          showNotificationToast("Chưa có bài thi nào được chấm trong đợt này.", true);
          return;
        }
      }

      const btn = evt ? evt.currentTarget : document.getElementById("btnMobExportExcel");
      const origHtml = btn ? btn.innerHTML : "";
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span>⏳ Đang tạo bảng điểm Excel...</span>`;
      }

      try {
        const res = await fetch("/api/export-excel");
        if (!res.ok) {
          // Fallback điều hướng trực tiếp
          window.location.href = "/api/export-excel";
          return;
        }

        const blob = await res.blob();
        const info = sessionData.exam_info || {};
        const subName = (info.subject || "MON").replace(/[^a-zA-Z0-9]/g, "_");
        const filename = `BANG_DIEM_${subName}_${Date.now()}.xlsx`;
        const file = new File([blob], filename, { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });

        // 1. Thử Web Share API trước (cho phép gửi trực tiếp qua Zalo, Mail, Drive, Files)
        if (navigator.canShare && navigator.canShare({ files: [file] })) {
          try {
            await navigator.share({
              files: [file],
              title: "Bảng Điểm OMR",
              text: `Bảng điểm ${info.subject || 'OMR'} (${subs.length} bài)`
            });
            showNotificationToast("✓ Đã chia sẻ bảng điểm thành công!", false);
            return;
          } catch (shareErr) {
            if (shareErr.name === "AbortError") return; // Người dùng bấm hủy
          }
        }

        // 2. Tải qua Blob URL (an toàn trên Mobile, giữ URL 60s không revoke ngay)
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => window.URL.revokeObjectURL(url), 60000);
        showNotificationToast("✓ Đang tải bảng điểm Excel về máy...", false);
      } catch (err) {
        console.warn("exportExcelMobile fallback to direct navigation:", err);
        window.location.href = "/api/export-excel";
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = origHtml;
        }
      }
    }

    async function exportPdfMobile(evt) {
      let subs = sessionData.submissions || [];
      if (subs.length === 0) {
        await fetchSessionWithRetry();
        subs = sessionData.submissions || [];
        if (subs.length === 0) {
          showNotificationToast("Chưa có bài thi nào được chấm trong đợt này.", true);
          return;
        }
      }

      const btn = evt ? evt.currentTarget : document.getElementById("btnMobExportPdf");
      const origHtml = btn ? btn.innerHTML : "";
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<span>⏳ Đang ghép PDF ${subs.length} bài...</span>`;
      }

      try {
        const res = await fetch("/api/export-pdf");
        if (!res.ok) {
          // Fallback điều hướng trực tiếp
          window.location.href = "/api/export-pdf";
          return;
        }

        const blob = await res.blob();
        const info = sessionData.exam_info || {};
        const subName = (info.subject || "MON").replace(/[^a-zA-Z0-9]/g, "_");
        const filename = `TAP_BAI_CHAM_${subName}_${Date.now()}.pdf`;
        const file = new File([blob], filename, { type: "application/pdf" });

        // 1. Thử Web Share API trước
        if (navigator.canShare && navigator.canShare({ files: [file] })) {
          try {
            await navigator.share({
              files: [file],
              title: "Tập Bài Chấm OMR",
              text: `Tập bài thi đã chấm ${info.subject || 'OMR'} (${subs.length} bài)`
            });
            showNotificationToast("✓ Đã chia sẻ tập bài chấm thành công!", false);
            return;
          } catch (shareErr) {
            if (shareErr.name === "AbortError") return;
          }
        }

        // 2. Tải qua Blob URL
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => window.URL.revokeObjectURL(url), 60000);
        showNotificationToast("✓ Đang tải tập PDF về máy...", false);
      } catch (err) {
        console.warn("exportPdfMobile fallback to direct navigation:", err);
        window.location.href = "/api/export-pdf";
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = origHtml;
        }
      }
    }
  </script>
</body>
</html>

```

## FILE: templates\sw.js
```js
// Service Worker cho OMR Mobile PWA (v12 - Fast End-to-End & Network-First)
const CACHE_NAME = 'omr-pwa-v12';
const ASSETS_TO_CACHE = [
  '/scanner',
  '/manifest.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    }).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

// Xử lý fetch request
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Không can thiệp các request không phải GET hoặc các endpoint API
  if (event.request.method !== 'GET' || url.pathname.startsWith('/api/')) {
    return;
  }

  // Đối với request điều hướng (Navigation / Scanner / Trang chủ): Luôn ưu tiên lấy bản mới nhất từ mạng (Network-First)
  const isNavigation = event.request.mode === 'navigate' || url.pathname === '/scanner' || url.pathname === '/';
  if (isNavigation) {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response && response.status === 200) {
            const resClone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, resClone));
          }
          return response;
        })
        .catch(async () => {
          const cached = await caches.match(event.request);
          if (cached) return cached;
          return caches.match('/scanner');
        })
    );
    return;
  }

  // Đối với các tài nguyên tĩnh khác: Network-First với fallback cache
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response && response.status === 200) {
          const resClone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, resClone));
        }
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});

```

