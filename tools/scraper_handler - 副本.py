"""
爬虫命令处理模块
"""
import asyncio
from datetime import datetime, time, timedelta
import threading
import time
from pathlib import Path
from typing import Dict, Optional, List
import json
import re
import hashlib
from tools.web_scraper import scraper
from email_module.sender import send_email
from tools.scraper_logger import scraper_logger
from tools.content_processor import process_content
from tools.smart_searcher import smart_searcher

# 定时任务存储文件
SCHEDULE_FILE = Path("C:/Users/hp/Desktop/upload/scrape/schedules.json")

def load_schedules() -> list:
    """加载定时任务"""
    if SCHEDULE_FILE.exists():
        try:
            with open(SCHEDULE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
    return []

def save_schedules(schedules: list):
    """保存定时任务"""
    SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SCHEDULE_FILE, 'w', encoding='utf-8') as f:
        json.dump(schedules, f, ensure_ascii=False, indent=2)

def get_next_run_time(schedule_type: str, schedule_detail: str, schedule_time: str) -> str:
    """计算下次运行时间"""
    now = datetime.now()
    hour, minute = map(int, schedule_time.split(':'))
    
    if schedule_type == 'daily':
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_run <= now:
            next_run = next_run + timedelta(days=1)
    
    elif schedule_type == 'weekly':
        # schedule_detail 是星期几 0-6 (周一=0, 周日=6)
        target_weekday = int(schedule_detail)
        days_ahead = target_weekday - now.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=days_ahead)
    
    elif schedule_type == 'monthly':
        # schedule_detail 是月份中的日期 (1-31)
        target_day = int(schedule_detail)
        if target_day > 28:
            # 处理月份天数不同的问题，简单处理为下个月1号
            next_run = now.replace(day=1, hour=hour, minute=minute, second=0, microsecond=0)
            if next_run <= now:
                next_run = next_run + timedelta(days=32)
                next_run = next_run.replace(day=1)
        else:
            try:
                next_run = now.replace(day=target_day, hour=hour, minute=minute, second=0, microsecond=0)
                if next_run <= now:
                    if next_run.month == 12:
                        next_run = next_run.replace(year=next_run.year + 1, month=1)
                    else:
                        next_run = next_run.replace(month=next_run.month + 1)
            except ValueError:
                next_run = now.replace(day=1, hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=32)
                next_run = next_run.replace(day=1)
    else:
        return ""
    
    return next_run.isoformat()


async def scrape_single_url(
    url: str, 
    output_format: str, 
    send_to_email: Optional[str] = None,
    need_process: bool = False,
    process_requirement: str = ""
) -> Dict:
    """爬取单个URL，可选内容整理"""
    result = await scraper.scrape_article(url)
    
    if not result["success"]:
        # 记录失败日志
        scraper_logger.log_scrape(
            urls=[url],
            output_format=output_format,
            send_to_email=send_to_email,
            schedule_type="once",
            success=False,
            error=result.get("message", "爬取失败"),
            need_process=need_process,
            process_requirement=process_requirement
        )
        return {
            "success": False,
            "url": url,
            "error": result.get("message", "爬取失败")
        }
    
    # 获取原始内容
    original_content = result.get("content", "")
    processed_content = None
    process_result = None
    
    # 如果启用整理
    if need_process and process_requirement:
        print(f"[Scraper] 正在使用 AI 整理内容...")
        process_result = await process_content(
            content=original_content,
            requirement=process_requirement,
            title=result.get("title", ""),
            url=url
        )
        
        if process_result["success"]:
            processed_content = process_result["processed_content"]
            print(f"[Scraper] 内容整理完成，原始长度: {process_result['original_length']}, 整理后长度: {process_result['processed_length']}")
        else:
            print(f"[Scraper] 内容整理失败: {process_result['message']}")
    
    # 格式化输出（使用整理后的内容）
    if output_format == "txt":
        output = scraper.format_as_txt(result, custom_content=processed_content)
        ext = "txt"
    else:
        output = scraper.format_as_markdown(result, custom_content=processed_content)
        ext = "md"
    
    # 保存文件
    save_dir = Path("C:/Users/hp/Desktop/upload/scrape")
    save_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    domain = url.replace("https://", "").replace("http://", "").split("/")[0]
    domain = re.sub(r'[^\w\-_.]', '_', domain)
    filename = f"{domain}_{timestamp}.{ext}"
    filepath = save_dir / filename
    filepath.write_text(output, encoding="utf-8")
    
    print(f"[Scraper] 文件已保存: {filepath}")
    
    # 发送邮件
    email_sent = False
    if send_to_email and send_to_email.strip():
        try:
            subject = f"🕷️ 网页爬取: {result.get('title', url)[:50]}"
            if need_process and process_requirement:
                subject = f"🤖 [整理] {subject}"
            print(f"[Scraper] 正在发送邮件到: {send_to_email}")
            email_sent = send_email(
                to=send_to_email,
                subject=subject,
                body=output[:5000],
                attachments=[str(filepath)]
            )
            print(f"[Scraper] 邮件发送结果: {email_sent}")
        except Exception as e:
            print(f"[Scraper] 邮件发送失败: {e}")
    
    # 记录成功日志（包含整理信息）
    result_data = {
        "title": result.get("title", ""),
        "content_length": len(processed_content) if processed_content else result.get("content_length", 0),
        "links_count": result.get("links_count", 0),
        "saved_to": str(filepath),
        "email_sent": email_sent,
        "email_to": send_to_email
    }
    
    # 如果有整理结果，添加整理信息
    if process_result and process_result.get("success"):
        result_data["original_length"] = process_result.get("original_length", 0)
        result_data["processed_length"] = process_result.get("processed_length", 0)
    
    scraper_logger.log_scrape(
        urls=[url],
        output_format=output_format,
        send_to_email=send_to_email,
        schedule_type="once",
        success=True,
        result=result_data,
        need_process=need_process,
        process_requirement=process_requirement
    )
    
    return {
        "success": True,
        "url": url,
        "title": result.get("title", ""),
        "content_length": len(processed_content) if processed_content else result.get("content_length", 0),
        "links_count": result.get("links_count", 0),
        "output_preview": output[:500] + "..." if len(output) > 500 else output,
        "saved_to": str(filepath),
        "filename": filename,
        "download_url": f"/api/download/scrape/{filename}",
        "email_sent": email_sent,
        "email_to": send_to_email,
        "need_process": need_process,
        "process_requirement": process_requirement,
        "processed": process_result.get("success") if process_result else False
    }


