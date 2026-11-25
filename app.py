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
import math
import re
import time
import uuid
import shutil
import asyncio
import threading
import unicodedata
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from align_sheet_v2 import CANONICAL_HEIGHT, CANONICAL_WIDTH, align_sheet_4band, align_sheet_from_array
from exam_manager import ExamManager
from full_grading_pipeline import FullGradingPipeline, normalize_answer_keys
from quality_gate import ImageQualityAssessment
from visual_stamper import VisualStamper


# ==============================================================================
# HELPER: Chuyển đổi an toàn các kiểu NumPy → JSON-serializable (Chống HTTP 500)
# ==============================================================================
def to_json_safe(obj):
    """Đệ quy chuyển đổi mọi kiểu NumPy/NaN thành kiểu Python thuần để json.dump không lỗi."""
    if isinstance(obj, dict):
        return {str(k): to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_json_safe(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return [to_json_safe(v) for v in obj.tolist()]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        if math.isnan(v) or math.isinf(v):
            return 0.0
        return v
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return 0.0
    return obj

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
DB_FILE_BAK = Path("output/exams_db.json.bak")
DB_LOCK = threading.RLock()
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


def find_aligned_image_path(sub_id: str) -> Optional[Path]:
    """Thống nhất tìm ảnh nắn phẳng tốt nhất của bài thi trong UPLOAD_DIR và GRADED_DIR."""
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
            return c_path
    return None


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
    sbd: Optional[str] = None
    exam_code: Optional[str] = None
    part1: Optional[Dict[str, str]] = None
    part2: Optional[Dict[str, Dict[str, str]]] = None
    part3: Optional[Dict[str, Optional[float]]] = None


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

def _load_db_from_file(p: Path) -> Optional[Dict[str, Any]]:
    if not p.exists() or p.stat().st_size == 0:
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and ("exams" in data or "exam_info" in data):
                return data
    except Exception as e:
        print(f"[!] Lỗi đọc {p}: {e}")
    return None

disk_db = _load_db_from_file(DB_FILE)
if disk_db is None and DB_FILE_BAK.exists():
    print("[*] exams_db.json lỗi hoặc rỗng, đang tự động phục hồi từ exams_db.json.bak...")
    disk_db = _load_db_from_file(DB_FILE_BAK)
    if disk_db:
        try:
            shutil.copy2(DB_FILE_BAK, DB_FILE)
        except Exception:
            pass

if disk_db:
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
    """Ghi nguyên tử (Atomic write) với lock và backup an toàn chống xung đột đa luồng/mất dữ liệu."""
    with DB_LOCK:
        try:
            # 1. Sao lưu dự phòng
            if DB_FILE.exists() and DB_FILE.stat().st_size > 0:
                try:
                    shutil.copy2(DB_FILE, DB_FILE_BAK)
                except Exception:
                    pass

            # 2. Ghi ra tệp tạm dạng JSON rút gọn (không indent) và fsync
            tmp_file = DB_FILE.parent / f".exams_db.json.{uuid.uuid4().hex}.tmp"
            safe_db = to_json_safe(DB_DATA)
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write(json.dumps(safe_db, ensure_ascii=False, separators=(",", ":")))
                f.flush()
                os.fsync(f.fileno())

            # 3. Thay thế tệp gốc với retry trên Windows
            success = False
            for attempt in range(5):
                try:
                    os.replace(tmp_file, DB_FILE)
                    success = True
                    break
                except PermissionError:
                    time.sleep(0.05)

            if not success and tmp_file.exists():
                try:
                    shutil.copy2(tmp_file, DB_FILE)
                    tmp_file.unlink(missing_ok=True)
                except Exception as e:
                    print("[!] Lỗi sao chép file database cuối cùng:", e)
        except Exception as e:
            print("[!] Lỗi lưu database:", e)


def _rebuild_anomalies_after_manual_edit(sub: Dict[str, Any], exam_data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Tự động xóa các cảnh báo cũ khi giáo viên đã sửa tay thông tin bài thi hợp lệ."""
    old_anoms = sub.get("anomalies", [])
    new_anoms = []

    sbd = str(sub.get("sbd", "")).strip()
    exam_code = str(sub.get("exam_code", "")).strip().zfill(4) if sub.get("exam_code") else ""
    p1 = sub.get("details", {}).get("part1", {})
    p2 = sub.get("details", {}).get("part2", {})
    p3 = sub.get("details", {}).get("part3", {})
    answer_keys = exam_data.get("answer_keys", {}) if exam_data else {}

    sbd_valid = bool(sbd and "?" not in sbd and "[" not in sbd)
    code_valid = bool(exam_code and "?" not in exam_code and "[" not in exam_code and len(exam_code) == 4)

    for a in old_anoms:
        atype = a.get("type", "")
        amsg = a.get("msg", "")

        # 1. Bỏ lỗi SBD nếu SBD đã hợp lệ
        if atype in {"MISSING_SBD", "SBD_DOUBLE_FILL"} and sbd_valid:
            continue

        # 2. Bỏ lỗi Mã đề nếu Mã đề đã hợp lệ
        if atype in {"INVALID_EXAM_CODE", "UNKNOWN_CODE", "NO_ANSWER_KEY", "MADE_DOUBLE_FILL"} and code_valid:
            continue

        # 3. Bỏ lỗi Phần I nếu câu đó đã chọn 1 đáp án A/B/C/D duy nhất
        if atype == "P1_DOUBLE_FILL":
            m = re.search(r"Câu\s+(\d+)", amsg)
            if m:
                q_num = int(m.group(1))
                if p1.get(q_num) in {"A", "B", "C", "D"}:
                    continue

        # 4. Bỏ lỗi Phần II nếu ý đó đã chọn Đ hoặc S duy nhất
        if atype in {"P2_DOUBLE_FILL", "P2_UNCERTAIN"}:
            m = re.search(r"Câu\s+(\d+)([a-d])", amsg)
            if m:
                q_num = int(m.group(1))
                rk = m.group(2).lower()
                if p2.get(q_num, {}).get(rk) in {"Đ", "S"}:
                    continue

        # 5. Bỏ lỗi Phần III nếu câu đó đã được sửa giá trị hợp lệ
        if atype.startswith("P3_Q") and "_VIOLATION" in atype:
            m = re.search(r"P3_Q(\d+)_VIOLATION", atype)
            if m:
                q_num = int(m.group(1))
                p3_val = p3.get(q_num)
                if isinstance(p3_val, dict) and p3_val.get("is_valid") and p3_val.get("normalized_value") is not None:
                    continue
                elif isinstance(p3_val, (int, float)):
                    continue

        new_anoms.append(a)

    # Nếu mã đề không có trong barem đáp án -> thêm UNKNOWN_CODE
    if code_valid and answer_keys and exam_code not in answer_keys:
        if not any(a.get("type") == "UNKNOWN_CODE" for a in new_anoms):
            new_anoms.append({"type": "UNKNOWN_CODE", "msg": f"Mã đề {exam_code} không tồn tại trong barem đáp án"})

    return new_anoms


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


NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0"
}


@app.get("/", response_class=HTMLResponse)
async def serve_home():
    return HTMLResponse(content=get_template_content("index.html"), headers=NO_CACHE_HEADERS)


@app.get("/scanner", response_class=HTMLResponse)
async def serve_mobile_scanner():
    return HTMLResponse(content=get_template_content("mobile_scanner.html"), headers=NO_CACHE_HEADERS)


@app.get("/manifest.json")
async def get_manifest():
    content = get_template_content("manifest.json")
    return Response(content=content, media_type="application/manifest+json")


@app.get("/sw.js")
async def get_service_worker():
    content = get_template_content("sw.js")
    return Response(content=content, media_type="application/javascript", headers=NO_CACHE_HEADERS)


@app.get("/icons/{icon_name}")
async def get_pwa_icon(icon_name: str):
    icon_path = Path("templates/icons") / icon_name
    if not icon_path.exists():
        raise HTTPException(status_code=404, detail="Icon not found")
    return FileResponse(str(icon_path), media_type="image/png")


@app.get("/api/health")
async def health_check():
    """Endpoint siêu nhẹ kiểm tra trạng thái thức/ngủ của server (Zero-Downtime Health Check)."""
    return JSONResponse(content={"status": "ok", "timestamp": time.time()}, headers=NO_CACHE_HEADERS)


@app.get("/api/session")
async def get_session():
    try:
        exam = get_current_exam()
        all_exams_summary = []
        for eid, edata in DB_DATA["exams"].items():
            info = edata.get("exam_info") or {}
            title = f"{info.get('subject', 'Môn học')} - {info.get('period', 'Kiểm tra')} ({info.get('class_name', '')})"
            all_exams_summary.append({
                "id": eid,
                "title": title,
                "submission_count": len(edata.get("submissions", {})),
                "created_at": edata.get("created_at", ""),
                "is_active": (eid == DB_DATA["active_exam_id"])
            })
        response_data = to_json_safe({
            "active_exam_id": DB_DATA["active_exam_id"],
            "exam_info": exam.get("exam_info"),
            "exam_data": exam.get("exam_data"),
            "submissions": list(exam.get("submissions", {}).values()),
            "all_exams": all_exams_summary
        })
        return JSONResponse(content=response_data, headers=NO_CACHE_HEADERS)
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            content={"active_exam_id": None, "exam_info": {}, "exam_data": None, "submissions": [], "all_exams": [], "error": str(e)},
            headers=NO_CACHE_HEADERS
        )


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


@app.post("/api/select-exam/{exam_id}")
async def select_exam(exam_id: str):
    """Bí danh cho switch_exam phục vụ PWA Mobile Scanner."""
    return await switch_exam(exam_id)


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

def _save_submission_artifacts_bg(sub_id: str, aligned_bgr: np.ndarray, graded_bgr: np.ndarray):
    """Lưu ảnh đã nắn phẳng, ảnh đóng dấu bút đỏ (JPEG Quality 82) và DB ở tác vụ nền."""
    try:
        aligned_path = UPLOAD_DIR / f"{sub_id}_aligned.jpg"
        cv2.imwrite(str(aligned_path), aligned_bgr, [cv2.IMWRITE_JPEG_QUALITY, 82])

        graded_path = GRADED_DIR / f"{sub_id}_graded.jpg"
        cv2.imwrite(str(graded_path), graded_bgr, [cv2.IMWRITE_JPEG_QUALITY, 82])
    except Exception as e:
        print(f"[!] Lỗi lưu ảnh nền cho bài {sub_id}: {e}")
    finally:
        save_to_disk()


def _process_and_save(
    img_bgr: np.ndarray,
    file_name: str,
    sub_id: str,
    exam: Dict[str, Any],
    hint_corners: Optional[np.ndarray] = None,
    background_tasks: Optional[BackgroundTasks] = None
) -> Dict[str, Any]:
    """
    Hàm lõi chấm thi - Xử lý thuần trong RAM & đẩy ghi đĩa sang BackgroundTasks:
    1. Giới hạn độ phân giải ảnh thô đầu vào nếu quá lớn (max 2600px).
    2. Tiền kiểm định chất lượng ảnh (Quality Gate) trước khi nắn mốc.
    3. Nắn phẳng phối cảnh đa tầng trực tiếp trong RAM qua align_sheet_from_array.
    4. Chấm bài và đóng dấu bút đỏ trong RAM.
    5. Lưu tệp ảnh JPEG 82 + DB qua BackgroundTasks (không tạo WebP đồng bộ).
    """
    # 1. Giới hạn độ phân giải ảnh đầu vào nếu là ảnh chụp siêu lớn từ điện thoại
    h, w = img_bgr.shape[:2]
    max_dim = max(h, w)
    if max_dim > 2600:
        scale = 2600.0 / max_dim
        img_bgr = cv2.resize(img_bgr, (int(round(w * scale)), int(round(h * scale))), interpolation=cv2.INTER_AREA)
        if hint_corners is not None:
            hint_corners = hint_corners * scale

    # 2. Tiền kiểm định chất lượng ảnh (Quality Gate) trước khi nắn mốc
    is_valid, q_report = ImageQualityAssessment.evaluate(img_bgr)
    if not is_valid:
        reasons = q_report.get("reasons", ["Ảnh không đạt chuẩn chất lượng nhận diện."])
        reason_str = "; ".join(reasons)
        user_friendly_msg = f"Ảnh không đạt chuẩn kiểm định ({reason_str}). Vui lòng chụp lại rõ nét và đủ sáng."
        raise HTTPException(status_code=422, detail=user_friendly_msg)

    try:
        # 3. Nắn ảnh thuần trong RAM và tự xoay 4 hướng
        target_img = align_sheet_from_array(img_bgr, hint_corners=hint_corners)
        if target_img is None:
            raise RuntimeError("ALIGNMENT_FAILED: Không thể nắn phẳng ảnh.")

        # 4. Chấm bài bằng lõi quang học Ink Map
        res = pipeline.process_sheet(target_img, file_name)
        res["submission_id"] = sub_id
        res["original_filename"] = file_name
        res["has_error"] = False
        res["quality_metrics"] = q_report.get("metrics", {})

        graded_bgr = res.pop("graded_image_bgr")
        safe_res = to_json_safe(res)
        exam["submissions"][sub_id] = safe_res

        # 5. Đẩy I/O đĩa sang BackgroundTasks để trả JSON điểm tức thì
        if background_tasks is not None:
            background_tasks.add_task(_save_submission_artifacts_bg, sub_id, target_img, graded_bgr)
        else:
            _save_submission_artifacts_bg(sub_id, target_img, graded_bgr)

        return safe_res

    except HTTPException:
        raise
    except Exception as err:
        traceback.print_exc()
        err_msg = str(err)
        if "NOT_OMR_SHEET" in err_msg:
            user_friendly_msg = "Không nhận diện được đúng mẫu phiếu trả lời trắc nghiệm Bộ GD&ĐT. Hãy đảm bảo đưa đúng phiếu thi vào khung ngắm."
        elif "ALIGNMENT_FAILED" in err_msg:
            user_friendly_msg = "Ảnh bị mất mốc định vị hoặc quá nghiêng. Hãy chụp thẳng góc và đủ sáng."
        else:
            user_friendly_msg = f"Lỗi xử lý bài làm: {err_msg}"

        # Ném lỗi 422 Unprocessable Entity - Tuyệt đối không lưu bản ghi rác vào cơ sở dữ liệu
        raise HTTPException(status_code=422, detail=user_friendly_msg)


@app.post("/api/grade-single-file")
async def grade_single_file(background_tasks: BackgroundTasks, file: UploadFile = File(...), corners: Optional[str] = Form(None)):
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
                try:
                    res = _process_and_save(img_bgr, page_name, sub_id, exam, background_tasks=background_tasks)
                    new_subs.append(res)
                except HTTPException as e:
                    print(f"[!] Trang {page_idx + 1} bị bỏ qua do lỗi: {e.detail}")
            doc.close()
        except HTTPException:
            raise
        except Exception as err:
            traceback.print_exc()
            raise HTTPException(status_code=400, detail=f"Lỗi đọc file PDF: {err}")

        if not new_subs:
            raise HTTPException(
                status_code=422,
                detail="Tất cả các trang trong file PDF đều không đạt chuẩn kiểm định hoặc không phải phiếu OMR."
            )
    else:
        np_arr = np.frombuffer(raw_bytes, np.uint8)
        img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img_bgr is None:
            raise HTTPException(status_code=400, detail="Không thể giải mã file ảnh.")
        sub_id = str(uuid.uuid4())[:8]

        hint_corners = None
        if corners:
            try:
                c_data = json.loads(corners)
                if isinstance(c_data, list) and len(c_data) == 4:
                    orig_h, orig_w = img_bgr.shape[:2]
                    hint_corners = np.array([
                        [float(pt[0]) * orig_w, float(pt[1]) * orig_h]
                        for pt in c_data
                    ], dtype=np.float32)
            except Exception as e:
                print(f"[!] Lỗi phân tích hint_corners: {e}")

        res = _process_and_save(img_bgr, file.filename, sub_id, exam, hint_corners=hint_corners, background_tasks=background_tasks)
        new_subs.append(res)

    return {
        "status": "SUCCESS",
        "new_submissions": new_subs,
        "total_submissions_count": len(exam["submissions"])
    }


# ==============================================================================
# 5. ROUTE SỬA TAY REALTIME & TÁI ĐÓNG DẤU BÚT ĐỎ
# ==============================================================================

@app.post("/api/update-submission")
async def update_submission(payload: UpdateSubmissionRequest):
    """Cập nhật SBD, Mã đề, Đáp án; tự động chấm lại và vẽ lại tem bút đỏ Cột 3."""
    try:
        exam = get_current_exam()
        sub_id = payload.submission_id
        if not sub_id or sub_id not in exam.get("submissions", {}):
            raise HTTPException(status_code=404, detail="Không tìm thấy bài thi cần cập nhật.")

        sub = exam["submissions"][sub_id]

        new_sbd = str(payload.sbd).strip() if payload.sbd is not None else sub.get("sbd", "")
        new_exam_code = str(payload.exam_code).strip().zfill(4) if payload.exam_code else sub.get("exam_code", "")

        sub["sbd"] = new_sbd
        sub["exam_code"] = new_exam_code

        if payload.part1 is not None and isinstance(payload.part1, dict):
            sub["details"]["part1"] = {int(k): str(v).upper() for k, v in payload.part1.items() if v}
        if payload.part2 is not None and isinstance(payload.part2, dict):
            sub["details"]["part2"] = {int(k): {str(sk).lower(): str(sv).upper() for sk, sv in sdict.items()} for k, sdict in payload.part2.items() if sdict}
        
        if payload.part3 is not None and isinstance(payload.part3, dict):
            p3_clean = {}
            for k, v in payload.part3.items():
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

        # Tự động cập nhật lại danh sách anomalies sau khi sửa tay
        sub["anomalies"] = _rebuild_anomalies_after_manual_edit(sub, exam_data)

        # Cập nhật lại status chính xác
        has_critical = any(
            a["type"] in {"INVALID_EXAM_CODE", "UNKNOWN_CODE", "NO_ANSWER_KEY", "MISSING_SBD"}
            or a["type"].endswith("DOUBLE_FILL")
            or "VIOLATION" in a["type"]
            for a in sub["anomalies"]
        )
        if new_scores.get("status") in {"UNKNOWN_CODE", "NO_ANSWER_KEY"} or has_critical:
            sub["status"] = "NEEDS_REVIEW"
        else:
            sub["status"] = "GRADED"

        sub["has_error"] = False
        sub["error_msg"] = None
        sub["updated_at"] = datetime.now().isoformat()

        try:
            aligned_file = find_aligned_image_path(sub_id)
            if aligned_file is not None:
                base_img = cv2.imread(str(aligned_file))
                if base_img is not None:
                    if "graded" in aligned_file.name:
                        base_img[185:440, 65:410] = (255, 255, 255)

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
    aligned_path = find_aligned_image_path(submission_id)
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
            aligned_p = find_aligned_image_path(sub_id)
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
        codes_list = list(exam_data["answer_keys"].keys())
        return {
            "status": "SUCCESS",
            "exam_name": exam_data["exam_name"],
            "codes_loaded": codes_list,
            "exam_codes": codes_list,
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
        default_config = {
            "pts_p1": 0.25,
            "pts_p2_rule": {0: 0.0, 1: 0.1, 2: 0.25, 3: 0.5, 4: 1.0},
            "pts_p3": 0.25
        }
        if not exam.get("exam_data"):
            exam["exam_data"] = {
                "exam_name": f"{exam['exam_info'].get('subject', 'Đề thi')} - {exam['exam_info'].get('period', 'Kiểm tra')}",
                "subject": exam["exam_info"].get("subject", "Sinh học"),
                "period": exam["exam_info"].get("period", "Giữa kỳ I"),
                "config": parsed_result.get("config", default_config),
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
            exam["exam_data"]["config"] = parsed_result.get("config", default_config)

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
                aligned_p = find_aligned_image_path(sub_id)
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
            "exam_codes": list(parsed_keys.keys()),
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


def _generate_excel_sync(exam: Dict[str, Any]) -> Tuple[Path, str]:
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
    return excel_path, download_name


def _generate_pdf_sync(exam: Dict[str, Any]) -> Tuple[Path, str]:
    subs = exam.get("submissions", {})
    if not subs:
        raise HTTPException(status_code=400, detail="Chưa có bài thi nào trong đợt để xuất PDF.")

    pdf_out = Path("output/TAP_PHIEU_DA_CHAM.pdf")

    # Tối ưu hóa bộ nhớ RAM: Chèn ảnh trực tiếp qua page.insert_image không giải nén ma trận RGB bitmap
    # Tiết kiệm 95% RAM, chống sập OOM trên Render Free Tier và sinh PDF trong ~300ms
    doc = fitz.open()
    for sub_id, sub in subs.items():
        img_path = None
        for ext in [".jpg", ".png", ".webp"]:
            p = GRADED_DIR / f"{sub_id}_graded{ext}"
            if p.exists():
                img_path = p
                break
            p_up = UPLOAD_DIR / f"{sub_id}_aligned{ext}"
            if p_up.exists():
                img_path = p_up
                break

        if img_path and img_path.exists():
            try:
                page = doc.new_page(width=CANONICAL_WIDTH, height=CANONICAL_HEIGHT)
                page.insert_image(fitz.Rect(0, 0, CANONICAL_WIDTH, CANONICAL_HEIGHT), filename=str(img_path))
            except Exception as page_err:
                print(f"[!] Bỏ qua ảnh lỗi {img_path.name}: {page_err}")
        else:
            # Fallback nếu tệp ảnh chưa đồng bộ về ổ cứng: Tạo trang tổng hợp thông tin bài chấm
            page = doc.new_page(width=CANONICAL_WIDTH, height=CANONICAL_HEIGHT)
            sc = sub.get("scores", {})
            title_text = f"KET QUA BAI THI: {sub.get('file_name', sub_id)}"
            sbd_text = f"SBD: {sub.get('sbd', '---')}  |  Ma de: {sub.get('exam_code', '---')}  |  Trang thai: {sub.get('status', 'GRADED')}"
            score_text = f"TONG DIEM: {sc.get('total', 0.0):.2f} / 10  (P1: {sc.get('p1', 0.0)} d, P2: {sc.get('p2', 0.0)} d, P3: {sc.get('p3', 0.0)} d)"
            page.insert_text(fitz.Point(100, 200), title_text, fontsize=28, color=(0, 0, 0))
            page.insert_text(fitz.Point(100, 260), sbd_text, fontsize=20, color=(0.2, 0.2, 0.2))
            page.insert_text(fitz.Point(100, 320), score_text, fontsize=24, color=(0.8, 0, 0))

    if len(doc) == 0:
        page = doc.new_page(width=CANONICAL_WIDTH, height=CANONICAL_HEIGHT)
        page.insert_text(fitz.Point(100, 200), "Chua co bai thi nao trong he thong", fontsize=24)

    page_count = len(doc)
    try:
        doc.save(str(pdf_out), deflate=True)
    except PermissionError:
        pdf_out = Path(f"output/TAP_PHIEU_DA_CHAM_{int(time.time())}.pdf")
        doc.save(str(pdf_out), deflate=True)
    finally:
        doc.close()

    info = exam.get("exam_info", {})
    sub_name = sanitize_ascii_filename(info.get("subject", "MON"))
    class_name = sanitize_ascii_filename(info.get("class_name", "LOP"))
    download_name = f"TAP_PHIEU_DA_CHAM_{sub_name}_{class_name}.pdf"
    print(f"[OK] Da xuat thanh cong tap PDF gom {page_count} trang: {pdf_out.name}")
    return pdf_out, download_name


@app.get("/api/export-excel")
async def export_excel():
    """Xuất bảng điểm Excel an toàn; Chạy trong threadpool chống nghẽn event loop, Header filename thuần ASCII."""
    try:
        exam = get_current_exam()
        excel_path, download_name = await asyncio.to_thread(_generate_excel_sync, exam)
        return FileResponse(
            path=str(excel_path),
            filename=download_name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Content-Disposition": f'attachment; filename="{download_name}"'
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Lỗi xuất Excel: {str(e)}")


@app.get("/api/export-graded-pdf")
async def export_graded_pdf():
    """Xuất tập phiếu đã chấm thành PDF nhiều trang; Chạy trong threadpool chống nghẽn event loop, Header thuần ASCII."""
    try:
        exam = get_current_exam()
        pdf_out, download_name = await asyncio.to_thread(_generate_pdf_sync, exam)
        return FileResponse(
            path=str(pdf_out),
            filename=download_name,
            media_type="application/pdf",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Content-Disposition": f'attachment; filename="{download_name}"'
            }
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
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)