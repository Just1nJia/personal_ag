"""
爬虫日志模块
记录所有爬取操作的详细信息
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
import socket

class ScraperLogger:
    """爬虫日志记录器"""
    
    def __init__(self, log_dir: str = None):
        if log_dir is None:
            log_dir = Path(__file__).parent.parent / "data" / "logs"
        
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # 日志文件路径
        self.json_log_path = self.log_dir / "scraper_operations.json"
        self.text_log_path = self.log_dir / "scraper_operations.log"
        
        # 获取本机IP
        self.local_ip = self._get_local_ip()
        
        # 设置 Python logging
        self._setup_logging()
    
    def _get_local_ip(self) -> str:
        """获取本机IP地址"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
    
    def _setup_logging(self):
        """设置文本日志"""
        self.logger = logging.getLogger("ScraperOperation")
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
    
    def log_scrape(
        self,
        urls: list,
        output_format: str,
        send_to_email: Optional[str] = None,
        schedule_type: str = "once",
        schedule_detail: str = None,
        schedule_time: str = None,
        success: bool = True,
        result: Dict = None,
        error: str = None,
        need_process: bool = False,
        process_requirement: str = None
    ):
        """
        记录爬取操作日志
        """
        # 构建日志条目
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "ip": self.local_ip,
            "urls": urls,
            "output_format": output_format,
            "send_to_email": send_to_email if send_to_email else "none",
            "schedule_type": schedule_type,
            "success": success,
            "need_process": need_process,  # 是否启用整理
        }
        
        # 记录整理要求
        if need_process and process_requirement:
            log_entry["process_requirement"] = process_requirement
            log_entry["process_requirement_preview"] = process_requirement[:200] + "..." if len(process_requirement) > 200 else process_requirement
        
        # 定时任务详细信息
        if schedule_type != "once":
            if schedule_type == "daily":
                log_entry["schedule_desc"] = f"每天 {schedule_time}"
            elif schedule_type == "weekly":
                weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
                day_name = weekdays[int(schedule_detail)] if schedule_detail else "未知"
                log_entry["schedule_desc"] = f"每周{day_name} {schedule_time}"
            elif schedule_type == "monthly":
                log_entry["schedule_desc"] = f"每月{schedule_detail}号 {schedule_time}"
            log_entry["schedule_time_point"] = schedule_time
            log_entry["schedule_detail"] = schedule_detail
        
        # 执行结果
        if success and result:
            log_entry["result"] = {
                "title": result.get("title", ""),
                "content_length": result.get("content_length", 0),
                "links_count": result.get("links_count", 0),
                "saved_to": result.get("saved_to", ""),
                "email_sent": result.get("email_sent", False),
                "email_to": result.get("email_to", send_to_email),
                "email_sent_time": datetime.now().isoformat() if result.get("email_sent") else None
            }
            
            # 如果整理成功，记录整理前后的长度
            if need_process and result.get("processed_length"):
                log_entry["result"]["original_length"] = result.get("original_length", 0)
                log_entry["result"]["processed_length"] = result.get("processed_length", 0)
                
        elif error:
            log_entry["error"] = error
        
        # 1. 写入文本日志
        status = "✅ 成功" if success else "❌ 失败"
        urls_str = ", ".join(urls) if len(urls) <= 3 else f"{len(urls)}个网址"
        
        msg = f"{status} | IP: {self.local_ip} | 网址: {urls_str} | 格式: {output_format} | 邮箱: {send_to_email or 'none'}"
        
        # 添加整理信息到文本日志
        if need_process and process_requirement:
            req_preview = process_requirement[:50] + "..." if len(process_requirement) > 50 else process_requirement
            msg += f" | 🤖 AI整理: {req_preview}"
        
        if schedule_type != "once":
            msg += f" | 定时: {log_entry.get('schedule_desc', schedule_type)}"
        
        if success and result:
            msg += f" | 内容长度: {result.get('content_length', 0)} | 邮件发送: {'是' if result.get('email_sent') else '否'}"
        
        self.logger.info(msg)
        
        # 2. 写入 JSON 日志
        logs = self._load_existing_logs()
        logs.append(log_entry)
        
        # 只保留最近 500 条记录
        if len(logs) > 500:
            logs = logs[-500:]
        
        self._save_json_logs(logs)
    
    def get_recent_logs(self, limit: int = 50) -> list:
        """获取最近的日志"""
        logs = self._load_existing_logs()
        return logs[-limit:][::-1]
    
    def get_logs_by_date(self, date: str) -> list:
        """按日期筛选日志（date 格式：YYYY-MM-DD）"""
        logs = self._load_existing_logs()
        return [log for log in logs if log.get("timestamp", "").startswith(date)]
    
    def get_logs_by_url(self, url_keyword: str) -> list:
        """按网址关键词筛选日志"""
        logs = self._load_existing_logs()
        return [log for log in logs if any(url_keyword in u for u in log.get("urls", []))]
    
    def get_logs_with_process(self) -> list:
        """获取启用了 AI 整理的日志"""
        logs = self._load_existing_logs()
        return [log for log in logs if log.get("need_process", False)]


# 全局实例
scraper_logger = ScraperLogger()