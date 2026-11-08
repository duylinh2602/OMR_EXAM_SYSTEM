# app.py
# -*- coding: utf-8 -*-
"""
FASTAPI WEB SERVER - OMR GRADING SYSTEM 2026 (PRODUCTION V6.9 - OPTIMIZED STORAGE & EXPORT)
Cập nhật:
- Lưu trữ nén thông minh: Chuyển đổi toàn bộ lưu trữ đĩa sang JPEG Quality 90 & WebP.
  Giảm 96% dung lượng ổ cứng (từ ~29MB/bài xuống còn ~1.1MB/bài).
- Tự động dọn dẹp file Raw sau khi đã nắn ảnh thành công.
- Tự động giới hạn kích thước ảnh đầu vào (max 2600px) để chống tràn RAM khi nạp ảnh camera lớn.
- Bổ sung hàm sanitize_ascii_filename: Triệt tiêu hoàn toàn lỗi HTTP 500 khi xuất Excel và PDF.
- Xuất PDF bằng PyMuPDF (fitz) tuần tự, không ngốn RAM.
"""
import os
import sys
import io
import json
import re
import time
import uuid
import unicodedata
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Cấu hình an toàn bảng mã console cho Windows .exe
if sys.platform == "win32":
    try:
        if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import cv2
import fitz  # PyMuPDF
import numpy as np
import openpyxl
from pydantic import BaseModel
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response

from align_sheet_v2 import CANONICAL_HEIGHT, CANONICAL_WIDTH, align_sheet_4band
from exam_manager import ExamManager
from full_grading_pipeline import FullGradingPipeline, normalize_answer_keys
from quality_gate import ImageQualityAssessment
from visual_stamper import VisualStamper

app = FastAPI(title="OMR Grading System 2026", version="6.9.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("output/web_uploads")
GRADED_DIR = Path("output/graded_sheets")
DB_FILE = Path("output/exams_db.json")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
GRADED_DIR.mkdir(parents=True, exist_ok=True)


def sanitize_ascii_filename(text: str, fallback: str = "FILE") -> str:
    """Khử 100% dấu tiếng Việt và ký tự đặc biệt cho tên file đính kèm HTTP Header."""
    if not text:
        return fallback
    nfkd = unicodedata.normalize('NFKD', str(text))
    ascii_text = nfkd.encode('ASCII', 'ignore').decode('ASCII')
    clean = re.sub(r'[^a-zA-Z0-9_\-\.]', '_', ascii_text)
    clean = re.sub(r'_+', '_', clean).strip('_')
    return clean if clean else fallback


# ==============================================================================
# 1. MODELS (PYDANTIC)
# ==============================================================================

class CreateExamRequest(BaseModel):
    subject: str
    period: str
    class_name: str
    school_year: str


class UpdateSubmissionRequest(BaseModel):
    submission_id: str
    sbd: str
    exam_code: str
    part1: Dict[str, str]
    part2: Dict[str, Dict[str, str]]
    part3: Dict[str, Optional[float]]


class SmartPasteRequest(BaseModel):
    text: str
    default_made: Optional[str] = "0001"


# ==============================================================================
# 2. DATABASE & SESSION MANAGEMENT (SINGLE SOURCE OF TRUTH)
# ==============================================================================

DB_DATA: Dict[str, Any] = {
    "active_exam_id": "default_exam",
    "exams": {
        "default_exam": {
            "id": "default_exam",
            "exam_info": {
                "subject": "Sinh học",
                "period": "Giữa kỳ I",
                "class_name": "11A",
                "school_year": "2026-2027",
                "is_configured": False
            },
            "exam_data": None,
            "submissions": {},
            "created_at": "05/11/2026 08:00"
        }
    }
}

if DB_FILE.exists():
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            disk_db = json.load(f)
            if "exams" in disk_db:
                DB_DATA = disk_db
            elif "exam_info" in disk_db:
                old_id = "exam_legacy"
                DB_DATA = {
                    "active_exam_id": old_id,
                    "exams": {
                        old_id: {
                            "id": old_id,
                            "exam_info": disk_db.get("exam_info", {}),
                            "exam_data": disk_db.get("exam_data"),
                            "submissions": disk_db.get("submissions", {}),
                            "created_at": "04/11/2026"
                        }
                    }
                }
    except Exception as e:
        print("[!] Lỗi nạp database:", e)


def get_current_exam() -> Dict[str, Any]:
    active_id = DB_DATA.get("active_exam_id", "default_exam")
    if active_id not in DB_DATA["exams"]:
        if DB_DATA["exams"]:
            active_id = list(DB_DATA["exams"].keys())[0]
            DB_DATA["active_exam_id"] = active_id
        else:
            new_id = f"exam_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            DB_DATA["exams"][new_id] = {
                "id": new_id,
                "exam_info": {
                    "subject": "Sinh học",
                    "period": "Giữa kỳ I",
                    "class_name": "11A",
                    "school_year": "2026-2027",
                    "is_configured": False
                },
                "exam_data": None,
                "submissions": {},
                "created_at": datetime.now().strftime("%d/%m/%Y %H:%M")
            }
            DB_DATA["active_exam_id"] = new_id
            active_id = new_id
    return DB_DATA["exams"][active_id]


