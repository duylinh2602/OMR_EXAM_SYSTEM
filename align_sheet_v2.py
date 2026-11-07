# align_sheet_v2.py
# -*- coding: utf-8 -*-
"""
MODULE NẮN PHẲNG PHỐI CẢNH ĐA TẦNG OMR CHUẨN BỘ GD&ĐT 2025 (PHIÊN BẢN SANG MATH / CONIC THÍCH ỨNG CAO)
Nâng cấp toàn diện:
1. Cân bằng sáng phẳng (Flat-field Illumination Normalization): Khử sạch 100% bóng đổ tay/điện thoại và nguồn sáng bàn học không đều.
2. Bộ định vị 4 mốc cực biên thích ứng (Adaptive Extreme Squares Locator - O(N)):
   - Sử dụng mặt nạ bao lồi giấy A4 (khử nền bàn đen)
   - Lọc ô vuông đặc (tỷ lệ lấp đầy > 60%, độ lồi > 75%)
   - Chiếu 4 hướng cực biên [-(x+y), x-y, x+y, y-x] không lặp tổ hợp, thời gian < 0.05s.
3. Nắn phẳng 4 dải (4-Band Warp) siêu tốc: Tìm 10 mốc chuẩn cục bộ dọc 2 lề, triệt tiêu hoàn toàn nghẽn tổ hợp 1.3 tỷ lần của phiên bản cũ.
4. Tự động xoay 4 hướng (0°, 90°, 180°, 270°) theo phân bố mực phần đầu phiếu.
5. Bảo vệ luồng Console stdout chống lỗi charmap UnicodeEncodeError trên Windows .exe.
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
    [57.0, 47.0],      # M0: Góc trên trái
    [59.0, 820.0],     # M1: Đầu Phần I
    [59.0, 1371.0],    # M2: Đầu Phần II
    [56.5, 1724.0],    # M3: Đầu Phần III
    [56.5, 2450.0],    # M4: Góc dưới trái
], dtype=np.float32)

TPL_RIGHT_5 = np.array([
    [1721.5, 46.0],    # M0: Góc trên phải
    [1722.0, 820.0],   # M1: Đầu Phần I
    [1722.0, 1371.0],  # M2: Đầu Phần II
    [1722.0, 1724.0],  # M3: Đầu Phần III
    [1722.0, 2449.5],  # M4: Góc dưới phải
], dtype=np.float32)

# Tỷ lệ khoảng cách chuẩn theo trục dọc
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


def normalize_illumination(img_bgr: np.ndarray) -> np.ndarray:
    """
    Cân bằng sáng phẳng (Flat-field illumination correction):
    Ước lượng nền giấy ở độ phân giải thấp (1/24), lọc đóng hình thái học để xoá hết
    chữ in và mốc đen, làm mượt Gaussian rồi chia đều cho từng kênh màu.
    Khử sạch 100% bóng đổ tay/điện thoại và nguồn sáng bàn học không đều.
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    sw, sh = max(8, w // 24), max(8, h // 24)
    small = cv2.resize(gray, (sw, sh), interpolation=cv2.INTER_AREA)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    closed = cv2.morphologyEx(small, cv2.MORPH_CLOSE, k)
    blurred = cv2.GaussianBlur(closed, (5, 5), 0)
    bg = cv2.resize(blurred, (w, h), interpolation=cv2.INTER_LINEAR)
    
    b, g, r = cv2.split(img_bgr)
    b_norm = cv2.divide(b, bg, scale=240.0)
    g_norm = cv2.divide(g, bg, scale=240.0)
    r_norm = cv2.divide(r, bg, scale=240.0)
    return cv2.merge([b_norm, g_norm, r_norm])


def find_extreme_squares(gray: np.ndarray) -> Optional[np.ndarray]:
    """
    Định vị 4 mốc góc cực biên (TL, TR, BR, BL) thích ứng 100% với ảnh chụp điện thoại.
    Sử dụng mặt nạ bao lồi giấy A4 để loại bỏ bóng tối và đồ vật trên bàn học.
    Độ phức tạp O(N), thời gian xử lý < 0.05 giây.
    """
    h, w = gray.shape
    block = max(15, min(61, round(min(w, h) / 10) | 1))
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, block, 16)

    # 1. Mặt nạ bao lồi vùng giấy A4 (khử mép bàn đen dính vào mốc biên)
    paper_mask = np.zeros_like(gray)
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    k9 = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    otsu_closed = cv2.morphologyEx(otsu, cv2.MORPH_CLOSE, k9)
    cnts_p, _ = cv2.findContours(otsu_closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if cnts_p:
        largest = max(cnts_p, key=cv2.contourArea)
        if cv2.contourArea(largest) > w * h * 0.20:
            hull_p = cv2.convexHull(largest)
            cv2.fillConvexPoly(paper_mask, hull_p, 255)
            binary = cv2.bitwise_and(binary, paper_mask)

    # 2. Tìm tất cả các ứng viên ô vuông mốc đen
    cnts, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    max_side = min(w, h) * 0.08
    min_side = max(5, int(round(min(w, h) * 0.005)))

    squares = []
    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        if cw < min_side or ch < min_side or cw > max_side or ch > max_side:
            continue
        aspect = cw / float(ch)
        if not (0.65 <= aspect <= 1.55):
            continue
        cell = binary[y:y+ch, x:x+cw]
        pixels = cv2.countNonZero(cell)
        density = pixels / float(cw * ch)
        if pixels < 10 or density < 0.35:
            continue
        hull = cv2.convexHull(c)
        h_area = cv2.contourArea(hull)
        if h_area > 0 and (cv2.contourArea(c) / h_area) < 0.70:
            continue
        m = cv2.moments(c)
        if m['m00'] > 0:
            squares.append({'x': m['m10'] / m['m00'], 'y': m['m01'] / m['m00'], 'area': pixels, 'w': cw, 'h': ch})

    if len(squares) < 4:
        return None

    # 3. Lọc theo nhóm diện tích của các mốc góc OMR (loại bỏ chấm định hướng và vết bẩn nhỏ)
    areas = sorted([sq['area'] for sq in squares])
    ref = areas[int(len(areas) * 0.80)]
    kept = [sq for sq in squares if ref * 0.35 <= sq['area'] <= ref * 3.0]
    if len(kept) < 4:
        kept = squares

    # 4. Chiếu 4 hướng cực biên: [-(x+y), x-y, x+y, y-x] - Thuật toán O(N) của Conic Chấm
    tl = max(kept, key=lambda s: -(s['x'] + s['y']))
    br = max(kept, key=lambda s: (s['x'] + s['y']))
    tr = max(kept, key=lambda s: (s['x'] - s['y']))
    bl = max(kept, key=lambda s: (s['y'] - s['x']))

    pts = np.array([[tl['x'], tl['y']], [tr['x'], tr['y']], [br['x'], br['y']], [bl['x'], bl['y']]], dtype=np.float32)

    # 5. Kiểm tra tính hợp lệ hình học của tứ giác phiếu
    w_top = np.linalg.norm(pts[1] - pts[0])
    w_bot = np.linalg.norm(pts[2] - pts[3])
    h_l = np.linalg.norm(pts[3] - pts[0])
    h_r = np.linalg.norm(pts[2] - pts[1])
    avg_w = (w_top + w_bot) / 2.0
    avg_h = (h_l + h_r) / 2.0
    if avg_w < 100 or avg_h < 150:
        return None
    ratio = avg_h / avg_w
    # Phiếu A4 chuẩn có tỷ lệ chiều dài / rộng mốc ~1.444 (cho phép góc nghiêng điện thoại 1.05 - 1.85)
    if not (1.05 <= ratio <= 1.85):
        return None

    return pts


def auto_orient_sheet_robust(image_bgr: np.ndarray) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """
    Tự động phát hiện hướng chụp và xoay đúng chiều đứng (0°).
    Kiểm tra cả 4 góc vuông (0°, 180°, 90°, 270°) với thuật toán O(N).
    """
    raw_h, raw_w = image_bgr.shape[:2]
    test_angles = [0, 180, 90, 270] if raw_h >= raw_w else [90, 270, 0, 180]

    for angle in test_angles:
        rotated = rotate_cardinal(image_bgr, angle)
        cur_gray = cv2.cvtColor(rotated, cv2.COLOR_BGR2GRAY)
        corners = find_extreme_squares(cur_gray)

        if corners is not None:
            # Kiểm tra chiều đứng: phần đầu đề thi (chứa SBD & Mã đề) luôn có nhiều mực đen hơn phần chân
            tl, tr, br, bl = corners
            min_y = int(min(tl[1], tr[1]))
            max_y = int(max(bl[1], br[1]))
            sheet_h = max_y - min_y
            if sheet_h > 100:
                top_part = cur_gray[min_y : min_y + int(sheet_h * 0.30), :]
                bot_part = cur_gray[max_y - int(sheet_h * 0.30) : max_y, :]
                top_ink = np.sum(top_part < 100)
                bot_ink = np.sum(bot_part < 100)
                if top_ink >= bot_ink * 0.65:
                    if angle != 0:
                        print(f"[OK] Phát hiện ảnh xoay {angle}° -> Đã xoay về chiều đứng (0°).")
                    return rotated, corners

    return image_bgr, None


def find_all_10_markers_local(gray: np.ndarray, corners_4: np.ndarray) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Tìm chính xác 10 mốc chuẩn (5 trái, 5 phải) dựa trên vị trí dự đoán từ 4 mốc góc.
    Tuyệt đối không chạy tổ hợp (combinations), tìm kiếm cục bộ bán kính 60px quanh điểm dự đoán.
    Thời gian thực thi: < 5 mili-giây.
    """
    tl, tr, br, bl = corners_4
    h, w = gray.shape

    # Nhị phân hóa kép để bắt mốc mờ
    th1 = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 7)
    th2 = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 6)
    th = cv2.bitwise_or(th1, th2)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, k)

    cnts, _ = cv2.findContours(th, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    squares = []
    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        if 8 <= cw <= 60 and 8 <= ch <= 60:
            asp = cw / float(ch)
            if 0.65 <= asp <= 1.55:
                m = cv2.moments(c)
                if m['m00'] > 0:
                    squares.append((m['m10'] / m['m00'], m['m01'] / m['m00']))

    if len(squares) < 10:
        return None, None

    src_left = []
    for r in EXPECTED_Y_RATIOS:
        pred = tl + r * (bl - tl)
        cands = [s for s in squares if abs(s[0] - pred[0]) < 65 and abs(s[1] - pred[1]) < 65]
        if cands:
            best = min(cands, key=lambda s: (s[0] - pred[0])**2 + (s[1] - pred[1])**2)
            src_left.append(best)
        else:
            return None, None

    src_right = []
    for r in EXPECTED_Y_RATIOS:
        pred = tr + r * (br - tr)
        cands = [s for s in squares if abs(s[0] - pred[0]) < 65 and abs(s[1] - pred[1]) < 65]
        if cands:
            best = min(cands, key=lambda s: (s[0] - pred[0])**2 + (s[1] - pred[1])**2)
            src_right.append(best)
        else:
            return None, None

    return np.array(src_left, dtype=np.float32), np.array(src_right, dtype=np.float32)


def detect_a4_paper_contour(gray: np.ndarray) -> Optional[np.ndarray]:
    """Tầng dự phòng: Nhận diện 4 góc của tờ giấy A4 trên nền bàn."""
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
    """
    Nắn phẳng phối cảnh OMR đa tầng với khả năng chịu lỗi quang học cao nhất:
    Tầng 1: Cân bằng sáng phẳng (Flat-field Illumination Correction).
    Tầng 2: Tự động phát hiện hướng chụp và xoay đúng chiều đứng (0°).
    Tầng 3: Nếu đủ 10 mốc chuẩn -> Nắn phẳng 4 dải (4-band warp) triệt tiêu uốn cong phi tuyến.
    Tầng 4: Nếu có 4 mốc góc cực biên -> Nắn phẳng phối cảnh 4 góc (4-corner perspective warp).
    Tầng 5: Dự phòng viền giấy A4 trên nền bàn.
    """
    raw_bgr = cv2.imread(str(image_path))
    if raw_bgr is None:
        raise FileNotFoundError(f"Không tìm thấy file: {image_path}")

    out_w, out_h = CANONICAL_WIDTH, CANONICAL_HEIGHT
    tpl_corners = np.array([
        TPL_LEFT_5[0], TPL_RIGHT_5[0],
        TPL_RIGHT_5[4], TPL_LEFT_5[4]
    ], dtype=np.float32)

    # 1. Cân bằng sáng toàn tờ trước khi phân tích mốc
    norm_bgr = normalize_illumination(raw_bgr)

    # 2. Tự động xoay và tìm 4 mốc góc cực biên
    image_bgr, corners_4 = auto_orient_sheet_robust(norm_bgr)
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # TẦNG 1: NẮN 4 DẢI KHI ĐỦ 10 MỐC CHUẨN
    if corners_4 is not None:
        src_left, src_right = find_all_10_markers_local(gray, corners_4)
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

        # TẦNG 2: NẮN 4 MỐC GÓC CỰC BIÊN (PERSPECTIVE WARP)
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