async def scrape_multiple_urls(
    urls: List[str], 
    output_format: str, 
    send_to_email: Optional[str] = None,
    need_process: bool = False,
    process_requirement: str = ""
) -> Dict:
    """爬取多个URL，可选内容整理"""
    results = []
    all_output = ""
    
    for i, url in enumerate(urls, 1):
        result = await scrape_single_url(url, output_format, None, need_process, process_requirement)
        results.append(result)
        all_output += f"\n{'='*60}\n【{i}】{url}\n{'='*60}\n\n"
        if result["success"]:
            all_output += result["output_preview"] if "output_preview" in result else "内容已保存"
        else:
            all_output += f"爬取失败: {result.get('error', '未知错误')}\n"
    
    # 保存合并后的文件
    save_dir = Path("C:/Users/hp/Desktop/upload/scrape")
    save_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = "txt" if output_format == "txt" else "md"
    filename = f"batch_{timestamp}.{ext}"
    filepath = save_dir / filename
    filepath.write_text(all_output, encoding="utf-8")
    
    # 发送合并邮件
    email_sent = False
    if send_to_email:
        subject = f"🕷️ 批量爬取结果 ({len(urls)}个网址)"
        if need_process and process_requirement:
            subject = f"🤖 [整理] {subject}"
        email_sent = send_email(
            to=send_to_email,
            subject=subject,
            body=all_output[:5000],
            attachments=[str(filepath)]
        )
        print(f"[Scraper] 批量邮件发送结果: {email_sent} 目标: {send_to_email}")
    
    # 记录批量日志
    scraper_logger.log_scrape(
        urls=urls,
        output_format=output_format,
        send_to_email=send_to_email,
        schedule_type="once",
        success=True,
        result={
            "title": f"批量爬取 {len(urls)} 个网址",
            "content_length": len(all_output),
            "links_count": 0,
            "saved_to": str(filepath),
            "email_sent": email_sent,
            "email_to": send_to_email
        },
        need_process=need_process,
        process_requirement=process_requirement
    )
    
    return {
        "success": True,
        "message": f"批量爬取完成，共 {len(urls)} 个网址",
        "urls": urls,
        "success_count": sum(1 for r in results if r["success"]),
        "fail_count": sum(1 for r in results if not r["success"]),
        "output_preview": all_output[:1000] + "..." if len(all_output) > 1000 else all_output,
        "saved_to": str(filepath),
        "download_url": f"/api/download/scrape/{filename}",
        "email_sent": email_sent,
        "email_to": send_to_email
    }

