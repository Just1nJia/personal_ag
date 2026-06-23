import os
import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# ── 统一配置中心 ──────────────────────────────────────────────────────────

CONFIG_FILE = DATA_DIR / "credential.json"

# 默认配置模板（修复：加上 API 默认值）
DEFAULT_CONFIG = {
    "user": {
        "owner_name": "用户",
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
        "upload_dir": "C:/Users/hp/Desktop/upload"
    }
}


def _save_config(config: dict):
    """保存 credential.json 配置"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _init_config():
    """初始化 credential.json（如果不存在）"""
    if not CONFIG_FILE.exists():
        _save_config(DEFAULT_CONFIG)
        print(f"[Config] 已创建默认配置文件: {CONFIG_FILE}")


def _load_config() -> dict:
    """加载 credential.json 配置"""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                data = json.load(f)
                # 合并默认配置（确保所有字段都存在）
                for key in DEFAULT_CONFIG:
                    if key not in data:
                        data[key] = DEFAULT_CONFIG[key].copy()
                    elif isinstance(DEFAULT_CONFIG[key], dict):
                        for sub_key in DEFAULT_CONFIG[key]:
                            if sub_key not in data[key]:
                                data[key][sub_key] = DEFAULT_CONFIG[key][sub_key]
                return data
        except json.JSONDecodeError:
            print(f"[Config] credential.json 格式错误，使用默认配置")
            return DEFAULT_CONFIG.copy()
    else:
        _save_config(DEFAULT_CONFIG)
        print(f"[Config] 已创建默认配置文件: {CONFIG_FILE}")
        return DEFAULT_CONFIG.copy()


# ── 执行初始化 ────────────────────────────────────────────────────────────

_init_config()
_config = _load_config()


# ── 配置读写函数 ──────────────────────────────────────────────────────────

def get_config(key: str, default=None):
    """从 credential.json 读取配置，如果为空则从 .credentials 读取"""
    keys = key.split(".")
    value = _config
    for k in keys:
        if isinstance(value, dict) and k in value:
            value = value[k]
        else:
            return default
    
    # 如果值为空，尝试从 .credentials 读取
    if value == "" or value is None:
        cred_value = _get_from_credentials(key)
        if cred_value is not None and cred_value != "":
            return cred_value
    
    return value

def _get_from_credentials(key: str):
    """从 .credentials 文件读取配置"""
    cred_file = BASE_DIR / ".credentials"
    if not cred_file.exists():
        return None
    try:
        with open(cred_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, _, v = line.partition("=")
                    if k.strip() == key:
                        return v.strip()
    except Exception:
        pass
    return None

def set_config(key: str, value):
    """设置并保存配置到 credential.json"""
    keys = key.split(".")
    target = _config
    for k in keys[:-1]:
        if k not in target or not isinstance(target[k], dict):
            target[k] = {}
        target = target[k]
    target[keys[-1]] = value
    _save_config(_config)


def get_all_config() -> dict:
    """获取所有配置"""
    return _config


def update_config(payload: dict) -> dict:
    updated = []
    for key, value in payload.items():
        if key in DEFAULT_CONFIG and isinstance(DEFAULT_CONFIG[key], dict):
            if key not in _config or not isinstance(_config[key], dict):
                _config[key] = {}
            for sub_key, sub_value in value.items():
                if sub_value is not None:
                    _config[key][sub_key] = sub_value
                    updated.append(f"{key}.{sub_key}")
        else:
            _config[key] = value
            updated.append(key)
    
    _save_config(_config)
    _reload_globals()  # ← 这个函数应该更新 UPLOAD_DIR
    return {
        "success": True,
        "message": f"已更新 {len(updated)} 项配置",
        "updated_keys": updated,
        "config": _config
    }


def reset_config_to_default() -> dict:
    """重置配置为默认模板"""
    # 保存默认配置到文件
    _save_config(DEFAULT_CONFIG)
    
    # 重新加载到内存
    global _config
    _config = DEFAULT_CONFIG.copy()
    
    # 重新加载所有全局变量
    _reload_globals()
    
    print(f"[Config] 已重置为默认配置")
    
    # 返回重置后的配置
    return get_config_for_web()


# ============================================================
# 定义所有全局变量
# ============================================================

# ── 从 credential.json 读取配置 ──────────────────────────────────────────

# 用户信息
OWNER_NAME       = get_config("user.owner_name", "用户")
OWNER_FULL_NAME  = get_config("user.owner_full_name", "")
OWNER_EN_NAME    = get_config("user.owner_en_name", "")
AEGIS_WXID       = get_config("wechat.wxid", "")
AEGIS_DISPLAY_NAME = get_config("wechat.display_name", "Aegis")

# API 配置（修复：get_config 会正确处理空字符串返回默认值）
VOLC_API_KEY     = get_config("api.volc_api_key", "")
VOLC_API_BASE    = get_config("api.volc_api_base", "http://10.60.2.31/ai-gateway/szzx_openclaw/qianwen")
VOLC_MODEL       = get_config("api.volc_model", "Qwen2.5-32B-Instruct")

# 网易邮箱
NETEASE_EMAIL      = get_config("email_163.email", "")
NETEASE_AUTH_CODE  = get_config("email_163.auth_code", "")
NETEASE_IMAP_HOST  = get_config("email_163.imap_host", "imap.163.com")
NETEASE_IMAP_PORT  = int(get_config("email_163.imap_port", 993))
NETEASE_SMTP_HOST  = get_config("email_163.smtp_host", "smtp.163.com")
NETEASE_SMTP_PORT  = int(get_config("email_163.smtp_port", 465))

# Gmail
GMAIL_EMAIL      = get_config("email_gmail.email", "")
GMAIL_APP_PWD    = get_config("email_gmail.app_password", "")
GMAIL_IMAP_HOST  = get_config("email_gmail.imap_host", "imap.gmail.com")
GMAIL_IMAP_PORT  = int(get_config("email_gmail.imap_port", 993))
GMAIL_SMTP_HOST  = get_config("email_gmail.smtp_host", "smtp.gmail.com")
GMAIL_SMTP_PORT  = int(get_config("email_gmail.smtp_port", 465))

# 文件操作目录
UPLOAD_DIR = Path(get_config("file.upload_dir", "C:/Users/hp/Desktop/upload"))
SCRIPTS_DIR = UPLOAD_DIR / "scripts"
SCRAPE_DIR = UPLOAD_DIR / "scrape"

# 数据路径
DB_PATH          = DATA_DIR / "jarvis.db"
PROFILE_PATH     = DATA_DIR / "profile.json"
FILE_INDEX_PATH  = DATA_DIR / "file_index.json"
CHROMA_PATH      = str(DATA_DIR / "chroma")
MEMORY_DIR       = DATA_DIR / "memory"
LOGS_DIR         = DATA_DIR / "logs"
FTS_DB_PATH      = DATA_DIR / "fts_index.db"

# 确保目录存在
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
SCRAPE_DIR.mkdir(parents=True, exist_ok=True)
MEMORY_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# _reload_globals 函数
# ============================================================

def _reload_globals():
    """重新加载全局配置变量"""
    global OWNER_NAME, OWNER_FULL_NAME, OWNER_EN_NAME, AEGIS_WXID, AEGIS_DISPLAY_NAME
    global VOLC_API_KEY, VOLC_API_BASE, VOLC_MODEL
    global NETEASE_EMAIL, NETEASE_AUTH_CODE, NETEASE_IMAP_HOST, NETEASE_IMAP_PORT
    global NETEASE_SMTP_HOST, NETEASE_SMTP_PORT
    global GMAIL_EMAIL, GMAIL_APP_PWD, GMAIL_IMAP_HOST, GMAIL_IMAP_PORT
    global GMAIL_SMTP_HOST, GMAIL_SMTP_PORT
    global UPLOAD_DIR, SCRIPTS_DIR, SCRAPE_DIR
    global DB_PATH, PROFILE_PATH, FILE_INDEX_PATH, CHROMA_PATH
    global MEMORY_DIR, LOGS_DIR, FTS_DB_PATH

    # 重新从文件加载 _config
    global _config
    _config = _load_config()

    OWNER_NAME       = _config.get("user", {}).get("owner_name", "用户")
    OWNER_FULL_NAME  = _config.get("user", {}).get("owner_full_name", "")
    OWNER_EN_NAME    = _config.get("user", {}).get("owner_en_name", "")
    AEGIS_WXID       = _config.get("wechat", {}).get("wxid", "")
    AEGIS_DISPLAY_NAME = _config.get("wechat", {}).get("display_name", "Aegis")

    VOLC_API_KEY     = _config.get("api", {}).get("volc_api_key", "")
    VOLC_API_BASE    = _config.get("api", {}).get("volc_api_base", "http://10.60.2.31/ai-gateway/szzx_openclaw/qianwen")
    VOLC_MODEL       = _config.get("api", {}).get("volc_model", "Qwen2.5-32B-Instruct")

    NETEASE_EMAIL      = _config.get("email_163", {}).get("email", "")
    NETEASE_AUTH_CODE  = _config.get("email_163", {}).get("auth_code", "")
    NETEASE_IMAP_HOST  = _config.get("email_163", {}).get("imap_host", "imap.163.com")
    NETEASE_IMAP_PORT  = int(_config.get("email_163", {}).get("imap_port", 993))
    NETEASE_SMTP_HOST  = _config.get("email_163", {}).get("smtp_host", "smtp.163.com")
    NETEASE_SMTP_PORT  = int(_config.get("email_163", {}).get("smtp_port", 465))

    GMAIL_EMAIL      = _config.get("email_gmail", {}).get("email", "")
    GMAIL_APP_PWD    = _config.get("email_gmail", {}).get("app_password", "")
    GMAIL_IMAP_HOST  = _config.get("email_gmail", {}).get("imap_host", "imap.gmail.com")
    GMAIL_IMAP_PORT  = int(_config.get("email_gmail", {}).get("imap_port", 993))
    GMAIL_SMTP_HOST  = _config.get("email_gmail", {}).get("smtp_host", "smtp.gmail.com")
    GMAIL_SMTP_PORT  = int(_config.get("email_gmail", {}).get("smtp_port", 465))

    # ============================================================
    # 关键修复：直接从 _config 读取 file.upload_dir
    # ============================================================
    file_config = _config.get("file", {})
    upload_dir_str = file_config.get("upload_dir", "")
    if upload_dir_str and upload_dir_str != "":
        UPLOAD_DIR = Path(upload_dir_str)
    else:
        # 如果配置为空，使用默认值
        UPLOAD_DIR = Path("C:/Users/hp/Desktop/upload")
    
    SCRIPTS_DIR = UPLOAD_DIR / "scripts"
    SCRAPE_DIR = UPLOAD_DIR / "scrape"

    DB_PATH          = DATA_DIR / "jarvis.db"
    PROFILE_PATH     = DATA_DIR / "profile.json"
    FILE_INDEX_PATH  = DATA_DIR / "file_index.json"
    CHROMA_PATH      = str(DATA_DIR / "chroma")
    MEMORY_DIR       = DATA_DIR / "memory"
    LOGS_DIR         = DATA_DIR / "logs"
    FTS_DB_PATH      = DATA_DIR / "fts_index.db"

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    SCRAPE_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[Config] 重新加载完成 - 文件目录: {UPLOAD_DIR}")


# ============================================================
# 导出函数（供 Web API 使用）
# ============================================================

def get_config_for_web() -> dict:
    """返回前端设置页面需要的所有配置"""
    config_data = get_all_config()
    
    # 如果 file 字段不存在，从 UPLOAD_DIR 创建
    if "file" not in config_data:
        config_data["file"] = {
            "upload_dir": str(UPLOAD_DIR),
            "scripts_dir": str(SCRIPTS_DIR),
            "scrape_dir": str(SCRAPE_DIR)
        }
    
    # 如果 upload 字段不存在，从 file 复制（而不是覆盖）
    if "upload" not in config_data:
        config_data["upload"] = config_data["file"].copy()
    else:
        # 如果 upload 存在但为空，从 file 更新
        if not config_data["upload"].get("upload_dir"):
            config_data["upload"] = config_data["file"].copy()
    
    return config_data


def update_config_from_web(payload: dict) -> dict:
    """从 Web 设置页面更新配置"""
    return update_config(payload)


def get_upload_dir_info() -> dict:
    """获取当前文件操作目录信息"""
    return {
        "upload_dir": str(UPLOAD_DIR),
        "scripts_dir": str(SCRIPTS_DIR),
        "scrape_dir": str(SCRAPE_DIR),
        "exists": UPLOAD_DIR.exists(),
    }


def update_upload_dir(new_path: str) -> dict:
    """更新文件操作目录"""
    new_dir = Path(new_path).resolve()
    if not new_dir.exists():
        return {"success": False, "message": f"目录不存在: {new_dir}"}
    
    set_config("file.upload_dir", str(new_dir))
    _reload_globals()
    
    return {
        "success": True,
        "message": f"已更新文件操作目录: {new_dir}",
        "upload_dir": str(UPLOAD_DIR),
        "scripts_dir": str(SCRIPTS_DIR),
        "scrape_dir": str(SCRAPE_DIR),
    }


def reset_config() -> dict:
    """重置配置为默认模板"""
    return reset_config_to_default()


def get(key: str, default=None):
    """兼容旧代码"""
    return get_config(key, default)


# ── 启动打印 ──────────────────────────────────────────────────────────────

print(f"[Config] 已加载配置: {CONFIG_FILE}")
print(f"[Config] API Base URL: {VOLC_API_BASE}")
print(f"[Config] API Key 已配置: {'是' if VOLC_API_KEY else '否（请设置）'}")