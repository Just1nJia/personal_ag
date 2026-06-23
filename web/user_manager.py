"""
用户管理模块
处理用户登录、注册、session管理
"""
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict
import config

USERS_FILE = config.DATA_DIR / "system" / "users.json"
USERS_DIR = config.DATA_DIR / "users"

# ── 会话管理 ──────────────────────────────────────────────────────────────

_CURRENT_USER = None

def set_current_user(username: str):
    """设置当前登录用户"""
    global _CURRENT_USER
    _CURRENT_USER = username

def get_current_user() -> str:
    """获取当前登录用户"""
    return _CURRENT_USER or "admin"

def is_logged_in() -> bool:
    """检查是否已登录"""
    return _CURRENT_USER is not None

# ── 目录和文件管理 ──────────────────────────────────────────────────────────

def _ensure_dirs():
    """确保用户相关目录存在"""
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_DIR.mkdir(parents=True, exist_ok=True)
    
    if not USERS_FILE.exists():
        _create_default_admin()

def _create_default_admin():
    """创建默认管理员账户"""
    password_hash = hashlib.sha256("admin123".encode()).hexdigest()
    
    users = {
        "admin": {
            "password_hash": password_hash,
            "created_at": datetime.now().isoformat(),
            "role": "admin",
            "display_name": "管理员"
        }
    }
    USERS_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[UserManager] 默认管理员已创建: admin / admin123")

def _load_users() -> dict:
    _ensure_dirs()
    try:
        return json.loads(USERS_FILE.read_text(encoding="utf-8"))
    except:
        return {}

def _save_users(users: dict):
    USERS_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")

# ── 认证和注册 ──────────────────────────────────────────────────────────────

def authenticate(username: str, password: str) -> bool:
    users = _load_users()
    if username not in users:
        return False
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    return users[username]["password_hash"] == password_hash

def register(username: str, password: str, display_name: str = "") -> dict:
    users = _load_users()
    
    if username in users:
        return {"success": False, "message": "用户名已存在"}
    if len(username) < 3:
        return {"success": False, "message": "用户名至少3个字符"}
    if len(password) < 6:
        return {"success": False, "message": "密码至少6个字符"}
    
    user_dir = USERS_DIR / username
    user_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建用户的 credential.json
    user_credential = user_dir / "credential.json"
    default_config = {
        "user": {
            "owner_name": display_name or username,
            "owner_full_name": "",
            "owner_en_name": ""
        },
        "api": {
            "volc_api_key": "",
            "volc_api_base": "",
            "volc_model": ""
        },
        "email_163": {
            "email": "",
            "auth_code": "",
            "imap_host": "imap.163.com",
            "imap_port": 993,
            "smtp_host": "smtp.163.com",
            "smtp_port": 465
        },
        "email_gmail": {
            "email": "",
            "app_password": "",
            "imap_host": "imap.gmail.com",
            "imap_port": 993,
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 465
        },
        "wechat": {
            "wxid": "",
            "display_name": "Aegis"
        },
        "file": {
            "upload_dir": ""
        }
    }
    user_credential.write_text(json.dumps(default_config, ensure_ascii=False, indent=2), encoding="utf-8")
    
    (user_dir / "upload").mkdir(exist_ok=True)
    (user_dir / "memory").mkdir(exist_ok=True)
    
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    users[username] = {
        "password_hash": password_hash,
        "created_at": datetime.now().isoformat(),
        "role": "user",
        "display_name": display_name or username,
        "user_dir": str(user_dir)
    }
    _save_users(users)
    
    return {"success": True, "message": "注册成功"}

# ── 查询函数 ──────────────────────────────────────────────────────────────

def get_user_dir(username: str) -> Path:
    return USERS_DIR / username

def get_user_config_path(username: str) -> Path:
    return get_user_dir(username) / "credential.json"

def user_exists(username: str) -> bool:
    return username in _load_users()

def list_users() -> list:
    users = _load_users()
    return [
        {
            "username": k,
            "display_name": v.get("display_name", k),
            "created_at": v.get("created_at", ""),
            "role": v.get("role", "user")
        }
        for k, v in users.items()
    ]

# ── 初始化 ──────────────────────────────────────────────────────────────────

_ensure_dirs()