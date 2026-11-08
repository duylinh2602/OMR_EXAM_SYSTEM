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
    def __init__(self, p3_coords: List[Dict[str, Any]], scale: float):
        self.coords = p3_coords
        self.scale = scale
        self.core_r = 3.0 * scale
        self.search_r = int(round(8.0 * scale))
        self.ring_in = 7.2 * scale
        self.ring_out = 10.8 * scale

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
        return val, (cx, cy)

    def read_filtered(self, gray: np.ndarray, ink_map: np.ndarray, active_q_nums: List[int]) -> Tuple[Dict[int, Dict[str, Any]], List[Dict[str, str]]]:
        resp = self._build_gradient_response(gray)
        results = {}
        anomalies = []
        fill_thresh = 16.0
        active_set = {int(q) for q in active_q_nums}

        for q in self.coords:
            q_num = int(q["question"])
            if q_num not in active_set:
                continue

            s_val, _ = self._refine_and_score(ink_map, resp, q["sign"][0], q["sign"][1])
            has_minus = s_val >= fill_thresh

            comma_opt = None
            for idx, cpos in enumerate(q["comma_positions"]):
                c_val, _ = self._refine_and_score(ink_map, resp, cpos[0], cpos[1])
                if c_val >= fill_thresh:
                    comma_opt = idx + 1

            col_digits: List[List[str]] = [[] for _ in range(4)]
            for col in range(4):
                scores = []
                for d in range(10):
                    val, _ = self._refine_and_score(ink_map, resp, q["digits"][str(d)][col][0], q["digits"][str(d)][col][1])
                    scores.append(val)
                ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
                top_d, top_s = ranked[0]
                sec_d, sec_s = ranked[1]
                hits = [str(d) for d, s in enumerate(scores) if s >= fill_thresh]

                if len(hits) > 1:
                    col_digits[col] = hits
                elif top_s >= fill_thresh and (top_s - sec_s) >= 9.5:
                    col_digits[col] = [str(top_d)]
                else:
                    col_digits[col] = []

            q_errors = []
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
                "anomalies": q_errors,
                "digits": col_digits
            }

        return results, anomalies


