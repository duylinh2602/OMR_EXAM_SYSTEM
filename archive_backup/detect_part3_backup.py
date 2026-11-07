
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
COORDINATE_PATH = Path("output/part3_coordinates.json")

DEFAULT_IMAGE = Path(
    "output/bai_kiem_tra_01_aligned.png"
)

OUTPUT_DIR = Path("output")

# Nguong thu nghiem
FILL_THRESHOLD = 90
REVIEW_THRESHOLD = 65

# Nguong chenh lech giua hai chu so
DIGIT_MARGIN = 25

BUBBLE_RADIUS = 5


# ==========================================
# DOC DO TOI TAI TAM O TRON
# ==========================================

def get_center_value(gray, x, y):

    x = int(round(x))
    y = int(round(y))

    r = BUBBLE_RADIUS

    x1 = x - r
    y1 = y - r
    x2 = x + r + 1
    y2 = y + r + 1

    if (
        x1 < 0 or y1 < 0
        or x2 > gray.shape[1]
        or y2 > gray.shape[0]
    ):
        raise ValueError(
            f"Toa do ngoai anh: ({x}, {y})"
        )

    roi = gray[y1:y2, x1:x2]

    yy, xx = np.ogrid[-r:r+1, -r:r+1]

    mask = xx**2 + yy**2 <= r**2

    return float(np.median(roi[mask]))


def get_score(student_gray, template_gray, position):

    x, y = position

    reference = get_center_value(
        template_gray, x, y
    )

    student = get_center_value(
        student_gray, x, y
    )

    return round(
        max(0, reference - student),
        1
    )


# ==========================================
# PHAN LOAI MOT O NHI PHAN
# ==========================================

def classify_single(score):

    if score >= FILL_THRESHOLD:
        return "MARKED"

    elif score >= REVIEW_THRESHOLD:
        return "REVIEW"

    return "BLANK"


# ==========================================
# NHAN DIEN HAI O DAU PHAY
# ==========================================

def classify_comma(scores):

    marked = [
        i for i, score in enumerate(scores)
        if score >= FILL_THRESHOLD
    ]

    if len(marked) >= 2:
        return "MULTIPLE"

    if len(marked) == 1:

        other = 1 - marked[0]

        if scores[other] < REVIEW_THRESHOLD:
            return str(marked[0] + 1)

        return "REVIEW"

    if max(scores) >= REVIEW_THRESHOLD:
        return "REVIEW"

    return ""


# ==========================================
# NHAN DIEN 10 CHU SO TRONG MOT COT
# ==========================================

def classify_digit(scores):

    ranked = sorted(
        enumerate(scores),
        key=lambda item: item[1],
        reverse=True
    )

    top_digit, top_score = ranked[0]

    second_digit, second_score = ranked[1]

    # Kiem tra nhieu chu so duoc to
    marked = [
        digit
        for digit, score in enumerate(scores)
        if score >= FILL_THRESHOLD
    ]

    if len(marked) > 1:
        return "MULTIPLE"

    margin = top_score - second_score

    if (
        top_score >= FILL_THRESHOLD
        and margin >= DIGIT_MARGIN
    ):
        return str(top_digit)

    if top_score >= REVIEW_THRESHOLD:
        return "REVIEW"

    return ""


# ==========================================
# NHAN DIEN PHAN III
# ==========================================

