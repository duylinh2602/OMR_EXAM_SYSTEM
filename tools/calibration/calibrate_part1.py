
import cv2
import json
import numpy as np
from pathlib import Path
import config

# ==========================================
# CAU HINH
# ==========================================

IMAGE_PATH = Path("output/answer_sheet_master.png")
OUTPUT_DIR = Path("output")

# Lay 4 toa do cau 1 da hieu chuan
FIRST_QUESTION = getattr(
    config,
    "PART1_Q1_POINTS",
    getattr(config, "ANSWER_POINTS", None)
)

if FIRST_QUESTION is None or len(FIRST_QUESTION) != 4:
    raise ValueError(
        "Config.py phai co PART1_Q1_POINTS hoac ANSWER_POINTS gom 4 toa do."
    )

FIRST_QUESTION = [
    tuple(map(float, point))
    for point in FIRST_QUESTION
]

# 13 diem can click them
LABELS = [
    "Cau 11 - A", "Cau 11 - B",
    "Cau 11 - C", "Cau 11 - D",

    "Cau 21 - A", "Cau 21 - B",
    "Cau 21 - C", "Cau 21 - D",

    "Cau 31 - A", "Cau 31 - B",
    "Cau 31 - C", "Cau 31 - D",

    "Cau 10 - A"
]

CHOICES = ["A", "B", "C", "D"]

# ==========================================
# DOC ANH
# ==========================================

image = cv2.imread(str(IMAGE_PATH))

if image is None:
    raise FileNotFoundError(
        f"Khong tim thay anh: {IMAGE_PATH}"
    )

height, width = image.shape[:2]

# Thu nho anh vua man hinh
scale = min(
    1050 / width,
    760 / height,
    1.0
)

display_width = int(width * scale)
display_height = int(height * scale)

scale_x = display_width / width
scale_y = display_height / height

display_image = cv2.resize(
    image,
    (display_width, display_height),
    interpolation=cv2.INTER_AREA
)

# Danh sach 13 diem vua click
clicked_points = []

window_name = "HIEU CHUAN 40 CAU PHAN I"

# Ve 4 diem cau 1 da co san
for i, (x, y) in enumerate(FIRST_QUESTION):

    px = int(round(x * scale_x))
    py = int(round(y * scale_y))

    cv2.circle(
        display_image, (px, py), 6,
        (255, 0, 0), 2
    )

    cv2.putText(
        display_image,
        f"1{CHOICES[i]}",
        (px + 7, py - 5),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.4,
        (255, 0, 0),
        1
    )


def mouse_callback(event, x, y, flags, param):

    if event != cv2.EVENT_LBUTTONDOWN:
        return

    if len(clicked_points) >= len(LABELS):
        print("Da chon du 13 diem.")
        return

    # Chuyen toa do man hinh ve toa do anh goc
    original_x = int(round(x / scale_x))
    original_y = int(round(y / scale_y))

    clicked_points.append(
        (original_x, original_y)
    )

    index = len(clicked_points)
    label = LABELS[index - 1]

    cv2.circle(
        display_image,
        (x, y),
        6,
        (0, 255, 0),
        2
    )

    cv2.putText(
        display_image,
        str(index),
        (x + 7, y - 5),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (0, 0, 255),
        1
    )

    cv2.imshow(window_name, display_image)

    print(
        f"{index}/13 - {label}: "
        f"x={original_x}, y={original_y}"
    )

    if index < len(LABELS):
        print("Tiep theo:", LABELS[index])


# ==========================================
# HUONG DAN VA HIEU CHUAN
# ==========================================

print("====================================")
print("HIEU CHUAN 40 CAU PHAN I")
print("====================================")
print("4 diem cua cau 1 da duoc nap san.")
print("Hay click vao TAM cac o tron theo thu tu:")
for i, label in enumerate(LABELS, start=1):
    print(f"{i}. {label}")

print("\nSau khi chon du 13 diem, nhan phim S de luu.")
print("Nhan ESC neu muon huy.")

cv2.namedWindow(
    window_name,
    cv2.WINDOW_NORMAL
)

cv2.resizeWindow(
    window_name,
    display_width,
    display_height
)

cv2.setMouseCallback(
    window_name,
    mouse_callback
)

while True:

    cv2.imshow(window_name, display_image)

    key = cv2.waitKey(20) & 0xFF

    if key == 27:
        print("Da huy hieu chuan.")
        break

    if key == ord("s"):

        if len(clicked_points) != len(LABELS):
            print(
                f"Chua du diem: "
                f"{len(clicked_points)}/13"
            )
            continue

        # ==================================
        # TINH KHOANG CACH CAC HANG
        # ==================================

        groups = [
            FIRST_QUESTION,
            clicked_points[0:4],
            clicked_points[4:8],
            clicked_points[8:12]
        ]

        y_starts = [
            float(np.mean([p[1] for p in group]))
            for group in groups
        ]

        # Cau 10 la hang thu 10 cua khoi dau
        y_step = (
            clicked_points[12][1] - y_starts[0]
        ) / 9

        if y_step <= 0:
            print("LOI: Khoang cach hang khong hop le.")
            continue

        # ==================================
        # TAO TOA DO 160 O
        # ==================================

        questions = []

        for block_index, group in enumerate(groups):

            x_positions = [
                float(point[0])
                for point in group
            ]

            for row in range(10):

                question_number = (
                    block_index * 10 + row + 1
                )

                y = y_starts[block_index] + row * y_step

                choices = {}

                for choice_index, choice in enumerate(CHOICES):

                    choices[choice] = [
                        round(x_positions[choice_index], 2),
                        round(y, 2)
                    ]

                questions.append({
                    "question": question_number,
                    "choices": choices
                })

        result = {
            "template": "answer_sheet_v1",
            "template_width": width,
            "template_height": height,
            "row_step": round(y_step, 3),
            "questions": questions
        }

        OUTPUT_DIR.mkdir(exist_ok=True)

        json_path = OUTPUT_DIR / "part1_coordinates.json"

        with open(json_path, "w", encoding="utf-8") as file:
            json.dump(
                result,
                file,
                ensure_ascii=False,
                indent=4
            )

        # ==================================
        # VE KIEM TRA 160 TOA DO
        # ==================================

        preview = image.copy()

        for question in questions:

            q = question["question"]

            for choice, point in question["choices"].items():

                x, y = map(int, point)

                cv2.circle(
                    preview,
                    (x, y),
                    7,
                    (0, 180, 0),
                    2
                )

                cv2.putText(
                    preview,
                    str(q),
                    (x + 7, y - 5),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.3,
                    (0, 0, 255),
                    1
                )

        preview_path = OUTPUT_DIR / "part1_calibration_preview.png"

        cv2.imwrite(
            str(preview_path),
            preview
        )

        print("\nHIEU CHUAN THANH CONG!")
        print("So cau:", len(questions))
        print("So o dap an:", len(questions) * 4)
        print("Khoang cach hang:", round(y_step, 2))
        print("File toa do:", json_path.resolve())
        print("Anh kiem tra:", preview_path.resolve())

        break

cv2.destroyAllWindows()
