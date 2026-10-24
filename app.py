import os
from pathlib import Path
import re
import secrets

import streamlit as st

from olpai.config import load_api_key, load_public_mode
from olpai.gemini import GeminiGateway
from olpai.models import ChatError, DEFAULT_MODEL, TOKEN_LIMIT
from olpai.runtime import Runtime
from olpai.service import ChatService
from olpai.storage import Store

st.set_page_config(page_title="OLPAI · 2.000 token", page_icon=":material/chat:", layout="centered")

@st.cache_resource(on_release=lambda value: value.lock.close())
def get_runtime(data_dir: str) -> Runtime:
    return Runtime(Path(data_dir))


@st.cache_resource(scope="session", max_entries=1, on_release=lambda value: value.client.close())
def get_gateway(api_key: str) -> GeminiGateway:
    return GeminiGateway(api_key)


project_dir = Path(__file__).resolve().parent
st.session_state.setdefault("visitor_api_key", "")
st.session_state.setdefault("suppress_local_key", False)
st.session_state.setdefault("restore_drafts", {})
st.session_state.setdefault("api_key_dialog_open", False)
try:
    public_mode = load_public_mode(project_dir)
    local_key = "" if public_mode or st.session_state.suppress_local_key else load_api_key(project_dir)
except ChatError as exc:
    st.error(str(exc))
    st.stop()
api_key = st.session_state.visitor_api_key or local_key


def dismiss_api_key_dialog():
    st.session_state.api_key_dialog_open = False


@st.dialog("API key Gemini", icon=":material/key:", on_dismiss=dismiss_api_key_dialog)
def api_key_dialog():
    st.caption("Key chỉ dùng trong phiên trình duyệt này. Tải lại trang cần nhập lại key.")
    st.caption("Key được gửi tới máy chủ ứng dụng để gọi Gemini; không ghi vào file hoặc lịch sử chat.")
    st.link_button("Lấy key từ Google AI Studio", "https://aistudio.google.com/apikey")
    with st.form("api_key_form", clear_on_submit=True):
        entered_key = st.text_input("API key của bạn", type="password", key="api_key_entry", autocomplete="off")
        submitted = st.form_submit_button("Dùng API key", type="primary", width="stretch")
    if submitted:
        if not entered_key or not entered_key.strip():
            st.error("Hãy nhập API key trước khi tiếp tục.")
        else:
            get_gateway.clear()
            st.session_state.visitor_api_key = entered_key.strip()
            st.session_state.suppress_local_key = True
            st.session_state.api_key_dialog_open = False
            st.session_state["key_notice"] = "Đã nhập API key cho phiên này."
            st.rerun()


st.html("""
<style>
#MainMenu { display: none; }
[data-testid="stAppDeployButton"] { display: none; }
[data-testid="stToolbarActions"] { margin-right: 3rem; }
.st-key-api_menu {
    position: fixed;
    top: 0.6rem;
    right: 0.65rem;
    width: auto !important;
    z-index: 1000000;
}
.st-key-api_menu button { min-width: 2rem; padding: 0.3rem 0.45rem; }
.st-key-api_menu button [aria-hidden="true"] { display: none; }
.st-key-api_menu button p { font-size: 1.6rem; line-height: 1; }
</style>
""")
key_actions = ["Nhập / đổi API key"]
if api_key:
    key_actions.append("Xóa API key khỏi phiên")
key_action = st.menu_button("⋮", key_actions, key="api_menu", help="Cài đặt API key", type="tertiary")
if key_action == "Nhập / đổi API key":
    st.session_state.api_key_dialog_open = True
elif key_action == "Xóa API key khỏi phiên":
    get_gateway.clear()
    st.session_state.visitor_api_key = ""
    st.session_state.suppress_local_key = True
    st.session_state["key_notice"] = "Đã xóa API key khỏi phiên này."
    st.rerun()
if st.session_state.api_key_dialog_open:
    api_key_dialog()

data_dir = os.environ.get("OLPAI_DATA_DIR", str(Path(__file__).resolve().parent / "data"))
if public_mode:
    workspace_id = st.query_params.get("workspace", "")
    if not re.fullmatch(r"[0-9a-f]{64}", workspace_id):
        workspace_id = secrets.token_hex(32)
        st.query_params["workspace"] = workspace_id
    data_dir = str(Path(data_dir) / "public")
try:
    runtime = get_runtime(data_dir)
except RuntimeError as exc:
    st.error(str(exc))
    st.stop()
store = runtime.workspace_store(workspace_id) if public_mode else runtime.store
if getattr(store, "BUDGET_VERSION", 1) != Store.BUDGET_VERSION:
    runtime.store = store = Store(store.path)
model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)


def new_chat():
    st.session_state["session"] = store.create_session(model)


sessions = store.list_sessions()
if not sessions:
    new_chat()
    sessions = store.list_sessions()
session_by_id = {session["id"]: session for session in sessions}
if st.session_state.get("session") not in session_by_id:
    st.session_state["session"] = sessions[0]["id"]

with st.sidebar:
    st.button("New chat", icon=":material/add:", on_click=new_chat, width="stretch")
    selected = st.radio(
        "Các cuộc trò chuyện", list(session_by_id), index=None,
        format_func=lambda sid: session_by_id[sid]["title"],
        key="session", bind="query-params", width="stretch",
    )
    st.caption("Lịch sử được lưu riêng cho lượt truy cập này." if public_mode else "Lịch sử được lưu tự động trên máy này.")
    st.button("Làm mới trạng thái", icon=":material/refresh:", width="stretch")

