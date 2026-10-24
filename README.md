# Chatbot luyện thi OLPAI — 2.000 token/session

Ứng dụng Streamlit, chỉ nhập text, dùng Google AI Studio. Mỗi session có context riêng
và hạn mức 2.000 token **chỉ tính input + output**. Thinking được thống kê riêng,
không trừ hạn mức. Lịch sử và bộ đếm lưu bằng SQLite.

## Nhập API key ngay trong app

Bấm **⋮** ở góc trên phải → **Nhập / đổi API key**, dán key vào ô mật khẩu rồi
bấm **Dùng API key**. Có thể chọn **Xóa API key khỏi phiên** để ngừng sử dụng key.
Key nhập theo cách này chỉ tồn tại trong phiên trình duyệt; tải lại trang cần
nhập lại. Key không được lưu vào file, URL hoặc lịch sử chat.

App hỗ trợ public từ repo GitHub qua Streamlit Community Cloud. Xem [DEPLOY.md](DEPLOY.md)
để tạo link cho mọi người sử dụng key riêng. Gói source để upload nằm tại
`dist/olpai-chat-public.zip`; gói không chứa key và dữ liệu chat cá nhân.

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

Biến môi trường có ưu tiên cao hơn file và chỉ áp dụng cho cửa sổ PowerShell hiện
tại. Nếu muốn chuyển về key trong file, chạy `Remove-Item Env:GEMINI_API_KEY`
rồi khởi động lại app. `check_api.py` cũng đọc key theo cùng quy tắc.

Nếu chính sách PowerShell chặn chạy `run.ps1`, dùng trực tiếp:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Nếu cổng đang bận, dừng app cũ hoặc chạy `.\run.ps1 -Port 8502` và mở cổng tương ứng.
Chỉ một tiến trình app được sử dụng cùng một thư mục dữ liệu; các tab trình duyệt
vẫn có thể mở đồng thời.

