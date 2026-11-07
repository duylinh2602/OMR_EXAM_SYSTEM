
import cv2
import json
from pathlib import Path

# ==========================================
# CAU HINH
# ==========================================

IMAGE_PATH = Path("output/answer_sheet_master.png")
OUTPUT_DIR = Path("output")

QUESTION_COUNT = 6
DIGITS = list(range(10))
DIGIT_COLUMNS = 4

# ==========================================
# TAO DANH SACH 28 DIEM CLICK
# ==========================================

CLICK_LABELS = [
    "Cau 1 - Chu so 0 - Cot 1",
    "Cau 1 - Chu so 0 - Cot 2",
    "Cau 1 - Chu so 0 - Cot 3",
    "Cau 1 - Chu so 0 - Cot 4",

    "Cau 1 - Chu so 9 - Cot 1",

    "Cau 1 - Dau am",
    "Cau 1 - Dau phay vi tri 1",
    "Cau 1 - Dau phay vi tri 2",
]

for q in range(2, 7):
    for col in range(1, 5):
        CLICK_LABELS.append(
            f"Cau {q} - Chu so 0 - Cot {col}"
        )

# ==========================================
# DOC ANH PHIEU MAU
# ==========================================

image = cv2.imread(str(IMAGE_PATH))

if image is None:
    raise FileNotFoundError(
        f"Khong tim thay anh: {IMAGE_PATH}"
    )

height, width = image.shape[:2]

# Thu nho anh vua man hinh
scale = min(
    760 / height,
    1100 / width,
    1.0
)

display_width = int(width * scale)
display_height = int(height * scale)

scale_x = display_width / width
scale_y = display_height / height

display_original = cv2.resize(
    image,
    (display_width, display_height),
    interpolation=cv2.INTER_AREA
)

display_image = display_original.copy()

points = []

WINDOW_NAME = "HIEU CHUAN PHAN III"

# ==========================================
# VE CAC DIEM DA CHON
# ==========================================

