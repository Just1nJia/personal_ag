"""
web/context.py - 用户上下文管理器
"""
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any
import sqlite3

_current_user: ContextVar[Optional[str]] = ContextVar('current_user', default=None)
_context_cache: Dict[str, 'UserContext'] = {}


@dataclass
class UserContext:
    """用户上下文，包含该用户的所有路径配置和凭证"""
    username: str
    base_dir: Path
    db_path: Path
    memory_dir: Path
    files_dir: Path
    scrape_dir: Path
    scripts_dir: Path
    logs_dir: Path
    config_dir: Path
    credentials: Dict[str, Any] = field(default_factory=dict)
    settings: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def create(cls, username: str) -> 'UserContext':
        """创建用户上下文（加载用户的凭证和设置）"""
        from web.user_data import (
            get_user_dir, get_user_memory_dir, get_user_files_dir,
            get_user_scrape_dir, get_user_scripts_dir, get_user_logs_dir,
            get_user_config_dir, get_user_settings
        )
        from web.user_config import get_user_credentials
        
        base_dir = get_user_dir(username)
        memory_dir = get_user_memory_dir(username)
        files_dir = get_user_files_dir(username)
        scrape_dir = get_user_scrape_dir(username)
        scripts_dir = get_user_scripts_dir(username)
        logs_dir = get_user_logs_dir(username)
        config_dir = get_user_config_dir(username)
        
        # 加载用户的凭证（邮箱、API Key等）
        credentials = get_user_credentials(username)
        
        # 加载用户的设置
        settings = get_user_settings(username)
        
        # 确保文件目录存在
        files_dir.mkdir(parents=True, exist_ok=True)
        
        return cls(
            username=username,
            base_dir=base_dir,
            db_path=base_dir / "user.db",
            memory_dir=memory_dir,
            files_dir=files_dir,
            scrape_dir=scrape_dir,
            scripts_dir=scripts_dir,
            logs_dir=logs_dir,
            config_dir=config_dir,
            credentials=credentials,
            settings=settings,
        )
    
    def get_credential(self, key: str, default=None):
        """获取用户的凭证配置项"""
        return self.credentials.get(key, default)
    
    def get_setting(self, key: str, default=None):
        """获取用户的设置项"""
        return self.settings.get(key, default)
    
    def get_file_path(self) -> Path:
        """获取用户的文件操作目录"""
        file_path = self.credentials.get("FILE_PATH", "")
        if file_path:
            return Path(file_path)
        # 默认使用用户目录下的 files 子目录
        return self.files_dir


def set_current_user(username: Optional[str]):
    """设置当前请求的用户"""
    _current_user.set(username)


def get_current_user() -> Optional[str]:
    """获取当前请求的用户名"""
    return _current_user.get()


def get_current_context() -> Optional[UserContext]:
    """获取当前用户的上下文（带缓存）"""
    username = get_current_user()
    if not username:
        return None
    
    global _context_cache
    if username not in _context_cache:
        _context_cache[username] = UserContext.create(username)
    
    return _context_cache[username]


def clear_context_cache(username: str = None):
    """清除用户上下文缓存（用户登出时调用）"""
    global _context_cache
    if username:
        _context_cache.pop(username, None)
    else:
        _context_cache.clear()


def get_current_user_credential(key: str, default=None):
    """获取当前用户的凭证配置项"""
    ctx = get_current_context()
    if ctx:
        return ctx.get_credential(key, default)
    return default


def get_current_user_setting(key: str, default=None):
    """获取当前用户的设置项"""
    ctx = get_current_context()
    if ctx:
        return ctx.get_setting(key, default)
    return default