def save_to_disk():
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(DB_DATA, f, ensure_ascii=False, indent=2)


def delete_submission_files(submission_id: str):
    """Xóa sạch các tệp ảnh liên quan của một bài làm (hỗ trợ cả định dạng .png và .jpg mới)."""
    extensions = [".png", ".jpg", ".jpeg", ".webp"]
    for ext in extensions:
        targets = [
            UPLOAD_DIR / f"{submission_id}_raw{ext}",
            UPLOAD_DIR / f"{submission_id}_aligned{ext}",
            GRADED_DIR / f"{submission_id}_graded{ext}",
            GRADED_DIR / f"{submission_id}_preview{ext}"
        ]
        for p in targets:
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass


current_exam = get_current_exam()
pipeline = FullGradingPipeline(exam_data=current_exam.get("exam_data"))


# ==============================================================================
# 3. ROUTE TÀI NGUYÊN GIAO DIỆN & QUẢN LÝ ĐỢT KIỂM TRA
# ==============================================================================

def get_template_content(template_name: str) -> str:
    candidates = [
        Path("templates") / template_name,
        Path(sys.executable).resolve().parent / "templates" / template_name if getattr(sys, 'frozen', False) else None,
        Path(getattr(sys, '_MEIPASS', '')) / "templates" / template_name if getattr(sys, 'frozen', False) else None,
        Path(sys.executable).resolve().parent / "_internal" / "templates" / template_name if getattr(sys, 'frozen', False) else None,
    ]
    for p in candidates:
        if p and p.exists() and p.is_file():
            return p.read_text(encoding="utf-8")
    return f"<h2>Không tìm thấy tệp giao diện: {template_name}</h2>"


@app.get("/", response_class=HTMLResponse)
async def serve_home():
    return HTMLResponse(content=get_template_content("index.html"))


@app.get("/scanner", response_class=HTMLResponse)
async def serve_mobile_scanner():
    return HTMLResponse(content=get_template_content("mobile_scanner.html"))


@app.get("/manifest.json")
async def get_manifest():
    content = get_template_content("manifest.json")
    return Response(content=content, media_type="application/manifest+json")


@app.get("/sw.js")
async def get_service_worker():
    content = get_template_content("sw.js")
    return Response(content=content, media_type="application/javascript")


@app.get("/icons/{icon_name}")
async def get_pwa_icon(icon_name: str):
    icon_path = Path("templates/icons") / icon_name
    if not icon_path.exists():
        raise HTTPException(status_code=404, detail="Icon not found")
    return FileResponse(str(icon_path), media_type="image/png")


@app.get("/api/session")
async def get_session():
    exam = get_current_exam()
    all_exams_summary = [
        {
            "id": eid,
            "title": f"{edata['exam_info']['subject']} - {edata['exam_info']['period']} ({edata['exam_info']['class_name']})",
            "submission_count": len(edata.get("submissions", {})),
            "created_at": edata.get("created_at", ""),
            "is_active": (eid == DB_DATA["active_exam_id"])
        }
        for eid, edata in DB_DATA["exams"].items()
    ]
    return {
        "active_exam_id": DB_DATA["active_exam_id"],
        "exam_info": exam.get("exam_info"),
        "exam_data": exam.get("exam_data"),
        "submissions": list(exam.get("submissions", {}).values()),
        "all_exams": all_exams_summary
    }


@app.post("/api/create-exam")
async def create_exam(payload: CreateExamRequest):
    global pipeline
    new_id = f"exam_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    new_exam = {
        "id": new_id,
        "exam_info": {
            "subject": payload.subject.strip(),
            "period": payload.period.strip(),
            "class_name": payload.class_name.strip(),
            "school_year": payload.school_year.strip(),
            "is_configured": False
        },
        "exam_data": None,
        "submissions": {},
        "created_at": datetime.now().strftime("%d/%m/%Y %H:%M")
    }

    DB_DATA["exams"][new_id] = new_exam
    DB_DATA["active_exam_id"] = new_id
    pipeline = FullGradingPipeline(exam_data=None)

    save_to_disk()
    return {"status": "SUCCESS", "active_exam_id": new_id, "exam_info": new_exam["exam_info"]}


@app.post("/api/switch-exam/{exam_id}")
async def switch_exam(exam_id: str):
    global pipeline
    if exam_id not in DB_DATA["exams"]:
        raise HTTPException(status_code=404, detail="Không tìm thấy đợt kiểm tra này")

    DB_DATA["active_exam_id"] = exam_id
    active_exam = DB_DATA["exams"][exam_id]
    pipeline = FullGradingPipeline(exam_data=active_exam.get("exam_data"))

    save_to_disk()
    return {
        "status": "SUCCESS",
        "active_exam_id": exam_id,
        "exam_info": active_exam["exam_info"],
        "submission_count": len(active_exam.get("submissions", {}))
    }