Lấy key tại [Google AI Studio](https://aistudio.google.com/apikey).
Model mặc định là `gemini-3.5-flash`. Theo [tài liệu Google](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash),
ID này có thể được Google chuyển sang 3.6 Flash. App hiển thị `model_version` thực
tế API trả về. Không có chức năng tự đổi model khi lỗi. Muốn đổi cấu hình cho
session **mới**, đặt `$env:GEMINI_MODEL = 'model-id'` trước khi chạy; session cũ giữ
model đã chọn lúc tạo.

## Cách dùng

1. Bấm **New chat** để bắt đầu session trống. Số session không bị giới hạn.
2. Gõ/dán text, code hoặc traceback; dùng `Shift+Enter` để xuống dòng.
3. Theo dõi tổng token và ba phần Input / Output / Thinking.
4. Toàn bộ session được liệt kê trực tiếp trong thanh bên; chọn để đọc hoặc tiếp
   tục nếu còn token. Thanh token luôn ở trên cùng khi cuộn hội thoại.
5. Code trong câu trả lời giữ định dạng và có nút copy của khối code. Nội dung
   không bị thêm ký tự để hoàn thiện câu hoặc đóng khối code bị cắt.

Không hỗ trợ file, ảnh, âm thanh, web search, chạy code, sửa tin nhắn, đồng hồ thi
hoặc bộ nhớ giữa các session. Nội dung các session khác không được gửi đến AI.

## Quy tắc đếm token

```text
used = tổng count_tokens(text người dùng mới)
     + tổng token câu trả lời được giữ lại
remaining = 2000 - used
```

- Input mới được đếm bằng endpoint `count_tokens` của chính model. Không ước lượng
  bằng ký tự; giữ nguyên tiếng Việt, emoji, khoảng trắng và xuống dòng.
- Mỗi tin nhắn chỉ tính một lần. Lịch sử gửi lại không trừ thêm vào ngân sách luyện
  tập. Đây là hạn mức của ứng dụng, **không phải** tổng token tính phí qua các lượt.
- Input vượt phần còn lại bị chặn; text được trả lại ô nhập để sửa.
- Input vừa hết phần còn lại được lưu, không gọi AI.
- Vì giới hạn API gồm cả thinking, app gửi `max_output_tokens=remaining+2048`
  để dành khoảng riêng cho thinking. Giữ `thinking_level=MINIMAL`; số thinking
  được API báo về chỉ phục vụ thống kê, không làm hết ngân sách luyện tập.
- Nếu token câu trả lời vượt phần còn lại, app đếm các tiền tố văn bản bằng
  `count_tokens` của Gemini và chỉ lưu/hiển thị một tiền tố đã xác nhận vừa hạn
  mức. Giữ nguyên Unicode, không tự hoàn thiện câu hay code. Phần bị cắt không
  được đưa vào context lượt sau. Việc đếm tiền tố có thể cần thêm vài lời gọi API.
- Câu trả lời không bị cắt dùng `candidates_token_count`; câu bị cắt dùng số token
  của tiền tố được giữ lại. Chi phí API vẫn có thể bao gồm thinking và phần output
  bị loại, độc lập với bộ đếm 2.000 token của app.
- Nếu AI chỉ suy nghĩ mà không trả văn bản, chỉ input mới bị trừ hạn mức; app
  không tự sinh lại. Usage metadata không đầy đủ/nhất quán vẫn khóa session.
- Session đạt 2.000 token chỉ đọc/sao chép được. Session trả lời ngắn có thể còn
  token để hỏi tiếp; không ép dùng hết 2.000.

Tham khảo [cách đếm token](https://ai.google.dev/gemini-api/docs/generate-content/tokens)
và [giới hạn cả thinking + output](https://ai.google.dev/gemini-api/docs/generate-content/thinking#token-limits-and-max_output_tokens).
Cách tính ngân sách trên là quy ước luyện tập đã chốt, chưa coi là bộ đếm nội bộ
được BTC OLPAI xác nhận.

## Lưu trữ và lỗi

- Dữ liệu nằm trong `data/chat.sqlite3`, độc lập với session tạm của Streamlit.
  URL ghi ID session đang chọn để có thể tải lại đúng cuộc trò chuyện.
- Khi nâng cấp từ cách tính cũ, app tự sao lưu SQLite vào `data/backups/` rồi
  tính lại `used_tokens=input_tokens+output_tokens`. Lịch sử và số thinking được
  giữ nguyên; session từng hết hạn mức do thinking có thể tiếp tục nếu còn token.
  Session bị khóa do usage không xác định vẫn giữ khóa vì phản hồi cũ không được lưu.
- Bảng `sessions` lưu ngân sách, model và trạng thái; `turns` ghi vòng đời lượt
  gửi; `messages` lưu text và số token. Không lưu API key hoặc phản hồi thô.
- Cập nhật SQLite theo transaction, khóa lượt khi đang sinh; hai tab không thể
  cùng tiêu ngân sách của một session. Lượt có ID đã xử lý không sinh lại.
- Lỗi xác thực/validation/quota bị API từ chối rõ ràng: hoàn tác lượt, trả lại
  ngân sách và text. Không có automatic retry hoặc automatic continuation.
- Timeout, lỗi server/mạng, thiếu usage hoặc app dừng giữa lượt: khóa session vì
  không xác định được token đã tiêu. Bộ đếm khi đó chỉ thể hiện phần đã xác nhận.
  Tạo session mới để tiếp tục; lịch sử cũ vẫn đọc được.
- Không xóa file `.app.lock` để mở khóa: khóa thuộc hệ điều hành, tự nhả khi tiến
  trình kết thúc. Session gián đoạn vẫn bị khóa khi app khởi động lại.

## Kiểm tra

```powershell
# Tự động: không cần key, không gọi AI thật
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# Kết nối AI Studio thật: cần key, có thể phát sinh token/chi phí API
.\.venv\Scripts\python.exe check_api.py
```

Kiểm thử gồm ranh giới 1.999/2.000/2.001, thinking không trừ hạn mức, cắt output,
chuyển đổi và sao lưu dữ liệu cũ, context độc lập, nhiều lượt, Unicode/code, không
retry, lỗi/khởi động lại, gửi đồng thời, hợp đồng request của SDK và thao tác giao
diện bằng Streamlit AppTest. Mock HTTP không thay thế
kiểm tra thực tế bằng API key của bạn.

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
