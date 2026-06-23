"""
Aegis Web UI — FastAPI 后端

启动方式：
  python main.py --web           # 默认 http://localhost:8077
  python main.py --web --port 8080
"""
from __future__ import annotations

import asyncio
import json
import sys
import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List

from web.file_operations import FileOperationManager
from web.command_parser import CommandParser
from web.models import FileCreate, FileUpdate, CommandRequest
from web.file_logger import file_logger
from tools.scraper_handler import execute_scrape_task, add_scheduled_task, get_scheduled_tasks, remove_scheduled_task
from tools.file_cleaner import file_cleaner
from pydantic import BaseModel
from fastapi.responses import FileResponse
from tools.scraper_logger import scraper_logger
from web.logger import log_chat, log_file, log_email, log_crawler, log_system, log_error
import config


# 把项目根目录加入路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from memory import db as main_db

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel

# ── 用户管理导入 ──────────────────────────────────────────────────────────
from web.user_manager import authenticate, register, get_user_dir, get_user_config_path, set_current_user, get_current_user

# ── 初始化 ─────────────────────────────────────────────────────────────────

app = FastAPI(title="Aegis", docs_url=None, redoc_url=None)

# ============================================================
# 中间件（注意添加顺序：后添加的先执行）
# 所以：CORS → Session → Token → LogUser
# 执行顺序：LogUser → Token → Session → CORS
# ============================================================

# 1. CORS（跨域）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8077", "http://127.0.0.1:8077"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# 2. Session 中间件（让 request.session 可用）
app.add_middleware(
    SessionMiddleware,
    secret_key="aegis-session-secret-key-change-me-in-production",
    session_cookie="aegis_session",
    max_age=86400,
    same_site="lax",
    https_only=False,
)

# ============================================================
# Token 认证中间件（用类实现，add_middleware 方式）
# ============================================================
_WEB_TOKEN: str = os.environ.get("JARVIS_WEB_TOKEN", "")
_NO_AUTH_PREFIXES = ("/static/", "/health", "/api/auth")

class TokenAuthMiddleware:
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        if _WEB_TOKEN:
            request = Request(scope)
            path = request.url.path
            if not any(path.startswith(p) for p in _NO_AUTH_PREFIXES):
                auth_header = request.headers.get("Authorization", "")
                query_token = request.query_params.get("token", "")
                provided = ""
                if auth_header.startswith("Bearer "):
                    provided = auth_header[7:]
                elif query_token:
                    provided = query_token
                if provided != _WEB_TOKEN:
                    from fastapi.responses import JSONResponse
                    response = JSONResponse({"detail": "Unauthorized"}, status_code=401)
                    await response(scope, receive, send)
                    return
        
        await self.app(scope, receive, send)

app.add_middleware(TokenAuthMiddleware)

# ============================================================
# 日志中间件（用类实现，add_middleware 方式）
# ============================================================
class LogUserMiddleware:
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        request = Request(scope)
        from web.logger import set_log_user
        import config as config_module
        
        # SessionMiddleware 已先执行，所以 request.session 可用
        try:
            username = request.session.get("username")
            if username:
                if config_module.get_current_user() != username:
                    config_module.set_current_user(username)
                set_log_user(username)
            else:
                set_log_user("anonymous")
        except Exception:
            set_log_user("anonymous")
        
        await self.app(scope, receive, send)

app.add_middleware(LogUserMiddleware)


# ============================================================
# 修改：使用 config.UPLOAD_DIR 替代硬编码路径
# ============================================================
FILE_REPO = config.UPLOAD_DIR
FILE_REPO.mkdir(parents=True, exist_ok=True)

print(f"[文件仓库] 文件操作目录: {FILE_REPO}")

file_manager = FileOperationManager(upload_dir=str(FILE_REPO))
command_parser = CommandParser()

class ScrapeRequest(BaseModel):
    url: Optional[str] = None
    smart_query: Optional[str] = None
    smart_mode: bool = False
    format: str = "markdown"
    email: Optional[str] = None
    need_process: bool = False
    process_requirement: Optional[str] = None

class ScrapeScheduleRequest(BaseModel):
    urls: Optional[str] = None
    smart_query: Optional[str] = None
    smart_mode: bool = False
    format: str = "markdown"
    email: Optional[str] = None
    schedule_type: str = "daily"
    schedule_detail: str = "0"
    schedule_time: str = "08:00"
    need_process: bool = False
    process_requirement: Optional[str] = None

@app.post("/api/scrape")
async def api_scrape(request: ScrapeRequest):
    """执行爬取任务"""
    result = await execute_scrape_task(
        urls_input=request.url,
        output_format=request.format,
        send_to_email=request.email,
        need_process=request.need_process,
        process_requirement=request.process_requirement,
        smart_mode=request.smart_mode,
        smart_query=request.smart_query
    )
    return result

@app.post("/api/scrape/schedule")
async def api_scrape_schedule(request: ScrapeScheduleRequest):
    """添加定时爬取任务"""
    
    # 智能搜索模式
    if request.smart_mode and request.smart_query:
        result = add_scheduled_task(
            urls=None,
            schedule_type=request.schedule_type,
            schedule_detail=request.schedule_detail,
            schedule_time=request.schedule_time,
            email=request.email,
            format_type=request.format,
            need_process=request.need_process,
            process_requirement=request.process_requirement,
            smart_query=request.smart_query,
            smart_mode=True
        )
    else:
        # 普通网址模式
        result = add_scheduled_task(
            urls=request.urls,
            schedule_type=request.schedule_type,
            schedule_detail=request.schedule_detail,
            schedule_time=request.schedule_time,
            email=request.email,
            format_type=request.format,
            need_process=request.need_process,
            process_requirement=request.process_requirement,
            smart_mode=False
        )
    
    if result["success"]:
        return {
            "success": True,
            "message": result["message"],
            "task": result["task"],
            "next_run": result["task"].get("next_run")
        }
    
    return {"success": False, "message": "添加失败"}

@app.get("/api/scrape/schedules")
async def api_get_schedules():
    """获取所有定时任务"""
    from tools.scraper_handler import get_scheduled_tasks
    return get_scheduled_tasks()

@app.delete("/api/scrape/schedule/{task_id}")
async def api_delete_schedule(task_id: str):
    """删除定时任务"""
    from tools.scraper_handler import remove_scheduled_task
    return remove_scheduled_task(task_id)

@app.get("/api/download/scrape/{filename}")
async def api_download_scrape_file(filename: str):
    """下载爬取文件（按用户隔离）"""
    from tools.scraper_handler import get_user_scrape_dir
    
    file_path = get_user_scrape_dir() / filename
    if file_path.exists():
        return FileResponse(
            path=file_path,
            filename=filename,
            media_type="application/octet-stream"
        )
    raise HTTPException(404, f"文件不存在: {filename}")

@app.get("/api/scraper/logs")
async def get_scraper_logs(limit: int = Query(50, le=200)):
    """获取爬虫操作日志"""
    logs = scraper_logger.get_recent_logs(limit)
    return {"logs": logs, "total": len(logs)}

STATIC_DIR = Path(__file__).parent / "static"
MEMORY_DIR = config.DATA_DIR / "memory"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── 工具函数 ────────────────────────────────────────────────────────────────