@app.delete("/api/delete-exam/{exam_id}")
async def delete_exam(exam_id: str):
    global pipeline
    if exam_id not in DB_DATA["exams"]:
        raise HTTPException(status_code=404, detail="Đợt kiểm tra không tồn tại")

    target_exam = DB_DATA["exams"][exam_id]
    for sub_id in list(target_exam.get("submissions", {}).keys()):
        delete_submission_files(sub_id)

    del DB_DATA["exams"][exam_id]

    if DB_DATA["active_exam_id"] == exam_id:
        if DB_DATA["exams"]:
            DB_DATA["active_exam_id"] = list(DB_DATA["exams"].keys())[0]
        else:
            new_id = f"exam_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            DB_DATA["exams"][new_id] = {
                "id": new_id,
                "exam_info": {
                    "subject": "Sinh học",
                    "period": "Giữa kỳ I",
                    "class_name": "11A",
                    "school_year": "2026-2027",
                    "is_configured": False
                },
                "exam_data": None,
                "submissions": {},
                "created_at": datetime.now().strftime("%d/%m/%Y %H:%M")
            }
            DB_DATA["active_exam_id"] = new_id

    active_exam = get_current_exam()
    pipeline = FullGradingPipeline(exam_data=active_exam.get("exam_data"))
    save_to_disk()

    return {
        "status": "SUCCESS",
        "active_exam_id": DB_DATA["active_exam_id"],
        "remaining_exams_count": len(DB_DATA["exams"])
    }


# ==============================================================================
# 4. ROUTE CHẤM THI TUẦN TỰ & TỐI ƯU HÓA KHÔNG GIAN LƯU TRỮ
# ==============================================================================

