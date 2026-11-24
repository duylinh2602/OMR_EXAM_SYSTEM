import cv2, json, sys, os, time, asyncio
from pathlib import Path
import numpy as np
from fastapi import HTTPException, UploadFile
import io

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from align_sheet_v2 import align_sheet_4band, verify_aligned_omr_template
from full_grading_pipeline import FullGradingPipeline
import app as omr_app

print("=" * 60)
print("TEST 1: CHỐNG CHẤM NHẦM ẢNH RÁC (NOT_OMR_SHEET)")
print("=" * 60)

# Tạo ảnh đen rác
black_img_path = Path("scratch/fake_black.jpg")
black_img = np.zeros((1000, 800, 3), dtype=np.uint8)
cv2.imwrite(str(black_img_path), black_img)

out_aligned = Path("scratch/fake_aligned.jpg")

threw_expected_error = False
try:
    align_sheet_4band(black_img_path, out_aligned)
except RuntimeError as e:
    if "NOT_OMR_SHEET" in str(e) or "ALIGNMENT_FAILED" in str(e):
        threw_expected_error = True
        print(f"[PASS] align_sheet_4band đã từ chối ảnh đen thành công: {e}")
    else:
        print(f"[FAIL] Ném lỗi nhưng không đúng thông điệp: {e}")
except Exception as e:
    print(f"[FAIL] Lỗi không mong đợi: {e}")

assert threw_expected_error, "align_sheet_4band PHẢI ném NOT_OMR_SHEET hoặc ALIGNMENT_FAILED khi gặp ảnh rác!"

# Test gọi _process_and_save với ảnh rác
exam = omr_app.get_current_exam()
threw_http_error = False
try:
    omr_app._process_and_save(black_img, "fake_black.jpg", "testsub1", exam)
except HTTPException as he:
    if he.status_code == 422:
        threw_http_error = True
        print(f"[PASS] _process_and_save đã ném HTTPException(status_code=422): {he.detail}")
    else:
        print(f"[FAIL] HTTPException với mã khác: {he.status_code}")
except Exception as e:
    print(f"[FAIL] Ngoại lệ không mong muốn: {e}")

assert threw_http_error, "_process_and_save PHẢI ném HTTPException(422) khi gặp ảnh rác!"

# Kiểm tra DB xem có bị lưu bản ghi rác không
assert "testsub1" not in exam.get("submissions", {}), "DB không được chứa bản ghi rác testsub1!"
print("[PASS] exams_db.json tuyệt đối không bị ô nhiễm bởi ảnh rác!")

print("\n" + "=" * 60)
print("TEST 2: KIỂM TRA CHẤM ĐÚNG ĐIỂM BÀI MẪU PHẦN III & SBD")
print("=" * 60)

mock_exam_data = {
    'exam_name': 'Kiểm tra Sinh học 11B',
    'answer_keys': {
        '0503': {
            'part1': {},
            'part2': {},
            'part3': {'1': 2134.0, '2': 3124.0, '3': 10.0, '4': 6.0}
        },
        '0504': {
            'part1': {},
            'part2': {},
            'part3': {'1': 6.0, '2': 2134.0, '3': 10.0, '4': 3124.0}
        }
    },
    'config': {'pts_p1': 0.25, 'pts_p2_rule': '0.1,0.25,0.5,1.0', 'pts_p3': 0.25}
}

pipeline = FullGradingPipeline(exam_data=mock_exam_data)

