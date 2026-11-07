
import argparse
from pathlib import Path

import cv2
import numpy as np

# ==========================================
# CAU HINH
# ==========================================

TEMPLATE_PATH = Path("output/answer_sheet_master.png")
OUTPUT_DIR = Path("output")


# ==========================================
# DOC ANH JPG, PNG HOAC PDF
# ==========================================

def load_image(path):

    if not path.exists():
        raise FileNotFoundError(
            f"Khong tim thay file: {path}"
        )

    if path.suffix.lower() == ".pdf":

        import fitz

        with fitz.open(path) as document:

            if len(document) == 0:
                raise ValueError("PDF khong co trang.")

            page = document[0]

            pix = page.get_pixmap(
                matrix=fitz.Matrix(3, 3),
                alpha=False
            )

            rgb = np.frombuffer(
                pix.samples,
                dtype=np.uint8
            ).reshape(
                pix.height,
                pix.width,
                pix.n
            )

            return cv2.cvtColor(
                rgb,
                cv2.COLOR_RGB2BGR
            )

    image = cv2.imread(str(path))

    if image is None:
        raise ValueError("Khong doc duoc anh.")

    return image


# ==========================================
# TIM 4 O VUONG DEN TAI 4 GOC PHIEU
# ==========================================


def find_corner_markers(image):

    height, width = image.shape[:2]

    # 1. Chuyen anh sang anh xam
    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )

    # 2. Tang do tuong phan cho anh photocopy nhat
    clahe = cv2.createCLAHE(
        clipLimit=2.5,
        tileGridSize=(8, 8)
    )

    enhanced = clahe.apply(gray)

    # 3. Nhi phan hoa thich nghi
    # Khong phu thuoc vao mot nguong do den co dinh
    block_size = int(min(width, height) * 0.025)

    if block_size % 2 == 0:
        block_size += 1

    block_size = max(31, min(block_size, 151))

    binary = cv2.adaptiveThreshold(
        enhanced,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        block_size,
        7
    )

    # 4. Noi cac diem muc bi dut do photocopy
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (3, 3)
    )

    binary = cv2.morphologyEx(
        binary,
        cv2.MORPH_CLOSE,
        kernel
    )

    # Luu anh nhi phan de kiem tra
    cv2.imwrite(
        "output/marker_threshold_debug.png",
        binary
    )

    # 5. Tim cac vung lien thong
    contours, _ = cv2.findContours(
        binary,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    candidates = []

    for contour in contours:

        area = cv2.contourArea(contour)

        x, y, w, h = cv2.boundingRect(contour)

        if w <= 0 or h <= 0:
            continue

        ratio = w / h
        fill_ratio = area / (w * h)
        area_ratio = area / (width * height)

        # Loc cac vung gan hinh vuong
        if not (0.55 <= ratio <= 1.55):
            continue

        # Chap nhan ca o photocopy nhat
        if fill_ratio < 0.35:
            continue

        # Kich thuoc tuong doi cua o dinh vi
        if not (0.00001 <= area_ratio <= 0.002):
            continue

        if not (0.004 <= w / width <= 0.055):
            continue

        if not (0.003 <= h / height <= 0.045):
            continue

        cx = x + w / 2
        cy = y + h / 2

        candidates.append((cx, cy, w, h))

    # 6. Vi tri mong doi cua 4 goc
    expected = {
        "TL": (0.032, 0.018),
        "TR": (0.973, 0.018),
        "BR": (0.973, 0.970),
        "BL": (0.032, 0.970)
    }

    # Gioi han vung tim kiem
    zones = {
        "TL": lambda x, y:
            x < 0.20 * width and y < 0.15 * height,

        "TR": lambda x, y:
            x > 0.80 * width and y < 0.15 * height,

        "BR": lambda x, y:
            x > 0.80 * width and y > 0.85 * height,

        "BL": lambda x, y:
            x < 0.20 * width and y > 0.85 * height
    }

    result = []

    # 7. Tim diem tot nhat o tung goc
    for name in ["TL", "TR", "BR", "BL"]:

        ex, ey = expected[name]

        options = [
            p for p in candidates
            if zones[name](p[0], p[1])
        ]

        if not options:
            raise ValueError(
                f"Khong tim thay diem dinh vi {name}. "
                "Kiem tra anh marker_threshold_debug.png"
            )

        best = min(
            options,
            key=lambda p:
                (p[0] / width - ex) ** 2
                + (p[1] / height - ey) ** 2
        )

        result.append((best[0], best[1]))

    return np.asarray(result, dtype=np.float32)



# ==========================================
# CAN CHINH PHIEU
# ==========================================

def align_sheet(input_path):

    # Doc anh mau chuan
    template = load_image(TEMPLATE_PATH)

    # Doc anh bai lam
    source = load_image(input_path)

    template_h, template_w = template.shape[:2]

    # Tim 4 diem goc tren anh bai lam
    source_points = find_corner_markers(source)

    # Tim 4 diem goc tren mau chuan
    target_points = find_corner_markers(template)

    names = ["TL", "TR", "BR", "BL"]

    print("\nTOA DO 4 DIEM GOC:")

    for name, point in zip(names, source_points):

        print(
            f"{name}: "
            f"x={point[0]:.1f}, "
            f"y={point[1]:.1f}"
        )

    # Tinh ma tran bien doi phoi canh
    matrix = cv2.getPerspectiveTransform(
        source_points,
        target_points
    )

    # Dua anh ve dung kich thuoc mau chuan
    aligned = cv2.warpPerspective(
        source,
        matrix,
        (template_w, template_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255)
    )

    OUTPUT_DIR.mkdir(exist_ok=True)

    # Luu anh da can chinh
    output_path = OUTPUT_DIR / f"{input_path.stem}_aligned.png"

    cv2.imwrite(
        str(output_path),
        aligned
    )

    # Luu anh danh dau 4 diem tren anh nguon
    debug = source.copy()

    for name, point in zip(names, source_points):

        x, y = map(
            int,
            np.round(point)
        )

        cv2.circle(
            debug,
            (x, y),
            12,
            (0, 0, 255),
            3
        )

        cv2.putText(
            debug,
            name,
            (x + 12, y - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2
        )

    debug_path = OUTPUT_DIR / f"{input_path.stem}_debug.png"

    cv2.imwrite(
        str(debug_path),
        debug
    )

    print("\n================================")
    print("CAN CHINH PHIEU THANH CONG!")
    print("Kich thuoc:", template_w, "x", template_h)
    print("Anh da can chinh:", output_path.resolve())
    print("Anh kiem tra:", debug_path.resolve())
    print("================================")


# ==========================================
# CHUONG TRINH CHINH
# ==========================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "input",
        nargs="?",
        default=str(TEMPLATE_PATH),
        help="Duong dan anh hoac PDF bai lam"
    )

    args = parser.parse_args()

    try:

        align_sheet(Path(args.input))

    except Exception as error:

        print("\nLOI:", error)
