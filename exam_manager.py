# exam_manager.py
# -*- coding: utf-8 -*-
"""
MODULE QUẢN LÝ CẤU HÌNH ĐỀ THI & ĐÁP ÁN CHUẨN HÓA BỘ GD&ĐT 2025
- Cấu hình thang điểm trực quan: Đúng 1, 2, 3, 4 ý chia thành 2 hàng ô trên - ô dưới rõ ràng.
- Đầy đủ 40 câu P1, 8 câu P2 (32 ý), 6 câu P3.
- Hỗ trợ xuất ra cả đĩa và bộ nhớ đệm (in-memory buffer) chống lỗi file lock trên Windows.
"""
import io
from pathlib import Path
from typing import Any, Dict, List, Optional
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


class ExamManager:
    MAX_P1 = 40
    MAX_P2 = 8
    MAX_P3 = 6

    @classmethod
    def generate_excel_template(
        cls,
        output_path: Optional[Path] = None,
        exam_name: str = "Kiểm tra trắc nghiệm",
        subject: str = "Sinh học",
        period: str = "Giữa kỳ I"
    ) -> bytes:
        """
        Tạo file Excel mẫu chuẩn:
        - Hàng 3-5: Cấu hình thang điểm. Đặc biệt Phần II hiển thị 4 cột:
          Ô trên: Đúng 1 ý | Đúng 2 ý | Đúng 3 ý | Đúng 4 ý
          Ô dưới:   0.10   |   0.25   |   0.50   |   1.00
        - Hàng 7: Header toàn bộ 78 cột (1 cột Mã đề + 40 P1 + 32 P2 + 6 P3).
        - Hàng 8-9: 2 dòng mã đề mẫu (0504, 0501).
        """
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "DAP_AN_TRAC_NGHIEM"
        ws.views.sheetView[0].showGridLines = True

        thin = Border(
            left=Side(style='thin', color='D3D3D3'),
            right=Side(style='thin', color='D3D3D3'),
            top=Side(style='thin', color='D3D3D3'),
            bottom=Side(style='thin', color='D3D3D3')
        )

        fill_navy = PatternFill("solid", fgColor="1B365D")
        fill_p1 = PatternFill("solid", fgColor="E8F0FE")    # Xanh dương nhạt
        fill_p2 = PatternFill("solid", fgColor="FEF7E0")    # Vàng cam nhạt
        fill_p3 = PatternFill("solid", fgColor="E6F4EA")    # Xanh lá nhạt
        fill_header = PatternFill("solid", fgColor="F1F3F4")
        fill_val = PatternFill("solid", fgColor="FFFFFF")

        font_title = Font(name="Times New Roman", size=13, bold=True, color="1B365D")
        font_sub = Font(name="Times New Roman", size=10, italic=True, color="555555")
        font_label = Font(name="Times New Roman", size=10, bold=True)
        font_val = Font(name="Times New Roman", size=11, bold=True, color="000080")
        font_h = Font(name="Times New Roman", size=10, bold=True)
        font_h_white = Font(name="Times New Roman", size=10, bold=True, color="FFFFFF")

        # 1. TIÊU ĐỀ & LƯU Ý
        ws["A1"] = f"BẢNG ĐÁP ÁN & CẤU HÌNH THANG ĐIỂM CHUẨN BỘ GD&ĐT: {subject.upper()} - {period.upper()}"
        ws["A1"].font = font_title

        ws["A2"] = "LƯU Ý: Thầy/cô có thể sửa điểm ở các ô màu trắng. Đề thi có bao nhiêu câu thì điền bấy nhiêu câu, câu không thi để trống hoàn toàn."
        ws["A2"].font = font_sub

        # 2. KHUNG CẤU HÌNH THANG ĐIỂM TRỰC QUAN (HÀNG 3 - 5)
        # Cột A-B: Thông tin chung
        ws["A3"] = "Tên bài kiểm tra:"
        ws["B3"] = f"{subject} - {period}"
        ws["A4"] = "Môn học:"
        ws["B4"] = subject
        ws["A5"] = "Năm học:"
        ws["B5"] = "2026-2027"

        # Cột C-D: Điểm Phần I & Phần III
        ws["C3"] = "Điểm 1 câu Phần I:"
        ws["D3"] = 0.25
        ws["C4"] = "Điểm 1 câu Phần III:"
        ws["D4"] = 0.25
        ws["C5"] = "Kỳ kiểm tra:"
        ws["D5"] = period

        # Cột E-H: BẢNG THANG ĐIỂM PHẦN II (ĐÚNG/SAI BẬC THANG)
        ws.merge_cells("E3:H3")
        ws["E3"] = "THANG ĐIỂM BẬC THANG PHẦN II (ĐÚNG / SAI BỘ GD&ĐT)"
        ws["E3"].font = font_label
        ws["E3"].alignment = Alignment(horizontal="center", vertical="center")
        ws["E3"].fill = fill_p2
        ws["E3"].border = thin

        # Hàng 4: Ô TRÊN - Tên mức đúng
        p2_headers = [("E4", "Đúng 1 ý"), ("F4", "Đúng 2 ý"), ("G4", "Đúng 3 ý"), ("H4", "Đúng 4 ý")]
        for cell_id, text in p2_headers:
            ws[cell_id] = text
            ws[cell_id].font = font_label
            ws[cell_id].alignment = Alignment(horizontal="center", vertical="center")
            ws[cell_id].fill = fill_header
            ws[cell_id].border = thin

        # Hàng 5: Ô DƯỚI - Số điểm tương ứng
        p2_scores = [("E5", 0.10), ("F5", 0.25), ("G5", 0.50), ("H5", 1.00)]
        for cell_id, val in p2_scores:
            ws[cell_id] = val
            ws[cell_id].font = font_val
            ws[cell_id].alignment = Alignment(horizontal="center", vertical="center")
            ws[cell_id].fill = fill_val
            ws[cell_id].border = thin

        # Định dạng viền và màu sắc khối A3..D5
        for r in range(3, 6):
            for c in ["A", "C"]:
                ws[f"{c}{r}"].font = font_label
                ws[f"{c}{r}"].fill = fill_header
                ws[f"{c}{r}"].border = thin
            for c in ["B", "D"]:
                ws[f"{c}{r}"].font = font_val if c == "D" else Font(name="Times New Roman", size=10)
                ws[f"{c}{r}"].fill = fill_val
                ws[f"{c}{r}"].border = thin
                if c == "D":
                    ws[f"{c}{r}"].alignment = Alignment(horizontal="center", vertical="center")

        # 3. HEADER BẢNG ĐÁP ÁN (DÒNG 7)
        header_row = 7
        headers = ["Mã Đề Thi"]
        col_types = ["CODE"]

        # 40 câu Phần I
        for i in range(1, cls.MAX_P1 + 1):
            headers.append(f"P1_C{i}")
            col_types.append("P1")

        # 8 câu Phần II (mỗi câu 4 ý a, b, c, d = 32 cột)
        for i in range(1, cls.MAX_P2 + 1):
            for sk in ["a", "b", "c", "d"]:
                headers.append(f"P2_C{i}_{sk}")
                col_types.append("P2")

        # 6 câu Phần III
        for i in range(1, cls.MAX_P3 + 1):
            headers.append(f"P3_C{i}")
            col_types.append("P3")

        for c_idx, (h_name, c_type) in enumerate(zip(headers, col_types), start=1):
            cell = ws.cell(row=header_row, column=c_idx, value=h_name)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin
            if c_type == "CODE":
                cell.font = font_h_white
                cell.fill = fill_navy
            elif c_type == "P1":
                cell.font = font_h
                cell.fill = fill_p1
            elif c_type == "P2":
                cell.font = font_h
                cell.fill = fill_p2
            else:
                cell.font = font_h
                cell.fill = fill_p3

        # 4. ĐIỀN DỮ LIỆU MẪU (2 MÃ ĐỀ 0504 & 0501)
        sample_rows = [
            ("0504", {
                "P1": ["B", "C", "A", "A", "C", "D", "C", "C", "B", "A", "C", "C", "C", "D", "A", "B"],
                "P2": [("Đ", "Đ", "Đ", "Đ"), ("Đ", "Đ", "Đ", "Đ")],
                "P3": ["214", "214", "1322"]
            }),
            ("0501", {
                "P1": ["B", "A", "B", "B", "D", "A", "D", "B", "D", "D", "A", "A", "A", "C", "D"],
                "P2": [("Đ", "S", "Đ", "S"), ("S", "S", "Đ", "Đ")],
                "P3": ["6", "2134", "10"]
            })
        ]

        for r_offset, (code, ans_dict) in enumerate(sample_rows, start=1):
            curr_r = header_row + r_offset
            row_data = [code]

            p1_vals = ans_dict.get("P1", [])
            for i in range(cls.MAX_P1):
                row_data.append(p1_vals[i] if i < len(p1_vals) else "")

            p2_tuples = ans_dict.get("P2", [])
            for q_i in range(cls.MAX_P2):
                if q_i < len(p2_tuples):
                    t_a, t_b, t_c, t_d = p2_tuples[q_i]
                    row_data.extend([t_a, t_b, t_c, t_d])
                else:
                    row_data.extend(["", "", "", ""])

            p3_vals = ans_dict.get("P3", [])
            for i in range(cls.MAX_P3):
                row_data.append(p3_vals[i] if i < len(p3_vals) else "")

            for c_idx, val in enumerate(row_data, start=1):
                cell = ws.cell(row=curr_r, column=c_idx, value=val)
                cell.font = Font(name="Times New Roman", size=11, bold=(c_idx == 1))
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.border = thin

        ws.column_dimensions["A"].width = 14
        ws.column_dimensions["B"].width = 24
        ws.column_dimensions["C"].width = 18
        ws.column_dimensions["D"].width = 14
        ws.column_dimensions["E"].width = 12
        ws.column_dimensions["F"].width = 12
        ws.column_dimensions["G"].width = 12
        ws.column_dimensions["H"].width = 12

        for col_idx in range(9, len(headers) + 1):
            letter = get_column_letter(col_idx)
            ws.column_dimensions[letter].width = 8

        # Xuất ra bộ nhớ (BytesIO) để chống hoàn toàn lỗi khóa file trên Windows
        mem_buffer = io.BytesIO()
        wb.save(mem_buffer)
        mem_buffer.seek(0)
        file_bytes = mem_buffer.getvalue()

        # Lưu xuống đĩa nếu có output_path
        if output_path is not None:
            try:
                output_path.parent.mkdir(exist_ok=True, parents=True)
                with open(output_path, "wb") as f:
                    f.write(file_bytes)
            except Exception as e:
                print(f"[!] Cảnh báo: Không thể ghi file ra đĩa (có thể đang mở trong Excel): {e}")

        return file_bytes

    @classmethod
    def parse_excel_config(cls, excel_path: Path) -> Dict[str, Any]:
        """
        Đọc cấu hình & barem đáp án từ file Excel.
        Hỗ trợ cấu hình Phần II ô trên (E4-H4) và ô dưới (E5-H5).
        """
        wb = openpyxl.load_workbook(excel_path, data_only=True)
        ws = wb.active

        exam_name = str(ws["B3"].value or "Bài kiểm tra trắc nghiệm").strip()

        # 1. Đọc điểm Phần I
        try:
            pts_p1 = float(ws["D3"].value)
        except (ValueError, TypeError):
            pts_p1 = 0.25

        # 2. Đọc điểm Phần III
        try:
            pts_p3 = float(ws["D4"].value)
        except (ValueError, TypeError):
            pts_p3 = 0.25

        # 3. Đọc thang điểm Phần II (Ô trên: E4-H4, Ô dưới: E5-H5)
        try:
            if ws["E5"].value is not None and ws["F5"].value is not None:
                v1 = float(ws["E5"].value)
                v2 = float(ws["F5"].value)
                v3 = float(ws["G5"].value) if ws["G5"].value is not None else 0.50
                v4 = float(ws["H5"].value) if ws["H5"].value is not None else 1.00
                p2_rule = {0: 0.0, 1: v1, 2: v2, 3: v3, 4: v4}
            else:
                raise ValueError("Use fallback")
        except Exception:
            raw_p2_rule = str(ws["D4"].value or "0.1, 0.25, 0.5, 1.0").strip()
            try:
                p2_list = [float(x.strip()) for x in raw_p2_rule.split(",")]
                p2_rule = {0: 0.0, 1: p2_list[0], 2: p2_list[1], 3: p2_list[2], 4: p2_list[3]}
            except Exception:
                p2_rule = {0: 0.0, 1: 0.1, 2: 0.25, 3: 0.5, 4: 1.0}

        # 4. Đọc Header ở dòng 7
        header_row = 7
        col_map = {}
        for c in range(1, ws.max_column + 1):
            v = ws.cell(row=header_row, column=c).value
            if v:
                col_map[c] = str(v).strip()

        # 5. Đọc Đáp án từng Mã đề
        answer_keys = {}
        for r in range(header_row + 1, ws.max_row + 1):
            code_v = ws.cell(row=r, column=1).value
            if not code_v:
                continue
            exam_code = str(code_v).strip().zfill(4)

            p1_dict = {}
            p2_dict = {}
            p3_dict = {}

            for c, h_name in col_map.items():
                if c == 1:
                    continue
                raw_cell = ws.cell(row=r, column=c).value
                if raw_cell is None:
                    continue
                ans_str = str(raw_cell).strip().upper()
                if not ans_str:
                    continue

                if h_name.startswith("P1_C"):
                    q_num = int(h_name.split("_C")[1])
                    p1_dict[q_num] = ans_str

                elif h_name.startswith("P2_C"):
                    parts = h_name.split("_")
                    q_num = int(parts[1][1:])
                    sub_k = parts[2].lower()
                    if q_num not in p2_dict:
                        p2_dict[q_num] = {}
                    p2_dict[q_num][sub_k] = ans_str

                elif h_name.startswith("P3_C"):
                    q_num = int(h_name.split("_C")[1])
                    try:
                        p3_dict[q_num] = float(ans_str.replace(",", "."))
                    except ValueError:
                        pass

            answer_keys[exam_code] = {
                "part1": p1_dict,
                "part2": p2_dict,
                "part3": p3_dict
            }

        return {
            "exam_name": exam_name,
            "config": {
                "pts_p1": pts_p1,
                "pts_p2_rule": p2_rule,
                "pts_p3": pts_p3
            },
            "answer_keys": answer_keys
        }

    @classmethod
    def smart_parse_text_keys(cls, text: str, default_made: str = "0001") -> Dict[str, Any]:
        """
        Bộ bóc tách đáp án thông minh từ văn bản thô (Word, Zalo, SMS, Excel copy-paste).
        Hỗ trợ dán đồng thời nhiều mã đề hoặc một mã đề đơn lẻ.
        """
        import re
        raw = str(text or "").replace("\r", "\n")
        made_blocks = re.split(r'(?i)(?:^|\n)\s*(?:MÃ ĐỀ|MÃ DE|MA DE|ĐỀ|DE)\s*[:#\s]*(\d+)', raw)
        
        answer_keys = {}
        if len(made_blocks) > 1 and made_blocks[1].isdigit():
            i = 1
            while i < len(made_blocks):
                code = made_blocks[i].strip().zfill(4)
                content = made_blocks[i+1] if i+1 < len(made_blocks) else ""
                answer_keys[code] = cls._parse_single_key_block(content)
                i += 2
        else:
            lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
            first_line = lines[0] if lines else ""
            code = default_made.zfill(4)
            body = raw
            if re.match(r'^\d{3,4}$', first_line):
                code = first_line.zfill(4)
                body = "\n".join(lines[1:])
            answer_keys[code] = cls._parse_single_key_block(body)
            
        return {
            "exam_name": "Nhập đáp án thông minh (Smart Paste)",
            "config": {
                "pts_p1": 0.25,
                "pts_p2_rule": {0: 0.0, 1: 0.1, 2: 0.25, 3: 0.5, 4: 1.0},
                "pts_p3": 0.25
            },
            "answer_keys": answer_keys
        }

    @classmethod
    @classmethod
    def _parse_single_key_block(cls, text: str) -> Dict[str, Any]:
        import re
        p1, p2, p3 = {}, {}, {}
        norm = text.upper().replace("Ð", "Đ")
        
        # Sắp xếp các cụm từ dài trước (III rồi II rồi I) để tránh khớp tiền tố nhầm lẫn
        sec_regex = r'(?i)(?:^|\n)\s*(PHẦN\s*III\b|PHAN\s*3\b|TLN\b|PHẦN\s*II\b|PHAN\s*2\b|DS\b|ĐS\b|PHẦN\s*I\b|PHAN\s*1\b|TN\b)\s*[:\-\.]?'
        matches = list(re.finditer(sec_regex, norm))
        
        p1_text, p2_text, p3_text = "", "", ""
        if matches:
            for idx, m in enumerate(matches):
                label = m.group(1).upper()
                start = m.end()
                end = matches[idx+1].start() if idx+1 < len(matches) else len(norm)
                chunk = norm[start:end]
                if any(k in label for k in ["III", "3", "TLN"]):
                    p3_text += "\n" + chunk
                elif any(k in label for k in ["II", "2", "DS", "ĐS"]):
                    p2_text += "\n" + chunk
                elif any(k in label for k in ["I", "1", "TN"]):
                    p1_text += "\n" + chunk
        else:
            lines_text = [l.strip() for l in norm.split("\n") if l.strip()]
            for line in lines_text:
                if re.search(r'[ĐS]', line) and not re.search(r'[A-D]', line):
                    p2_text += "\n" + line
                elif re.search(r'\d+(?:[.,]\d+)?', line) and not re.search(r'[A-DĐS]', line):
                    p3_text += "\n" + line
                else:
                    p1_text += "\n" + line

        # 1. Phần I
        p1_items = re.findall(r'(?:^|[\s;,]|câu\s*)(\d{1,2})[\.:\)\-\s]*([ABCD])\b', p1_text, re.IGNORECASE)
        if p1_items:
            for q_str, ans in p1_items:
                q_num = int(q_str)
                if 1 <= q_num <= cls.MAX_P1:
                    p1[q_num] = ans.upper()
        else:
            tokens = re.findall(r'\b[ABCD]+\b', p1_text)
            flat_chars = "".join(tokens)
            for idx, char in enumerate(flat_chars[:cls.MAX_P1], start=1):
                p1[idx] = char

        # 2. Phần II: Hỗ trợ linh hoạt cả khối câu 'Câu 1: a) Đ, b) S...' và dạng lặp '1a: Đ, 1b: S...'
        q_blocks = re.split(r'(?i)(?:^|\n)\s*(?:câu\s*)?(\d{1,2})\s*[:\.\)]', p2_text)
        if len(q_blocks) > 1:
            for i in range(1, len(q_blocks), 2):
                try:
                    q_num = int(q_blocks[i])
                    if 1 <= q_num <= cls.MAX_P2:
                        block = q_blocks[i+1]
                        subs = re.findall(r'([ABCDa-d])[\.:\)\-\s]*([ĐS])', block)
                        if subs:
                            p2[q_num] = {k.lower(): v for k, v in subs}
                except (ValueError, IndexError):
                    pass

        if not p2:
            p2_sub_items = re.findall(r'(?:^|[\s;,]|câu\s*)(\d{1,2})\s*([ABCDa-d])[\.:\)\-\s]*([ĐS])\b', p2_text, re.IGNORECASE)
            if p2_sub_items:
                for q_str, sub_key, val in p2_sub_items:
                    q_num = int(q_str)
                    if 1 <= q_num <= cls.MAX_P2:
                        if q_num not in p2:
                            p2[q_num] = {}
                        p2[q_num][sub_key.lower()] = val.upper()

        if not p2:
            for line in p2_text.split('\n'):
                line = line.strip()
                m = re.match(r'^(?:câu\s*)?(\d{1,2})[\.:\)\-\s]*([ĐS\s]{4,})', line, re.IGNORECASE)
                if m:
                    q_num = int(m.group(1))
                    chars = [c for c in m.group(2) if c in "ĐS"]
                    if len(chars) == 4 and 1 <= q_num <= cls.MAX_P2:
                        p2[q_num] = {"a": chars[0], "b": chars[1], "c": chars[2], "d": chars[3]}
            if not p2:
                all_ds = [c for c in p2_text if c in "ĐS"]
                num_rows = min(len(all_ds) // 4, cls.MAX_P2)
                for r_idx in range(num_rows):
                    chunk = all_ds[r_idx*4 : (r_idx+1)*4]
                    p2[r_idx + 1] = {"a": chunk[0], "b": chunk[1], "c": chunk[2], "d": chunk[3]}

        # 3. Phần III
        p3_items = re.findall(r'(?:^|[\s;,]|câu\s*)(\d{1,2})[:\)\.\s]+(-?\d+(?:[.,]\d+)?)\b', p3_text, re.IGNORECASE)
        if p3_items:
            for q_str, val_str in p3_items:
                q_num = int(q_str)
                if 1 <= q_num <= cls.MAX_P3:
                    try:
                        p3[q_num] = float(val_str.replace(",", "."))
                    except ValueError:
                        pass
        else:
            num_tokens = re.findall(r'-?\d+(?:[.,]\d+)?', p3_text)
            for idx, val_str in enumerate(num_tokens[:cls.MAX_P3], start=1):
                try:
                    p3[idx] = float(val_str.replace(",", "."))
                except ValueError:
                    pass

        return {"part1": p1, "part2": p2, "part3": p3}