async def search_and_scrape(
    query: str,
    output_format: str,
    send_to_email: Optional[str] = None,
    need_process: bool = False,
    process_requirement: str = "",
    max_urls: int = 3
) -> Dict:
    """
    根据需求搜索并抓取相关内容
    """
    # 1. 搜索相关网址
    print(f"[SmartSearch] 正在搜索: {query}")
    search_results = await smart_searcher.search_urls(query, max_results=max_urls * 2)
    
    if not search_results:
        return {
            "success": False,
            "message": f"未找到与 '{query}' 相关的网址",
            "urls": []
        }
    
    # 2. 过滤出有效的网址
    valid_urls = []
    for r in search_results:
        url = r.get("url", "")
        if url and url.startswith(("http://", "https://")):
            valid_urls.append({
                "url": url,
                "title": r.get("title", ""),
                "snippet": r.get("snippet", "")
            })
    
    # 3. 取前 max_urls 个网址进行抓取
    target_urls = valid_urls[:max_urls]
    
    # 4. 抓取每个网址的内容
    results = []
    all_output = ""
    
    for i, item in enumerate(target_urls, 1):
        url = item["url"]
        title = item["title"]
        print(f"[SmartSearch] 抓取 ({i}/{len(target_urls)}): {title}")
        
        result = await scrape_single_url(
            url=url,
            output_format=output_format,
            send_to_email=None,
            need_process=need_process,
            process_requirement=process_requirement
        )
        
        results.append({
            "url": url,
            "title": title,
            "success": result.get("success", False),
            "output_preview": result.get("output_preview", ""),
            "error": result.get("error", "")
        })
        
        all_output += f"\n{'='*60}\n【{i}】{title}\n{url}\n{'='*60}\n\n"
        if result.get("success"):
            all_output += result.get("output_preview", "内容已保存")
        else:
            all_output += f"抓取失败: {result.get('error', '未知错误')}\n"
    
    # 5. 保存合并文件
    save_dir = Path("C:/Users/hp/Desktop/upload/scrape")
    save_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = "txt" if output_format == "txt" else "md"
    filename = f"smart_search_{timestamp}.{ext}"
    filepath = save_dir / filename
    filepath.write_text(all_output, encoding="utf-8")
    
    # 6. 发送邮件
    email_sent = False
    if send_to_email:
        subject = f"🔍 智能搜索: {query[:50]}"
        if need_process:
            subject = f"🤖 [整理] {subject}"
        email_sent = send_email(
            to=send_to_email,
            subject=subject,
            body=all_output[:5000],
            attachments=[str(filepath)]
        )
    
    return {
        "success": True,
        "message": f"智能搜索完成，共抓取 {len(target_urls)} 个网址",
        "query": query,
        "urls_found": len(valid_urls),
        "urls_scraped": len(target_urls),
        "search_results": [
            {"title": r["title"], "url": r["url"], "snippet": r["snippet"]}
            for r in search_results[:10]
        ],
        "scrape_results": results,
        "saved_to": str(filepath),
        "download_url": f"/api/download/scrape/{filename}",
        "email_sent": email_sent,
        "email_to": send_to_email
    }

async def execute_scrape_task(
    urls_input: str,
    output_format: str = "markdown",
    send_to_email: Optional[str] = None,
    email_subject: Optional[str] = None,
    task_id: str = None,
    need_process: bool = False,
    process_requirement: str = ""
) -> Dict:
    urls = [u.strip() for u in urls_input.split(';') if u.strip()]
    
    if len(urls) == 1:
        result = await scrape_single_url(urls[0], output_format, send_to_email, need_process, process_requirement)
        if result["success"]:
            return {
                "success": True,
                "message": "爬取完成",
                "url": urls[0],
                "title": result.get("title", ""),
                "content_length": result.get("content_length", 0),
                "links_count": result.get("links_count", 0),
                "output_preview": result.get("output_preview", ""),
                "saved_to": result.get("saved_to", ""),
                "download_url": result.get("download_url", ""),
                "email_sent": result.get("email_sent", False),
                "email_to": result.get("email_to", send_to_email)
            }
        else:
            return {
                "success": False,
                "message": result.get("error", "爬取失败"),
                "url": urls[0]
            }
    else:
        return await scrape_multiple_urls(urls, output_format, send_to_email, need_process, process_requirement)