def _process_and_save(img_bgr: np.ndarray, file_name: str, sub_id: str, exam: Dict[str, Any]) -> Dict[str, Any]:
    """
    Hàm lõi chấm thi - Tối ưu hóa lưu trữ 96%:
    1. Giới hạn độ phân giải ảnh thô đầu vào nếu quá lớn (max 2600px).
    2. Tiền kiểm định chất lượng ảnh (Quality Gate) trước khi nắn mốc.
    3. Nắn phẳng phối cảnh đa tầng.
    4. Lưu ảnh nắn phẳng dạng JPEG Quality 92 (~450KB).
    5. Xóa tệp ảnh thô _raw sau khi đã nắn xong để tiết kiệm 100% dung lượng dư thừa.
    6. Lưu ảnh tem bút đỏ dạng JPEG Quality 90 (~480KB) và bản nén WebP Quality 80 (~180KB).
    """
    # 1. Giới hạn độ phân giải ảnh đầu vào nếu là ảnh chụp siêu lớn từ điện thoại
    h, w = img_bgr.shape[:2]
    max_dim = max(h, w)
    if max_dim > 2600:
        scale = 2600.0 / max_dim
        img_bgr = cv2.resize(img_bgr, (int(round(w * scale)), int(round(h * scale))), interpolation=cv2.INTER_AREA)

    # 2. Tiền kiểm định chất lượng ảnh (Quality Gate) trước khi nắn mốc
    is_valid, q_report = ImageQualityAssessment.evaluate(img_bgr)
    if not is_valid:
        reasons = q_report.get("reasons", ["Ảnh không đạt chuẩn chất lượng nhận diện."])
        reason_str = "; ".join(reasons)
        user_friendly_msg = f"Ảnh không đạt chuẩn kiểm định ({reason_str}). Vui lòng chụp lại rõ nét và đủ sáng."

        # Luôn lưu ảnh gốc vào GRADED_DIR để người dùng bấm xem lại được ngay ảnh vừa chụp
        graded_path = GRADED_DIR / f"{sub_id}_graded.jpg"
        cv2.imwrite(str(graded_path), img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
        preview_webp = GRADED_DIR / f"{sub_id}_preview.webp"
        cv2.imwrite(str(preview_webp), img_bgr, [cv2.IMWRITE_WEBP_QUALITY, 75])

        err_sub = {
            "submission_id": sub_id,
            "file_name": file_name,
            "sbd": "CHƯA RÕ",
            "exam_code": "CHƯA RÕ",
            "has_error": True,
            "status": "QUALITY_CHECK_FAILED",
            "error_msg": user_friendly_msg,
            "anomalies": [{"type": "QUALITY_ERROR", "msg": r} for r in reasons],
            "scores": {"status": "ERROR", "p1": 0.0, "p2": 0.0, "p3": 0.0, "total": 0.0},
            "details": {"part1": {}, "part2": {}, "part3": {}},
            "quality_metrics": q_report.get("metrics", {})
        }
        exam["submissions"][sub_id] = err_sub
        return err_sub

    temp_raw = UPLOAD_DIR / f"{sub_id}_raw.jpg"
    temp_aligned = UPLOAD_DIR / f"{sub_id}_aligned.jpg"
    
    # Ghi ảnh raw dạng JPEG chất lượng cao
    cv2.imwrite(str(temp_raw), img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])

    try:
        # Nắn ảnh và tự xoay 4 hướng
        align_sheet_4band(temp_raw, temp_aligned)
        target_img = cv2.imread(str(temp_aligned))

        if target_img is None:
            raise RuntimeError("ALIGNMENT_FAILED: Không thể đọc ảnh sau khi nắn phẳng.")

        # Xóa file raw sau khi nắn thành công để tiết kiệm dung lượng đĩa
        if temp_raw.exists():
            try:
                temp_raw.unlink()
            except Exception:
                pass

        # Chấm bài bằng lõi quang học Ink Map
        res = pipeline.process_sheet(target_img, file_name)
        res["submission_id"] = sub_id
        res["original_filename"] = file_name
        res["has_error"] = False
        res["quality_metrics"] = q_report.get("metrics", {})

        # Lưu ảnh đã chấm dạng JPEG Quality 90 sắc nét nhưng dung lượng siêu nhẹ (~450KB)
        graded_path = GRADED_DIR / f"{sub_id}_graded.jpg"
        cv2.imwrite(str(graded_path), res["graded_image_bgr"], [cv2.IMWRITE_JPEG_QUALITY, 90])
        
        # Sinh bản xem trước WebP Quality 80 phục vụ hiển thị mượt mà (~180KB)
        preview_webp = GRADED_DIR / f"{sub_id}_preview.webp"
        cv2.imwrite(str(preview_webp), res["graded_image_bgr"], [cv2.IMWRITE_WEBP_QUALITY, 80])
        del res["graded_image_bgr"]

        exam["submissions"][sub_id] = res
        return res

    except Exception as err:
        traceback.print_exc()
        # Luôn lưu ảnh gốc vào GRADED_DIR để người dùng bấm xem lại được ngay ảnh vừa chụp
        graded_path = GRADED_DIR / f"{sub_id}_graded.jpg"
        if not graded_path.exists() and img_bgr is not None:
            cv2.imwrite(str(graded_path), img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
            preview_webp = GRADED_DIR / f"{sub_id}_preview.webp"
            cv2.imwrite(str(preview_webp), img_bgr, [cv2.IMWRITE_WEBP_QUALITY, 75])

        if temp_raw.exists():
            try:
                temp_raw.unlink()
            except Exception:
                pass

        err_msg = str(err)
        if "ALIGNMENT_FAILED" in err_msg:
            user_friendly_msg = "Ảnh bị mất mốc định vị hoặc quá nghiêng. Hãy chụp thẳng góc và đủ sáng."
        else:
            user_friendly_msg = f"Lỗi xử lý bài làm: {err_msg}"

        err_sub = {
            "submission_id": sub_id,
            "file_name": file_name,
            "sbd": "CHƯA RÕ",
            "exam_code": "CHƯA RÕ",
            "has_error": True,
            "status": "PROCESSING_ERROR",
            "error_msg": user_friendly_msg,
            "anomalies": [{"type": "ALIGN_ERROR", "msg": user_friendly_msg}],
            "scores": {"status": "ERROR", "p1": 0.0, "p2": 0.0, "p3": 0.0, "total": 0.0},
            "details": {"part1": {}, "part2": {}, "part3": {}},
            "quality_metrics": q_report.get("metrics", {})
        }
        exam["submissions"][sub_id] = err_sub
        return err_sub


@app.post("/api/grade-single-file")
async def grade_single_file(file: UploadFile = File(...)):
    exam = get_current_exam()

    if not exam.get("exam_info", {}).get("is_configured", False) or not exam.get("exam_data", {}).get("answer_keys"):
        raise HTTPException(
            status_code=400,
            detail="Đợt kiểm tra hiện tại chưa được nạp đáp án. Vui lòng bấm 'Nạp File Đáp Án' trước khi chấm bài."
        )

    raw_bytes = await file.read()
    new_subs = []

    if file.filename.lower().endswith(".pdf"):
        try:
            doc = fitz.open(stream=raw_bytes, filetype="pdf")
            for page_idx in range(len(doc)):
                page = doc[page_idx]
                pix = page.get_pixmap(dpi=200)
                img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
                img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR if pix.n == 4 else cv2.COLOR_RGB2BGR)
                sub_id = str(uuid.uuid4())[:8]
                page_name = f"{file.filename}_Trang_{page_idx + 1}"
                res = _process_and_save(img_bgr, page_name, sub_id, exam)
                new_subs.append(res)
            doc.close()
        except Exception as err:
            traceback.print_exc()
            raise HTTPException(status_code=400, detail=f"Lỗi đọc file PDF: {err}")
    else:
        np_arr = np.frombuffer(raw_bytes, np.uint8)
        img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img_bgr is None:
            raise HTTPException(status_code=400, detail="Không thể giải mã file ảnh.")
        sub_id = str(uuid.uuid4())[:8]
        res = _process_and_save(img_bgr, file.filename, sub_id, exam)
        # Giữ lại bài thi trong danh sách để người dùng có thể bấm vào xem chi tiết ảnh chụp và nguyên nhân lỗi
        new_subs.append(res)

    save_to_disk()
    return {
        "status": "SUCCESS",
        "new_submissions": new_subs,
        "total_submissions_count": len(exam["submissions"])
    }