def _read_md(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""

def _build_chat_system_prompt() -> str:
    """构建对话系统提示词，注入关键记忆"""
    parts = [
        f"你是Aegis，{config.OWNER_NAME}的私人AI助理。你了解主人的研究背景、工作进展和生活情况。",
        "回答时直接、简洁，像一个了解主人的得力助理。支持中英文混用。",
        "",
    ]

    bg = _read_md(MEMORY_DIR / "personal" / "background.md")
    if bg:
        parts.append(f"## 关于用户的背景\n{bg[:3000]}")

    focus = _read_md(MEMORY_DIR / "focus.md")
    if focus:
        parts.append(f"## 当前工作焦点\n{focus[:800]}")

    wx_active = _read_md(MEMORY_DIR / "wechat_active.md")
    if wx_active:
        parts.append(f"## 近期微信活跃事项\n{wx_active[:800]}")

    from_emails = _read_md(MEMORY_DIR / "from_emails.md")
    if from_emails:
        parts.append(f"## 邮件摘要\n{from_emails[:2000]}")

    return "\n\n".join(parts)

# ── 格式化文件命令结果（独立函数）────────────────────────────────────────────

def format_file_command_result(result: dict) -> str:
    """格式化文件命令的执行结果"""
    action = result.get("action", "")
    name = result.get("name") or result.get("filename") or ""
    message = result.get("message", "")
    data = result.get("data", {})
    
    output = f"✅ {message}\n\n"
    
    if action == "read" and data:
        content = data.get("content", "")
        preview = content[:500] + ("..." if len(content) > 500 else "")
        output += f"📄 **{name}** 的内容：\n\n```\n{preview}\n```\n"
        
    elif action == "create" and data:
        output += f"📄 **{name}**\n"
        output += f"   大小: {data.get('size', 0)} 字节\n"
        if data.get("generated_content_preview"):
            output += f"\n📝 内容预览：\n```\n{data['generated_content_preview']}\n```\n"
            
    elif action == "update" and data:
        output += f"✏️ **{name}** 已更新\n"
        if data.get("generated_content_preview"):
            output += f"\n📝 内容预览：\n```\n{data['generated_content_preview']}\n```\n"
            
    elif action == "rename":
        old_name = result.get("name", "")
        new_name = result.get("new_name", "")
        output += f"🔄 {old_name} → {new_name}\n"
        
    elif action == "copy":
        source = result.get("name", "")
        dest = result.get("dest_name", "")
        output += f"📋 已复制: {source} → {dest}\n"
            
    elif action == "list" and data:
        files = data if isinstance(data, list) else []
        if files:
            output += f"📁 共有 **{len(files)}** 个文件：\n\n"
            for f in files[:20]:
                size_kb = f.get('size', 0) / 1024
                output += f"   📄 {f.get('name')} ({size_kb:.1f} KB)\n"
            if len(files) > 20:
                output += f"\n   ... 还有 {len(files) - 20} 个文件\n"
        else:
            output += "📁 暂无文件\n"
            
    elif action == "search" and data:
        search_results = data if isinstance(data, list) else []
        if search_results:
            output += f"🔍 找到 **{len(search_results)}** 个包含关键词的文件：\n\n"
            for r in search_results[:10]:
                output += f"   📄 {r.get('name')}\n"
                if r.get("content_preview"):
                    preview_text = r['content_preview'][:100].replace('\n', ' ')
                    output += f"      {preview_text}...\n"
        else:
            output += f"🔍 未找到包含关键词的文件\n"
    
    elif action == "merge" and data:
        sources = data.get("sources", [])
        destination = data.get("destination", "")
        output += f"📑 合并 {len(sources)} 个文件 → **{destination}**\n"
        output += f"   源文件: {', '.join(sources)}\n"
        output += f"   大小: {data.get('size', 0)} 字节\n"

    # 添加快捷操作提示
    output += f"\n---\n💡 你可以继续：\n"
    if name and action != "read":
        output += f"   • “读取 {name}” 查看内容\n"
        output += f"   • “修改 {name} 改成 xxx” 更新内容\n"
    if name:
        output += f"   • “重命名 {name} 为 新名称”\n"
        output += f"   • “复制 {name} 为 目标名称”\n"
    output += f"   • “列出所有文件” 查看全部\n"
    
    return output

# ── Pydantic 模型 ───────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    inject_memory: bool = True

class PendingAction(BaseModel):
    action: str
    note: Optional[str] = None

class RenameRequest(BaseModel):
    old_name: str
    new_name: str

class CopyRequest(BaseModel):
    source: str
    destination: str

class FolderCreateRequest(BaseModel):
    folder_name: str

# ── 用户认证 ──────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = ""

@app.post("/api/auth/login")
async def api_login(request: LoginRequest, fastapi_request: Request):
    """用户登录 - 使用 Session 存储"""
    import config as config_module
    from web.user_manager import get_user_config_path
    import importlib
    
    if authenticate(request.username, request.password):
        # 登录成功，设置当前用户
        config_module.set_current_user(request.username)
        
        # 关键：在 Session 中存储用户信息
        fastapi_request.session["username"] = request.username
        
        # 强制重新加载 config 模块
        importlib.reload(config_module)
        
        # 更新全局 FILE_REPO
        global FILE_REPO, file_manager
        FILE_REPO = config_module.UPLOAD_DIR
        file_manager = FileOperationManager(upload_dir=str(FILE_REPO))
        MEMORY_DIR = config_module.MEMORY_DIR
        
        return {
            "success": True,
            "message": "登录成功",
            "username": request.username,
            "user_dir": str(get_user_dir(request.username))
        }
    else:
        return {
            "success": False,
            "message": "用户名或密码错误"
        }

@app.post("/api/auth/register")
async def api_register(request: RegisterRequest):
    """用户注册"""
    result = register(request.username, request.password, request.display_name)
    return result

@app.post("/api/auth/logout")
async def api_logout(fastapi_request: Request):
    """用户登出 - 清除 Session"""
    import config as config_module
    
    # 清除 Session
    fastapi_request.session.clear()
    
    config_module.CURRENT_USER = None
    
    return {"success": True, "message": "已登出"}

@app.get("/api/auth/status")
async def api_auth_status(fastapi_request: Request):
    """检查登录状态 - 从 Session 读取"""
    import config as config_module
    
    # 优先从 Session 读取用户名
    username = fastapi_request.session.get("username")
    
    if username:
        # 确保 config 中的 CURRENT_USER 也是正确的
        if config_module.get_current_user() != username:
            config_module.set_current_user(username)
        
        return {
            "logged_in": True,
            "username": username
        }
    else:
        return {
            "logged_in": False,
            "username": None
        }

# ── 路由：页面 ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """首页 - 从 Session 检查登录状态"""
    import config as config_module
    
    html_path = STATIC_DIR / "index.html"
    login_path = STATIC_DIR / "login.html"
    
    # 从 Session 检查是否已登录
    username = request.session.get("username")
    
    if username:
        # 确保 config 中的 CURRENT_USER 正确
        if config_module.get_current_user() != username:
            config_module.set_current_user(username)
        
        if html_path.exists():
            return html_path.read_text(encoding="utf-8")
        return "<h1>Aegis Web UI</h1><p>static/index.html 未找到</p>"
    
    # 否则返回登录页面
    if login_path.exists():
        return login_path.read_text(encoding="utf-8")
    return """
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"><title>Aegis 登录</title></head>
    <body style="background:#0d1117;color:#e6edf3;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;">
    <div style="text-align:center;">
    <h1 style="font-size:48px;">🤖</h1>
    <h2>Aegis</h2>
    <p style="color:#8b949e;">请访问 <a href="/api/auth/status" style="color:#58a6ff;">/api/auth/status</a> 检查状态</p>
    <p style="color:#8b949e;">默认账户: admin / admin123</p>
    <p style="color:#8b949e;">请创建 <code>web/static/login.html</code> 登录页面</p>
    </div>
    </body></html>
    """

# ── 路由：系统状态 ──────────────────────────────────────────────────────────

@app.get("/api/status")
async def get_status():
    """系统状态统计"""
    try:
        with main_db.get_conn() as conn:
            email_count = conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
            email_important = conn.execute(
                "SELECT COUNT(*) FROM emails WHERE importance >= 3"
            ).fetchone()[0]
            wechat_count = conn.execute(
                "SELECT COUNT(DISTINCT chat_id) FROM wechat_messages"
            ).fetchone()[0]
            wechat_msgs = conn.execute("SELECT COUNT(*) FROM wechat_messages").fetchone()[0]
            file_count = conn.execute("SELECT COUNT(*) FROM file_index").fetchone()[0]
            hot_files = conn.execute(
                "SELECT COUNT(*) FROM file_index WHERE activity_tier='hot'"
            ).fetchone()[0] if _has_column(conn, "file_index", "activity_tier") else 0
            pending_count = conn.execute(
                "SELECT COUNT(*) FROM memory_pending WHERE status='pending'"
            ).fetchone()[0]
            contact_count = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]

        mem_files = list(MEMORY_DIR.rglob("*.md")) if MEMORY_DIR.exists() else []
        contact_files = list((MEMORY_DIR / "contacts").glob("*.md")) if (MEMORY_DIR / "contacts").exists() else []
        group_files = list((MEMORY_DIR / "groups").glob("*.md")) if (MEMORY_DIR / "groups").exists() else []
        project_files = list((MEMORY_DIR / "projects").glob("*.md")) if (MEMORY_DIR / "projects").exists() else []

        return {
            "emails": {"total": email_count, "important": email_important},
            "wechat": {"chats": wechat_count, "messages": wechat_msgs},
            "files": {"indexed": file_count, "hot": hot_files},
            "memory": {
                "total_md": len(mem_files),
                "contacts": len(contact_files),
                "groups": len(group_files),
                "projects": len(project_files),
            },
            "pending": pending_count,
            "db_contacts": contact_count,
            "updated_at": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"error": str(e)}

