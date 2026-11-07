# restore_coordinates.py
# -*- coding: utf-8 -*-
"""
CÔNG CỤ KHÔI PHỤC TOÀN DIỆN 4 TỆP TỌA ĐỘ MỐC CHUẨN OMR BỘ GD&ĐT 2025
Tự động tái tạo các tệp JSON trong thư mục output/ nếu bị xóa nhầm.
"""
import json
from pathlib import Path

output_dir = Path("output")
output_dir.mkdir(exist_ok=True, parents=True)

# 1. Tọa độ Header (Mục 7 SBD 8 cột, Mục 8 Mã đề 4 cột)
header_data = {
    "template": "answer_sheet_master",
    "template_width": 1769,
    "template_height": 2526,
    "row_step": 49.657,
    "digits_y_rows": [286.08, 335.74, 385.4, 435.06, 484.71, 534.37, 584.03, 633.69, 683.34, 733.0],
    "sbd_columns": [
        {"column": 1, "x": 1241.0, "digits": {str(d): [1241.0, round(286.08 + d * 49.657, 2)] for d in range(10)}},
        {"column": 2, "x": 1273.0, "digits": {str(d): [1273.0, round(286.08 + d * 49.657, 2)] for d in range(10)}},
        {"column": 3, "x": 1309.0, "digits": {str(d): [1309.0, round(286.08 + d * 49.657, 2)] for d in range(10)}},
        {"column": 4, "x": 1345.0, "digits": {str(d): [1345.0, round(286.08 + d * 49.657, 2)] for d in range(10)}},
        {"column": 5, "x": 1377.0, "digits": {str(d): [1377.0, round(286.08 + d * 49.657, 2)] for d in range(10)}},
        {"column": 6, "x": 1413.0, "digits": {str(d): [1413.0, round(286.08 + d * 49.657, 2)] for d in range(10)}},
        {"column": 7, "x": 1445.0, "digits": {str(d): [1445.0, round(286.08 + d * 49.657, 2)] for d in range(10)}},
        {"column": 8, "x": 1477.0, "digits": {str(d): [1477.0, round(286.08 + d * 49.657, 2)] for d in range(10)}}
    ],
    "made_columns": [
        {"column": 1, "x": 1545.0, "digits": {str(d): [1545.0, round(286.08 + d * 49.657, 2)] for d in range(10)}},
        {"column": 2, "x": 1584.0, "digits": {str(d): [1584.0, round(286.08 + d * 49.657, 2)] for d in range(10)}},
        {"column": 3, "x": 1620.0, "digits": {str(d): [1620.0, round(286.08 + d * 49.657, 2)] for d in range(10)}},
        {"column": 4, "x": 1649.0, "digits": {str(d): [1649.0, round(286.08 + d * 49.657, 2)] for d in range(10)}}
    ]
}

# 2. Tọa độ Phần I (40 câu trắc nghiệm)
p1_questions = []
col_x_bases = [
    {"A": 191.0, "B": 264.0, "C": 334.0, "D": 402.0, "y0": 925.5},
    {"A": 592.0, "B": 665.0, "C": 735.0, "D": 805.0, "y0": 923.75},
    {"A": 991.0, "B": 1061.0, "C": 1131.0, "D": 1204.0, "y0": 927.0},
    {"A": 1393.0, "B": 1460.0, "C": 1533.0, "D": 1606.0, "y0": 925.5}
]
y_step_p1 = 42.722
for block_idx, base in enumerate(col_x_bases):
    for r in range(10):
        q_num = block_idx * 10 + r + 1
        y_val = round(base["y0"] + r * y_step_p1, 2)
        p1_questions.append({
            "question": q_num,
            "choices": {opt: [base[opt], y_val] for opt in ["A", "B", "C", "D"]}
        })
part1_data = {
    "template": "answer_sheet_v1",
    "template_width": 1769,
    "template_height": 2526,
    "row_step": 42.722,
    "questions": p1_questions
}

# 3. Tọa độ Phần II (8 câu Đúng/Sai)
p2_questions = []
p2_x_bases = [
    (193.0, 265.0, 1523.5),
    (332.0, 404.0, 1520.5),
    (588.0, 660.0, 1523.5),
    (730.0, 802.0, 1523.5),
    (989.0, 1061.0, 1522.0),
    (1134.0, 1204.0, 1523.5),
    (1390.0, 1459.0, 1523.5),
    (1532.0, 1602.0, 1526.5)
]
y_step_p2 = 41.5
for q_idx, (tx, fx, y0) in enumerate(p2_x_bases, start=1):
    rows_dict = {}
    for r_idx, rk in enumerate(["a", "b", "c", "d"]):
        y_val = round(y0 + r_idx * y_step_p2, 2)
        rows_dict[rk] = {
            "true": [tx, y_val],
            "false": [fx, y_val]
        }
    p2_questions.append({"question": q_idx, "rows": rows_dict})
part2_data = {
    "template": "answer_sheet_v1",
    "template_width": 1769,
    "template_height": 2526,
    "row_step": 41.5,
    "questions": p2_questions
}

# 4. Tọa độ Phần III (6 câu Trả lời ngắn)
p3_questions = []
p3_x_bases = [
    [180.0, 223.0, 266.0, 309.0],
    [436.0, 482.0, 522.0, 565.0],
    [690.0, 735.0, 775.0, 818.0],
    [946.0, 990.0, 1032.0, 1074.0],
    [1200.0, 1244.0, 1286.0, 1328.0],
    [1454.0, 1498.0, 1540.0, 1582.0]
]
y_step_p3 = 47.222
for q_idx, xs in enumerate(p3_x_bases, start=1):
    digits_map = {}
    for d in range(10):
        y_val = round(1938.0 + d * y_step_p3, 2)
        digits_map[str(d)] = [[xs[c], y_val] for c in range(4)]
    p3_questions.append({
        "question": q_idx,
        "sign": [xs[0], 1845.0],
        "comma_positions": [[xs[1], 1894.0], [xs[2], 1894.0]],
        "digits": digits_map
    })
part3_data = {
    "template": "answer_sheet_v1",
    "template_width": 1769,
    "template_height": 2526,
    "row_step": 47.222,
    "questions": p3_questions
}

files_to_restore = {
    "header_coordinates.json": header_data,
    "part1_coordinates.json": part1_data,
    "part2_coordinates.json": part2_data,
    "part3_coordinates.json": part3_data
}

for filename, content in files_to_restore.items():
    file_path = output_dir / filename
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False, indent=4)
    print(f"[✓] Đã khôi phục thành công: {file_path}")

print("=" * 75)
print("TOÀN BỘ 4 TỆP TỌA ĐỘ ĐÃ SẴN SÀNG TRONG THƯ MỤC output/!")
print("=" * 75)