"""
文件操作日志模块
记录所有文件操作的详细信息
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
import traceback

class FileOperationLogger:
    """文件操作日志记录器"""
    
    def __init__(self, log_dir: str = None):
        if log_dir is None:
            # 默认日志目录在 data/logs 下
            log_dir = Path(__file__).parent.parent / "data" / "logs"
        
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # 日志文件路径
        self.json_log_path = self.log_dir / "file_operations.json"
        self.text_log_path = self.log_dir / "file_operations.log"
        
        # 设置 Python logging
        self._setup_logging()
        
    def _setup_logging(self):
        """设置文本日志"""
        self.logger = logging.getLogger("FileOperation")
        self.logger.setLevel(logging.INFO)
        
        # 避免重复添加 handler
        if not self.logger.handlers:
            # 文件 handler
            file_handler = logging.FileHandler(self.text_log_path, encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            formatter = logging.Formatter(
                '%(asctime)s | %(levelname)s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
    
    def _load_existing_logs(self) -> list:
        """加载现有的 JSON 日志"""
        if self.json_log_path.exists():
            try:
                with open(self.json_log_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return []
        return []
    
    def _save_json_logs(self, logs: list):
        """保存 JSON 日志"""
        with open(self.json_log_path, 'w', encoding='utf-8') as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)
    
    def log_operation(
        self, 
        operation: str, 
        success: bool, 
        details: Dict[str, Any],
        error: str = None
    ):
        """记录操作日志"""
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "success": success,
            "details": details,
        }
        
        if error:
            log_entry["error"] = error
        
        # 1. 写入文本日志（人类可读）
        status = "✅ 成功" if success else "❌ 失败"
        msg = f"{status} | {operation} | {details}"
        if error:
            msg += f" | 错误: {error}"
        self.logger.info(msg)
        
        # 2. 写入 JSON 日志（便于程序分析）
        logs = self._load_existing_logs()
        logs.append(log_entry)
        
        # 只保留最近 1000 条记录，避免文件过大
        if len(logs) > 1000:
            logs = logs[-1000:]
        
        self._save_json_logs(logs)
    
    def get_recent_logs(self, limit: int = 50) -> list:
        """获取最近的日志"""
        logs = self._load_existing_logs()
        return logs[-limit:][::-1]  # 倒序返回，最新的在前
    
    def get_logs_by_operation(self, operation: str, limit: int = 50) -> list:
        """按操作类型筛选日志"""
        logs = self._load_existing_logs()
        filtered = [log for log in logs if log.get("operation") == operation]
        return filtered[-limit:][::-1]
    
    def get_logs_by_date(self, date: str) -> list:
        """按日期筛选日志（date 格式：YYYY-MM-DD）"""
        logs = self._load_existing_logs()
        return [log for log in logs if log.get("timestamp", "").startswith(date)]


# 创建全局实例
file_logger = FileOperationLogger()