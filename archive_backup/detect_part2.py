
import cv2
import json
import csv
import numpy as np

from pathlib import Path
from datetime import datetime

# ==========================================
# CAU HINH
# ==========================================

TEMPLATE_PATH = Path("output/answer_sheet_master.png")
COORDINATE_PATH = Path("output/part2_coordinates.json")

DEFAULT_STUDENT_IMAGE = Path(
    "output/bai_kiem_tra_01_aligned.png"
)

OUTPUT_DIR = Path("output")

CHOICES = ["true", "false"]
ROWS = ["a", "b", "c", "d"]

# Nguong thu nghiem tren phieu photocopy
FILL_THRESHOLD = 70
REVIEW_THRESHOLD = 58

BUBBLE_RADIUS = 5


# ==========================================
# DOC DO TOI TAI TAM O TRON
# ==========================================

def get_center_value(gray, x, y):

    x = int(round(x))
    y = int(round(y))

    radius = BUBBLE_RADIUS

    x1 = x - radius
    y1 = y - radius
    x2 = x + radius + 1
    y2 = y + radius + 1

    if (
        x1 < 0 or y1 < 0
        or x2 > gray.shape[1]
        or y2 > gray.shape[0]
    ):
        raise ValueError(
            f"Toa do nam ngoai anh: ({x}, {y})"
        )

    roi = gray[y1:y2, x1:x2]

    yy, xx = np.ogrid[
        -radius:radius + 1,
        -radius:radius + 1
    ]

    mask = xx**2 + yy**2 <= radius**2

    return float(np.median(roi[mask]))


# ==========================================
# NHAN DIEN PHAN II
# ==========================================

def detect_part2(image_path):

    # Doc anh bai lam da can chinh
    student = cv2.imread(str(image_path))

    if student is None:
        raise FileNotFoundError(
            f"Khong doc duoc anh bai lam: {image_path}"
        )

    # Doc anh phieu mau trang
    template = cv2.imread(str(TEMPLATE_PATH))

    if template is None:
        raise FileNotFoundError(
            "Khong tim thay anh phieu mau."
        )

    # Kiem tra kich thuoc
    if student.shape[:2] != template.shape[:2]:
        raise ValueError(
            "Kich thuoc anh khong khop phieu mau. "
            "Hay can chinh lai truoc."
        )

    # Doc file toa do
    with open(
        COORDINATE_PATH,
        "r",
        encoding="utf-8"
    ) as f:
        coordinate_data = json.load(f)

    questions = coordinate_data.get("questions", [])

    if len(questions) != 8:
        raise ValueError(
            f"Can 8 cau, hien co {len(questions)} cau."
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

    debug = student.copy()

    results = []

    print("\nKET QUA NHAN DIEN PHAN II")
    print("=" * 65)

    # ======================================
    # DOC 8 CAU X 4 Y
    # ======================================

    for question in questions:

        q_number = question["question"]

        for row_label in ROWS:

            row_data = question["rows"][row_label]

            scores = {}

            # Doc hai o DUNG va SAI
            for choice in CHOICES:

                x, y = row_data[choice]

                reference_value = get_center_value(
                    template_gray, x, y
                )

                student_value = get_center_value(
                    student_gray, x, y
                )

                # So sanh voi phieu mau
                score = reference_value - student_value

                scores[choice] = round(
                    max(0, score), 1
                )

            true_score = scores["true"]
            false_score = scores["false"]


            
            # ==================================
            # PHAN LOAI DUNG / SAI
            # ==================================

            true_score = scores["true"]
            false_score = scores["false"]

            if (
                true_score >= FILL_THRESHOLD
                and false_score >= FILL_THRESHOLD
            ):
                answer = "MULTIPLE"
                status = "MULTIPLE_MARKS"

            elif (
                true_score >= FILL_THRESHOLD
                and false_score < REVIEW_THRESHOLD
            ):
                answer = "DUNG"
                status = "VALID"

            elif (
                false_score >= FILL_THRESHOLD
                and true_score < REVIEW_THRESHOLD
            ):
                answer = "SAI"
                status = "VALID"

            elif max(true_score, false_score) >= REVIEW_THRESHOLD:
                answer = "REVIEW"
                status = "UNCERTAIN"

            else:
                answer = ""
                status = "BLANK"


            # ==================================
            # LUU KET QUA
            # ==================================

            results.append({
                "question": q_number,
                "statement": row_label,
                "answer": answer,
                "status": status,
                "true_score": true_score,
                "false_score": false_score
            })

            print(
                f"Cau {q_number:02d} - {row_label}: "
                f"{answer if answer else 'BO TRONG':10s} "
                f"| Dung={true_score:5.1f} "
                f"Sai={false_score:5.1f}"
            )

            # ==================================
            # VE KET QUA LEN ANH
            # ==================================

            for choice in CHOICES:

                x, y = row_data[choice]

                x = int(round(x))
                y = int(round(y))

                score = scores[choice]

                if score >= FILL_THRESHOLD:
                    color = (0, 0, 255)

                elif score >= REVIEW_THRESHOLD:
                    color = (0, 165, 255)

                else:
                    color = (150, 150, 150)

                cv2.circle(
                    debug,
                    (x, y),
                    9,
                    color,
                    2
                )

            # Ghi ket qua ben phai o Sai
            false_x, false_y = row_data["false"]

            display_answer = (
                answer if answer else "-"
            )

            cv2.putText(
                debug,
                display_answer,
                (int(false_x) + 12, int(false_y) + 4),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.35,
                (255, 0, 0),
                1
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

    # ======================================
    # LUU FILE KET QUA
    # Tao ten rieng de tranh ghi de CSV dang mo
    # ======================================

    OUTPUT_DIR.mkdir(exist_ok=True)

    stem = Path(image_path).stem

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    csv_path = OUTPUT_DIR / (
        f"{stem}_part2_{timestamp}.csv"
    )

    json_path = OUTPUT_DIR / (
        f"{stem}_part2_{timestamp}.json"
    )

    debug_path = OUTPUT_DIR / (
        f"{stem}_part2_debug_{timestamp}.png"
    )

    # Luu CSV
    with open(
        csv_path,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        writer = csv.writer(f)

        writer.writerow([
            "Cau",
            "Y",
            "Dap an",
            "Trang thai",
            "Diem Dung",
            "Diem Sai"
        ])

        for item in results:

            writer.writerow([
                item["question"],
                item["statement"],
                item["answer"],
                item["status"],
                item["true_score"],
                item["false_score"]
            ])

    # Luu JSON
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

    # Luu anh kiem tra
    cv2.imwrite(
        str(debug_path),
        debug
    )

    print("\n" + "=" * 65)
    print("THONG KE NHAN DIEN PHAN II")

    print("Nhan dang mot lua chon:", valid)
    print("Bo trong:", blank)
    print("To ca hai:", multiple)
    print("Can kiem tra:", uncertain)

    print("\nDA LUU KET QUA:")
    print(csv_path.resolve())
    print(json_path.resolve())
    print(debug_path.resolve())


# ==========================================
# CHUONG TRINH CHINH
# ==========================================

if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--image",
        default=str(DEFAULT_STUDENT_IMAGE),
        help="Anh bai lam da can chinh"
    )

    args = parser.parse_args()

    try:

        detect_part2(Path(args.image))

    except Exception as error:

        print("\nLOI:", error)
