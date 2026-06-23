"""
用户认证与授权模块 - 支持角色管理
"""
import hashlib
import jwt
from datetime import datetime, timedelta
from pathlib import Path
import json
from typing import Dict, Optional
from enum import Enum

class UserRole(str, Enum):
    ADMIN = "admin"
    USER = "user"

SECRET_KEY = "your-secret-key-change-this-in-production"
ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 7

# 系统数据目录
SYSTEM_DIR = Path("data/system")
USERS_FILE = SYSTEM_DIR / "users.json"

def _ensure_system_dir():
    """确保系统目录存在"""
    SYSTEM_DIR.mkdir(parents=True, exist_ok=True)

def _load_users() -> Dict:
    """加载所有用户"""
    _ensure_system_dir()
    if USERS_FILE.exists():
        return json.loads(USERS_FILE.read_text(encoding='utf-8'))
    return {}

def _save_users(users: Dict):
    """保存用户数据"""
    USERS_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding='utf-8')

def hash_password(password: str) -> str:
    """密码哈希"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password: str, hash_val: str) -> bool:
    return hash_password(password) == hash_val

def create_token(username: str, role: str) -> str:
    """创建 JWT token（包含角色信息）"""
    payload = {
        "sub": username,
        "role": role,
        "exp": datetime.now() + timedelta(days=TOKEN_EXPIRE_DAYS),
        "iat": datetime.now()
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> Optional[Dict]:
    """解码 token，返回用户信息"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return {"username": payload.get("sub"), "role": payload.get("role")}
    except:
        return None

def register_user(username: str, password: str) -> Dict:
    """注册新用户（默认为普通用户）"""
    users = _load_users()
    if username in users:
        return {"success": False, "message": "用户名已存在"}
    
    users[username] = {
        "username": username,
        "password_hash": hash_password(password),
        "role": UserRole.USER,
        "created_at": datetime.now().isoformat(),
        "last_login": None
    }
    _save_users(users)
    
    # 创建用户数据目录
    from web.user_data import init_user_data_dir
    init_user_data_dir(username)
    
    # 初始化用户的 credentials（从全局 .credentials 复制配置）
    # 注释掉这整个 try-except 块，不要预填配置
    # try:
    #     from web.user_config import init_user_credentials_from_global
    #     init_user_credentials_from_global(username)
    # except Exception as e:
    #     print(f"[Auth] 初始化用户 {username} 凭证失败: {e}")
    
    return {"success": True, "message": "注册成功"}

def login_user(username: str, password: str) -> Dict:
    """用户登录"""
    users = _load_users()
    if username not in users:
        return {"success": False, "message": "用户名不存在"}
    
    if not verify_password(password, users[username]["password_hash"]):
        return {"success": False, "message": "密码错误"}
    
    # 更新最后登录时间
    users[username]["last_login"] = datetime.now().isoformat()
    _save_users(users)
    
    token = create_token(username, users[username]["role"])
    return {
        "success": True,
        "token": token,
        "username": username,
        "role": users[username]["role"]
    }

def create_admin_user(username: str, password: str) -> Dict:
    """创建管理员用户（首次部署时使用）"""
    users = _load_users()
    if username in users:
        return {"success": False, "message": "用户已存在"}
    
    users[username] = {
        "username": username,
        "password_hash": hash_password(password),
        "role": UserRole.ADMIN,
        "created_at": datetime.now().isoformat(),
        "last_login": None
    }
    _save_users(users)
    
    from web.user_data import init_user_data_dir
    init_user_data_dir(username)
    
    # 初始化用户的 credentials
    # try:
    #     from web.user_config import init_user_credentials_from_global
    #     init_user_credentials_from_global(username)
    # except Exception as e:
    #     print(f"[Auth] 初始化用户 {username} 凭证失败: {e}")
    
    return {"success": True, "message": "管理员创建成功"}

def list_all_users() -> list:
    """列出所有用户（仅管理员可调用）"""
    users = _load_users()
    return [
        {
            "username": u["username"],
            "role": u["role"],
            "created_at": u.get("created_at"),
            "last_login": u.get("last_login")
        }
        for u in users.values()
    ]

def delete_user(username: str) -> Dict:
    """删除用户及其所有数据（仅管理员）"""
    import shutil
    users = _load_users()
    if username not in users:
        return {"success": False, "message": "用户不存在"}
    
    if users[username]["role"] == UserRole.ADMIN:
        # 不能删除最后一个管理员
        admin_count = sum(1 for u in users.values() if u["role"] == UserRole.ADMIN)
        if admin_count <= 1:
            return {"success": False, "message": "不能删除最后一个管理员账号"}
    
    # 删除用户数据目录
    user_data_dir = Path(f"data/users/{username}")
    if user_data_dir.exists():
        shutil.rmtree(user_data_dir)
    
    # 删除用户记录
    del users[username]
    _save_users(users)
    
    return {"success": True, "message": f"用户 {username} 已删除"}