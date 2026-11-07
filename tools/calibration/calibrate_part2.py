
import cv2
import json
from pathlib import Path

# ==========================================
# CAU HINH
# ==========================================

IMAGE_PATH = Path("output/answer_sheet_master.png")
OUTPUT_DIR = Path("output")

ROWS = ["a", "b", "c", "d"]

# Tao danh sach 17 diem can click
CLICK_LABELS = [
    "Cau 1 - y a - DUNG",
    "Cau 1 - y a - SAI",
    "Cau 1 - y d - DUNG",
]

for q in range(2, 9):
    CLICK_LABELS.extend([
        f"Cau {q} - y a - DUNG",
        f"Cau {q} - y a - SAI",
    ])

# ==========================================
# DOC ANH PHIEU MAU
# ==========================================

image = cv2.imread(str(IMAGE_PATH))

if image is None:
    raise FileNotFoundError(
        f"Khong tim thay anh: {IMAGE_PATH}"
    )

height, width = image.shape[:2]

# Tu dong thu nho anh vua cua so
screen_width = 1100
screen_height = 800

scale = min(
    screen_width / width,
    screen_height / height,
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

original_display = display_image.copy()

points = []

WINDOW_NAME = "HIEU CHUAN PHAN II"


# ==========================================
# VE CAC DIEM DA CHON
# ==========================================

def redraw():

    global display_image

    display_image = original_display.copy()

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
# XU LY CLICK CHUOT
# ==========================================

def mouse_callback(event, x, y, flags, param):

    if event != cv2.EVENT_LBUTTONDOWN:
        return

    if len(points) >= len(CLICK_LABELS):
        print("Da chon du 17 diem.")
        return

    # Chuyen toa do hien thi ve toa do anh goc
    original_x = int(round(x / scale_x))
    original_y = int(round(y / scale_y))

    points.append((original_x, original_y))

    index = len(points) - 1

    print(
        f"{index + 1}/17 - "
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
        print("\nDA CHON DU 17 DIEM!")
        print("Nhan S de luu toa do.")


# ==========================================
# TAO 64 TOA DO
# ==========================================

def generate_coordinates():

    # Hai diem dau la True va False cua y a cau 1
    q1_true = points[0]
    q1_false = points[1]

    # Diem thu ba la True cua y d cau 1
    q1_last = points[2]

    # Tinh toa do trung binh hang a
    q1_y = (q1_true[1] + q1_false[1]) / 2

    # Khoang cach giua cac hang
    row_step = (q1_last[1] - q1_y) / 3

    if not (10 <= row_step <= 150):
        raise ValueError(
            "Khoang cach hang khong hop le. "
            "Hay kiem tra lai diem cau 1."
        )

    questions = []

    # Cau 1
    anchors = {
        1: {
            "true_x": q1_true[0],
            "false_x": q1_false[0],
            "start_y": q1_y
        }
    }

    # Cau 2 den cau 8
    index = 3

    for q in range(2, 9):

        true_point = points[index]
        false_point = points[index + 1]

        index += 2

        if abs(true_point[1] - false_point[1]) > 12:
            raise ValueError(
                f"Hai diem Dung/Sai cau {q} "
                "khong cung hang. Hay hieu chuan lai."
            )

        anchors[q] = {
            "true_x": true_point[0],
            "false_x": false_point[0],
            "start_y": (
                true_point[1] + false_point[1]
            ) / 2
        }

    # Sinh 8 cau x 4 y x 2 lua chon = 64 o
    for q in range(1, 9):

        anchor = anchors[q]

        question_data = {
            "question": q,
            "rows": {}
        }

        for row_index, row_label in enumerate(ROWS):

            y = (
                anchor["start_y"]
                + row_index * row_step
            )

            question_data["rows"][row_label] = {
                "true": [
                    round(float(anchor["true_x"]), 2),
                    round(float(y), 2)
                ],
                "false": [
                    round(float(anchor["false_x"]), 2),
                    round(float(y), 2)
                ]
            }

        questions.append(question_data)

    return questions, row_step


# ==========================================
# LUU TOA DO VA ANH KIEM TRA
# ==========================================

def save_calibration():

    if len(points) != 17:
        print("Chua chon du 17 diem.")
        return

    questions, row_step = generate_coordinates()

    result = {
        "template": "answer_sheet_v1",
        "template_width": width,
        "template_height": height,
        "row_step": round(row_step, 3),
        "questions": questions
    }

    OUTPUT_DIR.mkdir(exist_ok=True)

    json_path = OUTPUT_DIR / "part2_coordinates.json"

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

    # Ve 64 vi tri len anh mau
    preview = image.copy()

    for question in questions:

        q = question["question"]

        for row_label in ROWS:

            row = question["rows"][row_label]

            for choice in ["true", "false"]:

                x, y = row[choice]

                x = int(round(x))
                y = int(round(y))

                cv2.circle(
                    preview,
                    (x, y),
                    9,
                    (0, 180, 0),
                    2
                )

                label = (
                    str(q) + row_label
                    + ("T" if choice == "true" else "S")
                )

                cv2.putText(
                    preview,
                    label,
                    (x + 8, y - 4),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.25,
                    (0, 0, 255),
                    1
                )

    preview_path = (
        OUTPUT_DIR / "part2_calibration_preview.png"
    )

    cv2.imwrite(
        str(preview_path),
        preview
    )

    print("\n================================")
    print("HIEU CHUAN PHAN II THANH CONG!")
    print("So cau:", len(questions))
    print("So o:", len(questions) * 4 * 2)
    print("Khoang cach hang:", round(row_step, 2))
    print("File toa do:", json_path.resolve())
    print("Anh kiem tra:", preview_path.resolve())
    print("================================")


# ==========================================
# CHUONG TRINH CHINH
# ==========================================

print("HUONG DAN HIEU CHUAN PHAN II")
print("--------------------------------")

for i, label in enumerate(CLICK_LABELS, start=1):
    print(f"{i}. {label}")

print("\nClick dung TAM cac o tron.")
print("S: Luu khi da chon du 17 diem.")
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
        print("Da huy hieu chuan.")
        break

    if key == ord("s"):

        try:
            save_calibration()
            break

        except Exception as error:
            print("LOI:", error)

cv2.destroyAllWindows()