def _has_column(conn, table, col):
    try:
        conn.execute(f"SELECT {col} FROM {table} LIMIT 1")
        return True
    except Exception:
        return False

# ── 路由：邮件 ──────────────────────────────────────────────────────────────

@app.get("/api/emails")
async def get_emails(
    limit: int = Query(30, le=100),
    importance: int = Query(1, ge=1, le=5),
    offset: int = Query(0),
):
    with main_db.get_conn() as conn:
        rows = conn.execute("""
            SELECT id, from_addr, from_name, subject, date, summary,
                   importance, category, needs_reply, is_processed
            FROM emails
            WHERE importance >= ?
            ORDER BY date DESC
            LIMIT ? OFFSET ?
        """, (importance, limit, offset)).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM emails WHERE importance >= ?", (importance,)
        ).fetchone()[0]
    return {"total": total, "items": [dict(r) for r in rows]}

@app.get("/api/emails/detail")
async def get_email_detail(id: str = Query(...)):
    with main_db.get_conn() as conn:
        row = conn.execute("SELECT * FROM emails WHERE id = ?", (id,)).fetchone()
    if not row:
        raise HTTPException(404, "邮件不存在")
    return dict(row)

@app.get("/api/emails/{email_id}")
async def get_email_detail_path(email_id: int):
    with main_db.get_conn() as conn:
        row = conn.execute("SELECT * FROM emails WHERE id=?", (email_id,)).fetchone()
    if not row:
        raise HTTPException(404, "邮件不存在")
    return dict(row)

@app.post("/api/emails/sync")
async def sync_emails(months: int = Query(6, ge=1, le=24)):
    """同步邮件（前端按钮调用）"""
    import config as config_module
    username = config_module.get_current_user() or "anonymous"
    
    try:
        def do_sync():
            from email_module.reader import fetch_new_emails
            from email_module.summarizer import process_new_emails
            from email_module.gmail_reader import fetch_new_gmail
            
            result = {
                "163": {"status": "skipped", "count": 0},
                "gmail": {"status": "skipped", "count": 0},
                "total": 0,
                "message": ""
            }
            
            # 同步 163 邮箱
            try:
                print(f"[Sync] 开始同步 163 邮箱...")
                new_emails = fetch_new_emails(limit=100)
                if new_emails:
                    important = process_new_emails(new_emails)
                    result["163"]["status"] = "success"
                    result["163"]["count"] = len(new_emails)
                    result["total"] += len(new_emails)
                    print(f"[Sync] 163 邮箱同步完成: {len(new_emails)} 封新邮件")
                else:
                    result["163"]["status"] = "no_new"
                    result["163"]["count"] = 0
            except Exception as e:
                result["163"]["status"] = "error"
                result["163"]["error"] = str(e)
                print(f"[Sync] 163 邮箱同步失败: {e}")
            
            # 同步 Gmail（如果配置了）
            try:
                if config.GMAIL_EMAIL and config.GMAIL_APP_PWD:
                    print(f"[Sync] 开始同步 Gmail...")
                    gmail_emails = fetch_new_gmail(limit=100)
                    if gmail_emails:
                        important = process_new_emails(gmail_emails)
                        result["gmail"]["status"] = "success"
                        result["gmail"]["count"] = len(gmail_emails)
                        result["total"] += len(gmail_emails)
                        print(f"[Sync] Gmail 同步完成: {len(gmail_emails)} 封新邮件")
                    else:
                        result["gmail"]["status"] = "no_new"
                        result["gmail"]["count"] = 0
                else:
                    result["gmail"]["status"] = "not_configured"
            except Exception as e:
                result["gmail"]["status"] = "error"
                result["gmail"]["error"] = str(e)
                print(f"[Sync] Gmail 同步失败: {e}")
            
            result["message"] = f"同步完成，共 {result['total']} 封新邮件"
            return result
        
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(do_sync)
            result = future.result(timeout=120)
        
        # 记录日志
        log_email(username, f"同步邮件: {result['total']} 封新邮件")
        
        return {
            "success": True,
            "data": result,
            "message": result.get("message", "同步完成")
        }
        
    except TimeoutError:
        log_email(username, f"同步邮件超时")
        return {
            "success": False,
            "message": "同步超时，请稍后重试"
        }
    except Exception as e:
        log_email(username, f"同步邮件失败: {str(e)}")
        return {
            "success": False,
            "message": f"同步失败: {str(e)}"
        }

# ── 路由：联系人 ────────────────────────────────────────────────────────────

