
import cv2
import json
import csv
import argparse
import numpy as np

from pathlib import Path

# ==========================================
# CAU HINH
# ==========================================

TEMPLATE_PATH = Path("output/answer_sheet_master.png")
COORDINATE_PATH = Path("output/part1_coordinates.json")
OUTPUT_DIR = Path("output")

FILL_THRESHOLD = 55
REVIEW_THRESHOLD = 28
BUBBLE_RADIUS = 5

CHOICES = ["A", "B", "C", "D"]


# ==========================================
# DOC GIA TRI TAM O TRON
# ==========================================

def get_center_value(gray, x, y):

    x = int(round(x))
    y = int(round(y))

    r = BUBBLE_RADIUS

    roi = gray[
        y-r:y+r+1,
        x-r:x+r+1
    ]

    if roi.shape != (2*r+1, 2*r+1):
        raise ValueError("O dap an nam ngoai anh.")

    yy, xx = np.ogrid[-r:r+1, -r:r+1]

    mask = xx**2 + yy**2 <= r**2

    return float(np.median(roi[mask]))


# ==========================================
# NHAN DIEN O TO
# ==========================================

def detect_part1(image_path):

    # Doc anh bai lam da can chinh
    student = cv2.imread(str(image_path))

    if student is None:
        raise FileNotFoundError(
            f"Khong doc duoc anh: {image_path}"
        )

    # Doc anh phieu mau trang
    template = cv2.imread(str(TEMPLATE_PATH))

    if template is None:
        raise FileNotFoundError(
            "Khong tim thay anh phieu mau."
        )

    # Doc toa do 160 o
    with open(
        COORDINATE_PATH,
        "r",
        encoding="utf-8"
    ) as f:
        coordinate_data = json.load(f)

    if student.shape[:2] != template.shape[:2]:
        raise ValueError(
            "Kich thuoc anh bai lam khong khop phieu mau. "
            "Hay chay align_sheet.py truoc."
        )

    # Chuyen sang anh xam
    student_gray = cv2.cvtColor(
        student,
        cv2.COLOR_BGR2GRAY
    )

    template_gray = cv2.cvtColor(
        template,
        cv2.COLOR_BGR2GRAY
    )

    questions = coordinate_data["questions"]

    if len(questions) != 40:
        raise ValueError(
            f"Can 40 cau, hien co {len(questions)} cau."
        )

    results = []
    debug = student.copy()

    print("\nKET QUA NHAN DIEN PHAN I")
    print("=" * 65)

    for question in questions:

        q_number = question["question"]

        scores = {}

        # Doc do den cua 4 phuong an
        for choice in CHOICES:

            x, y = question["choices"][choice]

            reference_value = get_center_value(
                template_gray, x, y
            )

            student_value = get_center_value(
                student_gray, x, y
            )

            # Do muc do toi hon so voi phieu mau
            score = reference_value - student_value

            scores[choice] = round(
                max(0, score), 1
            )

        # Tim cac phuong an duoc to ro
        
        # ======================================
        # PHAN LOAI DAP AN THEO TUONG QUAN
        # ======================================

        ranked = sorted(
            scores.items(),
            key=lambda item: item[1],
            reverse=True
        )

        top_choice, top_score = ranked[0]
        second_choice, second_score = ranked[1]

        # Lay 2 diem thap nhat lam muc nen
        lowest_two = sorted(scores.values())[:2]
        baseline = float(np.mean(lowest_two))

        top_margin = top_score - baseline
        second_margin = second_score - baseline

        MARK_MARGIN = 55
        REVIEW_MARGIN = 30

        filled = []
        uncertain = []

        if top_margin >= MARK_MARGIN:

            if second_margin >= MARK_MARGIN:
                answer = "MULTIPLE"
                status = "MULTIPLE_MARKS"

                filled = [
                    choice
                    for choice in CHOICES
                    if scores[choice] - baseline >= MARK_MARGIN
                ]

            else:
                answer = top_choice
                status = "VALID"
                filled = [top_choice]

        elif top_margin >= REVIEW_MARGIN:

            answer = "REVIEW"
            status = "UNCERTAIN"
            uncertain = [top_choice]

        else:

            answer = ""
            status = "BLANK"

        
        # ======================================
        # LUU KET QUA CUA TUNG CAU
        # ======================================

        results.append({
            "question": q_number,
            "answer": answer,
            "status": status,
            "scores": scores.copy()
        })

        print(
            f"Cau {q_number:02d}: "
            f"{answer if answer else 'BO TRONG'} "
            f"| {status}"
        )

        # Danh dau cac o tren anh kiem tra
        for choice in CHOICES:

            x, y = question["choices"][choice]
            x, y = int(x), int(y)

            if choice in filled:
                color = (0, 0, 255)       # Do: da to

            elif choice in uncertain:
                color = (0, 165, 255)     # Cam: can kiem tra

            else:
                color = (150, 150, 150)   # Xam: bo trong

            cv2.circle(
                debug,
                (x, y),
                9,
                color,
                2
            )

        # Ghi dap an nhan dang
        first_x, first_y = question["choices"]["D"]

        # Ghi dap an nhan dang
        first_x, first_y = question["choices"]["D"]

        cv2.putText(
            debug,
            answer if answer else "-",
            (int(first_x) + 12, int(first_y) + 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (255, 0, 0),
            1
        )

    # ======================================
    # LUU KET QUA CSV VA JSON
    # ======================================

    OUTPUT_DIR.mkdir(exist_ok=True)

    stem = Path(image_path).stem

    csv_path = OUTPUT_DIR / f"{stem}_part1.csv"
    json_path = OUTPUT_DIR / f"{stem}_part1.json"
    debug_path = OUTPUT_DIR / f"{stem}_part1_debug.png"

    with open(
        csv_path,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        writer = csv.writer(f)

        writer.writerow([
            "Cau",
            "Dap an",
            "Trang thai",
            "Diem A",
            "Diem B",
            "Diem C",
            "Diem D"
        ])

        for item in results:

            writer.writerow([
                item["question"],
                item["answer"],
                item["status"],
                item["scores"]["A"],
                item["scores"]["B"],
                item["scores"]["C"],
                item["scores"]["D"]
            ])

    with open(
        json_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            results,
            f,
            ensure_ascii=False,
            indent=4
        )

    cv2.imwrite(
        str(debug_path),
        debug
    )

    # ======================================
    # THONG KE
    # ======================================

    valid = sum(
        r["status"] == "VALID"
        for r in results
    )

    blank = sum(
        r["status"] == "BLANK"
        for r in results
    )

    multiple = sum(
        r["status"] == "MULTIPLE_MARKS"
        for r in results
    )

    uncertain = sum(
        r["status"] == "UNCERTAIN"
        for r in results
    )

    print("\n" + "=" * 65)
    print("THONG KE NHAN DIEN")
    print("Nhan dang mot dap an:", valid)
    print("Bo trong:", blank)
    print("To nhieu dap an:", multiple)
    print("Can kiem tra:", uncertain)

    print("\nDa luu:")
    print(csv_path.resolve())
    print(json_path.resolve())
    print(debug_path.resolve())


# ==========================================
# CHUONG TRINH CHINH
# ==========================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--image",
        default="output/bai_kiem_tra_01_aligned.png",
        help="Anh bai lam da can chinh"
    )

    args = parser.parse_args()

    try:

        detect_part1(Path(args.image))

    except Exception as error:

        print("\nLOI:", error)
