# web/logger.py
"""
统一日志管理模块
按日期自动分割日志文件，记录用户操作
"""
import logging
from datetime import datetime
from pathlib import Path
import config

LOG_DIR = config.DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 日志格式: 时间 | 级别 | 用户 | 模块 | 消息
LOG_FORMAT = '%(asctime)s | %(levelname)s | %(user)s | %(module)s | %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# 当前用户（由中间件或调用方设置）
_current_user = "system"

def set_log_user(username: str):
    """设置当前日志用户"""
    global _current_user
    _current_user = username or "system"

def get_log_user():
    return _current_user


class UserFilter(logging.Filter):
    """添加用户信息到日志记录"""
    def filter(self, record):
        record.user = get_log_user()
        return True


class DailyFileHandler(logging.FileHandler):
    """按日期自动切换日志文件"""
    def __init__(self, base_dir, module_name):
        self.base_dir = Path(base_dir)
        self.module_name = module_name
        self.current_date = None
        super().__init__(self._get_log_path(), mode='a', encoding='utf-8')
    
    def _get_log_path(self):
        today = datetime.now().strftime("%Y-%m-%d")
        self.current_date = today
        log_dir = self.base_dir / today
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / f"{self.module_name}.log"
    
    def emit(self, record):
        # 每天切换日志文件
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self.current_date:
            self.baseFilename = self._get_log_path()
        super().emit(record)


# 日志器缓存
_loggers = {}

def get_logger(module: str = "system"):
    """获取指定模块的日志器"""
    if module in _loggers:
        return _loggers[module]
    
    logger = logging.getLogger(f"aegis.{module}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    
    if logger.handlers:
        return logger
    
    # 用户过滤器
    user_filter = UserFilter()
    logger.addFilter(user_filter)
    
    # 控制台输出
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    logger.addHandler(console)
    
    # 文件输出（按日期分割）
    file_handler = DailyFileHandler(LOG_DIR, module)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    logger.addHandler(file_handler)
    
    _loggers[module] = logger
    return logger


# ── 各模块日志器 ──────────────────────────────────────────────────────────

def get_chat_logger():
    return get_logger("chat")

def get_file_logger():
    return get_logger("file")

def get_email_logger():
    return get_logger("email")

def get_crawler_logger():
    return get_logger("crawler")

def get_system_logger():
    return get_logger("system")

def get_error_logger():
    return get_logger("errors")


# ── 便捷函数（一行记录）──────────────────────────────────────────────────

def log_chat(user: str, msg: str, level: str = "info"):
    """记录对话日志"""
    set_log_user(user)
    logger = get_chat_logger()
    getattr(logger, level)(msg)

def log_file(user: str, msg: str, level: str = "info"):
    """记录文件操作日志"""
    set_log_user(user)
    logger = get_file_logger()
    getattr(logger, level)(msg)

def log_email(user: str, msg: str, level: str = "info"):
    """记录邮件日志"""
    set_log_user(user)
    logger = get_email_logger()
    getattr(logger, level)(msg)

def log_crawler(user: str, msg: str, level: str = "info"):
    """记录爬虫日志"""
    set_log_user(user)
    logger = get_crawler_logger()
    getattr(logger, level)(msg)

def log_system(user: str, msg: str, level: str = "info"):
    """记录系统日志"""
    set_log_user(user)
    logger = get_system_logger()
    getattr(logger, level)(msg)

def log_error(user: str, msg: str, error: Exception = None):
    """记录错误日志"""
    set_log_user(user)
    logger = get_error_logger()
    if error:
        logger.error(f"{msg} | {error}")
    else:
        logger.error(msg)