@app.get("/api/contacts")
async def get_contacts(limit: int = Query(50, le=200)):
    with main_db.get_conn() as conn:
        rows = conn.execute("""
            SELECT id, display_name, email, wechat_id, role, importance,
                   last_seen, email_count, wechat_msg_count, institution
            FROM contacts
            ORDER BY importance DESC, last_seen DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/contacts/files")
async def get_contact_files():
    contacts_dir = MEMORY_DIR / "contacts"
    if not contacts_dir.exists():
        return []
    files = []
    for f in sorted(contacts_dir.glob("*.md")):
        stat = f.stat()
        files.append({
            "name": f.stem,
            "path": str(f.relative_to(MEMORY_DIR)),
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return files

# ── 路由：记忆 ──────────────────────────────────────────────────────────────

@app.get("/api/memory/tree")
async def get_memory_tree():
    if not MEMORY_DIR.exists():
        return []

    def _scan(directory: Path, depth=0):
        items = []
        try:
            for p in sorted(directory.iterdir()):
                if p.name.startswith(".") or p.name.endswith(".db"):
                    continue
                if p.is_dir():
                    children = _scan(p, depth + 1) if depth < 3 else []
                    items.append({
                        "type": "dir",
                        "name": p.name,
                        "path": str(p.relative_to(MEMORY_DIR)),
                        "children": children,
                    })
                elif p.suffix == ".md":
                    items.append({
                        "type": "file",
                        "name": p.name,
                        "path": str(p.relative_to(MEMORY_DIR)),
                        "size": p.stat().st_size,
                    })
        except PermissionError:
            pass
        return items
    return _scan(MEMORY_DIR)

@app.get("/api/memory/file")
async def get_memory_file(path: str = Query(...)):
    safe_path = MEMORY_DIR / path.lstrip("/\\").replace("..", "")
    if not safe_path.exists() or not safe_path.is_file():
        raise HTTPException(404, f"文件不存在: {path}")
    if safe_path.suffix not in (".md", ".txt"):
        raise HTTPException(400, "只支持 .md 和 .txt 文件")
    return {
        "path": path,
        "content": safe_path.read_text(encoding="utf-8"),
        "modified": datetime.fromtimestamp(safe_path.stat().st_mtime).isoformat(),
    }

@app.get("/api/memory/overview")
async def get_memory_overview():
    return {
        "background": _read_md(MEMORY_DIR / "personal" / "background.md")[:3000],
        "focus": _read_md(MEMORY_DIR / "focus.md"),
        "from_emails_summary": _read_md(MEMORY_DIR / "from_emails.md")[:2000],
        "wechat_active": _read_md(MEMORY_DIR / "wechat_active.md")[:2000],
        "index": _read_md(MEMORY_DIR / "INDEX.md"),
    }

class FocusAction(BaseModel):
    action: str
    text: str

@app.post("/api/focus/action")
async def focus_action(body: FocusAction):
    focus_path = MEMORY_DIR / "focus.md"
    if not focus_path.exists():
        raise HTTPException(404, "focus.md 不存在")
    content = focus_path.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    new_lines = []
    found = False
    search = body.text.strip()
    for line in lines:
        stripped = line.strip()
        if not found and (
            stripped == f"- [ ] {search}" or
            stripped == f"- [x] {search}" or
            stripped.startswith(f"- [ ] {search}") or
            stripped.startswith(f"- [x] {search}")
        ):
            found = True
            if body.action == "complete":
                from datetime import date
                done_line = line.replace("[ ]", "[x]", 1).rstrip()
                done_line += f"  ✓ {date.today()}\n"
                new_lines.append(done_line)
        else:
            new_lines.append(line)
    if not found:
        raise HTTPException(404, f"未找到条目: {search}")
    new_content = "".join(new_lines)
    try:
        from memory.writer import get_writer
        get_writer().write("focus.md", "update", new_content, "web_ui")
    except Exception:
        focus_path.write_text(new_content, encoding="utf-8")
    return {"ok": True, "action": body.action, "text": search}

class FocusSource(BaseModel):
    db_ref: str

@app.post("/api/focus/source")
async def focus_source(body: FocusSource):
    ref = body.db_ref.strip()
    if not ref:
        raise HTTPException(400, "db_ref 不能为空")
    m = re.match(r'^(email|wechat):(.+)$', ref)
    if not m:
        return {"ok": False, "text": "无法解析来源引用"}
    src_type, src_id = m.group(1), m.group(2)
    try:
        if src_type == "email":
            from memory import db as _db
            with _db.get_conn() as conn:
                row = conn.execute(
                    "SELECT subject, from_addr, from_name, date, summary, body FROM emails WHERE id=? LIMIT 1",
                    (src_id,)
                ).fetchone()
            if not row:
                return {"ok": False, "text": f"未找到邮件 (id={src_id})"}
            sender = row["from_name"] or row["from_addr"] or "未知"
            date_str = (row["date"] or "")[:10]
            body_preview = (row["body"] or row["summary"] or "")[:300]
            return {
                "ok": True,
                "source_type": "email",
                "sender": sender,
                "sender_addr": row["from_addr"],
                "date": date_str,
                "subject": row["subject"] or "",
                "text": body_preview,
            }
        elif src_type == "wechat":
            from memory import db as _db
            with _db.get_conn() as conn:
                rows = conn.execute("""
                    SELECT talker_name, content, ts
                    FROM wechat_messages
                    WHERE talker_wxid = ? AND is_self = 0
                    ORDER BY create_time DESC LIMIT 5
                """, (src_id,)).fetchall()
                if not rows:
                    rows = conn.execute("""
                        SELECT talker_name, content, ts
                        FROM wechat_messages
                        WHERE talker_wxid LIKE ?
                        ORDER BY create_time DESC LIMIT 5
                    """, (f"%{src_id}%",)).fetchall()
            if not rows:
                return {"ok": False, "text": f"未找到微信消息 (wxid={src_id})"}
            sender = rows[0]["talker_name"] or src_id
            snippets = "\n".join(f"[{r['ts'][:16]}] {r['content'][:100]}" for r in rows)
            return {
                "ok": True,
                "source_type": "wechat",
                "sender": sender,
                "date": (rows[0]["ts"] or "")[:10],
                "text": snippets,
            }
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"ok": False, "text": "未知来源类型"}

class FocusReply(BaseModel):
    focus_text: str
    contact: str
    channel: str = "wechat"
    core_message: str

@app.post("/api/focus/reply")
async def focus_reply(body: FocusReply):
    if not body.core_message.strip():
        raise HTTPException(400, "回复内容不能为空")
    if not body.contact.strip():
        raise HTTPException(400, "收件人不能为空")
    try:
        from email_module.command_handler import _handle_reply_instruction
        result = _handle_reply_instruction(
            channel=body.channel,
            contact_hint=body.contact.strip(),
            core_message=body.core_message.strip(),
            context={"focus_text": body.focus_text},
        )
        return {"ok": True, "result": result}
    except Exception as e:
        raise HTTPException(500, str(e))

class FocusAdd(BaseModel):
    text: str
    ai_parse: bool = True

@app.post("/api/focus/add")
async def focus_add(body: FocusAdd):
    from ai import client as ai_client
    import json as _json
    from datetime import date

    raw = body.text.strip()
    if not raw:
        raise HTTPException(400, "内容不能为空")

    if body.ai_parse:
        try:
            parse_prompt = f"""用户想添加一条焦点事项：

「{raw}」

请解析并输出 JSON：
{{
  "text": "简洁的条目描述（≤30字）",
  "priority": "urgent | normal | waiting",
  "deadline": "YYYY-MM-DD 或空字符串",
  "project": "关联项目名（如有）",
  "section": "紧急 | 常规 | 等待/观察"
}}

今天是 {date.today()}。
只输出 JSON。"""
            result = ai_client.chat(
                messages=[{"role": "user", "content": parse_prompt}],
                system_prompt="你是任务解析助手。",
                temperature=0.1,
            )
            result = result.strip().strip("```json").strip("```").strip()
            parsed = _json.loads(result)
        except Exception:
            parsed = {"text": raw, "priority": "normal", "deadline": "", "project": "", "section": "常规"}
    else:
        parsed = {"text": raw, "priority": "normal", "deadline": "", "project": "", "section": "常规"}

    text = parsed.get("text", raw).strip()
    deadline = parsed.get("deadline", "").strip()
    project = parsed.get("project", "").strip()
    section = parsed.get("section", "常规").strip()
    priority = parsed.get("priority", "normal")

    item_line = f"- [ ] {text}"
    if deadline:
        item_line += f" (截止:{deadline})"
    if project:
        item_line += f" [{project}]"

    focus_path = MEMORY_DIR / "focus.md"
    if not focus_path.exists():
        init_content = (
            f"# 当前焦点清单\n> 更新: {date.today()}\n\n"
            "## 紧急\n\n## 常规\n\n## 等待/观察\n"
        )
        try:
            from memory.writer import get_writer
            get_writer().write("focus.md", "update", init_content, "web_ui")
        except Exception:
            focus_path.write_text(init_content, encoding="utf-8")

    content = focus_path.read_text(encoding="utf-8")
    section_map = {
        "紧急": "## 紧急", "urgent": "## 紧急",
        "常规": "## 常规", "normal": "## 常规",
        "等待/观察": "## 等待/观察", "waiting": "## 等待/观察",
    }
    target_header = section_map.get(section, section_map.get(priority, "## 常规"))

    if target_header in content:
        lines = content.split("\n")
        insert_idx = None
        in_section = False
        for i, line in enumerate(lines):
            if line.strip() == target_header:
                in_section = True
                continue
            if in_section:
                if line.startswith("## "):
                    insert_idx = i
                    break
                if line.strip().startswith("- "):
                    insert_idx = i + 1
        if insert_idx is None:
            insert_idx = len(lines)
        lines.insert(insert_idx, item_line)
        content = "\n".join(lines)
    else:
        content = content.rstrip() + f"\n\n{target_header}\n{item_line}\n"

    try:
        from memory.writer import get_writer
        get_writer().write("focus.md", "update", content, "web_ui")
    except Exception:
        focus_path.write_text(content, encoding="utf-8")

    return {
        "ok": True,
        "item": item_line,
        "section": target_header,
        "parsed": parsed,
    }

@app.get("/api/memory/groups")
async def get_group_files():
    groups_dir = MEMORY_DIR / "groups"
    if not groups_dir.exists():
        return []
    files = []
    for f in sorted(groups_dir.glob("*.md")):
        stat = f.stat()
        files.append({
            "name": f.stem,
            "path": str(f.relative_to(MEMORY_DIR)),
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return files

@app.get("/api/memory/projects")
async def get_project_files():
    projects_dir = MEMORY_DIR / "projects"
    if not projects_dir.exists():
        return []
    files = []
    for f in sorted(projects_dir.glob("*.md")):
        stat = f.stat()
        files.append({
            "name": f.stem,
            "path": str(f.relative_to(MEMORY_DIR)),
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return files

# ── 路由：待审核 ────────────────────────────────────────────────────────────

@app.get("/api/pending")
async def get_pending(status: str = Query("pending"), limit: int = Query(50)):
    with main_db.get_conn() as conn:
        rows = conn.execute("""
            SELECT id, source, source_ref, content, proposed_layer,
                   proposed_target, item_type, confidence,
                   extracted_at, status, notes
            FROM memory_pending
            WHERE status = ?
            ORDER BY extracted_at DESC
            LIMIT ?
        """, (status, limit)).fetchall()
    return [dict(r) for r in rows]

@app.post("/api/pending/{item_id}")
async def handle_pending(item_id: int, body: PendingAction):
    from memory.pending import approve, reject
    with main_db.get_conn() as conn:
        row = conn.execute("SELECT * FROM memory_pending WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, "条目不存在")
    if body.action == "approve":
        approve(item_id)
        return {"ok": True, "action": "approved"}
    elif body.action == "reject":
        reject(item_id)
        return {"ok": True, "action": "rejected"}
    else:
        raise HTTPException(400, "action 必须是 approve 或 reject")

# ── 路由：微信消息 ──────────────────────────────────────────────────────────

@app.get("/api/wechat/chats")
async def get_wechat_chats(limit: int = Query(50)):
    with main_db.get_conn() as conn:
        rows = conn.execute("""
            SELECT chat_id, talker_name,
                   COUNT(*) as msg_count,
                   MAX(create_time) as last_time,
                   SUM(CASE WHEN is_sender=1 THEN 1 ELSE 0 END) as my_count
            FROM wechat_messages
            GROUP BY chat_id
            ORDER BY msg_count DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]

