import cv2
import json
import csv
import numpy as np

from pathlib import Path
from datetime import datetime

# =========================================================
# CAU HINH PHAN III
# =========================================================

TEMPLATE_PATH = Path("output/answer_sheet_master.png")
COORDINATE_PATH = Path("output/part3_coordinates.json")
DEFAULT_IMAGE = Path("output/bai_kiem_tra_01_aligned.png")
OUTPUT_DIR = Path("output")

# Nguong moi: diem duoc tinh tu high-pass + tam o da tinh chinh.
# Khong dung lai nguong 90/65 cua phien ban cu.
FILL_THRESHOLD = 16
REVIEW_THRESHOLD = 10
DIGIT_MARGIN = 10

# Kich thuoc hinh hoc tren anh xem thu nghiem 1434 px rong.
# Anh trong du an duoc chuan hoa ve 1769 px rong, nen tu dong scale.
REFERENCE_PREVIEW_WIDTH = 1434.0

# Ban kinh cua vong tron va vung loi, tinh theo scale anh.
CORE_RADIUS_BASE = 3.0
RING_INNER_BASE = 7.2
RING_OUTER_BASE = 10.8
CENTER_SEARCH_BASE = 8.0
ILLUMINATION_SIGMA_BASE = 18.0

CHOICES = list(range(10))


# =========================================================
# TAO BAN DO GRADIENT DE TIM LAI TAM O TRON
# =========================================================