# ==============================================================================
# 5. ROUTE SỬA TAY REALTIME & TÁI ĐÓNG DẤU BÚT ĐỎ
# ==============================================================================

@app.post("/api/update-submission")
async def update_submission(payload: dict):
    """Cập nhật SBD, Mã đề, Đáp án; tự động chấm lại và vẽ lại tem bút đỏ Cột 3."""
    try:
        exam = get_current_exam()
        sub_id = payload.get("submission_id")
        if not sub_id or sub_id not in exam.get("submissions", {}):
            raise HTTPException(status_code=404, detail="Không tìm thấy bài thi cần cập nhật.")

        sub = exam["submissions"][sub_id]

        new_sbd = str(payload.get("sbd", sub.get("sbd", ""))).strip()
        new_exam_code = str(payload.get("exam_code", sub.get("exam_code", ""))).strip().zfill(4)

        sub["sbd"] = new_sbd
        sub["exam_code"] = new_exam_code

        if "part1" in payload and isinstance(payload["part1"], dict):
            sub["details"]["part1"] = {int(k): str(v).upper() for k, v in payload["part1"].items() if v}
        if "part2" in payload and isinstance(payload["part2"], dict):
            sub["details"]["part2"] = {int(k): {str(sk).lower(): str(sv).upper() for sk, sv in sdict.items()} for k, sdict in payload["part2"].items() if sdict}
        
        if "part3" in payload and isinstance(payload["part3"], dict):
            p3_clean = {}
            for k, v in payload["part3"].items():
                if v is not None and str(v).strip() != "":
                    try:
                        f_val = float(str(v).replace(",", "."))
                        p3_clean[int(k)] = {
                            "raw_string": str(v),
                            "normalized_value": f_val,
                            "is_valid": True,
                            "anomalies": []
                        }
                    except ValueError:
                        pass
            if p3_clean:
                sub["details"]["part3"] = p3_clean

        exam_data = exam.get("exam_data")
        if exam_data and "answer_keys" in exam_data:
            pipeline.answer_keys = normalize_answer_keys(exam_data["answer_keys"])

        new_scores = pipeline._grade(
            new_exam_code,
            sub["details"].get("part1", {}),
            sub["details"].get("part2", {}),
            sub["details"].get("part3", {})
        )
        sub["scores"] = new_scores
        sub["has_error"] = False
        sub["error_msg"] = None
        sub["status"] = "GRADED" if new_scores.get("status") == "GRADED" else "NEEDS_REVIEW"
        sub["updated_at"] = datetime.now().isoformat()

        try:
            # Tìm ảnh nền đã nắn phẳng (hỗ trợ cả đuôi .jpg và .png)
            base_img = None
            candidates = [
                UPLOAD_DIR / f"{sub_id}_aligned.jpg",
                UPLOAD_DIR / f"{sub_id}_aligned.png",
                GRADED_DIR / f"{sub_id}_aligned.jpg",
                GRADED_DIR / f"{sub_id}_aligned.png",
                GRADED_DIR / f"{sub_id}_graded.jpg",
                GRADED_DIR / f"{sub_id}_graded.png",
            ]
            for c_path in candidates:
                if c_path.exists():
                    base_img = cv2.imread(str(c_path))
                    if base_img is not None:
                        if "graded" in c_path.name:
                            base_img[185:440, 65:410] = (255, 255, 255)
                        break

            if base_img is not None:
                key_dict = pipeline.answer_keys.get(new_exam_code, {})
                stamped = VisualStamper.stamp_graded_sheet(
                    aligned_bgr=base_img,
                    submission=sub,
                    p1_coords=pipeline.p1_coords,
                    p2_coords=pipeline.p2_coords,
                    p3_coords=pipeline.p3_coords,
                    key_dict=key_dict,
                    sbd_columns=pipeline.sbd_columns,
                    made_columns=pipeline.made_columns
                )
                graded_path = GRADED_DIR / f"{sub_id}_graded.jpg"
                cv2.imwrite(str(graded_path), stamped, [cv2.IMWRITE_JPEG_QUALITY, 90])
                
                preview_webp = GRADED_DIR / f"{sub_id}_preview.webp"
                cv2.imwrite(str(preview_webp), stamped, [cv2.IMWRITE_WEBP_QUALITY, 80])
                print(f"[OK] Da ve lai tem but do: {sub_id} (Diem: {new_scores['total']})")
        except Exception as stamp_err:
            print(f"[!] Canh bao ve tem but do: {stamp_err}")

        save_to_disk()

        return {
            "status": "success",
            "message": "Đã cập nhật và chấm lại thành công!",
            "updated_submission": sub
        }

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Lỗi cập nhật máy chủ: {str(e)}")


