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
        self.core_r = max(1, int(round(3.5 * scale)))
        self.search_r = 2
        self.tight_sr = 1
        self.template_ink_map = template_ink_map

        # Precompute disk kernel và ma trận phạt khoảng cách (bước nhảy 1px, phạt 0.35*dist)
        rc = self.core_r
        yy_c, xx_c = np.ogrid[-rc : rc + 1, -rc : rc + 1]
        c_mask = (xx_c * xx_c + yy_c * yy_c <= rc * rc).astype(np.float32)
        c_sum = float(c_mask.sum())
        if c_sum > 0:
            c_mask /= c_sum
        self._core_mask = c_mask

        sr = self.search_r
        yy_p, xx_p = np.mgrid[-sr : sr + 1, -sr : sr + 1]
        self._penalty_grid = (0.35 * np.hypot(xx_p, yy_p)).astype(np.float32)

        tsr = self.tight_sr
        yy_t, xx_t = np.mgrid[-tsr : tsr + 1, -tsr : tsr + 1]
        self._tight_penalty_grid = (0.35 * np.hypot(xx_t, yy_t)).astype(np.float32)

    def _refine_and_score(self, ink_map: np.ndarray, x: float, y: float, tight: bool = False) -> Tuple[float, Tuple[int, int]]:
        """Dịch tâm trực tiếp theo độ đậm mực thuần (net_ink) trong bán kính nhỏ giữ trọn trong lòng ô tròn."""
        xi0, yi0 = int(round(x)), int(round(y))
        h, w = ink_map.shape
        rc = self.core_r
        sr = self.tight_sr if tight else self.search_r
        pen_grid = self._tight_penalty_grid if tight else self._penalty_grid
        pad = sr + rc

        if xi0 - pad < 0 or yi0 - pad < 0 or xi0 + pad >= w or yi0 + pad >= h:
            if xi0 - rc < 0 or yi0 - rc < 0 or xi0 + rc >= w or yi0 + rc >= h:
                return 0.0, (xi0, yi0)
            patch = ink_map[yi0 - rc : yi0 + rc + 1, xi0 - rc : xi0 + rc + 1]
            mask = self._core_mask > 0
            val = float(np.mean(patch[mask]))
            if self.template_ink_map is not None:
                th, tw = self.template_ink_map.shape
                if xi0 - rc >= 0 and yi0 - rc >= 0 and xi0 + rc < tw and yi0 + rc < th:
                    tpl_patch = self.template_ink_map[yi0 - rc : yi0 + rc + 1, xi0 - rc : xi0 + rc + 1]
                    val = max(0.0, val - max(0.0, float(np.mean(tpl_patch[mask]))) * 0.90)
            return max(0.0, val), (xi0, yi0)

        patch_ink = ink_map[yi0 - pad : yi0 + pad + 1, xi0 - pad : xi0 + pad + 1]
        if self.template_ink_map is not None:
            th, tw = self.template_ink_map.shape
            if yi0 - pad >= 0 and xi0 - pad >= 0 and yi0 + pad + 1 <= th and xi0 + pad + 1 <= tw:
                patch_tpl = self.template_ink_map[yi0 - pad : yi0 + pad + 1, xi0 - pad : xi0 + pad + 1]
                patch_net = np.maximum(0.0, patch_ink - np.maximum(0.0, patch_tpl) * 0.90)
            else:
                patch_net = np.maximum(0.0, patch_ink)
        else:
            patch_net = np.maximum(0.0, patch_ink)

        core_resp = cv2.filter2D(patch_net, -1, self._core_mask)
        search_win = core_resp[pad - sr : pad + sr + 1, pad - sr : pad + sr + 1]
        adjusted = np.maximum(0.0, search_win - pen_grid)
        iy, ix = np.unravel_index(np.argmax(adjusted), adjusted.shape)
        cx = int(xi0 + ix - sr)
        cy = int(yi0 + iy - sr)
        return float(adjusted[iy, ix]), (cx, cy)

    def read_filtered(self, gray: np.ndarray, ink_map: np.ndarray, active_q_nums: List[int]) -> Tuple[Dict[int, Dict[str, Any]], List[Dict[str, str]]]:
        results = {}
        anomalies = []
        active_set = {int(q) for q in active_q_nums}

        for q in self.coords:
            q_num = int(q["question"])
            if q_num not in active_set:
                continue

            q_errors = []

            # Đọc 4 cột chữ số (0..9) trước để lấy nền động cục bộ của câu (chống bóng đổ & nhiễu nén JPEG)
            col_digits: List[List[str]] = [[] for _ in range(4)]
            col_bgs: List[float] = []
            for col in range(4):
                net_scores = [
                    self._refine_and_score(ink_map, q["digits"][str(d)][col][0], q["digits"][str(d)][col][1], tight=False)[0]
                    for d in range(10)
                ]

                # Nền động cột = phân vị 50%
                col_bg = float(np.percentile(net_scores, 50))
                col_bgs.append(col_bg)
                rel_scores = [max(0.0, s - col_bg) for s in net_scores]

                ranked = sorted(enumerate(rel_scores), key=lambda x: x[1], reverse=True)
                top_d, top_rel = ranked[0]
                sec_d, sec_rel = ranked[1]

                # Kết luận tô đúp (ngưỡng chặt hơn để tránh bắt nhầm rìa mực ô liền kề)
                if top_rel >= 16.5 and sec_rel >= 15.5 and (top_rel - sec_rel) < 6.5:
                    col_digits[col] = [str(top_d), str(sec_d)]
                # Kết luận tô hợp lệ 1 chữ số (bắt trọn nét chì nhạt, ổn định tuyệt đối)
                elif top_rel >= 10.0 and (top_rel - sec_rel) >= 5.8:
                    col_digits[col] = [str(top_d)]
                else:
                    col_digits[col] = []

            q_bg = float(np.median(col_bgs)) if col_bgs else 0.0

            # Đọc dấu âm (-) và dấu phẩy (,) có bù trừ nền câu q_bg
            s_raw, _ = self._refine_and_score(ink_map, q["sign"][0], q["sign"][1], tight=True)
            s_val = max(0.0, s_raw - q_bg)
            has_minus = s_val >= 13.0

            comma_hits = []
            for idx, cpos in enumerate(q["comma_positions"]):
                c_raw, _ = self._refine_and_score(ink_map, cpos[0], cpos[1], tight=True)
                c_val = max(0.0, c_raw - q_bg)
                if c_val >= 13.0:
                    comma_hits.append(idx + 1)

            if len(comma_hits) > 1:
                q_errors.append("Tô đúp dấu phẩy")
                comma_opt = None
            elif len(comma_hits) == 1:
                comma_opt = comma_hits[0]
            else:
                comma_opt = None

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

                if sec_net >= 13.5 and (top_net - sec_net) < 7.0:
                    res.append(f"[{top_d}{sec_d}]")
                    anomalies.append({
                        "type": f"{grid_name}_DOUBLE_FILL",
                        "msg": f"{grid_name} Cột {col_idx} tô đúp ({top_d} và {sec_d})"
                    })
                elif top_net >= 9.5 and top_raw >= 12.5:
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

            if sec_val >= 14.5 and (top_val - sec_val) < 7.0:
                p1_res[q_num] = "MULTIPLE"
                p1_anom.append({"type": "P1_DOUBLE_FILL", "msg": f"Phần I Câu {q_num} tô đúp ({top_opt} và {sec_opt})"})
            elif top_val >= 11.5 or (top_rel >= 8.5 and (top_val - sec_val) >= 5.5):
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

                if st >= 16.5 and sf >= 16.5 and abs(st - sf) < 7.5:
                    row_dict[rk] = "ĐS"
                    p2_anom.append({"type": "P2_DOUBLE_FILL", "msg": f"Phần II Câu {q_num}{rk} tô cả Đúng và Sai"})
                elif max(st, sf) >= 9.0 and abs(st - sf) >= 5.5:
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