def add_scheduled_task(
    urls: str, 
    schedule_type: str, 
    schedule_detail: str, 
    schedule_time: str, 
    email: str, 
    format_type: str,
    need_process: bool = False,
    process_requirement: str = ""
) -> Dict:
    """添加定时爬取任务"""
    schedules = load_schedules()
    
    import hashlib
    unique_str = f"{urls}_{schedule_type}_{schedule_detail}_{schedule_time}_{datetime.now().timestamp()}"
    task_id = hashlib.md5(unique_str.encode()).hexdigest()
    
    task = {
        "id": task_id,
        "urls": urls,
        "schedule_type": schedule_type,
        "schedule_detail": schedule_detail,
        "schedule_time": schedule_time,
        "email": email,
        "format": format_type,
        "need_process": need_process,  # 保存整理开关
        "process_requirement": process_requirement,  # 保存整理要求
        "next_run": get_next_run_time(schedule_type, schedule_detail, schedule_time),
        "created_at": datetime.now().isoformat(),
        "last_run": None,
        "enabled": True
    }
    
    schedules.append(task)
    save_schedules(schedules)
    
    desc = get_schedule_desc(schedule_type, schedule_detail, schedule_time)
    if need_process and process_requirement:
        desc += f"（已启用 AI 整理）"
    
    return {
        "success": True, 
        "task": task, 
        "message": f"定时任务已设定，将在{desc}执行"
    }


def get_schedule_desc(schedule_type: str, schedule_detail: str, schedule_time: str) -> str:
    """获取定时任务的描述"""
    weekday_names = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
    
    if schedule_type == 'daily':
        return f"每天 {schedule_time}"
    elif schedule_type == 'weekly':
        return f"每周{weekday_names[int(schedule_detail)]} {schedule_time}"
    elif schedule_type == 'monthly':
        return f"每月{schedule_detail}号 {schedule_time}"
    return "未知时间"


def get_scheduled_tasks() -> list:
    """获取所有定时任务"""
    return load_schedules()


def remove_scheduled_task(task_id: str) -> Dict:
    """删除定时任务"""
    schedules = load_schedules()
    schedules = [t for t in schedules if t.get("id") != task_id]
    save_schedules(schedules)
    return {"success": True, "message": "定时任务已删除"}

def run_async_task(
    urls: str, 
    output_format: str, 
    email: str, 
    schedule_type: str, 
    schedule_detail: str, 
    schedule_time: str,
    need_process: bool = False,
    process_requirement: str = ""
):
    """在线程中运行异步任务"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            execute_scrape_task(
                urls_input=urls,
                output_format=output_format,
                send_to_email=email,
                need_process=need_process,
                process_requirement=process_requirement
            )
        )
        print(f"[Scheduler] 任务执行完成: {result.get('message', '')}")
        if need_process and process_requirement:
            print(f"[Scheduler] 已启用 AI 内容整理")
        return result
    except Exception as e:
        print(f"[Scheduler] 任务执行失败: {e}")
        return None
    finally:
        # 清理所有挂起的任务，避免事件循环关闭错误
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            # 等待所有任务取消完成
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
        finally:
            loop.close()



def check_and_execute_scheduled_tasks():
    """检查并执行到期的定时任务"""
    schedules = load_schedules()
    now = datetime.now()
    updated = False
    
    for task in schedules:
        if not task.get("enabled", True):
            continue
        
        next_run = task.get("next_run")
        if not next_run:
            continue
        
        next_run_time = datetime.fromisoformat(next_run)
        
        if next_run_time <= now:
            print(f"[Scheduler] 执行定时任务: {task['urls']} (预定时间: {next_run_time})")
            
            # 获取整理选项
            need_process = task.get("need_process", False)
            process_requirement = task.get("process_requirement", "")
            
            if need_process and process_requirement:
                print(f"[Scheduler] 启用 AI 内容整理，要求: {process_requirement[:100]}...")
            
            # 执行爬取，传入整理参数
            result = run_async_task(
                urls=task['urls'],
                output_format=task.get('format', 'markdown'),
                email=task.get('email'),
                schedule_type=task['schedule_type'],
                schedule_detail=task.get('schedule_detail', '0'),
                schedule_time=task.get('schedule_time', '08:00'),
                need_process=need_process,
                process_requirement=process_requirement
            )
            
            # 更新最后执行时间
            task['last_run'] = now.isoformat()
            
            # 计算下次执行时间
            task['next_run'] = get_next_run_time(
                task['schedule_type'],
                task.get('schedule_detail', '0'),
                task.get('schedule_time', '08:00')
            )
            updated = True
            
            print(f"[Scheduler] 下次执行时间: {task['next_run']}")
    
    if updated:
        save_schedules(schedules)


def start_scheduler():
    """启动定时任务调度器"""
    def scheduler_loop():
        print("[Scheduler] 定时任务调度器已启动，每分钟检查一次")
        while True:
            try:
                check_and_execute_scheduled_tasks()
            except Exception as e:
                print(f"[Scheduler] 调度器错误: {e}")
            time.sleep(60)  # 每分钟检查一次
    
    thread = threading.Thread(target=scheduler_loop, daemon=True)
    thread.start()