@app.delete("/api/delete-submission/{submission_id}")
async def delete_submission(submission_id: str):
    exam = get_current_exam()
    if submission_id not in exam.get("submissions", {}):
        raise HTTPException(status_code=404, detail="Không tìm thấy bài làm cần xóa")

    delete_submission_files(submission_id)
    del exam["submissions"][submission_id]
    save_to_disk()

    return {"status": "SUCCESS", "remaining_count": len(exam["submissions"])}


@app.get("/api/crop-info/{submission_id}")
async def get_crop_info(submission_id: str):
    # Tìm ảnh nắn phẳng để cắt thông tin viết tay
    aligned_path = None
    for ext in [".jpg", ".png"]:
        p = UPLOAD_DIR / f"{submission_id}_aligned{ext}"
        if p.exists():
            aligned_path = p
            break
        p = GRADED_DIR / f"{submission_id}_aligned{ext}"
        if p.exists():
            aligned_path = p
            break
        p = GRADED_DIR / f"{submission_id}_graded{ext}"
        if p.exists():
            aligned_path = p
            break

    if not aligned_path or not aligned_path.exists():
        raise HTTPException(status_code=404, detail="Không tìm thấy bài làm")

    img = cv2.imread(str(aligned_path))
    if img is None:
        raise HTTPException(status_code=500, detail="Không thể đọc tệp ảnh bài làm.")

    # Vùng cắt thông tin thí sinh: Y từ 205 đến 725, X từ 440 đến 1225
    crop = img[205:725, 440:1225]

    _, buffer = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return Response(
        content=buffer.tobytes(),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache"}
    )


@app.get("/api/graded-image/{sub_id}")
async def get_graded_image(sub_id: str):
    """Phục vụ ảnh WebP nén nhẹ kết hợp HTTP Cache ETag."""
    webp_path = GRADED_DIR / f"{sub_id}_preview.webp"
    jpg_path = GRADED_DIR / f"{sub_id}_graded.jpg"
    png_path = GRADED_DIR / f"{sub_id}_graded.png"

    source_path = None
    for p in [jpg_path, png_path]:
        if p.exists():
            source_path = p
            break

    if not source_path and not webp_path.exists():
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh bài làm đã chấm.")

    need_regenerate = False
    if not webp_path.exists():
        need_regenerate = True
    elif source_path and source_path.stat().st_mtime > webp_path.stat().st_mtime:
        need_regenerate = True

    if need_regenerate and source_path:
        bgr = cv2.imread(str(source_path))
        if bgr is not None:
            cv2.imwrite(str(webp_path), bgr, [cv2.IMWRITE_WEBP_QUALITY, 80])

    target_file = webp_path if webp_path.exists() else source_path
    media_type = "image/webp" if target_file.suffix == ".webp" else "image/jpeg"
    last_modified = int(target_file.stat().st_mtime)

    return FileResponse(
        target_file,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "ETag": f'"{sub_id}-{last_modified}"'
        }
    )


@app.get("/api/image/{sub_id}")
async def get_image_alias(sub_id: str):
    """Bí danh phục vụ ảnh bài làm cho các client gọi /api/image/{sub_id}"""
    return await get_graded_image(sub_id)


# ==============================================================================
# 6. ROUTE IMPORT / EXPORT DỮ LIỆU (KHỬ HOÀN TOÀN DẤU TIẾNG VIỆT CHO HEADER)
# ==============================================================================

@app.get("/api/download-template")
async def download_template():
    tpl_path = Path("output/MAU_DAP_AN_TRAC_NGHIEM_2025.xlsx")
    exam = get_current_exam()
    info = exam.get("exam_info", {})

    file_bytes = ExamManager.generate_excel_template(
        output_path=tpl_path,
        exam_name=f"{info.get('subject', 'Sinh học')} - {info.get('period', 'Giữa kỳ I')}",
        subject=info.get("subject", "Sinh học"),
        period=info.get("period", "Giữa kỳ I")
    )

    return Response(
        content=file_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": 'attachment; filename="MAU_DAP_AN_TRAC_NGHIEM_2025.xlsx"'
        }
    )


@app.post("/api/upload-answer-key")
async def upload_answer_key(file: UploadFile = File(...)):
    global pipeline
    raw_bytes = await file.read()
    temp_path = UPLOAD_DIR / "uploaded_key.xlsx"
    temp_path.write_bytes(raw_bytes)

    try:
        exam_data = ExamManager.parse_excel_config(temp_path)
        exam = get_current_exam()
        exam["exam_data"] = exam_data
        exam["exam_info"]["is_configured"] = True

        pipeline = FullGradingPipeline(exam_data=exam_data)

        # Chấm lại các bài thi hiện có theo đáp án mới
        for sub_id, sub in exam["submissions"].items():
            aligned_p = None
            for ext in [".jpg", ".png"]:
                p = UPLOAD_DIR / f"{sub_id}_aligned{ext}"
                if p.exists():
                    aligned_p = p
                    break
                p = GRADED_DIR / f"{sub_id}_aligned{ext}"
                if p.exists():
                    aligned_p = p
                    break

            if aligned_p and aligned_p.exists():
                img = cv2.imread(str(aligned_p))
                if img is not None:
                    updated = pipeline.process_sheet(img, sub["file_name"], forced_exam_code=sub["exam_code"])
                    updated["submission_id"] = sub_id
                    updated["original_filename"] = sub["file_name"]
                    
                    graded_path = GRADED_DIR / f"{sub_id}_graded.jpg"
                    cv2.imwrite(str(graded_path), updated["graded_image_bgr"], [cv2.IMWRITE_JPEG_QUALITY, 90])
                    
                    preview_webp = GRADED_DIR / f"{sub_id}_preview.webp"
                    cv2.imwrite(str(preview_webp), updated["graded_image_bgr"], [cv2.IMWRITE_WEBP_QUALITY, 80])
                    
                    del updated["graded_image_bgr"]
                    exam["submissions"][sub_id] = updated

        save_to_disk()
        return {
            "status": "SUCCESS",
            "exam_name": exam_data["exam_name"],
            "codes_loaded": list(exam_data["answer_keys"].keys()),
            "exam_info": exam["exam_info"]
        }
    except Exception as err:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"Lỗi file đáp án: {err}")


