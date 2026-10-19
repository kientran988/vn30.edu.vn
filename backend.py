import os
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client, Client
import uvicorn

app = FastAPI(title="VN30.EDU.VN - Core Engine Giải Đấu Phái Sinh")

# BẬT CORS: Cho phép giao diện frontend index.html gọi dữ liệu an toàn
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Trong thực tế bạn thay bằng https://vn30.edu.vn
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# THÔNG TIN KẾT NỐI ĐÁM MÂY SUPABASE
# Hãy thay thế các thông số này bằng URL và KEY từ dự án Supabase cá nhân của bạn
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://iqatavayvuzsgfigmwtx.supabase.co/rest/v1/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_publishable_Z3FgUuuoS-KJPZVqjn2bJA_Lo3MZdWg")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Định dạng dữ liệu đăng ký đầu vào chuẩn bảo mật
class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=20)
    phone_zalo: str = Field(..., pattern=r"^[0-9]{10}$") # Bắt buộc là số điện thoại 10 số
    password: str = Field(..., min_length=6)

class UpdateBalanceRequest(BaseModel):
    phone_zalo: str
    new_balance: float
    is_liquidated: bool

@app.post("/api/v1/auth/register", status_code=status.HTTP_201_CREATED)
def register_trader(data: RegisterRequest):
    """API xử lý đăng ký thành viên mới và cấp 100 triệu VND ảo"""
    try:
        # Kiểm tra xem số điện thoại Zalo này đã đăng ký tham gia giải đấu chưa
        existing_user = supabase.table("tournament_traders").select("phone_zalo").eq("phone_zalo", data.phone_zalo).execute()
        if existing_user.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="❌ Số điện thoại Zalo này đã đăng ký tham gia cuộc thi tuần này rồi!"
            )
        
        # Tiến hành nạp dữ liệu người chơi mới lên Đám mây
        new_trader = {
            "username": data.username,
            "phone_zalo": data.phone_zalo,
            "password_hash": data.password, # Trong production thực tế nên hash bằng bcrypt
            "balance": 100000000.00,
            "is_liquidated": False
        }
        
        response = supabase.table("tournament_traders").insert(new_trader).execute()
        return {
            "status": "Thành công",
            "message": "🎉 Chúc mừng bạn đã đăng ký Đấu trường VN30.EDU.VN thành công!",
            "data": {"username": data.username, "balance": 100000000.00}
        }
        
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=f"Lỗi kết nối cơ sở dữ liệu: {str(e)}")

@app.get("/api/v1/trader/{phone_zalo}")
def get_trader_status(phone_zalo: str):
    """API đồng bộ trạng thái số dư và kiểm tra tài khoản đã bị khóa cháy chưa"""
    user = supabase.table("tournament_traders").select("*").eq("phone_zalo", phone_zalo).execute()
    if not user.data:
        raise HTTPException(status_code=404, detail="Không tìm thấy thông tin tài khoản người chơi")
    return user.data[0]

@app.post("/api/v1/trader/update-status")
def update_trader_status(data: UpdateBalanceRequest):
    """API lưu trữ số dư thời gian thực và thực thi lệnh khóa tài khoản khi cháy"""
    try:
        response = supabase.table("tournament_traders").update({
            "balance": data.new_balance,
            "is_liquidated": data.is_liquidated
        }).eq("phone_zalo", data.phone_zalo).execute()
        
        if data.is_liquidated:
            return {"status": "Locked", "message": "🚨 Hệ thống Risk Engine đã khóa tài khoản do cháy!"}
        return {"status": "Đồng bộ thành công"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/tournament/reset-weekly")
def reset_weekly_tournament():
    """API Admin dùng vào sáng thứ Hai hằng tuần để Hồi sinh tất cả tài khoản về 100 triệu"""
    try:
        # Reset toàn bộ bảng về trạng thái ban đầu để mở mùa giải mới
        response = supabase.table("tournament_traders").update({
            "balance": 100000000.00,
            "is_liquidated": False
        }).neq("phone_zalo", "").execute() # Thực thi trên toàn bộ danh sách khách hàng
        return {"status": "Thành công", "message": "🔄 Toàn bộ đấu trường đã được Hồi sinh về mốc 100M VND!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    # Khởi chạy server ảo tại cổng 8000
    uvicorn.run("backend.py:app", host="0.0.0.0", port=8000, reload=True)