class FullGradingPipeline:
    def __init__(self, exam_data: Optional[Dict[str, Any]] = None):
        header_coord_path = resolve_data_path("output/header_coordinates.json")
        p1_path = resolve_data_path("output/part1_coordinates.json")
        p2_path = resolve_data_path("output/part2_coordinates.json")
        p3_path = resolve_data_path("output/part3_coordinates.json")

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

        scale = CANONICAL_WIDTH / 1434.0
        self.p3_reader = Part3ShadowfixReader(self.p3_coords, scale)
        self.stamper = VisualStamper

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
    def _eval_bubble_ink(ink_map: np.ndarray, cx: float, cy: float, r_core: int = 8) -> float:
        xi, yi = int(round(cx)), int(round(cy))
        h, w = ink_map.shape
        if xi - r_core < 0 or yi - r_core < 0 or xi + r_core >= w or yi + r_core >= h:
            return 0.0
        patch = ink_map[yi - r_core : yi + r_core + 1, xi - r_core : xi + r_core + 1]
        yy, xx = np.ogrid[-r_core : r_core + 1, -r_core : r_core + 1]
        mask = (xx * xx + yy * yy) <= (r_core * r_core)
        return float(np.mean(patch[mask]))

    def _read_header_ink(self, ink_map: np.ndarray) -> Tuple[str, str, str, List[Dict[str, str]]]:
        """Đọc Số báo danh và Mã đề với nguyên tắc không tự ý suy đoán."""
        anomalies = []
        FILL_THRESH = 16.0
        DOUBLE_THRESH = 15.0

        def decode_grid(cols, grid_name="SBD"):
            res = []
            for col_idx, col in enumerate(cols, start=1):
                scores = [self._eval_bubble_ink(ink_map, col["digits"][str(d)][0], col["digits"][str(d)][1], r_core=8) for d in range(10)]
                ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
                top_d, top_s = ranked[0]
                sec_d, sec_s = ranked[1]

                if top_s >= FILL_THRESH and sec_s >= DOUBLE_THRESH and (top_s - sec_s) < 8.0:
                    res.append(f"[{top_d}{sec_d}]")
                    anomalies.append({
                        "type": f"{grid_name}_DOUBLE_FILL",
                        "msg": f"{grid_name} Cột {col_idx} tô đúp ({top_d} và {sec_d})"
                    })
                elif top_s >= FILL_THRESH and (top_s - sec_s) >= 7.0:
                    res.append(str(top_d))
                elif top_s >= 25.0:
                    res.append(str(top_d))
                else:
                    res.append("?")
            return "".join(res)

        sbd = decode_grid(self.sbd_columns, "SBD")
        raw_made = decode_grid(self.made_columns, "MADE")

        if "?" in sbd or "[" in sbd:
            anomalies.append({"type": "MISSING_SBD", "msg": f"Số báo danh chưa rõ ràng ({sbd})"})

        # KHỬ HOÀN TOÀN FUZZY MATCHING: Chỉ chấp nhận khi đọc rõ đủ 4 chữ số hợp lệ
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

        # 1. TẠO INK MAP TOÀN CỤC (High-performance Gaussian background subtraction)
        bg = cv2.GaussianBlur(gray, (0, 0), sigmaX=22.0, sigmaY=22.0, borderType=cv2.BORDER_REFLECT)
        ink_map = bg.astype(np.float32) - gray.astype(np.float32)

        # 2. ĐỌC HEADER
        sbd, raw_made, detected_made, h_anom = self._read_header_ink(ink_map)
        
        # Nếu giáo viên cưỡng chế mã đề (sửa tay), sử dụng forced_exam_code
        if forced_exam_code and str(forced_exam_code).strip():
            exam_code = str(forced_exam_code).strip().zfill(4)
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
        FILL_P1_THRESH = 16.0
        MARGIN_P1 = 9.0

        for q in self.p1_coords:
            q_num = int(q["question"])
            if q_num not in active_p1:
                continue
            scores = {opt: self._eval_bubble_ink(ink_map, q["choices"][opt][0], q["choices"][opt][1], r_core=8) for opt in ["A", "B", "C", "D"]}
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            top_opt, top_val = ranked[0]
            sec_opt, sec_val = ranked[1]

            if top_val < FILL_P1_THRESH:
                p1_res[q_num] = ""
            elif sec_val >= FILL_P1_THRESH and (top_val - sec_val) < MARGIN_P1:
                # SỬA LỖI 1: Tô đúp gán MULTIPLE -> Tuyệt đối không cho điểm câu này
                p1_res[q_num] = "MULTIPLE"
                p1_anom.append({"type": "P1_DOUBLE_FILL", "msg": f"Phần I Câu {q_num} tô đúp ({top_opt} và {sec_opt})"})
            else:
                p1_res[q_num] = top_opt

        # 5. QUÉT PHẦN II (ĐÚNG / SAI BẬC THANG)
        p2_res = {}
        p2_anom = []
        FILL_P2_THRESH = 16.0
        MARGIN_P2 = 9.0

        for q in self.p2_coords:
            q_num = int(q["question"])
            if q_num not in active_p2:
                continue
            row_dict = {}
            for rk in ["a", "b", "c", "d"]:
                tx, ty = q["rows"][rk]["true"]
                fx, fy = q["rows"][rk]["false"]
                st = self._eval_bubble_ink(ink_map, tx, ty, r_core=8)
                sf = self._eval_bubble_ink(ink_map, fx, fy, r_core=8)

                if st < FILL_P2_THRESH and sf < FILL_P2_THRESH:
                    row_dict[rk] = ""
                elif st >= FILL_P2_THRESH and sf >= FILL_P2_THRESH:
                    # SỬA LỖI 1: Cả Đ và S cùng có nét chì -> Gán ĐS -> Tính 0 điểm ý này
                    row_dict[rk] = "ĐS"
                    p2_anom.append({"type": "P2_DOUBLE_FILL", "msg": f"Phần II Câu {q_num}{rk} tô cả Đúng và Sai"})
                elif st >= FILL_P2_THRESH and (st - sf) >= MARGIN_P2:
                    row_dict[rk] = "Đ"
                elif sf >= FILL_P2_THRESH and (sf - st) >= MARGIN_P2:
                    row_dict[rk] = "S"
                elif max(st, sf) >= FILL_P2_THRESH:
                    row_dict[rk] = "Đ" if st > sf else "S"
                    p2_anom.append({"type": "P2_UNCERTAIN", "msg": f"Phần II Câu {q_num}{rk} tô mờ/chưa rõ giữa Đ và S"})
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
        p2_rule = {int(k): float(v) for k, v in raw_p2_rule.items()}
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