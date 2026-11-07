
import fitz
from pathlib import Path

# Tim file PDF mau trong thu muc du an
pdf_files = list(Path(".").glob("*.pdf"))

if not pdf_files:
    print("LOI: Khong tim thay file PDF mau!")
else:
    pdf_path = pdf_files[0]
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    print("Dang doc file:", pdf_path.name)

    # Mo file PDF
    document = fitz.open(pdf_path)

    # Chi xu ly trang dau tien
    page = document[0]

    # Tang do phan giai anh len 3 lan
    matrix = fitz.Matrix(3, 3)

    # Chuyen trang PDF thanh anh
    pixmap = page.get_pixmap(
        matrix=matrix,
        alpha=False
    )

    # Luu anh PNG
    output_path = output_dir / "answer_sheet_master.png"
    pixmap.save(output_path)

    print("--------------------------------")
    print("CHUYEN DOI THANH CONG!")
    print("So trang PDF:", len(document))
    print("Kich thuoc anh:", pixmap.width, "x", pixmap.height)
    print("Anh duoc luu tai:", output_path.resolve())
    print("--------------------------------")

    document.close()
