
## Chạy ngay trên máy này

Môi trường `.venv` và thư viện đã được cài trong thư mục ứng dụng.
Mở file `.streamlit/secrets.toml`, dán API key vào giữa dấu nháy kép và lưu:

```toml
GEMINI_API_KEY = "API_KEY_CUA_BAN"
OLPAI_PUBLIC_MODE = false
```

Sau đó mở PowerShell và chạy:

```powershell
Set-Location -LiteralPath 'D:\challenge CLB CNTT\chatbot_2000token\olpai-chat'
.\run.ps1
```

Mở **http://127.0.0.1:8501**. Dừng bằng `Ctrl+C`. Khi sửa key trong file,
bấm tải lại trang để app đọc key mới. File `secrets.toml` đã nằm trong `.gitignore`
và key không được ghi vào lịch sử chat. Nếu thiếu file, sao chép từ
`.streamlit/secrets.toml.example`.

Bạn vẫn có thể nhập key qua biến môi trường thay cho file:

```powershell
$chatSecureKey = Read-Host 'Nhap API key tu Google AI Studio' -AsSecureString
$env:GEMINI_API_KEY = [System.Net.NetworkCredential]::new('', $chatSecureKey).Password
.\run.ps1
```

## Kiểm tra

```powershell
# Tự động: không cần key, không gọi AI thật
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# Kết nối AI Studio thật: cần key, có thể phát sinh token/chi phí API
.\.venv\Scripts\python.exe check_api.py
```

## Cài lại môi trường khi chuyển máy

Yêu cầu Python 3.10 trở lên:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Phiên bản thư viện trực tiếp được cố định trong `requirements.txt`; toàn bộ môi
trường đã kiểm thử được ghi trong `requirements.lock.txt` (Windows, Python 3.10).
Không sao chép `.venv` giữa các máy. Muốn chuyển lịch sử, dừng app trước rồi sao
chép thư mục `data` cùng mã nguồn.

Mã chính: `app.py` (giao diện), `olpai/service.py` (luồng gửi), `olpai/gemini.py`
(SDK), `olpai/storage.py` (SQLite), `olpai/runtime.py` (khóa tiến trình/khôi phục).