def redraw():

    global display_image

    display_image = display_original.copy()

    for index, (x, y) in enumerate(points):

        px = int(round(x * scale_x))
        py = int(round(y * scale_y))

        cv2.circle(
            display_image,
            (px, py),
            5,
            (0, 255, 0),
            2
        )

        cv2.putText(
            display_image,
            str(index + 1),
            (px + 5, py - 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (0, 0, 255),
            1
        )

    cv2.imshow(WINDOW_NAME, display_image)


# ==========================================
# CLICK CHUOT
# ==========================================

def mouse_callback(event, x, y, flags, param):

    if event != cv2.EVENT_LBUTTONDOWN:
        return

    if len(points) >= len(CLICK_LABELS):
        print("Da chon du 28 diem.")
        return

    original_x = int(round(x / scale_x))
    original_y = int(round(y / scale_y))

    points.append((original_x, original_y))

    index = len(points) - 1

    print(
        f"{index + 1}/28 - "
        f"{CLICK_LABELS[index]}: "
        f"x={original_x}, y={original_y}"
    )

    redraw()

    if len(points) < len(CLICK_LABELS):
        print(
            "Tiep theo:",
            CLICK_LABELS[len(points)]
        )
    else:
        print("\nDA CHON DU 28 DIEM!")
        print("Nhan S de luu toa do.")


# ==========================================
# KIEM TRA VA TAO TOA DO
# ==========================================

def save_calibration():

    if len(points) != 28:
        print("Chua chon du 28 diem.")
        return

    # Toa do hang chu so 0 va 9 cua cau 1
    row_zero = points[0][1]
    row_nine = points[4][1]

    row_step = (row_nine - row_zero) / 9

    if not (12 <= row_step <= 80):
        raise ValueError(
            "Khoang cach hang khong hop le."
        )

    # Dau am va dau phay
    sign_y = points[5][1]

    comma_y1 = points[6][1]
    comma_y2 = points[7][1]

    if abs(comma_y1 - comma_y2) > 12:
        raise ValueError(
            "Hai diem dau phay khong cung hang."
        )

    comma_y = (comma_y1 + comma_y2) / 2

    # Lay 4 toa do cot chu so cua 6 cau
    x_groups = []

    # Cau 1
    x_groups.append([
        points[i][0]
        for i in range(4)
    ])

    # Cau 2 den cau 6
    index = 8

    for q in range(2, 7):

        xs = [
            points[index + i][0]
            for i in range(4)
        ]

        index += 4

        x_groups.append(xs)

    # Kiem tra cac cot tang dan
    for q, xs in enumerate(x_groups, start=1):

        if not all(
            xs[i] < xs[i + 1]
            for i in range(3)
        ):
            raise ValueError(
                f"Toa do cot chu so cau {q} khong hop le."
            )

    # Kiem tra vi tri dau am va dau phay
    ref_xs = x_groups[0]

    if abs(points[5][0] - ref_xs[0]) > 20:
        raise ValueError(
            "Vi tri dau am khong dung cot 1."
        )

    if abs(points[6][0] - ref_xs[1]) > 20:
        raise ValueError(
            "Dau phay vi tri 1 khong dung."
        )

    if abs(points[7][0] - ref_xs[2]) > 20:
        raise ValueError(
            "Dau phay vi tri 2 khong dung."
        )

    # ======================================
    # SINH TOA DO 6 CAU
    # ======================================

    questions = []

    for q in range(QUESTION_COUNT):

        xs = x_groups[q]

        question_data = {
            "question": q + 1,

            "sign": [
                round(float(xs[0]), 2),
                round(float(sign_y), 2)
            ],

            "comma_positions": [
                [
                    round(float(xs[1]), 2),
                    round(float(comma_y), 2)
                ],
                [
                    round(float(xs[2]), 2),
                    round(float(comma_y), 2)
                ]
            ],

            "digits": {}
        }

        for digit in DIGITS:

            y = row_zero + digit * row_step

            question_data["digits"][str(digit)] = [
                [
                    round(float(x), 2),
                    round(float(y), 2)
                ]
                for x in xs
            ]

        questions.append(question_data)

    result = {
        "template": "answer_sheet_v1",
        "template_width": width,
        "template_height": height,
        "row_step": round(row_step, 3),
        "questions": questions
    }

    # ======================================
    # LUU JSON
    # ======================================

    OUTPUT_DIR.mkdir(exist_ok=True)

    json_path = OUTPUT_DIR / "part3_coordinates.json"

    with open(
        json_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            result,
            f,
            ensure_ascii=False,
            indent=4
        )

    # ======================================
    # VE ANH KIEM TRA
    # ======================================

    preview = image.copy()

    for question in questions:

        # Dau am - xanh duong
        x, y = question["sign"]

        cv2.circle(
            preview,
            (int(x), int(y)),
            8,
            (255, 0, 0),
            2
        )

        # Dau phay - mau vang
        for x, y in question["comma_positions"]:

            cv2.circle(
                preview,
                (int(x), int(y)),
                8,
                (0, 165, 255),
                2
            )

        # 40 o chu so cua moi cau - xanh la
        for digit, positions in question["digits"].items():

            for x, y in positions:

                cv2.circle(
                    preview,
                    (int(x), int(y)),
                    7,
                    (0, 180, 0),
                    2
                )

    preview_path = (
        OUTPUT_DIR / "part3_calibration_preview.png"
    )

    cv2.imwrite(
        str(preview_path),
        preview
    )

    print("\n================================")
    print("HIEU CHUAN PHAN III THANH CONG!")
    print("So cau:", len(questions))
    print("So o chu so:", 240)
    print("So dau am:", 6)
    print("So vi tri dau phay:", 12)
    print("Khoang cach hang:", round(row_step, 2))
    print("File toa do:", json_path.resolve())
    print("Anh kiem tra:", preview_path.resolve())
    print("================================")


# ==========================================
# CHUONG TRINH CHINH
# ==========================================

print("HIEU CHUAN PHAN III")
print("--------------------------------")

for i, label in enumerate(CLICK_LABELS, start=1):
    print(f"{i}. {label}")

print("\nClick vao TAM cac o tron.")
print("S: Luu toa do khi da chon du 28 diem.")
print("Backspace: Xoa diem vua chon.")
print("ESC: Huy.")

cv2.namedWindow(
    WINDOW_NAME,
    cv2.WINDOW_NORMAL
)

cv2.resizeWindow(
    WINDOW_NAME,
    display_width,
    display_height
)

cv2.setMouseCallback(
    WINDOW_NAME,
    mouse_callback
)

while True:

    cv2.imshow(WINDOW_NAME, display_image)

    key = cv2.waitKey(20) & 0xFF

    if key == 27:
        print("Da huy.")
        break

    elif key in (8, 127):

        if points:
            removed = points.pop()
            print("Da xoa diem:", removed)
            redraw()

    elif key == ord("s"):

        try:
            save_calibration()
            break

        except Exception as error:
            print("LOI:", error)

cv2.destroyAllWindows()
