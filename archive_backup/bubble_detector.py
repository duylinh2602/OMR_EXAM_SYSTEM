# bubble_detector.py
# -*- coding: utf-8 -*-
"""
THUẬT TOÁN ĐO ĐỘ TÔ Ô TRÒN KHÁNG BÓNG ĐỔ & TỰ THÍCH ỨNG BÚT CHÌ NHẠT
Hỗ trợ Dynamic Row Contrast và tương thích ngược toàn bộ tham số cũ/mới.
"""
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np


class BubbleDetector:
    def __init__(
        self,
        core_radius: int = 9,       # Bán kính lõi bút chì r < 12.8 px
        ring_inner: int = 17,       # Vành nền ngoài viền in r > 15.3 px
        ring_outer: int = 22        # Vành ngoài an toàn
    ):
        self.r_core = core_radius
        self.r_in = ring_inner
        self.r_out = ring_outer

    def compute_relative_darkness(self, gray_img: np.ndarray, cx: float, cy: float) -> float:
        """
        Tính độ đậm tương đối của lõi so với nền giấy trắng bao quanh.
        """
        x_base = int(round(cx))
        y_base = int(round(cy))
        h, w = gray_img.shape

        search_r = 4
        if (x_base - search_r < 0 or y_base - search_r < 0 or
            x_base + search_r >= w or y_base + search_r >= h):
            best_x, best_y = x_base, y_base
        else:
            patch_s = gray_img[y_base - search_r : y_base + search_r + 1,
                               x_base - search_r : x_base + search_r + 1]
            min_y, min_x = np.unravel_index(np.argmin(patch_s), patch_s.shape)
            best_x = x_base - search_r + min_x
            best_y = y_base - search_r + min_y

        r = self.r_out
        if best_x - r < 0 or best_y - r < 0 or best_x + r >= w or best_y + r >= h:
            return 0.0

        patch = gray_img[best_y - r : best_y + r + 1, best_x - r : best_x + r + 1].astype(np.float32)
        yy, xx = np.ogrid[-r : r + 1, -r : r + 1]
        dist_sq = xx * xx + yy * yy

        core_mask = dist_sq <= (self.r_core ** 2)
        ring_mask = (dist_sq >= (self.r_in ** 2)) & (dist_sq <= (self.r_out ** 2))

        core_vals = patch[core_mask]
        ring_vals = patch[ring_mask]

        if core_vals.size == 0 or ring_vals.size == 0:
            return 0.0

        core_mean = float(np.mean(core_vals))
        ring_ref = float(np.percentile(ring_vals, 70))

        if ring_ref < 35.0:
            return 0.0

        relative_darkness = (ring_ref - core_mean) / ring_ref
        return max(0.0, float(relative_darkness))

    def classify_mcq_row(
        self,
        gray_img: np.ndarray,
        coords: Dict[str, Tuple[float, float]],
        min_signal: float = 0.095,
        contrast_margin: float = 0.055,
        fill_thresh: Optional[float] = None,
        margin_thresh: Optional[float] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Phân loại Phần I. Tương thích cả min_signal lẫn fill_thresh.
        """
        if fill_thresh is not None:
            min_signal = fill_thresh
        if margin_thresh is not None:
            contrast_margin = margin_thresh

        scores = {}
        for opt, (x, y) in coords.items():
            scores[opt] = round(self.compute_relative_darkness(gray_img, x, y), 3)

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top_opt, top_score = ranked[0]
        second_opt, second_score = ranked[1]

        if top_score < min_signal:
            return {"answer": "", "status": "BLANK", "scores": scores}

        if second_score >= min_signal and (top_score - second_score) < contrast_margin:
            return {"answer": "MULTIPLE", "status": "DOUBLE_FILL", "scores": scores}

        if (top_score - second_score) >= contrast_margin or (top_score >= 1.8 * max(second_score, 0.04)):
            return {"answer": top_opt, "status": "VALID", "scores": scores}

        return {"answer": "", "status": "UNCERTAIN", "scores": scores}

    def classify_true_false_row(
        self,
        gray_img: np.ndarray,
        true_coord: Tuple[float, float],
        false_coord: Tuple[float, float],
        min_signal: float = 0.145,       # Ngưỡng tối thiểu của ô tô chì thật (vết chì nhạt nhất là 0.177)
        contrast_margin: float = 0.055,  # Chênh lệch tối thiểu giữa 2 ô
        fill_thresh: Optional[float] = None,
        margin_thresh: Optional[float] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Phân loại Phần II (Đúng/Sai) chuẩn xác, chống bẫy nhiễu nền giấy xám.
        """
        if fill_thresh is not None:
            min_signal = fill_thresh
        if margin_thresh is not None:
            contrast_margin = margin_thresh

        s_true = round(self.compute_relative_darkness(gray_img, true_coord[0], true_coord[1]), 3)
        s_false = round(self.compute_relative_darkness(gray_img, false_coord[0], false_coord[1]), 3)
        
        max_s = max(s_true, s_false)
        diff = abs(s_true - s_false)

        # 1. Nếu cả 2 ô đều không đạt ngưỡng nét chì (chỉ là nền giấy) -> BỎ TRỐNG
        if max_s < min_signal:
            return {"answer": "", "status": "BLANK", "score_true": s_true, "score_false": s_false}

        # 2. Nếu có vết tô nhưng cả 2 ô đậm gần bằng nhau -> TÔ ĐÚP
        if diff < contrast_margin and min(s_true, s_false) >= (min_signal * 0.85):
            return {"answer": "BOTH", "status": "DOUBLE_FILL", "score_true": s_true, "score_false": s_false}

        # 3. Ô hợp lệ
        ans = "Đ" if s_true > s_false else "S"
        return {"answer": ans, "status": "VALID", "score_true": s_true, "score_false": s_false}