@app.post("/api/smart-paste-answer-key")
async def smart_paste_answer_key(payload: SmartPasteRequest):
    global pipeline
    if not payload.text or not payload.text.strip():
        raise HTTPException(status_code=400, detail="Vui lòng nhập hoặc dán nội dung đáp án.")

    try:
        parsed_result = ExamManager.smart_parse_text_keys(payload.text, default_made=payload.default_made or "0001")
        parsed_keys = parsed_result.get("answer_keys", {})
        if not parsed_keys:
            raise HTTPException(status_code=400, detail="Không nhận diện được câu hỏi hoặc đáp án nào. Hãy kiểm tra định dạng dán (VD: 1.A 2.B hoặc 1A 2B).")

        exam = get_current_exam()
        if not exam.get("exam_data"):
            exam["exam_data"] = {
                "exam_name": f"{exam['exam_info'].get('subject', 'Đề thi')} - {exam['exam_info'].get('period', 'Kiểm tra')}",
                "subject": exam["exam_info"].get("subject", "Sinh học"),
                "period": exam["exam_info"].get("period", "Giữa kỳ I"),
                "config": parsed_result.get("config", {"part1_max": 18, "part2_max": 4, "part3_max": 6}),
                "answer_keys": {},
                "scoring_rules": {
                    "part1": {"points_per_question": 0.25},
                    "part2": {
                        "type": "graduated_moet",
                        "table": {"1": 0.1, "2": 0.25, "3": 0.5, "4": 1.0}
                    },
                    "part3": {"points_per_question": 0.25}
                }
            }
        elif "config" not in exam["exam_data"]:
            exam["exam_data"]["config"] = parsed_result.get("config", {"part1_max": 18, "part2_max": 4, "part3_max": 6})

        # Cập nhật các mã đề mới parsed vào answer_keys (merge từng phần, không xóa Phần II, III)
        for code, new_k in parsed_keys.items():
            if code not in exam["exam_data"]["answer_keys"]:
                exam["exam_data"]["answer_keys"][code] = new_k
            else:
                for part in ["part1", "part2", "part3"]:
                    if new_k.get(part):
                        exam["exam_data"]["answer_keys"][code][part] = new_k[part]
        exam["exam_info"]["is_configured"] = True

        pipeline = FullGradingPipeline(exam_data=exam["exam_data"])

        # Tái chấm các bài thi có trong danh sách
        re_graded_count = 0
        for sub_id, sub in exam.get("submissions", {}).items():
            sub_code = sub.get("exam_code", "")
            if sub_code in exam["exam_data"]["answer_keys"]:
                aligned_p = None
                for p in [GRADED_DIR / f"{sub_id}_aligned.png", UPLOAD_DIR / f"{sub_id}_aligned.png", GRADED_DIR / f"{sub_id}_aligned.jpg"]:
                    if p.exists():
                        aligned_p = p
                        break

                if aligned_p and aligned_p.exists():
                    img = cv2.imread(str(aligned_p))
                    if img is not None:
                        updated = pipeline.process_sheet(img, sub.get("file_name", ""), forced_exam_code=sub_code)
                        updated["submission_id"] = sub_id
                        updated["original_filename"] = sub.get("file_name", "")
                        
                        graded_path = GRADED_DIR / f"{sub_id}_graded.jpg"
                        cv2.imwrite(str(graded_path), updated["graded_image_bgr"], [cv2.IMWRITE_JPEG_QUALITY, 90])
                        
                        preview_webp = GRADED_DIR / f"{sub_id}_preview.webp"
                        cv2.imwrite(str(preview_webp), updated["graded_image_bgr"], [cv2.IMWRITE_WEBP_QUALITY, 80])
                        
                        del updated["graded_image_bgr"]
                        exam["submissions"][sub_id] = updated
                        re_graded_count += 1

        save_to_disk()
        return {
            "status": "SUCCESS",
            "codes_loaded": list(parsed_keys.keys()),
            "total_codes": list(exam["exam_data"]["answer_keys"].keys()),
            "re_graded_count": re_graded_count,
            "details": {
                c: {
                    "part1": len(k.get("part1", {})),
                    "part2": len(k.get("part2", {})),
                    "part3": len(k.get("part3", {}))
                } for c, k in parsed_keys.items()
            },
            "exam_info": exam["exam_info"]
        }
    except HTTPException:
        raise
    except Exception as err:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"Lỗi xử lý đáp án dán: {err}")


