# test_bubble_detector.py
# -*- coding: utf-8 -*-
"""
KIỂM CHỨNG THỰC NGHIỆM THUẬT TOÁN BUBBLE DETECTOR KHÁNG BÓNG ĐỔ
"""
import json
from pathlib import Path
import cv2
import numpy as np

from bubble_detector import BubbleDetector


def run_benchmark():
    detector = BubbleDetector(core_radius=9, ring_inner=17, ring_outer=22)

    part1_coord_path = Path("output/part1_coordinates.json")
    part2_coord_path = Path("output/part2_coordinates.json")

    if not part1_coord_path.exists() or not part2_coord_path.exists():
        print("[!] Lỗi: Chưa tìm thấy file tọa độ part1_coordinates.json hoặc part2_coordinates.json.")
        return

    with open(part1_coord_path, "r", encoding="utf-8") as f:
        p1_data = json.load(f)["questions"]
    with open(part2_coord_path, "r", encoding="utf-8") as f:
        p2_data = json.load(f)["questions"]

    test_images = [
        Path("output/bai_kiem_tra_01_aligned.png"),
        Path("output/bai_kiem_tra_02_aligned.png"),
    ]

    print("=" * 80)
    print("BENCHMARK: KIỂM CHỨNG CHỈ SỐ RELATIVE DARKNESS TRÊN DỮ LIỆU THỰC TẾ")
    print("=" * 80)

    for img_path in test_images:
        if not img_path.exists():
            print(f"[!] Bỏ qua (chưa có file): {img_path}")
            continue

        img_bgr = cv2.imread(str(img_path))
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        print(f"\n[*] Đang đánh giá: {img_path.name} (Kích thước: {gray.shape[1]}x{gray.shape[0]})")

        filled_scores = []
        blank_scores = []

        # 1. Đánh giá Phần I (40 câu) sử dụng tham số tối ưu (min_signal=0.095)
        p1_results = []
        for q_item in p1_data:
            q_num = q_item["question"]
            res = detector.classify_mcq_row(gray, q_item["choices"], min_signal=0.095, contrast_margin=0.055)
            p1_results.append((q_num, res["answer"], res["status"], res["scores"]))

            for opt, score in res["scores"].items():
                if res["answer"] == opt and res["status"] == "VALID":
                    filled_scores.append(score)
                elif res["answer"] == "":
                    blank_scores.append(score)

        print("  --- Kết quả Phần I (16 câu đầu) ---")
        for q_num, ans, status, scores in p1_results[:16]:
            print(f"  Câu {q_num:02d}: Đáp án=[{ans or ' '}] | Trạng thái={status:<11} | Scores={scores}")

        # 2. Đánh giá Phần II (8 câu x 4 ý)
        p2_results = []
        for q_item in p2_data:
            q_num = q_item["question"]
            row_res = {}
            for row_k in ["a", "b", "c", "d"]:
                true_pt = tuple(q_item["rows"][row_k]["true"])
                false_pt = tuple(q_item["rows"][row_k]["false"])
                eval_res = detector.classify_true_false_row(gray, true_pt, false_pt, min_signal=0.095, contrast_margin=0.055)
                row_res[row_k] = eval_res
                if eval_res["answer"] == "Đ":
                    filled_scores.append(eval_res["score_true"])
                    blank_scores.append(eval_res["score_false"])
                elif eval_res["answer"] == "S":
                    filled_scores.append(eval_res["score_false"])
                    blank_scores.append(eval_res["score_true"])
                else:
                    blank_scores.append(eval_res["score_true"])
                    blank_scores.append(eval_res["score_false"])

            p2_results.append((q_num, row_res))

        print("\n  --- Kết quả Phần II (Câu 1 và Câu 2) ---")
        for q_num, row_dict in p2_results[:2]:
            row_str = " | ".join([f"{k}:{v['answer'] or '-'}(T:{v['score_true']},F:{v['score_false']})" for k, v in row_dict.items()])
            print(f"  Câu {q_num}: {row_str}")

        # Thống kê phân phối
        if filled_scores and blank_scores:
            print("\n  --- THỐNG KÊ PHÂN TÁCH GIÁ TRỊ (SEPARATION MARGIN) ---")
            print(f"  Ô ĐÃ TÔ    : Min = {min(filled_scores):.3f} | Mean = {np.mean(filled_scores):.3f} | Max = {max(filled_scores):.3f}")
            print(f"  Ô BỎ TRỐNG : Min = {min(blank_scores):.3f} | Mean = {np.mean(blank_scores):.3f} | Max = {max(blank_scores):.3f}")


if __name__ == "__main__":
    run_benchmark()