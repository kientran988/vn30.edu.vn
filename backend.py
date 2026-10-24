
import os
import re
import hmac
from pathlib import Path

import bcrypt
from fastapi import FastAPI, HTTPException, status, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from supabase import create_client, Client
import uvicorn

app = FastAPI(title="VN30.EDU.VN - Core Engine Giải Đấu Phái Sinh")

# Đường dẫn đến index.html nằm cùng thư mục với backend.py
BASE_DIR = Path(__file__).resolve().parent
INDEX_FILE = BASE_DIR / "index.html"


# Configure FRONTEND_ORIGINS in Render, comma-separated.
# Example: https://vn30edu.vn,https://www.vn30edu.vn
origins = [
    item.strip()
    for item in os.getenv("FRONTEND_ORIGINS", "").split(",")
    if item.strip()
]
if not origins:
    origins = [
        "https://vn30edu.vn",
        "https://www.vn30edu.vn",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Admin-Key"],
)


# Trang chủ: hiển thị giao diện index.html
@app.get("/", include_in_schema=False)
def homepage():
    if not INDEX_FILE.is_file():
        raise HTTPException(
            status_code=500,
            detail="Không tìm thấy index.html. Hãy đặt index.html cùng thư mục với backend.py trong GitHub."
        )
    return FileResponse(INDEX_FILE, media_type="text/html")


# In Render, set SUPABASE_URL and SUPABASE_KEY in Environment Variables.
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    supabase: Client | None = None
else:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

INITIAL_BALANCE = 100_000_000.00


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=20)
    phone_zalo: str = Field(..., pattern=r"^[0-9]{10}$")
    password: str = Field(..., min_length=8, max_length=128)


class UpdateBalanceRequest(BaseModel):
    phone_zalo: str = Field(..., pattern=r"^[0-9]{10}$")
    new_balance: float = Field(..., ge=0, le=INITIAL_BALANCE * 100)
    is_liquidated: bool


def get_supabase() -> Client:
    if supabase is None:
        raise HTTPException(
            status_code=503,
            detail="Backend chưa được cấu hình SUPABASE_URL/SUPABASE_KEY trên Render."
        )
    return supabase


def require_admin(x_admin_key: str | None) -> None:
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_API_KEY chưa được cấu hình trên Render."
        )
    if not x_admin_key or not hmac.compare_digest(x_admin_key, expected):
        raise HTTPException(
            status_code=401,
            detail="Không có quyền thực hiện thao tác quản trị."
        )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "database_configured": supabase is not None
    }


@app.post("/api/v1/auth/register", status_code=status.HTTP_201_CREATED)
def register_trader(data: RegisterRequest):
    """Create a trader and grant 100,000,000 VND virtual balance."""
    db = get_supabase()
    username = data.username.strip()
    phone = data.phone_zalo.strip()

    if len(username) < 2:
        raise HTTPException(
            status_code=422,
            detail="Tên hiển thị cần ít nhất 2 ký tự."
        )

    try:
        existing_user = (
            db.table("tournament_traders")
            .select("phone_zalo")
            .eq("phone_zalo", phone)
            .limit(1)
            .execute()
        )
        if existing_user.data:
            raise HTTPException(
                status_code=409,
                detail="Số điện thoại này đã đăng ký tham gia."
            )

        password_hash = bcrypt.hashpw(
            data.password.encode("utf-8"),
            bcrypt.gensalt(rounds=12)
        ).decode("utf-8")

        new_trader = {
            "username": username,
            "phone_zalo": phone,
            "password_hash": password_hash,
            "balance": INITIAL_BALANCE,
            "is_liquidated": False,
        }
                db.table("tournament_traders").insert(new_trader).execute()

        return {
            "status": "success",
            "message": "Đăng ký VN30 thành công! Bạn đã nhận 100 triệu VND vốn ảo.",
            "data": {"username": username, "balance": INITIAL_BALANCE},
        }

    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.exception("Lỗi đăng ký tài khoản VN30 khi ghi vào Supabase")
        raise HTTPException(
            status_code=500,
            detail=f"Lỗi lưu tài khoản: {str(e)}"
        )


@app.get("/api/v1/trader/{phone_zalo}")
def get_trader_status(phone_zalo: str):
    """Return public trader status only; never expose password_hash."""
    if not re.fullmatch(r"[0-9]{10}", phone_zalo):
        raise HTTPException(
            status_code=422,
            detail="Số điện thoại không hợp lệ."
        )

    db = get_supabase()
    try:
        result = (
            db.table("tournament_traders")
            .select("username,phone_zalo,balance,is_liquidated")
            .eq("phone_zalo", phone_zalo)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise HTTPException(
                status_code=404,
                detail="Không tìm thấy tài khoản."
            )
        return result.data[0]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Không thể đọc trạng thái tài khoản."
        )


@app.post("/api/v1/trader/update-status")
def update_trader_status(
    data: UpdateBalanceRequest,
    x_admin_key: str | None = Header(default=None),
):
    """Admin/server-only endpoint. Do not call from public browser JavaScript."""
    require_admin(x_admin_key)
    db = get_supabase()
    try:
        result = (
            db.table("tournament_traders")
            .update({
                "balance": data.new_balance,
                "is_liquidated": data.is_liquidated,
            })
            .eq("phone_zalo", data.phone_zalo)
            .execute()
        )
        if not result.data:
            raise HTTPException(
                status_code=404,
                detail="Không tìm thấy tài khoản để cập nhật."
            )
        if data.is_liquidated:
            return {
                "status": "locked",
                "message": "Tài khoản đã bị khóa do cháy vốn ảo."
            }
        return {
            "status": "success",
            "message": "Đã đồng bộ số dư."
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Không thể cập nhật trạng thái tài khoản."
        )


@app.post("/api/v1/tournament/reset-weekly")
def reset_weekly_tournament(x_admin_key: str | None = Header(default=None)):
    """Admin-only endpoint. Protect with ADMIN_API_KEY in Render."""
    require_admin(x_admin_key)
    db = get_supabase()
    try:
        db.table("tournament_traders").update({
            "balance": INITIAL_BALANCE,
            "is_liquidated": False,
        }).neq("phone_zalo", "").execute()
        return {
            "status": "success",
            "message": "Đã reset vốn ảo về 100 triệu VND cho mùa giải mới."
        }
    except Exception:
        raise HTTPException(
            status_code=500,
            detail="Không thể reset giải đấu."
        )


if __name__ == "__main__":
    uvicorn.run(
        "backend:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000"))
    )