@app.get("/api/export-excel")
async def export_excel():
    """Xuất bảng điểm Excel an toàn; Header filename thuần ASCII chống sập HTTP 500."""
    try:
        exam = get_current_exam()
        subs = exam.get("submissions", {})
        if not subs:
            raise HTTPException(status_code=400, detail="Chưa có bài thi nào trong đợt để xuất bảng điểm.")

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "BangDiem"

        headers = ["STT", "Tên Tệp", "Số Báo Danh (Vào Sổ)", "Mã Đề", "Điểm P1", "Điểm P2", "Điểm P3", "TỔNG ĐIỂM", "Trạng Thái", "Cảnh Báo"]
        ws.append(headers)

        for idx, (sub_id, sub) in enumerate(subs.items(), start=1):
            sc = sub.get("scores", {})
            ws.append([
                idx,
                sub.get("file_name", ""),
                sub.get("sbd", ""),
                sub.get("exam_code", ""),
                sc.get("p1", 0.0),
                sc.get("p2", 0.0),
                sc.get("p3", 0.0),
                sc.get("total", 0.0),
                sub.get("status", "GRADED"),
                ", ".join([a["msg"] for a in sub.get("anomalies", [])]) if sub.get("anomalies") else "Hợp lệ"
            ])

        excel_path = Path("output/BANG_DIEM_VAO_SO.xlsx")
        try:
            wb.save(excel_path)
        except PermissionError:
            excel_path = Path(f"output/BANG_DIEM_VAO_SO_{int(time.time())}.xlsx")
            wb.save(excel_path)

        info = exam.get("exam_info", {})
        sub_name = sanitize_ascii_filename(info.get("subject", "MON"))
        period_name = sanitize_ascii_filename(info.get("period", "KY"))
        download_name = f"BANG_DIEM_{sub_name}_{period_name}.xlsx"

        return FileResponse(
            path=str(excel_path),
            filename=download_name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Lỗi xuất Excel: {str(e)}")


@app.get("/api/export-graded-pdf")
async def export_graded_pdf():
    """Xuất tập phiếu đã chấm thành PDF nhiều trang bằng PyMuPDF (fitz); Header thuần ASCII."""
    try:
        exam = get_current_exam()
        subs = exam.get("submissions", {})
        if not subs:
            raise HTTPException(status_code=400, detail="Chưa có bài thi nào trong đợt để xuất PDF.")

        image_paths = []
        for sub_id in subs.keys():
            # Quét tìm cả định dạng ảnh .jpg mới và .png cũ
            for ext in [".jpg", ".png"]:
                p = GRADED_DIR / f"{sub_id}_graded{ext}"
                if p.exists():
                    image_paths.append(p)
                    break

        if not image_paths:
            raise HTTPException(status_code=400, detail="Không tìm thấy tệp ảnh bài thi đã chấm nào trên ổ cứng.")

        pdf_out = Path("output/TAP_PHIEU_DA_CHAM.pdf")

        doc = fitz.open()
        for p in image_paths:
            try:
                img_doc = fitz.open(str(p))
                pdf_bytes = img_doc.convert_to_pdf()
                img_doc.close()
                img_pdf = fitz.open("pdf", pdf_bytes)
                doc.insert_pdf(img_pdf)
                img_pdf.close()
            except Exception as page_err:
                print(f"[!] Bỏ qua ảnh lỗi {p.name}: {page_err}")

        if len(doc) == 0:
            raise HTTPException(status_code=500, detail="Không thể tạo trang PDF từ các ảnh bài thi.")

        try:
            doc.save(str(pdf_out))
        except PermissionError:
            pdf_out = Path(f"output/TAP_PHIEU_DA_CHAM_{int(time.time())}.pdf")
            doc.save(str(pdf_out))
        finally:
            doc.close()

        info = exam.get("exam_info", {})
        sub_name = sanitize_ascii_filename(info.get("subject", "MON"))
        class_name = sanitize_ascii_filename(info.get("class_name", "LOP"))
        download_name = f"TAP_PHIEU_DA_CHAM_{sub_name}_{class_name}.pdf"

        print(f"[OK] Da xuat thanh cong tap PDF gom {len(image_paths)} trang: {pdf_out.name}")

        return FileResponse(
            path=str(pdf_out),
            filename=download_name,
            media_type="application/pdf"
        )
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Lỗi xuất PDF: {str(e)}")


@app.get("/api/export-pdf")
async def export_pdf_alias():
    """Bí danh xuất tập phiếu đã chấm thành PDF"""
    return await export_graded_pdf()


# ==============================================================================
# 7. KHỞI CHẠY MÁY CHỦ
# ==============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)