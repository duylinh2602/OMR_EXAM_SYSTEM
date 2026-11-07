# OMR EXAM SYSTEM 2026 - TASK TRACKER

## ĐÃ HOÀN THÀNH (STABLE)
- [x] Lõi nắn phẳng đa tầng: 4 dải (scan phẳng) & 4 mốc góc OMR (mobile).
- [x] Tự động phát hiện góc xoay (0°, 90°, 180°, 270°) và xoay thẳng đứng.
- [x] Quy chuẩn tem bút đỏ: Đúng = Xanh lá, Sai = Đỏ, Bỏ trống = Vàng hổ phách.
- [x] Tối ưu hóa dung lượng lưu trữ: JPEG Quality 90 + WebP (giảm 96% dung lượng đĩa).
- [x] Khử dấu tiếng Việt trong HTTP Header, sửa triệt để lỗi HTTP 500 khi xuất file.
- [x] Xuất PDF nhiều trang bằng PyMuPDF (fitz) tiết kiệm RAM, chống khóa file.
- [x] Xuất Excel bảng điểm an toàn, bắt ngoại lệ PermissionError.
- [x] Hộp thoại Save As chọn nơi lưu tệp cho PDF và Excel.
- [x] Loại bỏ ký tự Unicode lạ tránh lỗi charmap trên Windows .exe.

## BACKLOG TIẾP THEO (GIAI ĐOẠN 2 & 3)
- [x] Task 1: Tích hợp `quality_gate.py` vào luồng `_process_and_save` trong `app.py` (cảnh báo ảnh nhòe, rung tay hoặc lóa sáng trước khi nắn mốc).
- [ ] Task 2: Chuyển đổi nhãn điểm trên tem bút đỏ từ cố định "/ 10" sang thang điểm OMR động theo cấu hình thực tế của từng đề thi.
- [ ] Task 3: Bổ sung trường nhập điểm Tự luận thủ công ở Cột 2 và tính tổng điểm toàn bài (OMR + Tự luận).