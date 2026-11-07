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

        overlay = canvas.copy()
        cv2.circle(overlay, (cx, cy), radius, color, -1, cv2.LINE_AA)
        cv2.addWeighted(overlay, alpha, canvas, 1.0 - alpha, 0, canvas)
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
                stu_digits_list = stu_item.get("digits", [[], [], [], []])
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
                cls._draw_centered_text(canvas, "+0.25 d", box_cx, score_y, cv2.FONT_HERSHEY_DUPLEX, 0.75, cls.COLOR_GREEN, 2)
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
                cls._draw_centered_text(canvas, f"[Trong] DA: {exp_str}", box_cx, score_y, cv2.FONT_HERSHEY_DUPLEX, 0.55, cls.COLOR_YELLOW, 2)
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
                cls._draw_centered_text(canvas, f"0d [DA: {exp_str}]", box_cx, score_y, cv2.FONT_HERSHEY_DUPLEX, 0.55, cls.COLOR_RED, 2)
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