if not selected or selected not in session_by_id:
    st.info("Chọn một session hoặc bấm New chat.")
    st.stop()
session = store.get_session(selected)
remaining = TOKEN_LIMIT - session["used_tokens"]
token_background = st.get_option("theme.backgroundColor") or (
    "#0e1117" if st.context.theme.type == "dark" else "#ffffff"
)
st.html(f"""
<style>
.st-key-session [data-testid="stRadioGroup"] {{
    gap: 0.5rem;
}}
.st-key-session [data-testid="stRadioGroup"] > div {{
    width: 100%;
}}
.st-key-session [data-testid="stRadioOption"] {{
    display: block;
    width: 100%;
    min-height: 3rem;
    margin: 0;
    padding: 0.75rem 0.875rem;
    border: 1px solid color-mix(in srgb, currentColor 20%, transparent);
    border-radius: 0.625rem;
    background: color-mix(in srgb, currentColor 3%, transparent);
    cursor: pointer;
    transition: background 120ms ease, border-color 120ms ease;
}}
.st-key-session [data-testid="stRadioOption"] > div > div:first-child {{
    display: none;
}}
.st-key-session [data-testid="stRadioOption"] p {{
    margin: 0;
    white-space: normal;
    overflow-wrap: anywhere;
}}
.st-key-session [data-testid="stRadioOption"]:hover {{
    background: color-mix(in srgb, currentColor 7%, transparent);
    border-color: color-mix(in srgb, currentColor 35%, transparent);
}}
.st-key-session [data-testid="stRadioOption"][data-selected="true"] {{
    border-color: #4b9cff;
    background: rgba(59, 130, 246, 0.12);
    box-shadow: inset 3px 0 #4b9cff;
}}
.st-key-session [data-testid="stRadioOption"][data-selected="true"] p {{
    font-weight: 600;
}}
.st-key-session [data-testid="stRadioOption"][data-focus-visible="true"] {{
    outline: 2px solid #4b9cff;
    outline-offset: 2px;
}}
[data-testid="stLayoutWrapper"]:has(> .st-key-token_bar) {{
    position: sticky;
    top: 3.75rem;
    z-index: 100;
    background: {token_background};
    padding: 0.5rem 0;
    border-bottom: 1px solid rgba(128, 128, 128, 0.25);
}}
</style>
""")
with st.container(key="token_bar", gap="small"):
    st.progress(session["used_tokens"] / TOKEN_LIMIT,
                text=f"Input + output: {session['used_tokens']} / 2.000 token — Còn {remaining}")
    st.caption(
        f"Input: {session['input_tokens']} · Output: {session['output_tokens']} · "
        f"Thinking: {session['thinking_tokens']} (không trừ hạn mức)"
    )
st.subheader(session["title"])
st.caption(
    f"Model yêu cầu: {session['model']} · "
    f"Model phản hồi: {session['actual_model'] or 'chưa có phản hồi'}"
)

notice = st.session_state.pop("notice", None)
if notice:
    st.error(notice)
key_notice = st.session_state.pop("key_notice", None)
if key_notice:
    st.success(key_notice)
if not api_key:
    st.info("Mở menu ⋮ ở góc trên bên phải → Nhập / đổi API key để bắt đầu.")

messages = store.messages(selected)
if not messages:
    st.info("Nhập câu hỏi, dán code hoặc traceback để bắt đầu. Session này có context riêng.")
for message in messages:
    with st.chat_message(message["role"]):
        if message["content"]:
            if message["role"] == "user":
                st.text(message["content"])
            else:
                st.markdown(message["content"])
        elif message["finish_reason"] == "INPUT_EXHAUSTED":
            st.caption("Tin nhắn đã dùng hết ngân sách; không gọi AI.")
        else:
            st.caption("AI không trả văn bản. Thinking chỉ được thống kê, không trừ hạn mức.")
        if message["role"] == "assistant":
            st.caption(
                f"Output: {message['token_count']} · Thinking: {message['thinking_tokens']} · "
                f"Kết thúc: {message['finish_reason']}"
            )
            if message["finish_reason"] in {"MAX_TOKENS", "LOCAL_TOKEN_LIMIT"}:
                st.warning("AI đã chạm giới hạn đầu ra. Câu trả lời có thể bị cắt giữa câu hoặc code.")

if session["status"] == "exhausted":
    st.warning("Session đã hết 2.000 token. Bấm New chat để tiếp tục với context trống.")
elif session["status"] == "locked":
    st.error(session["lock_reason"] or "Không xác định được token đã tiêu. Session đã bị khóa.")
    st.caption("Bộ đếm chỉ thể hiện token đã xác nhận. Bạn vẫn có thể đọc và sao chép lịch sử.")
elif session["status"] == "busy":
    st.info("Session đang xử lý một lượt gửi. Bấm Làm mới trạng thái sau khi lượt đó hoàn tất.")

chat_key = f"chat_{selected}"
draft = st.session_state.restore_drafts.pop(selected, None)
if draft is not None:
    st.session_state[chat_key] = draft
text = st.chat_input(
    "Nhập text hoặc dán code…", key=chat_key, accept_file=False,
    accept_audio=False, submit_mode="disable",
    disabled=session["status"] != "active" or not api_key,
)
if text is not None:
    try:
        with st.spinner("Đang đếm token và chờ AI…"):
            ChatService(store, get_gateway(api_key)).send_turn(selected, text)
    except ChatError as exc:
        st.session_state.restore_drafts[selected] = text
        st.session_state["notice"] = str(exc)
    st.rerun()
