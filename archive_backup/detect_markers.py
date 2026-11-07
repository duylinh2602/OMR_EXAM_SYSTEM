
import cv2
from pathlib import Path

# Duong dan anh phieu mau
IMAGE_PATH = Path("output") / "answer_sheet_master.png"
OUTPUT_DIR = Path("output")


def detect_markers():
    image = cv2.imread(str(IMAGE_PATH))

    if image is None:
        print("LOI: Khong doc duoc anh phieu mau!")
        return

    # Chuyen sang anh xam
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Nhi phan hoa
    _, binary = cv2.threshold(
        gray, 70, 255, cv2.THRESH_BINARY_INV
    )

    # Tim cac vung den
    contours, _ = cv2.findContours(
        binary,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    markers = []

    for contour in contours:
        area = cv2.contourArea(contour)

        if area < 100 or area > 3000:
            continue

        x, y, w, h = cv2.boundingRect(contour)

        ratio = w / h

        if not (0.75 <= ratio <= 1.25):
            continue

        rectangular_area = w * h
        fill_ratio = area / rectangular_area

        if fill_ratio < 0.65:
            continue

        markers.append((x, y, w, h))

    # Sap xep tu tren xuong duoi
    markers.sort(key=lambda item: (item[1], item[0]))

    print("TOA DO CAC DIEM DINH VI:")

    for index, (x, y, w, h) in enumerate(markers, start=1):
        center_x = x + w / 2
        center_y = y + h / 2

        print(
            f"Diem {index}: "
            f"x={center_x:.1f}, "
            f"y={center_y:.1f}, "
            f"w={w}, h={h}"
        )

    # Ve cac diem dinh vi len anh
    result = image.copy()

    for x, y, w, h in markers:
        cv2.rectangle(
            result,
            (x, y),
            (x + w, y + h),
            (0, 255, 0),
            3
        )

    OUTPUT_DIR.mkdir(exist_ok=True)

    output_path = OUTPUT_DIR / "detected_markers.png"
    cv2.imwrite(str(output_path), result)

    print("--------------------------------")
    print("NHAN DIEN DIEM DINH VI HOAN TAT")
    print("Tong so vung nghi la diem dinh vi:", len(markers))
    print("Anh ket qua:", output_path.resolve())
    print("--------------------------------")


if __name__ == "__main__":
    detect_markers()