def detect_part3(image_path):

    # Doc anh hoc sinh
    student = cv2.imread(str(image_path))

    if student is None:
        raise FileNotFoundError(
            f"Khong doc duoc anh: {image_path}"
        )

    # Doc phieu mau
    template = cv2.imread(str(TEMPLATE_PATH))

    if template is None:
        raise FileNotFoundError(
            "Khong tim thay anh phieu mau."
        )

    if student.shape[:2] != template.shape[:2]:
        raise ValueError(
            "Kich thuoc anh khong khop phieu mau."
        )

    # Doc toa do
    with open(
        COORDINATE_PATH,
        "r",
        encoding="utf-8"
    ) as f:

        coordinate_data = json.load(f)

    questions = coordinate_data.get("questions", [])

    if len(questions) != 6:
        raise ValueError(
            f"Can 6 cau, hien co {len(questions)} cau."
        )

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

    print("\nKET QUA NHAN DIEN PHAN III")
    print("=" * 70)

    # ======================================
    # XU LY TUNG CAU
    # ======================================

    for question in questions:

        q_number = question["question"]

        # ----------------------------------
        # DOC DAU AM
        # ----------------------------------

        sign_score = get_score(
            student_gray,
            template_gray,
            question["sign"]
        )

        sign_status = classify_single(
            sign_score
        )

        sign = ""

        if sign_status == "MARKED":
            sign = "-"

        # ----------------------------------
        # DOC DAU PHAY
        # ----------------------------------

        comma_scores = []

        for position in question["comma_positions"]:

            score = get_score(
                student_gray,
                template_gray,
                position
            )

            comma_scores.append(score)

        comma_result = classify_comma(
            comma_scores
        )

        # ----------------------------------
        # DOC 4 COT CHU SO
        # ----------------------------------

        digit_columns = []
        digit_scores_all = []

        for column in range(4):

            scores = []

            # Doc 10 chu so tu 0 den 9
            for digit in range(10):

                position = (
                    question["digits"][str(digit)][column]
                )

                score = get_score(
                    student_gray,
                    template_gray,
                    position
                )

                scores.append(score)

            digit_result = classify_digit(scores)

            digit_columns.append(digit_result)

            digit_scores_all.append(scores)

        # ----------------------------------
        # XAC DINH TRANG THAI CAU HOI
        # ----------------------------------

        has_multiple = (
            comma_result == "MULTIPLE"
            or "MULTIPLE" in digit_columns
        )

        has_review = (
            sign_status == "REVIEW"
            or comma_result == "REVIEW"
            or "REVIEW" in digit_columns
        )

        digit_values = [
            d for d in digit_columns
            if d not in ("", "REVIEW", "MULTIPLE")
        ]

        # Chuoi 4 cot, giu vi tri trong de kiem tra
        raw_digits = "".join(
            d if d not in ("", "REVIEW", "MULTIPLE") else "_"
            for d in digit_columns
        )

        has_digit_error = (
            "REVIEW" in digit_columns
            or "MULTIPLE" in digit_columns
        )

        if has_multiple:

            status = "MULTIPLE_MARKS"

        elif has_review:

            status = "UNCERTAIN"

        elif not digit_values:

            status = "BLANK"

        else:

            status = "VALID"

        # Chua tu dong chen dau phay vao so
        # De tranh dien giai sai vi tri dau phay
        result = {
            "question": q_number,
            "sign": sign,
            "sign_status": sign_status,
            "sign_score": sign_score,
            "comma_option": comma_result,
            "comma_scores": comma_scores,
            "digit_1": digit_columns[0],
            "digit_2": digit_columns[1],
            "digit_3": digit_columns[2],
            "digit_4": digit_columns[3],
            "raw_digits": raw_digits,
            "status": status
        }

        results.append(result)

        print(
            f"Cau {q_number}: "
            f"{sign}{raw_digits} "
            f"| Dau phay={comma_result or 'KHONG'} "
            f"| {status}"
        )

        # ==================================
        # VE KET QUA LEN ANH
        # ==================================

        # Ve dau am
        sx, sy = map(
            int,
            map(round, question["sign"])
        )

        sign_color = (
            (0, 0, 255)
            if sign_status == "MARKED"
            else (0, 165, 255)
            if sign_status == "REVIEW"
            else (150, 150, 150)
        )

        cv2.circle(
            debug,
            (sx, sy),
            9,
            sign_color,
            2
        )

        # Ve dau phay
        for index, position in enumerate(
            question["comma_positions"]
        ):

            x, y = map(
                int,
                map(round, position)
            )

            score = comma_scores[index]

            color = (
                (0, 0, 255)
                if score >= FILL_THRESHOLD
                else (0, 165, 255)
                if score >= REVIEW_THRESHOLD
                else (150, 150, 150)
            )

            cv2.circle(
                debug,
                (x, y),
                8,
                color,
                2
            )

        # Ve 240 o chu so
        for column in range(4):

            for digit in range(10):

                position = (
                    question["digits"][str(digit)][column]
                )

                x, y = map(
                    int,
                    map(round, position)
                )

                score = digit_scores_all[column][digit]

                if score >= FILL_THRESHOLD:
                    color = (0, 0, 255)

                elif score >= REVIEW_THRESHOLD:
                    color = (0, 165, 255)

                else:
                    color = (150, 150, 150)

                cv2.circle(
                    debug,
                    (x, y),
                    7,
                    color,
                    2
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
    # LUU KET QUA
    # ======================================

    OUTPUT_DIR.mkdir(exist_ok=True)

    stem = Path(image_path).stem

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    csv_path = OUTPUT_DIR / (
        f"{stem}_part3_{timestamp}.csv"
    )

    json_path = OUTPUT_DIR / (
        f"{stem}_part3_{timestamp}.json"
    )

    debug_path = OUTPUT_DIR / (
        f"{stem}_part3_debug_{timestamp}.png"
    )

    # Luu CSV
    with open(
        csv_path,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=list(results[0].keys())
        )

        writer.writeheader()
        writer.writerows(results)

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

    # Luu anh debug
    cv2.imwrite(
        str(debug_path),
        debug
    )

    print("\n" + "=" * 70)
    print("THONG KE PHAN III")
    print("Nhan dang hop le:", valid)
    print("Bo trong:", blank)
    print("To nhieu o:", multiple)
    print("Can kiem tra:", uncertain)

    print("\nDA LUU:")
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
        default=str(DEFAULT_IMAGE),
        help="Anh bai lam da can chinh"
    )

    args = parser.parse_args()

    try:

        detect_part3(Path(args.image))

    except Exception as error:

        print("\nLOI:", error)