# Test Bài 3 (0503)
img_bai3 = cv2.imread('output/web_uploads/300ab73a_aligned.png')
res_bai3 = pipeline.process_sheet(img_bai3, file_name='bai3.png')
print("Bai 3 - Ma de:", res_bai3.get("exam_code"))
assert res_bai3.get("exam_code") == "0503", "Mã đề bài 3 phải là 0503!"
p3_b3 = res_bai3.get("details", {}).get("part3", {})
print("Bai 3 - P3 Q1:", p3_b3.get(1, {}).get("raw_string"), p3_b3.get(1, {}).get("normalized_value"))
print("Bai 3 - P3 Q2:", p3_b3.get(2, {}).get("raw_string"), p3_b3.get(2, {}).get("normalized_value"))
print("Bai 3 - P3 Q3:", p3_b3.get(3, {}).get("raw_string"), p3_b3.get(3, {}).get("normalized_value"))
print("Bai 3 - P3 Q4:", p3_b3.get(4, {}).get("raw_string"), p3_b3.get(4, {}).get("normalized_value"))
assert p3_b3.get(1, {}).get("normalized_value") == 2134.0, "Câu 1 Bài 3 phải là 2134.0!"
assert p3_b3.get(3, {}).get("normalized_value") == 10.0, "Câu 3 Bài 3 phải là 10.0!"
assert res_bai3.get("scores", {}).get("p3") == 1.0, "Điểm Phần III Bài 3 phải đạt 1.0 điểm!"
print("[PASS] Bài 3 chấm đúng 4/4 câu Phần III (1.00d)!")

# Test Bài 5 (0504)
img_bai5 = cv2.imread('output/web_uploads/307f437e_aligned.png')
res_bai5 = pipeline.process_sheet(img_bai5, file_name='bai5.png')
print("Bai 5 - Ma de:", res_bai5.get("exam_code"))
assert res_bai5.get("exam_code") == "0504", "Mã đề bài 5 phải là 0504!"
p3_b5 = res_bai5.get("details", {}).get("part3", {})
print("Bai 5 - P3 Q1:", p3_b5.get(1, {}).get("raw_string"), p3_b5.get(1, {}).get("normalized_value"))
print("Bai 5 - P3 Q2:", p3_b5.get(2, {}).get("raw_string"), p3_b5.get(2, {}).get("normalized_value"))
print("Bai 5 - P3 Q3:", p3_b5.get(3, {}).get("raw_string"), p3_b5.get(3, {}).get("normalized_value"))
print("Bai 5 - P3 Q4:", p3_b5.get(4, {}).get("raw_string"), p3_b5.get(4, {}).get("normalized_value"))
assert p3_b5.get(2, {}).get("normalized_value") == 2134.0, "Câu 2 Bài 5 phải là 2134.0!"
assert p3_b5.get(3, {}).get("normalized_value") == 10.0, "Câu 3 Bài 5 phải là 10.0!"
assert res_bai5.get("scores", {}).get("p3") == 1.0, "Điểm Phần III Bài 5 phải đạt 1.0 điểm!"
print("[PASS] Bài 5 chấm đúng 4/4 câu Phần III (1.00d)!")

print("\n" + "=" * 60)
print("TEST 3: KIỂM TRA CÁC ROUTE API")
print("=" * 60)

async def test_apis():
    # Test API switch-exam
    all_exams = list(omr_app.DB_DATA.get("exams", {}).keys())
    if all_exams:
        target_id = all_exams[0]
        resp_sw = await omr_app.switch_exam(target_id)
        assert resp_sw.get("status") == "SUCCESS", f"switch-exam failed: {resp_sw}"
        print(f"[PASS] POST /api/switch-exam/{target_id} thành công!")

        # Test API bí danh select-exam
        resp_sel = await omr_app.select_exam(target_id)
        assert resp_sel.get("status") == "SUCCESS", f"select-exam failed: {resp_sel}"
        print(f"[PASS] POST /api/select-exam/{target_id} thành công!")

    # Test API smart-paste
    smart_payload = omr_app.SmartPasteRequest(
        text='''Mã đề: 0503
Phần 1:
1.A 2.B 3.C 4.D
Phần 2:
1. a Đ, b S, c Đ, d S
Phần 3:
1. 2134
2. 3124
3. 10
4. 6''',
        default_made="0503"
    )

    resp_paste = await omr_app.smart_paste_answer_key(smart_payload)
    assert resp_paste.get("status") == "SUCCESS", f"smart-paste failed: {resp_paste}"
    print(f"[PASS] POST /api/smart-paste-answer-key thành công, codes: {resp_paste.get('codes_loaded')}")

asyncio.run(test_apis())

print("\n" + "=" * 60)
print("TẤT CẢ CÁC BÀI KIỂM TRA ĐỀU PASS 100%!")
print("=" * 60)
