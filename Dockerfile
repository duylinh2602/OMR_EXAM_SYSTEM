FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7860

WORKDIR /app

# Cài đặt thư viện hệ thống tối thiểu cho OpenCV Headless và PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Khởi tạo thư mục dữ liệu với toàn quyền đọc ghi
RUN mkdir -p output/web_uploads output/graded_sheets && \
    chmod -R 777 output

EXPOSE 7860

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-7860}"]
