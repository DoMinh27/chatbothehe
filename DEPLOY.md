# Public app từ GitHub

Mã nguồn có sẵn luồng **⋮ → Nhập / đổi API key → Dùng API key**. Mỗi người nhập
key của mình; không cần đăng nhập app. Hạn mức vẫn là 2.000 token input + output
mỗi cuộc trò chuyện, thinking ở mức MINIMAL và không trừ hạn mức.

## Tạo repo và link Streamlit Community Cloud

1. Dùng các file bên trong `dist/olpai-chat-public.zip` để tạo repo GitHub.
   Gói này chỉ chứa mã nguồn, không có key cá nhân, dữ liệu chat hoặc `.venv`.
2. Đăng nhập [Streamlit Community Cloud](https://share.streamlit.io/), chọn
   **Create app**, chọn repo và branch của bạn.
3. **Main file path**: `app.py` nếu bạn đặt mã nguồn ở gốc repo.
   Chọn Python 3.12 trong phần Advanced settings.
4. Trong **Secrets**, chỉ cần nhập cấu hình sau, không nhập key cá nhân:

   ```toml
   OLPAI_PUBLIC_MODE = true
   ```

5. Deploy rồi chia sẻ link có dạng `https://ten-app.streamlit.app/`.
6. Người truy cập bấm **⋮** góc trên phải, nhập API key Google AI Studio của họ,
   bấm **Dùng API key** rồi chat.

[Hướng dẫn deploy chính thức](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).
GitHub chứa source; app cần máy chủ Python như Streamlit Community Cloud để chạy.

## Key và lịch sử riêng

- Public là chế độ mặc định khi không có cấu hình cá nhân. Trong chế độ này,
  app không dùng key từ biến `GEMINI_API_KEY` hoặc file secrets của máy chủ.
- Key nhập ở menu chỉ nằm trong bộ nhớ phiên trình duyệt, không ghi vào SQLite,
  file, URL hoặc cache dùng chung. Tải lại trang cần nhập lại key.
- Nút **Xóa API key khỏi phiên** đóng kết nối của chính phiên đó và khóa ô gửi
  cho đến khi nhập key khác; không ảnh hưởng key của người khác.
- Mỗi lượt truy cập mới có một mã workspace ngẫu nhiên trong URL; các cuộc trò
  chuyện của workspace được lưu trong SQLite riêng. Tải lại đúng URL sẽ mở lại
  lịch sử đó. Mã này là quyền truy cập lịch sử ẩn danh: khi chia sẻ app cho người
  khác, hãy chia sẻ link gốc **không có `?workspace=...` và `session=...`**.
- Key được gửi qua kết nối tới máy chủ Streamlit để gọi Google Gemini; app
  không chạy Gemini trực tiếp trong trình duyệt. API usage/quota thuộc key của
  người nhập. Tính phí Google có thể bao gồm thinking và phần output bị cắt.
- SQLite trên hosting miễn phí không phải kho lưu trữ lâu dài; lịch sử có thể
  bị mất khi máy chủ được tạo lại hoặc redeploy. Bản local vẫn lưu ở thư mục `data`.

## Chạy local với key trong file

File `.streamlit/secrets.toml` cá nhân dùng cấu hình:

```toml
GEMINI_API_KEY = "key_cua_ban"
OLPAI_PUBLIC_MODE = false
```

Menu nhập key vẫn hoạt động và ưu tiên key riêng của phiên hơn key trong file.
Không đưa `secrets.toml` lên GitHub; file đã được `.gitignore` loại trừ.
Chế độ public dùng vùng dữ liệu `data/public`, không đưa lịch sử local cá nhân
ra danh sách chat của khách truy cập.

Để tạo lại gói source sau khi chỉnh code:

```powershell
.\.venv\Scripts\python.exe package_public.py
```

Để thử public trên máy cá nhân:

```powershell
$env:OLPAI_PUBLIC_MODE = 'true'
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

Muốn dùng server khác, cài `requirements.txt`, đặt `OLPAI_PUBLIC_MODE=true` và
chạy `streamlit run app.py --server.address 0.0.0.0 --server.port 8501` sau HTTPS
reverse proxy của nền tảng hosting.
