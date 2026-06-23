"""
用户配置管理 - 每个用户独立的 credentials
相当于每个用户有自己的 .credentials 文件
"""
import json
from pathlib import Path
from typing import Dict, Any
from web.user_data import get_user_config_dir


def get_user_credentials(username: str) -> Dict[str, Any]:
    """获取用户的凭证配置（相当于用户的 .credentials 文件）"""
    config_dir = get_user_config_dir(username)
    cred_file = config_dir / "credentials.json"
    
    # 默认配置模板（纯 JSON，无注释）
    default_config = {
        "VOLC_API_KEY": "",
        "VOLC_API_BASE": "https://ark.cn-beijing.volces.com/api/v3",
        "VOLC_MODEL": "doubao-1-5-lite-32k-250115",
        "NETEASE_EMAIL": "",
        "NETEASE_AUTH_CODE": "",
        "NETEASE_IMAP_HOST": "imap.163.com",
        "NETEASE_IMAP_PORT": 993,
        "NETEASE_SMTP_HOST": "smtp.163.com",
        "NETEASE_SMTP_PORT": 465,
        "GMAIL_EMAIL": "",
        "GMAIL_APP_PWD": "",
        "GMAIL_IMAP_HOST": "imap.gmail.com",
        "GMAIL_IMAP_PORT": 993,
        "GMAIL_SMTP_HOST": "smtp.gmail.com",
        "GMAIL_SMTP_PORT": 587,
        "OWNER_NAME": "",
        "OWNER_FULL_NAME": "",
        "OWNER_EN_NAME": "",
        "AEGIS_WXID": "",
        "AEGIS_DISPLAY_NAME": "Aegis",
        "FILE_PATH": "",
        "SCAN_ROOTS": [],
    }
    
    if cred_file.exists():
        try:
            with open(cred_file, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
                default_config.update(user_config)
        except Exception as e:
            print(f"[UserConfig] 加载 {username} 配置失败: {e}")
    
    return default_config


def save_user_credentials(username: str, config: Dict[str, Any]):
    """保存用户的凭证配置"""
    config_dir = get_user_config_dir(username)
    config_dir.mkdir(parents=True, exist_ok=True)
    cred_file = config_dir / "credentials.json"
    
    # 只保存非默认值的配置（可选，保持文件整洁）
    with open(cred_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    
    print(f"[UserConfig] 已保存 {username} 的配置")


def init_user_credentials_from_global(username: str):
    pass
    """从全局 .credentials 初始化新用户的配置"""
    # try:
    #     import config as global_config
        
    #     user_config = {
    #         "VOLC_API_KEY": getattr(global_config, "VOLC_API_KEY", ""),
    #         "VOLC_API_BASE": getattr(global_config, "VOLC_API_BASE", "https://ark.cn-beijing.volces.com/api/v3"),
    #         "VOLC_MODEL": getattr(global_config, "VOLC_MODEL", "doubao-1-5-lite-32k-250115"),
    #         "NETEASE_EMAIL": getattr(global_config, "NETEASE_EMAIL", ""),
    #         "NETEASE_AUTH_CODE": getattr(global_config, "NETEASE_AUTH_CODE", ""),
    #         "NETEASE_IMAP_HOST": getattr(global_config, "NETEASE_IMAP_HOST", "imap.163.com"),
    #         "NETEASE_IMAP_PORT": getattr(global_config, "NETEASE_IMAP_PORT", 993),
    #         "NETEASE_SMTP_HOST": getattr(global_config, "NETEASE_SMTP_HOST", "smtp.163.com"),
    #         "NETEASE_SMTP_PORT": getattr(global_config, "NETEASE_SMTP_PORT", 465),
    #         "GMAIL_EMAIL": getattr(global_config, "GMAIL_EMAIL", ""),
    #         "GMAIL_APP_PWD": getattr(global_config, "GMAIL_APP_PWD", ""),
    #         "GMAIL_IMAP_HOST": getattr(global_config, "GMAIL_IMAP_HOST", "imap.gmail.com"),
    #         "GMAIL_IMAP_PORT": getattr(global_config, "GMAIL_IMAP_PORT", 993),
    #         "GMAIL_SMTP_HOST": getattr(global_config, "GMAIL_SMTP_HOST", "smtp.gmail.com"),
    #         "GMAIL_SMTP_PORT": getattr(global_config, "GMAIL_SMTP_PORT", 587),
    #         "OWNER_NAME": username,  # 使用用户名作为显示名
    #         "OWNER_FULL_NAME": "",
    #         "OWNER_EN_NAME": "",
    #         "AEGIS_WXID": getattr(global_config, "AEGIS_WXID", ""),
    #         "AEGIS_DISPLAY_NAME": getattr(global_config, "AEGIS_DISPLAY_NAME", "Aegis"),
    #         "FILE_PATH": getattr(global_config, "FILE_PATH", ""),
    #         "SCAN_ROOTS": getattr(global_config, "SCAN_ROOTS", []),
    #     }
    #     save_user_credentials(username, user_config)
    #     print(f"[UserConfig] 已从全局配置初始化 {username} 的凭证")
    # except Exception as e:
    #     print(f"[UserConfig] 初始化失败: {e}")


def get_user_setting(username: str, key: str, default=None):
    """获取用户的单个配置项"""
    config = get_user_credentials(username)
    return config.get(key, default)


def set_user_setting(username: str, key: str, value):
    """设置用户的单个配置项"""
    config = get_user_credentials(username)
    config[key] = value
    save_user_credentials(username, config)