@app.get("/api/wechat/messages")
async def get_wechat_messages(
    chat_id: str = Query(...),
    limit: int = Query(50),
    offset: int = Query(0),
):
    with main_db.get_conn() as conn:
        rows = conn.execute("""
            SELECT id, talker_name, content, is_sender, create_time, msg_type
            FROM wechat_messages
            WHERE chat_id = ?
            ORDER BY create_time DESC
            LIMIT ? OFFSET ?
        """, (chat_id, limit, offset)).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) FROM wechat_messages WHERE chat_id=?", (chat_id,)
        ).fetchone()[0]
    return {"total": total, "items": [dict(r) for r in rows]}

# ── 路由：文件操作 ──────────────────────────────────────────────────────────

@app.post("/api/files/create")
async def api_create_file(file_create: FileCreate):
    """创建文件"""
    import config as config_module
    username = config_module.get_current_user() or "anonymous"
    
    if not (file_create.filename.endswith('.txt') or file_create.filename.endswith('.docx')):
        raise HTTPException(status_code=400, detail="文件类型必须是.txt或.docx")
    result = await file_manager.create_file(file_create.filename, file_create.content)
    
    if result["success"]:
        log_file(username, f"创建文件: {file_create.filename}")
    else:
        log_file(username, f"创建文件失败: {file_create.filename} | {result['message']}")
    
    return result

@app.get("/api/files/read/{filename}")
async def api_read_file(filename: str):
    """读取文件内容"""
    result = await file_manager.read_file(filename)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    return result

@app.put("/api/files/update/{filename}")
async def api_update_file(filename: str, file_update: FileUpdate):
    """更新文件内容"""
    result = await file_manager.update_file(filename, file_update.content)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result

@app.post("/api/files/rename")
async def api_rename_file(request: RenameRequest):
    """重命名文件或文件夹"""
    result = await file_manager.rename_file(request.old_name, request.new_name)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result

@app.post("/api/files/copy")
async def api_copy_file(request: CopyRequest):
    """复制文件或文件夹"""
    result = await file_manager.copy_file(request.source, request.destination)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result

@app.post("/api/folder/create")
async def api_create_folder(request: FolderCreateRequest):
    """创建文件夹"""
    result = await file_manager.create_folder(request.folder_name)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return result

@app.get("/api/items/list")
async def api_list_items():
    """列出所有文件和文件夹"""
    result = await file_manager.list_items()
    return result

@app.get("/api/files/search")
async def api_search_files(keyword: str = Query(..., min_length=1)):
    """搜索文件内容"""
    result = await file_manager.search_files(keyword)
    return result

@app.post("/api/command/file")
async def api_file_command(request: CommandRequest):
    """执行自然语言文件命令"""
    import config as config_module
    username = config_module.get_current_user() or "anonymous"
    
    parse_result = await command_parser.parse_command(request.command)
    if not parse_result["success"]:
        raise HTTPException(status_code=400, detail=f"命令解析失败: {parse_result.get('error', '未知错误')}")
    
    parsed = parse_result["command"]
    action = parsed.get("action")
    name = parsed.get("name")
    new_name = parsed.get("new_name")
    dest_name = parsed.get("dest_name")
    content_description = parsed.get("content_description")
    keyword = parsed.get("keyword")
    need_generate = parsed.get("need_generate", False)
    
    actual_content = None
    if need_generate and content_description and action in ["create", "update"]:
        actual_content = await command_parser.generate_content(content_description)
    elif content_description and not need_generate:
        actual_content = content_description
    
    result = None
    
    # 根据操作类型执行
    if action == "merge":
        if isinstance(name, str):
            if name.startswith('['):
                import ast
                try:
                    source_list = ast.literal_eval(name)
                except:
                    source_list = [n.strip() for n in name.strip('[]').split(',')]
            else:
                source_list = [n.strip() for n in name.split(',')]
        elif isinstance(name, list):
            source_list = name
        else:
            source_list = [name]
        
        if not source_list:
            raise HTTPException(status_code=400, detail="合并操作需要提供源文件列表")
        if not dest_name:
            raise HTTPException(status_code=400, detail="合并操作需要提供目标文件名")
        
        result = await file_manager.merge_files(source_list, dest_name)
            
    elif action == "create":
        if not name:
            raise HTTPException(status_code=400, detail="创建操作需要提供文件名")
        result = await file_manager.create_file(name, actual_content or "")
            
    elif action == "read":
        if not name:
            raise HTTPException(status_code=400, detail="读取操作需要提供文件名")
        result = await file_manager.read_file(name)
        
    elif action == "update":
        if not name:
            raise HTTPException(status_code=400, detail="更新操作需要提供文件名")
        if not actual_content:
            raise HTTPException(status_code=400, detail="更新操作需要提供新内容")
        result = await file_manager.update_file(name, actual_content)
        
    elif action == "rename":
        if not name:
            raise HTTPException(status_code=400, detail="重命名操作需要提供原名称")
        if not new_name:
            raise HTTPException(status_code=400, detail="重命名操作需要提供新名称")
        result = await file_manager.rename_file(name, new_name)
        
    elif action == "copy":
        if not name:
            raise HTTPException(status_code=400, detail="复制操作需要提供源名称")
        if not dest_name:
            raise HTTPException(status_code=400, detail="复制操作需要提供目标名称")
        result = await file_manager.copy_file(name, dest_name)
        
    elif action == "list":
        result = await file_manager.list_files()
        
    elif action == "search":
        if not keyword:
            raise HTTPException(status_code=400, detail="搜索操作需要提供关键词")
        result = await file_manager.search_files(keyword)
        
    else:
        raise HTTPException(status_code=400, detail=f"不支持的操作类型: {action}")
    
    response_data = result.get("data")
    if need_generate and actual_content and action in ["create", "update"] and response_data:
        if isinstance(response_data, dict):
            response_data["generated_content_preview"] = actual_content[:200] + "..." if len(actual_content) > 200 else actual_content
    
    # 记录文件操作日志
    if result["success"]:
        log_file(username, f"执行文件操作: {action} {name or ''}")
    else:
        log_file(username, f"文件操作失败: {action} {name or ''} | {result.get('message', '')}")
    
    return {
        "action": action,
        "name": name or "",
        "new_name": new_name or "",
        "dest_name": dest_name or "",
        "keyword": keyword or "",
        "success": result["success"],
        "message": result["message"],
        "data": response_data
    }

# ── 路由：搜索 ──────────────────────────────────────────────────────────────

