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
    # Ngưỡng Laplacian Variance tối thiểu để không bị mờ nhòe (Motion Blur)
    BLUR_THRESHOLD: float = 60.0
    # Độ tương phản tối thiểu (độ lệch chuẩn độ xám toàn trang)
    CONTRAST_MIN_STD: float = 18.0
    # Độ sáng trung bình tối thiểu và tối đa [40, 248]
    MIN_MEAN_BRIGHTNESS: float = 40.0
    MAX_MEAN_BRIGHTNESS: float = 248.0
    # Tỷ lệ pixel quá tối (underexposed) hoặc quá sáng (burned out) tối đa
    MAX_EXTREME_PIXELS_RATIO: float = 0.40

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

        # 1. Đánh giá độ nét (Sharpness / Blur Detection) qua toán tử Laplacian
        laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
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
