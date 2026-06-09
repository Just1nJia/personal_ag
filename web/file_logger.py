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
            log_dir = Path(__file__).parent.parent / "data" / "logs"
        
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.json_log_path = self.log_dir / "file_operations.json"
        self.text_log_path = self.log_dir / "file_operations.log"
        
        self._setup_logging()
        
    def _setup_logging(self):
        """设置文本日志"""
        self.logger = logging.getLogger("FileOperation")
        self.logger.setLevel(logging.INFO)
        
        if not self.logger.handlers:
            file_handler = logging.FileHandler(self.text_log_path, encoding='utf-8')
            file_handler.setLevel(logging.INFO)
            formatter = logging.Formatter(
                '%(asctime)s | %(levelname)s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
    
    def _load_existing_logs(self) -> list:
        if self.json_log_path.exists():
            try:
                with open(self.json_log_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return []
        return []
    
    def _save_json_logs(self, logs: list):
        with open(self.json_log_path, 'w', encoding='utf-8') as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)
    
    def log_operation(
        self, 
        operation: str, 
        success: bool, 
        details: Dict[str, Any],
        error: str = None,
        command_text: str = None  # 新增：原始命令文本
    ):
        """
        记录操作日志
        
        Args:
            operation: 操作类型 (create_file, read_file, update_file, rename_file, 
                       copy_file, list_files, search_files, merge_files, clean_file, ai_clean_file)
            success: 是否成功
            details: 操作详情
            error: 错误信息
            command_text: 原始命令文本（用于清洗/整理类操作）
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "success": success,
            "details": details,
        }
        
        # 记录原始命令
        if command_text:
            log_entry["command_text"] = command_text
            log_entry["command_preview"] = command_text[:200] + "..." if len(command_text) > 200 else command_text
        
        if error:
            log_entry["error"] = error
        
        # 写入文本日志
        status = "✅ 成功" if success else "❌ 失败"
        
        # 根据操作类型构建日志消息
        if operation in ["clean_file", "ai_clean_file"]:
            action_name = "文件清洗" if operation == "clean_file" else "AI智能清洗"
            filename = details.get("filepath", details.get("filename", "未知"))
            msg = f"{status} | {action_name} | 文件: {filename}"
            
            if command_text:
                cmd_preview = command_text[:80] + "..." if len(command_text) > 80 else command_text
                msg += f" | 指令: {cmd_preview}"
            
            if success:
                msg += f" | 原始: {details.get('original_length', 0)}字 → 处理后: {details.get('new_length', 0)}字"
                if details.get("original_lines"):
                    msg += f" | {details.get('original_lines', 0)}行 → {details.get('new_lines', 0)}行"
            else:
                msg += f" | 错误: {error}"
        
        elif operation == "ai_clean_file_with_rename":
            msg = f"{status} | AI智能清洗并重命名 | 源文件: {details.get('source_file', '未知')} → 目标文件: {details.get('target_file', '未知')}"
            if command_text:
                cmd_preview = command_text[:80] + "..." if len(command_text) > 80 else command_text
                msg += f" | 指令: {cmd_preview}"
            if success:
                msg += f" | 原始: {details.get('original_length', 0)}字 → 处理后: {details.get('new_length', 0)}字"
        
        else:
            # 原有操作类型的日志
            msg = f"{status} | {operation} | {details}"
            if error:
                msg += f" | 错误: {error}"
        
        self.logger.info(msg)
        
        # 写入 JSON 日志
        logs = self._load_existing_logs()
        logs.append(log_entry)
        
        if len(logs) > 1000:
            logs = logs[-1000:]
        
        self._save_json_logs(logs)
    
    def get_recent_logs(self, limit: int = 50) -> list:
        logs = self._load_existing_logs()
        return logs[-limit:][::-1]
    
    def get_logs_by_operation(self, operation: str, limit: int = 50) -> list:
        logs = self._load_existing_logs()
        filtered = [log for log in logs if log.get("operation") == operation]
        return filtered[-limit:][::-1]
    
    def get_logs_by_date(self, date: str) -> list:
        logs = self._load_existing_logs()
        return [log for log in logs if log.get("timestamp", "").startswith(date)]
    
    def get_clean_logs(self, limit: int = 50) -> list:
        """获取清洗/整理相关的日志"""
        logs = self._load_existing_logs()
        clean_ops = ["clean_file", "ai_clean_file", "ai_clean_file_with_rename"]
        filtered = [log for log in logs if log.get("operation") in clean_ops]
        return filtered[-limit:][::-1]


file_logger = FileOperationLogger()