
import cv2
from pathlib import Path

# Anh phieu mau
IMAGE_PATH = Path("output") / "answer_sheet_master.png"

# Doc anh
image = cv2.imread(str(IMAGE_PATH))

if image is None:
    print("LOI: Khong tim thay anh phieu mau!")
    exit()

# Hien thi anh
display_image = image.copy()

print("HUONG DAN:")
print("1. Click chuot vao tam o dap an A cua cau 1")
print("2. Click chuot vao tam o dap an B cua cau 1")
print("3. Click chuot vao tam o dap an C cua cau 1")
print("4. Click chuot vao tam o dap an D cua cau 1")
print("5. Nhan phim ESC de ket thuc")

points = []


def mouse_callback(event, x, y, flags, param):
    if event == cv2.EVENT_LBUTTONDOWN:
        points.append((x, y))

        cv2.circle(
            display_image,
            (x, y),
            8,
            (0, 255, 0),
            -1
        )

        cv2.putText(
            display_image,
            str(len(points)),
            (x + 10, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),
            2
        )

        print(f"Diem {len(points)}: x={x}, y={y}")

        # Thu nho anh de vua man hinh

# Thu nho anh de vua man hinh
screen_width = 1000
screen_height = 700

h, w = image.shape[:2]

scale = min(
    screen_width / w,
    screen_height / h,
    1.0
)

small_image = cv2.resize(
    image,
    None,
    fx=scale,
    fy=scale,
    interpolation=cv2.INTER_AREA
)

# Hien thi anh voi cua so co the thay doi kich thuoc
cv2.namedWindow(
    "HIEU CHINH TOA DO",
    cv2.WINDOW_NORMAL
)

cv2.imshow("HIEU CHINH TOA DO", small_image)

cv2.resizeWindow(
    "HIEU CHINH TOA DO",
    screen_width,
    screen_height
)



cv2.namedWindow("HIEU CHINH TOA DO")
cv2.setMouseCallback("HIEU CHINH TOA DO", mouse_callback)

while True:
    cv2.imshow("HIEU CHINH TOA DO", display_image)

    key = cv2.waitKey(1) & 0xFF

    if key == 27:  # ESC
        break

cv2.destroyAllWindows()

print("\nTOA DO CAC DIEM DA CHON:")
print(points)