def build_gradient_response(gray, scale):
    """Tao phan hoi vien tron tu gradient, giam anh huong bong nen."""
    smoothed = cv2.GaussianBlur(
        gray,
        (0, 0),
        sigmaX=max(0.8, 1.0 * scale),
        sigmaY=max(0.8, 1.0 * scale)
    )

    gx = cv2.Sobel(smoothed, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(smoothed, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(gx, gy)

    ring_inner = RING_INNER_BASE * scale
    ring_outer = RING_OUTER_BASE * scale
    radius = int(np.ceil(ring_outer))

    yy, xx = np.ogrid[-radius:radius + 1, -radius:radius + 1]
    distance = np.sqrt(xx * xx + yy * yy)

    ring_mask = (
        (distance >= ring_inner)
        & (distance <= ring_outer)
    ).astype(np.float32)

    total = float(ring_mask.sum())
    if total <= 0:
        raise ValueError("Khong tao duoc mat na vong tron.")

    kernel = ring_mask / total

    response = cv2.filter2D(
        magnitude,
        cv2.CV_32F,
        kernel,
        borderType=cv2.BORDER_REFLECT
    )

    return response


def refine_center(response, x, y, scale):
    """
    Tim lai tam o tron quanh toa do hieu chuan.
    Dung do manh gradient tren vong vien, khong dung do toi o loi.
    """
    x = int(round(x))
    y = int(round(y))
    search = int(round(CENTER_SEARCH_BASE * scale))

    h, w = response.shape

    x1 = max(0, x - search)
    x2 = min(w, x + search + 1)
    y1 = max(0, y - search)
    y2 = min(h, y + search + 1)

    patch = response[y1:y2, x1:x2]

    yy, xx = np.mgrid[y1:y2, x1:x2]

    # Uu tien tam gan toa do chuan neu hai vi tri co gradient gan nhau.
    distance_penalty = 0.4 * np.sqrt(
        (xx - x) ** 2 + (yy - y) ** 2
    )

    adjusted = patch - distance_penalty

    iy, ix = np.unravel_index(
        np.argmax(adjusted),
        adjusted.shape
    )

    return int(x1 + ix), int(y1 + iy)


# =========================================================
# BU SANG NEN VA DO MUC TO O LOI
# =========================================================

def build_ink_map(gray, scale):
    """
    Gaussian blur uoc luong nen sang thay doi cham.
    Nen - anh goc tao ban do muc toi cuc bo:
    - bong dien thoai dien rong duoc giam anh huong;
    - vet but trong loi o tao gia tri duong ro hon.
    """
    sigma = ILLUMINATION_SIGMA_BASE * scale

    background = cv2.GaussianBlur(
        gray,
        (0, 0),
        sigmaX=sigma,
        sigmaY=sigma,
        borderType=cv2.BORDER_REFLECT
    )

    ink_map = (
        background.astype(np.float32)
        - gray.astype(np.float32)
    )

    return ink_map


def disk_mean(ink_map, x, y, radius):
    x = int(x)
    y = int(y)
    r = max(1, int(round(radius)))

    h, w = ink_map.shape

    if (
        x - r < 0 or y - r < 0
        or x + r >= w or y + r >= h
    ):
        raise ValueError(
            f"Vung do vuot ngoai anh tai ({x}, {y})."
        )

    yy, xx = np.ogrid[-r:r + 1, -r:r + 1]
    mask = xx * xx + yy * yy <= r * r

    patch = ink_map[
        y - r:y + r + 1,
        x - r:x + r + 1
    ]

    return float(np.mean(patch[mask]))


def get_score(
    student_ink,
    template_ink,
    student_response,
    template_response,
    position,
    scale
):
    """
    Diem = muc toi cuc bo tren bai hoc sinh
           - muc toi cuc bo tren phieu mau.

    Truoc khi do, tu dong tinh chinh tam o tren anh hoc sinh va anh mau.
    """
    x, y = position

    student_center = refine_center(
        student_response, x, y, scale
    )

    template_center = refine_center(
        template_response, x, y, scale
    )

    radius = CORE_RADIUS_BASE * scale

    student_value = disk_mean(
        student_ink,
        student_center[0],
        student_center[1],
        radius
    )

    template_value = disk_mean(
        template_ink,
        template_center[0],
        template_center[1],
        radius
    )

    score = student_value - template_value

    return (
        round(float(score), 1),
        student_center,
        template_center
    )


# =========================================================
# PHAN LOAI
# =========================================================

def classify_single(score):
    if score >= FILL_THRESHOLD:
        return "MARKED"
    if score >= REVIEW_THRESHOLD:
        return "REVIEW"
    return "BLANK"


def classify_comma(scores):
    marked = [
        index for index, score in enumerate(scores)
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


def classify_digit(scores):
    ranked = sorted(
        enumerate(scores),
        key=lambda item: item[1],
        reverse=True
    )

    top_digit, top_score = ranked[0]
    second_score = ranked[1][1]

    marked = [
        digit for digit, score in enumerate(scores)
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


# =========================================================
# NHAN DIEN PHAN III
# =========================================================

def detect_part3(image_path):
    student = cv2.imread(str(image_path))
    if student is None:
        raise FileNotFoundError(
            f"Khong doc duoc anh bai lam: {image_path}"
        )

    template = cv2.imread(str(TEMPLATE_PATH))
    if template is None:
        raise FileNotFoundError(
            f"Khong doc duoc anh mau: {TEMPLATE_PATH}"
        )

    if student.shape[:2] != template.shape[:2]:
        raise ValueError(
            "Kich thuoc anh bai lam khong khop anh mau. "
            "Hay chay align_sheet.py truoc."
        )

    with open(COORDINATE_PATH, "r", encoding="utf-8") as f:
        coordinate_data = json.load(f)

    questions = coordinate_data.get("questions", [])
    if len(questions) != 6:
        raise ValueError(
            f"Can 6 cau, hien co {len(questions)} cau."
        )

    # Anh mau du an rong 1769 px; anh trong tin nhan co the duoc
    # nen xuong 1434 px. Scale nay giu dung kich thuoc hinh hoc.
    scale = student.shape[1] / REFERENCE_PREVIEW_WIDTH

    student_gray = cv2.cvtColor(student, cv2.COLOR_BGR2GRAY)
    template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

    # Ban do muc toi sau bu sang
    student_ink = build_ink_map(student_gray, scale)
    template_ink = build_ink_map(template_gray, scale)

    # Ban do gradient de tu can tam cac vong tron
    student_response = build_gradient_response(student_gray, scale)
    template_response = build_gradient_response(template_gray, scale)

    debug = student.copy()
    results = []

    print("\nKET QUA NHAN DIEN PHAN III - BU SANG + TU CAN TAM")
    print("=" * 76)
    print(
        f"Scale={scale:.3f} | Fill={FILL_THRESHOLD} | "
        f"Review={REVIEW_THRESHOLD}"
    )

    for question in questions:
        q_number = question["question"]

        # -------------------------------------------------
        # DAU AM
        # -------------------------------------------------
        sign_score, sign_center, _ = get_score(
            student_ink,
            template_ink,
            student_response,
            template_response,
            question["sign"],
            scale
        )

        sign_status = classify_single(sign_score)
        sign = "-" if sign_status == "MARKED" else ""

        # -------------------------------------------------
        # DAU PHAY
        # -------------------------------------------------
        comma_scores = []
        comma_centers = []

        for position in question["comma_positions"]:
            score, center, _ = get_score(
                student_ink,
                template_ink,
                student_response,
                template_response,
                position,
                scale
            )
            comma_scores.append(score)
            comma_centers.append(center)

        comma_result = classify_comma(comma_scores)

        # -------------------------------------------------
        # BON COT CHU SO
        # -------------------------------------------------
        digit_columns = []
        digit_scores_all = []
        digit_centers_all = []

        for column in range(4):
            scores = []
            centers = []

            for digit in range(10):
                position = question["digits"][str(digit)][column]

                score, center, _ = get_score(
                    student_ink,
                    template_ink,
                    student_response,
                    template_response,
                    position,
                    scale
                )

                scores.append(score)
                centers.append(center)

            digit_columns.append(classify_digit(scores))
            digit_scores_all.append(scores)
            digit_centers_all.append(centers)

        # -------------------------------------------------
        # TRANG THAI
        # -------------------------------------------------
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

        raw_digits = "".join(
            d if d not in ("", "REVIEW", "MULTIPLE") else "_"
            for d in digit_columns
        )

        if has_multiple:
            status = "MULTIPLE_MARKS"
        elif has_review:
            status = "UNCERTAIN"
        elif not digit_values and sign_status != "MARKED" and not comma_result:
            status = "BLANK"
        elif not digit_values:
            status = "UNCERTAIN"
        else:
            status = "VALID"

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
            "digit_scores": digit_scores_all,
            "status": status
        }

        results.append(result)

        print(
            f"Cau {q_number}: {sign}{raw_digits} "
            f"| Dau phay={comma_result or 'KHONG'} "
            f"| {status}"
        )

        # -------------------------------------------------
        # VE ANH KIEM TRA
        # -------------------------------------------------
        def draw_point(center, color, radius):
            cv2.circle(
                debug,
                (int(center[0]), int(center[1])),
                radius,
                color,
                2
            )

        sign_color = (
            (0, 0, 255) if sign_status == "MARKED"
            else (0, 165, 255) if sign_status == "REVIEW"
            else (150, 150, 150)
        )
        draw_point(sign_center, sign_color, max(6, int(9 * scale)))

        for index, center in enumerate(comma_centers):
            score = comma_scores[index]
            color = (
                (0, 0, 255) if score >= FILL_THRESHOLD
                else (0, 165, 255) if score >= REVIEW_THRESHOLD
                else (150, 150, 150)
            )
            draw_point(center, color, max(6, int(8 * scale)))

        for column in range(4):
            for digit in range(10):
                score = digit_scores_all[column][digit]
                center = digit_centers_all[column][digit]

                color = (
                    (0, 0, 255) if score >= FILL_THRESHOLD
                    else (0, 165, 255) if score >= REVIEW_THRESHOLD
                    else (150, 150, 150)
                )

                draw_point(
                    center,
                    color,
                    max(5, int(7 * scale))
                )

    # =====================================================
    # THONG KE
    # =====================================================
    valid = sum(r["status"] == "VALID" for r in results)
    blank = sum(r["status"] == "BLANK" for r in results)
    multiple = sum(r["status"] == "MULTIPLE_MARKS" for r in results)
    uncertain = sum(r["status"] == "UNCERTAIN" for r in results)

    # =====================================================
    # LUU KET QUA - TEN FILE CO DONG HO
    # =====================================================
    OUTPUT_DIR.mkdir(exist_ok=True)

    stem = Path(image_path).stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    csv_path = OUTPUT_DIR / f"{stem}_part3_shadowfix_{timestamp}.csv"
    json_path = OUTPUT_DIR / f"{stem}_part3_shadowfix_{timestamp}.json"
    debug_path = OUTPUT_DIR / f"{stem}_part3_shadowfix_debug_{timestamp}.png"

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(results[0].keys())
        )
        writer.writeheader()
        writer.writerows(results)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=4)

    cv2.imwrite(str(debug_path), debug)

    print("\n" + "=" * 76)
    print("THONG KE PHAN III")
    print("Nhan dang hop le:", valid)
    print("Bo trong:", blank)
    print("To nhieu o:", multiple)
    print("Can kiem tra:", uncertain)

    print("\nDA LUU:")
    print(csv_path.resolve())
    print(json_path.resolve())
    print(debug_path.resolve())


# =========================================================
# CHUONG TRINH CHINH
# =========================================================

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