@app.get("/api/search")
async def search(q: str = Query(..., min_length=1), limit: int = Query(20)):
    results = []
    pat = f"%{q}%"
    with main_db.get_conn() as conn:
        rows = conn.execute("""
            SELECT 'email' as source, id,
                   COALESCE(subject,'(无主题)') as title,
                   COALESCE(summary, subject, '') as snippet,
                   COALESCE(from_addr,'') as meta,
                   COALESCE(date,'') as ts,
                   COALESCE(importance,1) as importance
            FROM emails
            WHERE subject LIKE ? OR summary LIKE ? OR from_addr LIKE ? OR from_name LIKE ?
            ORDER BY importance DESC, date DESC
            LIMIT ?
        """, (pat, pat, pat, pat, limit // 2)).fetchall()
        results.extend([dict(r) for r in rows])

        wx_rows = conn.execute("""
            SELECT 'wechat' as source, id,
                   COALESCE(talker_name,'') as title,
                   COALESCE(content,'') as snippet,
                   COALESCE(chat_id,'') as meta,
                   COALESCE(create_time,'') as ts,
                   0 as importance
            FROM wechat_messages
            WHERE content LIKE ?
            ORDER BY create_time DESC
            LIMIT ?
        """, (pat, limit // 3)).fetchall()
        results.extend([dict(r) for r in wx_rows])

        file_rows = conn.execute("""
            SELECT 'file' as source, rowid as id,
                   COALESCE(filename,'') as title,
                   COALESCE(path,'') as snippet,
                   COALESCE(extension,'') as meta,
                   COALESCE(indexed_at,'') as ts,
                   0 as importance
            FROM file_index
            WHERE filename LIKE ? OR path LIKE ?
            ORDER BY indexed_at DESC
            LIMIT ?
        """, (pat, pat, 10)).fetchall()
        results.extend([dict(r) for r in file_rows])

    for md_file in MEMORY_DIR.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
            if q.lower() in content.lower():
                results.append({
                    "source": "memory",
                    "id": None,
                    "title": md_file.stem,
                    "snippet": _find_snippet(content, q, 150),
                    "meta": str(md_file.relative_to(MEMORY_DIR)),
                    "ts": datetime.fromtimestamp(md_file.stat().st_mtime).isoformat(),
                    "importance": 3,
                })
        except Exception:
            pass

    results.sort(key=lambda x: (-(x.get("importance") or 0), x.get("ts", "") or ""), reverse=False)
    return {"query": q, "total": len(results), "results": results[:limit]}

def _find_snippet(text: str, query: str, length: int = 150) -> str:
    idx = text.lower().find(query.lower())
    if idx < 0:
        return text[:length]
    start = max(0, idx - 30)
    return ("..." if start > 0 else "") + text[start:start + length] + "..."

# ── 路由：流式对话 ──────────────────────────────────────────────────────────

async def _execute_file_command(command: str) -> dict:
    """异步执行文件命令"""
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8077/api/command/file",
            json={"command": command},
            timeout=60.0
        )
        return resp.json()

def _execute_email_command(command: str) -> str:
    """同步执行邮件/任务命令"""
    from email_module.command_handler import _execute_command
    return _execute_command(command, context={"source": "web"})

@app.post("/api/emails/summarize")
async def summarize_emails_direct(request: Request):
    """独立的邮件汇总接口 - 不经过文件操作判断"""
    try:
        body = await request.json()
        emails = body.get("emails", [])
        
        if not emails:
            return {"success": False, "message": "没有邮件内容"}
        
        summary_lines = []
        for i, email in enumerate(emails, 1):
            from_name = email.get("from", "未知")
            date = email.get("date", "未知日期")
            content = email.get("content", "无内容")
            summary_lines.append(f"邮件{i}：{from_name}，{date}，{content}")
        
        prompt = f"""请按以下格式汇总邮件，每条邮件后必须换行：

邮件1：谁发的，时间，内容
邮件2：谁发的，时间，内容
邮件3：谁发的，时间，内容
邮件4：谁发的，时间，内容
邮件5：谁发的，时间，内容

邮件内容：
{chr(10).join(summary_lines)}"""
        
        from ai import client as ai_client
        result = ai_client.chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="你是邮件助理。每条邮件汇总后必须换行，不要合并成一行。",
            temperature=0.3,
        )
        
        # 强制格式化：确保每条邮件后都有换行
        formatted = re.sub(r'(邮件\d+[：:])', r'\n\1', result)
        formatted = formatted.strip()
        
        return {"success": True, "summary": formatted}
        
    except Exception as e:
        print(f"邮件汇总失败: {e}")
        return {"success": False, "message": str(e)}

@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    """流式对话 (SSE)"""

    async def generate():
        try:
            import ai.client as ai_client
            import re
            import openai
            import json
            import config as config_module

            last_user = next(
                (m.content for m in reversed(req.messages) if m.role == "user"), ""
            )

            username = config_module.get_current_user() or "anonymous"

            print(f"[DEBUG] 用户输入: {last_user}")

            # ============================================================
            # 使用大模型解析用户指令
            # ============================================================
            parse_prompt = f"""你是一个指令解析助手。用户输入了一段话，请判断用户想要执行什么操作，并输出JSON格式的指令。

用户输入：{last_user}

请判断用户意图，输出以下JSON格式：
{{
    "action": "操作类型",
    "params": {{"参数1": "值1", "参数2": "值2"}},
    "is_command": true/false
}}

支持的操作类型：
1. "write_file" - 写入文件内容（创建新文件或追加内容）
2. "read_file" - 读取文件内容
3. "create_file" - 创建空文件
4. "delete_file" - 删除文件
5. "rename_file" - 重命名文件
6. "copy_file" - 复制文件
7. "list_files" - 列出所有文件
8. "search_files" - 搜索文件内容
9. "send_email" - 发送邮件
10. "search_knowledge" - 搜索知识库
11. "run_script" - 运行脚本
12. "list_scripts" - 列出脚本
13. "chat" - 普通对话

参数说明：
- write_file: {{"filename": "文件名", "content": "要写入的内容", "append": true/false}}
- read_file: {{"filename": "文件名"}}
- create_file: {{"filename": "文件名"}}
- delete_file: {{"filename": "文件名"}}
- rename_file: {{"old_name": "旧文件名", "new_name": "新文件名"}}
- copy_file: {{"source": "源文件名", "destination": "目标文件名"}}
- search_files: {{"keyword": "关键词"}}
- send_email: {{"to": "收件人", "subject": "主题", "content": "内容"}}
- search_knowledge: {{"query": "搜索关键词"}}
- run_script: {{"script": "脚本名", "args": "参数"}}

如果用户没有明确说要做文件操作，而是普通聊天，则 is_command: false。

只输出JSON，不要有其他内容。"""

            try:
                parse_result = ai_client.chat(
                    messages=[{"role": "user", "content": parse_prompt}],
                    system_prompt="你是一个指令解析助手，只输出纯JSON。",
                    temperature=0.1,
                )
                parse_result = parse_result.strip().strip("```json").strip("```").strip()
                parsed = json.loads(parse_result)
                action = parsed.get("action", "chat")
                params = parsed.get("params", {})
                is_command = parsed.get("is_command", False)
                
                print(f"[DEBUG] 大模型解析结果: action={action}, params={params}")
                
            except Exception as e:
                print(f"[DEBUG] 大模型解析失败: {e}，使用普通对话")
                action = "chat"
                params = {}
                is_command = False

            # ============================================================
            # 根据解析结果执行操作
            # ============================================================

            # ---- 1. 写入文件 ----
            if action == "write_file":
                filename = params.get("filename", "")
                content = params.get("content", "")
                append = params.get("append", True)
                
                if not filename:
                    output = "❌ 请指定文件名"
                elif not content:
                    output = "❌ 请指定要写入的内容"
                else:
                    try:
                        # 判断是否是经典文章标题，如果是则调用大模型生成全文
                        article_titles = ["岳阳楼记", "逍遥游", "滕王阁序", "赤壁赋", "阿房宫赋", 
                                          "出师表", "劝学", "师说", "过秦论", "六国论",
                                          "桃花源记", "归去来兮辞", "兰亭集序"]
                        
                        is_article = any(title in content for title in article_titles) and len(content) < 30
                        
                        if is_article:
                            print(f"[DEBUG] 检测到文章标题「{content}」，调用大模型生成全文...")
                            try:
                                article_prompt = f"""请提供「{content}」的完整原文（全文），不要添加任何注释、翻译或说明，只输出文章本身的内容。"""
                                
                                article_result = ai_client.chat(
                                    messages=[{"role": "user", "content": article_prompt}],
                                    system_prompt="你是一个古文资料库，提供经典文章的完整原文。只输出文章内容，不要添加任何额外信息。",
                                    temperature=0.1,
                                )
                                
                                if article_result and len(article_result) > 50:
                                    content = article_result.strip()
                                    print(f"[DEBUG] 大模型生成了 {len(content)} 字符的完整内容")
                            except Exception as e:
                                print(f"[DEBUG] 调用大模型生成文章失败: {e}")
                        
                        file_path = FILE_REPO / filename
                        if file_path.exists() and append:
                            with open(file_path, 'a', encoding='utf-8') as f:
                                f.write('\n' + content)
                            output = f"✅ 内容已追加到 **{filename}**！\n\n📝 新增内容：\n```\n{content[:200]}\n```"
                        else:
                            with open(file_path, 'w', encoding='utf-8') as f:
                                f.write(content)
                            output = f"✅ 文件 **{filename}** 已创建并写入内容！\n\n📝 内容：\n```\n{content[:200]}\n```"
                        
                        # 记录文件写入日志
                        log_file(username, f"写入文件: {filename}")
                        
                    except Exception as e:
                        output = f"❌ 写入失败: {str(e)}"
                        log_error(username, f"写入文件失败: {filename}", e)

            # ---- 2. 读取文件 ----
            elif action == "read_file":
                filename = params.get("filename", "")
                if not filename:
                    output = "❌ 请指定要读取的文件名"
                else:
                    try:
                        file_path = FILE_REPO / filename
                        if not file_path.exists():
                            output = f"❌ 文件不存在: {filename}"
                        else:
                            content = file_path.read_text(encoding="utf-8")
                            preview = content[:2000] + ("..." if len(content) > 2000 else "")
                            output = f"📄 **{filename}** 的内容：\n\n```\n{preview}\n```\n\n**总长度**: {len(content)} 字符"
                            log_file(username, f"读取文件: {filename}")
                    except Exception as e:
                        output = f"❌ 读取失败: {str(e)}"
                        log_error(username, f"读取文件失败: {filename}", e)

            # ---- 3. 创建文件 ----
            elif action == "create_file":
                filename = params.get("filename", "")
                if not filename:
                    output = "❌ 请指定要创建的文件名"
                else:
                    try:
                        file_path = FILE_REPO / filename
                        if file_path.exists():
                            output = f"⚠️ 文件已存在: {filename}"
                        else:
                            file_path.touch()
                            output = f"✅ 文件已创建: **{filename}**"
                            log_file(username, f"创建文件: {filename}")
                    except Exception as e:
                        output = f"❌ 创建失败: {str(e)}"
                        log_error(username, f"创建文件失败: {filename}", e)

            # ---- 4. 删除文件 ----
            elif action == "delete_file":
                filename = params.get("filename", "")
                if not filename:
                    output = "❌ 请指定要删除的文件名"
                else:
                    try:
                        file_path = FILE_REPO / filename
                        if not file_path.exists():
                            output = f"❌ 文件不存在: {filename}"
                        else:
                            file_path.unlink()
                            output = f"✅ 文件已删除: **{filename}**"
                            log_file(username, f"删除文件: {filename}")
                    except Exception as e:
                        output = f"❌ 删除失败: {str(e)}"
                        log_error(username, f"删除文件失败: {filename}", e)

            # ---- 5. 重命名文件 ----
            elif action == "rename_file":
                old_name = params.get("old_name", "")
                new_name = params.get("new_name", "")
                if not old_name or not new_name:
                    output = "❌ 请指定原文件名和新文件名"
                else:
                    try:
                        old_path = FILE_REPO / old_name
                        new_path = FILE_REPO / new_name
                        if not old_path.exists():
                            output = f"❌ 文件不存在: {old_name}"
                        elif new_path.exists():
                            output = f"❌ 目标文件已存在: {new_name}"
                        else:
                            old_path.rename(new_path)
                            output = f"✅ 重命名成功！\n\n**原文件名**: {old_name}\n**新文件名**: {new_name}"
                            log_file(username, f"重命名文件: {old_name} → {new_name}")
                    except Exception as e:
                        output = f"❌ 重命名失败: {str(e)}"
                        log_error(username, f"重命名文件失败: {old_name} → {new_name}", e)

            # ---- 6. 复制文件 ----
            elif action == "copy_file":
                source = params.get("source", "")
                destination = params.get("destination", "")
                if not source or not destination:
                    output = "❌ 请指定源文件名和目标文件名"
                else:
                    try:
                        src_path = FILE_REPO / source
                        dst_path = FILE_REPO / destination
                        if not src_path.exists():
                            output = f"❌ 文件不存在: {source}"
                        else:
                            shutil.copy2(src_path, dst_path)
                            output = f"✅ 复制成功！\n\n**源文件**: {source}\n**目标文件**: {destination}"
                            log_file(username, f"复制文件: {source} → {destination}")
                    except Exception as e:
                        output = f"❌ 复制失败: {str(e)}"
                        log_error(username, f"复制文件失败: {source} → {destination}", e)

            # ---- 7. 列出文件 ----
            elif action == "list_files":
                try:
                    files = list(FILE_REPO.glob("*"))
                    if files:
                        output = f"📁 共有 **{len(files)}** 个文件：\n\n"
                        for f in sorted(files, key=lambda x: x.name)[:30]:
                            size_kb = f.stat().st_size / 1024
                            output += f"   📄 {f.name} ({size_kb:.1f} KB)\n"
                        if len(files) > 30:
                            output += f"\n... 还有 {len(files) - 30} 个文件\n"
                    else:
                        output = "📁 暂无文件"
                    log_file(username, f"列出文件: 共 {len(files) if files else 0} 个")
                except Exception as e:
                    output = f"❌ 列出文件失败: {str(e)}"
                    log_error(username, f"列出文件失败", e)

            # ---- 8. 搜索文件 ----
            elif action == "search_files":
                keyword = params.get("keyword", "")
                if not keyword:
                    output = "❌ 请指定搜索关键词"
                else:
                    try:
                        results = []
                        for f in FILE_REPO.glob("*"):
                            if keyword.lower() in f.name.lower():
                                results.append(f)
                        if results:
                            output = f"🔍 找到 **{len(results)}** 个包含关键词的文件：\n\n"
                            for f in results[:20]:
                                output += f"   📄 {f.name}\n"
                        else:
                            output = f"🔍 未找到包含「{keyword}」的文件"
                        log_file(username, f"搜索文件: {keyword} → {len(results) if results else 0} 个结果")
                    except Exception as e:
                        output = f"❌ 搜索失败: {str(e)}"
                        log_error(username, f"搜索文件失败: {keyword}", e)

            # ---- 9. 发送邮件 ----
            elif action == "send_email":
                try:
                    from email_module.command_handler import _execute_command
                    output = _execute_command(last_user, context={"source": "web"})
                    log_email(username, f"发送邮件: {last_user[:100]}")
                except Exception as e:
                    output = f"❌ 邮件操作失败: {str(e)}"
                    log_error(username, f"邮件操作失败", e)

            # ---- 10. 搜索知识库 ----
            elif action == "search_knowledge":
                query = params.get("query", last_user)
                try:
                    from memory import fts_store
                    results = fts_store.search(query, top_k=10)
                    if results:
                        output = f"🔍 搜索「{query}」找到 {len(results)} 条结果：\n\n"
                        for r in results[:10]:
                            output += f"   📄 {r.get('text', '')[:100]}...\n"
                    else:
                        output = f"🔍 未找到与「{query}」相关的内容"
                except Exception as e:
                    output = f"❌ 搜索失败: {str(e)}"

            # ---- 11. 运行脚本 ----
            elif action == "run_script":
                try:
                    from email_module.command_handler import _handle_run_script, _handle_list_scripts
                    output = _handle_run_script(last_user)
                    log_file(username, f"运行脚本: {last_user[:100]}")
                except Exception as e:
                    output = f"❌ 脚本执行失败: {str(e)}"
                    log_error(username, f"脚本执行失败", e)

            # ---- 12. 列出脚本 ----
            elif action == "list_scripts":
                try:
                    from email_module.command_handler import _handle_list_scripts
                    output = _handle_list_scripts()
                except Exception as e:
                    output = f"❌ 列出脚本失败: {str(e)}"

            # ---- 13. 普通对话 ----
            else:
                system_prompt = _build_chat_system_prompt() if req.inject_memory else "你是Aegis，一个智能AI助理。"
                messages = [{"role": m.role, "content": m.content} for m in req.messages]
                msgs = [{"role": "system", "content": system_prompt}] + messages

                try:
                    if not config.VOLC_API_KEY or config.VOLC_API_KEY == "":
                        raise ValueError("❌ API Key 未配置，请在设置页面填写")
                    if not config.VOLC_MODEL or config.VOLC_MODEL == "":
                        raise ValueError("❌ 模型名称未配置，请在设置页面填写")
                    
                    client = openai.OpenAI(
                        api_key=config.VOLC_API_KEY,
                        base_url=config.VOLC_API_BASE,
                    )
                    
                    stream = client.chat.completions.create(
                        model=config.VOLC_MODEL,
                        messages=msgs,
                        stream=True,
                        temperature=0.7,
                    )

                    # 收集回复内容用于日志
                    full_reply = ""
                    for chunk in stream:
                        delta = chunk.choices[0].delta
                        if delta.content:
                            full_reply += delta.content
                            data = json.dumps({"text": delta.content}, ensure_ascii=False)
                            yield f"data: {data}\n\n"
                    
                    # 记录对话日志
                    log_chat(username, f"用户输入: {last_user[:200]}")
                    log_chat(username, f"AI回复: {full_reply[:200]}")
                    
                    yield "data: [DONE]\n\n"
                    
                except Exception as e:
                    error_msg = str(e)
                    print(f"[DEBUG] API 调用失败: {error_msg}")
                    log_error(username, f"AI对话失败: {last_user[:100]}", e)
                    if "401" in error_msg or "AuthenticationError" in error_msg or "认证失败" in error_msg:
                        yield f"data: {json.dumps({'text': '❌ API 认证失败，请检查 API Key 是否正确'}, ensure_ascii=False)}\n\n"
                    elif "参数不完整" in error_msg or "30001" in error_msg:
                        yield f"data: {json.dumps({'text': f'❌ API 参数不完整，请检查模型名称: {config.VOLC_MODEL}'}, ensure_ascii=False)}\n\n"
                    else:
                        yield f"data: {json.dumps({'text': f'❌ 错误: {error_msg[:200]}'}, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                return

            # ============================================================
            # 输出操作结果
            # ============================================================
            for i in range(0, len(output), 80):
                data = json.dumps({"text": output[i:i+80]}, ensure_ascii=False)
                yield f"data: {data}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as e:
            import traceback
            traceback.print_exc()
            err = json.dumps({"error": str(e)}, ensure_ascii=False)
            yield f"data: {err}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

# ── 新增大模型解析函数 ──────────────────────────────────────────────────────

async def parse_clean_command_with_ai(text: str) -> Optional[Dict]:
    """使用大模型解析文件清洗指令"""
    try:
        from ai import client as ai_client
        
        prompt = f"""请解析以下用户指令，提取出【文件路径】和【操作要求】。

用户指令：{text}

请严格按照以下 JSON 格式输出（不要添加任何其他内容）：
{{
    "filepath": "文件名（只包含文件名，不要包含动词，如 temp1.txt）",
    "instruction": "用户想要对文件执行的操作描述",
    "is_ai_clean": true
}}

示例1：
输入："把 temp1.txt 的所有中文提取出来"
输出：{{"filepath": "temp1.txt", "instruction": "提取所有中文", "is_ai_clean": true}}

示例2：
输入："清洗 1234.txt 删除空行"
输出：{{"filepath": "1234.txt", "instruction": "删除空行", "is_ai_clean": false}}

只输出 JSON，不要有其他内容。"""
        
        result = ai_client.chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="你是指令解析助手，只输出 JSON。",
            temperature=0.1,
        )
        
        # 解析 JSON
        result = result.strip()
        if result.startswith("```json"):
            result = result[7:]
        if result.startswith("```"):
            result = result[3:]
        if result.endswith("```"):
            result = result[:-3]
        result = result.strip()
        
        data = json.loads(result)
        
        return {
            "action": "ai_clean",
            "filepath": data.get("filepath", ""),
            "instruction": data.get("instruction", text),
        }
    except Exception as e:
        print(f"AI解析指令失败: {e}")
        return None

def parse_clean_command(text: str) -> Optional[Dict]:
    """解析文件清洗指令，支持 AI 智能清洗"""
    import re
    
    file_match = re.search(r'([\w\u4e00-\u9fa5]+\.(txt|md|csv|json|xml))', text)
    if not file_match:
        return None
    
    ai_keywords = ["提取", "保留", "删除", "总结", "概括", "翻译", "改写", "润色", "格式化", "处理"]
    is_ai = any(kw in text for kw in ai_keywords)
    
    filepath = file_match.group(1)
    
    if is_ai:
        return {
            "action": "need_ai_parse",
            "filepath": filepath,
            "instruction": text.strip()
        }
    
    text_lower = text.lower()
    rules = {
        "strip_lines": True,
        "save_as_new": False
    }
    
    if "空行" in text or "empty" in text_lower:
        rules["remove_empty_lines"] = True
    if "重复" in text or "duplicate" in text_lower:
        rules["remove_duplicate_lines"] = True
    if "特殊字符" in text or "special" in text_lower:
        rules["remove_special_chars"] = True
    if "另存为" in text or "新文件" in text:
        rules["save_as_new"] = True
    
    if not rules.get("remove_empty_lines") and not rules.get("remove_duplicate_lines") and not rules.get("remove_special_chars"):
        rules["remove_empty_lines"] = True
        rules["strip_lines"] = True
    
    return {
        "action": "clean",
        "filepath": filepath,
        "rules": rules
    }

@app.get("/api/files/list")
async def list_files(directory: str = Query("", description="相对路径，空表示根目录")):
    """列出可清洗的文件"""
    files = file_cleaner.list_available_files()
    if directory:
        files = [f for f in files if f.startswith(directory)]
    return {"success": True, "files": files[:50], "total": len(files)}

# ============================================================
# 新增：获取/更新文件操作目录的 API
# ============================================================

class UploadDirUpdate(BaseModel):
    upload_dir: str

@app.get("/api/settings/upload-dir")
async def get_upload_dir_info():
    """获取当前文件操作目录信息"""
    return config.get_upload_dir_info()

@app.post("/api/settings/upload-dir")
async def update_upload_dir(data: UploadDirUpdate):
    """更新文件操作目录"""
    return config.update_upload_dir(data.upload_dir)

# ============================================================
# 新增：获取所有设置（供前端设置页面使用）
# ============================================================

@app.post("/api/settings/reset")
async def reset_settings():
    """重置配置为默认模板（「重新加载」按钮调用）"""
    result = config.reset_config()
    return {
        "success": True,
        "message": "已重置为默认配置",
        "config": result
    }

@app.get("/api/settings")
async def get_all_settings():
    """获取所有系统设置（供前端设置页面）"""
    return config.get_config_for_web()

@app.post("/api/settings")
async def update_settings(payload: dict):
    """更新系统设置（供前端设置页面）"""
    result = config.update_config_from_web(payload)
    
    if result["success"]:
        # 如果更新了 upload_dir，同步更新 file_manager
        if "file" in payload and "upload_dir" in payload["file"]:
            global FILE_REPO, file_manager
            FILE_REPO = Path(payload["file"]["upload_dir"])
            file_manager = FileOperationManager(upload_dir=str(FILE_REPO))
            print(f"[Config] 文件目录已更新: {FILE_REPO}")
        
        if "api" in payload:
            print(f"[Config] API 配置已更新")
    
    return result


# ── 启动入口 ────────────────────────────────────────────────────────────────

def start_web(host: str = "127.0.0.1", port: int = 8077):
    import uvicorn
    main_db.init_db()
    
    # 启动定时任务调度器
    from tools.scraper_handler import start_scheduler
    start_scheduler()
    
    print(f"\nAegis Web UI 启动中...")
    print(f"  地址: http://localhost:{port}")
    print(f"  文件操作目录: {FILE_REPO}")
    print(f"  定时任务调度器已启动，每分钟检查一次")
    print(f"  按 Ctrl+C 停止\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")