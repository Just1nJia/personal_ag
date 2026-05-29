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
from pydantic import BaseModel
from fastapi.responses import FileResponse
from tools.scraper_logger import scraper_logger

# 把项目根目录加入路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from memory import db as main_db

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── 初始化 ─────────────────────────────────────────────────────────────────

app = FastAPI(title="Aegis", docs_url=None, redoc_url=None)

# 统一文件仓库目录
FILE_REPO = Path("C:/Users/hp/Desktop/upload")
FILE_REPO.mkdir(parents=True, exist_ok=True)

print(f"[文件仓库] 文件操作目录: {FILE_REPO}")

file_manager = FileOperationManager(upload_dir=str(FILE_REPO))
command_parser = CommandParser()

class ScrapeRequest(BaseModel):
    url: str
    format: str = "markdown"
    email: Optional[str] = None
    need_process: bool = False
    process_requirement: Optional[str] = None

class ScrapeScheduleRequest(BaseModel):
    urls: str
    format: str = "markdown"
    email: Optional[str] = None
    schedule_type: str = "daily"
    schedule_detail: str = "0"
    schedule_time: str = "08:00"
    need_process: bool = False
    process_requirement: Optional[str] = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8077", "http://127.0.0.1:8077"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Token 认证中间件 ─────────────────────────────────────────────────────────
_WEB_TOKEN: str = os.environ.get("JARVIS_WEB_TOKEN", "")
_NO_AUTH_PREFIXES = ("/static/", "/health")

@app.post("/api/scrape")
async def api_scrape(request: ScrapeRequest):
    """执行爬取任务"""
    result = await execute_scrape_task(
        urls_input=request.url,
        output_format=request.format,
        send_to_email=request.email,
        need_process=request.need_process,
        process_requirement=request.process_requirement
    )
    return result

@app.post("/api/scrape/schedule")
async def api_scrape_schedule(request: ScrapeScheduleRequest):
    """添加定时爬取任务"""
    result = add_scheduled_task(
        urls=request.urls,
        schedule_type=request.schedule_type,
        schedule_detail=request.schedule_detail,
        schedule_time=request.schedule_time,
        email=request.email,
        format_type=request.format,
        need_process=request.need_process,
        process_requirement=request.process_requirement
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
    """下载爬取文件"""
    file_path = Path("C:/Users/hp/Desktop/upload/scrape") / filename
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

@app.middleware("http")
async def token_auth_middleware(request: Request, call_next):
    if _WEB_TOKEN:
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
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)

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

# ── 路由：页面 ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return html_path.read_text(encoding="utf-8")
    return "<h1>Aegis Web UI</h1><p>static/index.html 未找到</p>"

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
    importance: int = Query(3, ge=1, le=5),
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
    if not (file_create.filename.endswith('.txt') or file_create.filename.endswith('.docx')):
        raise HTTPException(status_code=400, detail="文件类型必须是.txt或.docx")
    result = await file_manager.create_file(file_create.filename, file_create.content)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
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

# ── 文件清洗工具 ──────────────────────────────────────────────────────────

class FileCleaner:
    def __init__(self):
        self.base_dir = FILE_REPO
    
    def list_available_files(self) -> List[str]:
        """列出所有可清洗的文件"""
        files = []
        for ext in ['*.txt', '*.md', '*.csv', '*.json', '*.xml']:
            files.extend(self.base_dir.rglob(ext))
        files = [f for f in files if f.is_file()]
        return [str(f.relative_to(self.base_dir)) for f in files]
    
    def clean_file(self, filepath: str, rules: Dict) -> Dict:
        """清洗文件"""
        full_path = self.base_dir / filepath
        
        if not full_path.exists():
            return {"success": False, "message": f"文件不存在: {filepath}"}
        
        try:
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            original_length = len(content)
            lines = content.splitlines()
            
            # 1. 去除每行首尾空白
            if rules.get("strip_lines", False):
                lines = [line.strip() for line in lines]
            
            # 2. 删除空行
            if rules.get("remove_empty_lines", False):
                lines = [line for line in lines if line]
            
            # 3. 删除重复行
            if rules.get("remove_duplicate_lines", False):
                seen = set()
                unique_lines = []
                for line in lines:
                    if line not in seen:
                        seen.add(line)
                        unique_lines.append(line)
                lines = unique_lines
            
            # 4. 删除特殊字符
            if rules.get("remove_special_chars", False):
                cleaned_lines = []
                for line in lines:
                    cleaned = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s\.\,\!\?\;:\"\'\(\)\【\】\《\》\、\。\，\！\？\；\：\“\”\n]', '', line)
                    cleaned_lines.append(cleaned)
                lines = cleaned_lines
            
            # 5. 自定义替换
            custom_replace = rules.get("custom_replace", [])
            for cr in custom_replace:
                from_text = cr.get("from", "")
                to_text = cr.get("to", "")
                if from_text:
                    lines = [line.replace(from_text, to_text) for line in lines]
            
            new_content = '\n'.join(lines)
            
            output_path = full_path
            if rules.get("save_as_new", False):
                stem = full_path.stem
                suffix = full_path.suffix
                output_path = full_path.parent / f"{stem}_cleaned{suffix}"
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            return {
                "success": True,
                "message": f"文件清洗完成",
                "filepath": str(output_path.relative_to(self.base_dir)),
                "original_length": original_length,
                "new_length": len(new_content),
                "original_lines": len(content.splitlines()),
                "new_lines": len(lines)
            }
        except Exception as e:
            return {"success": False, "message": f"清洗失败: {str(e)}"}

    async def ai_clean_file(self, filepath: str, instruction: str) -> Dict:
        """使用 AI 智能清洗文件内容，支持重命名"""
        full_path = self.base_dir / filepath
        
        if not full_path.exists():
            return {"success": False, "message": f"文件不存在: {filepath}"}
        
        try:
            # 读取文件内容
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            if not content.strip():
                return {"success": False, "message": "文件内容为空"}
            
            # 限制内容长度
            max_chars = 8000
            if len(content) > max_chars:
                content = content[:max_chars] + "\n\n...(内容过长，已截取前8000字符)"
            
            # 调用 AI 处理内容
            from ai import client as ai_client
            
            # 1. 先让 AI 解析指令，提取目标文件名
            parse_prompt = f"""从以下指令中提取：
    1. 要处理的内容要求
    2. 目标文件名（如果用户指定了新文件名，如“命名为temp2.txt”则提取；否则返回None）

    用户指令：{instruction}

    请输出JSON格式：
    {{
        "content_instruction": "要如何处理文件内容",
        "target_filename": "新文件名.txt（如果用户指定了则填，否则填null）"
    }}"""

            parse_result = ai_client.chat(
                messages=[{"role": "user", "content": parse_prompt}],
                system_prompt="你是指令解析助手，只输出纯JSON。",
                temperature=0.1,
            )
            
            # 解析JSON
            parse_result = parse_result.strip()
            if parse_result.startswith("```json"):
                parse_result = parse_result[7:]
            if parse_result.startswith("```"):
                parse_result = parse_result[3:]
            if parse_result.endswith("```"):
                parse_result = parse_result[:-3]
            parse_result = parse_result.strip()
            
            parsed = json.loads(parse_result)
            content_instruction = parsed.get("content_instruction", instruction)
            target_filename = parsed.get("target_filename")
            
            # 2. 处理内容
            content_prompt = f"""请根据以下指令处理文本内容：

    指令：{content_instruction}

    原始文本：
    {content}

    要求：
    1. 只输出处理后的结果，不要添加任何解释
    2. 严格按照指令要求处理
    3. 如果指令要求删除非中文内容，只保留中文"""

            result_content = ai_client.chat(
                messages=[{"role": "user", "content": content_prompt}],
                system_prompt="你是文档处理助手，严格按照用户指令处理文本，只输出处理结果，不添加任何额外说明。",
                temperature=0.3,
            )
            
            # 3. 确定输出文件路径
            if target_filename:
                output_filename = target_filename
            else:
                stem = full_path.stem
                suffix = full_path.suffix
                output_filename = f"{stem}_ai_cleaned{suffix}"
            
            output_path = full_path.parent / output_filename
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(result_content)
            
            return {
                "success": True,
                "message": f"AI智能清洗完成",
                "filepath": str(output_path.relative_to(self.base_dir)),
                "original_length": len(content),
                "new_length": len(result_content),
                "instruction": instruction,
                "target_filename": target_filename
            }
            
        except Exception as e:
            return {"success": False, "message": f"AI清洗失败: {str(e)}"}

file_cleaner = FileCleaner()

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
        # 去掉可能的 markdown 代码块标记
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
    
    # 先用正则快速提取文件名（只匹配 .txt/.md 等结尾的）
    file_match = re.search(r'([\w\u4e00-\u9fa5]+\.(txt|md|csv|json|xml))', text)
    if not file_match:
        return None
    
    # 检查是否需要 AI 处理（包含这些关键词）
    ai_keywords = ["提取", "保留", "删除", "总结", "概括", "翻译", "改写", "润色", "格式化", "处理"]
    is_ai = any(kw in text for kw in ai_keywords)
    
    filepath = file_match.group(1)
    
    if is_ai:
        # 对于复杂指令，返回标记，让上层用 AI 解析
        return {
            "action": "need_ai_parse",
            "filepath": filepath,
            "instruction": text.strip()
        }
    
    # 基础清洗
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

            last_user = next(
                (m.content for m in reversed(req.messages) if m.role == "user"), ""
            )

            print(f"[DEBUG] 用户输入: {last_user}")

            # ──────────────────────────────────────────────────────────────
            # 1. 优先判断 AI 智能清洗操作（用大模型解析指令）
            # ──────────────────────────────────────────────────────────────
            # 检查是否包含清洗关键词和文件名
            has_clean_keyword = any(kw in last_user for kw in ["提取", "保留", "删除", "总结", "概括", "翻译", "改写", "润色", "格式化", "清洗", "处理"])
            has_file = any(ext in last_user for ext in [".txt", ".md", ".csv", ".json", ".xml"])
            
            if has_clean_keyword and has_file:
                print(f"[DEBUG] 识别为AI智能清洗指令，正在用大模型解析...")
                try:
                    # 用大模型解析指令
                    parse_prompt = f"""请解析以下用户指令，提取出【文件路径】和【操作要求】。

用户指令：{last_user}

请严格按照以下 JSON 格式输出（只输出JSON，不要有其他内容）：
{{
    "filepath": "文件名（只包含文件名，不要包含动词和中文标点，例如：temp1.txt）",
    "instruction": "用户想要对文件执行的操作描述",
    "is_valid": true
}}

如果无法提取文件名，设置 "is_valid": false。

示例：
输入："把 temp1.txt 的所有中文提取出来"
输出：{{"filepath": "temp1.txt", "instruction": "提取所有中文", "is_valid": true}}"""

                    ai_result = ai_client.chat(
                        messages=[{"role": "user", "content": parse_prompt}],
                        system_prompt="你是指令解析助手，只输出纯JSON，不要添加任何额外内容。",
                        temperature=0.1,
                    )
                    
                    # 清理 AI 返回内容
                    ai_result = ai_result.strip()
                    if ai_result.startswith("```json"):
                        ai_result = ai_result[7:]
                    if ai_result.startswith("```"):
                        ai_result = ai_result[3:]
                    if ai_result.endswith("```"):
                        ai_result = ai_result[:-3]
                    ai_result = ai_result.strip()
                    
                    parsed = json.loads(ai_result)
                    
                    if parsed.get("is_valid") and parsed.get("filepath"):
                        print(f"[DEBUG] AI解析结果: filepath={parsed['filepath']}, instruction={parsed['instruction']}")
                        
                        result = await file_cleaner.ai_clean_file(
                            filepath=parsed["filepath"],
                            instruction=parsed["instruction"]
                        )

                        if result["success"]:
                            output = f"""✅ AI智能清洗完成！

                        **原始文件**: {parsed['filepath']}
                        **处理后文件**: {result['filepath']}
                        **原始长度**: {result['original_length']} 字符
                        **处理后长度**: {result['new_length']} 字符
                        **执行指令**: {parsed['instruction']}"""
                            if result.get("target_filename"):
                                output += f"\n**文件已重命名为**: {result['target_filename']}"
                        else:
                            output = f"❌ AI清洗失败: {result['message']}"
                        
                        for i in range(0, len(output), 80):
                            data = json.dumps({"text": output[i:i+80]}, ensure_ascii=False)
                            yield f"data: {data}\n\n"
                        yield "data: [DONE]\n\n"
                        return
                    else:
                        output = f"❌ 无法解析指令中的文件名，请确保包含文件名（如 temp1.txt）"
                        for i in range(0, len(output), 80):
                            data = json.dumps({"text": output[i:i+80]}, ensure_ascii=False)
                            yield f"data: {data}\n\n"
                        yield "data: [DONE]\n\n"
                        return
                        
                except json.JSONDecodeError as e:
                    print(f"[DEBUG] JSON解析失败: {e}, AI返回: {ai_result}")
                    output = f"❌ 指令解析失败，请重新输入（如：提取 temp1.txt 的中文）"
                    for i in range(0, len(output), 80):
                        data = json.dumps({"text": output[i:i+80]}, ensure_ascii=False)
                        yield f"data: {data}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                except Exception as e:
                    print(f"[DEBUG] AI清洗异常: {e}")
                    output = f"❌ AI清洗失败: {str(e)}"
                    for i in range(0, len(output), 80):
                        data = json.dumps({"text": output[i:i+80]}, ensure_ascii=False)
                        yield f"data: {data}\n\n"
                    yield "data: [DONE]\n\n"
                    return

            # ──────────────────────────────────────────────────────────────
            # 2. 基础清洗操作（不需要 AI 理解内容）
            # ──────────────────────────────────────────────────────────────
            clean_cmd = parse_clean_command(last_user)
            if clean_cmd and clean_cmd.get("action") == "clean":
                print(f"[DEBUG] 识别为基础清洗操作: {clean_cmd}")
                try:
                    result = file_cleaner.clean_file(
                        filepath=clean_cmd["filepath"],
                        rules=clean_cmd["rules"]
                    )
                    if result["success"]:
                        output = f"""✅ 文件清洗完成！

**文件**: {result['filepath']}
**清洗前**: {result['original_length']} 字符, {result['original_lines']} 行
**清洗后**: {result['new_length']} 字符, {result['new_lines']} 行

已应用规则：
- 删除空行
- 去除首尾空白"""
                        if clean_cmd["rules"].get("remove_duplicate_lines"):
                            output += "\n- 删除重复行"
                        if clean_cmd["rules"].get("remove_special_chars"):
                            output += "\n- 删除特殊字符"
                    else:
                        output = f"❌ 清洗失败: {result['message']}"
                    
                    for i in range(0, len(output), 80):
                        data = json.dumps({"text": output[i:i+80]}, ensure_ascii=False)
                        yield f"data: {data}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                except Exception as e:
                    output = f"❌ 清洗失败: {str(e)}"
                    for i in range(0, len(output), 80):
                        data = json.dumps({"text": output[i:i+80]}, ensure_ascii=False)
                        yield f"data: {data}\n\n"
                    yield "data: [DONE]\n\n"
                    return

            # ──────────────────────────────────────────────────────────────
            # 3. 脚本操作
            # ──────────────────────────────────────────────────────────────
            low = last_user.lower()
            is_script = any(kw in low for kw in ["运行", "执行", "run", "列出脚本", "有哪些脚本", "脚本列表"])
            
            if is_script:
                print(f"[DEBUG] 识别为脚本操作")
                try:
                    from email_module.command_handler import _handle_run_script, _handle_list_scripts
                    
                    if "列出脚本" in low or "有哪些脚本" in low or "脚本列表" in low:
                        output = _handle_list_scripts()
                    else:
                        output = _handle_run_script(last_user)
                    
                    for i in range(0, len(output), 80):
                        data = json.dumps({"text": output[i:i+80]}, ensure_ascii=False)
                        yield f"data: {data}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    err_msg = f"[脚本执行失败: {str(e)}]\n\n"
                    yield f"data: {json.dumps({'text': err_msg}, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                    return

            # ──────────────────────────────────────────────────────────────
            # 4. 邮件/文件操作
            # ──────────────────────────────────────────────────────────────
            is_email = any(kw in low for kw in ["发邮件", "发送邮件", "回复邮件", "发给", "发到", "邮件给"])
            is_file = any(kw in low for kw in ["创建", "新建", "读取", "查看", "修改", "更新", 
                                                "删除", "列出所有文件", "有哪些文件"])
            
            print(f"[DEBUG] 是否邮件操作: {is_email}")
            print(f"[DEBUG] 是否文件操作: {is_file}")
            
            if is_email or is_file:
                try:
                    if is_email:
                        from email_module.command_handler import _execute_command
                        output = _execute_command(last_user, context={"source": "web"})
                    else:
                        result = await _execute_file_command(last_user)
                        if result.get("success"):
                            output = format_file_command_result(result)
                        else:
                            output = f"❌ {result.get('message', result.get('detail', '执行失败'))}"
                    
                    for i in range(0, len(output), 80):
                        data = json.dumps({"text": output[i:i+80]}, ensure_ascii=False)
                        yield f"data: {data}\n\n"
                    yield "data: [DONE]\n\n"
                    return
                    
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    err_msg = f"[执行失败: {str(e)}，切换为普通对话模式]\n\n"
                    yield f"data: {json.dumps({'text': err_msg}, ensure_ascii=False)}\n\n"

            # ──────────────────────────────────────────────────────────────
            # 5. 普通对话：流式 AI 回复
            # ──────────────────────────────────────────────────────────────
            system_prompt = _build_chat_system_prompt() if req.inject_memory else "你是Aegis，一个智能AI助理。"
            messages = [{"role": m.role, "content": m.content} for m in req.messages]
            msgs = [{"role": "system", "content": system_prompt}] + messages

            stream = ai_client.get_client().chat.completions.create(
                model=config.VOLC_MODEL,
                messages=msgs,
                stream=True,
                temperature=0.7,
            )

            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    data = json.dumps({"text": delta.content}, ensure_ascii=False)
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

@app.post("/api/chat")
async def chat_simple(req: ChatRequest):
    """非流式对话"""
    import ai.client as ai_client
    system_prompt = _build_chat_system_prompt() if req.inject_memory else "你是Aegis。"
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    result = ai_client.chat(messages, system_prompt=system_prompt)
    return {"content": result}

# ── 路由：任务触发 ──────────────────────────────────────────────────────────

@app.post("/api/tasks/{task_name}/run")
async def run_task(task_name: str):
    allowed = {
        "briefing", "focus_update", "check_emails",
        "build_email_memory", "build_wechat_memory",
    }
    if task_name not in allowed:
        raise HTTPException(400, f"未知任务: {task_name}，支持: {', '.join(allowed)}")

    import threading

    def _run():
        main_db.init_db()
        if task_name == "briefing":
            from scheduler.jobs import send_daily_briefing
            send_daily_briefing()
        elif task_name == "focus_update":
            from scheduler.focus_updater import run_focus_update
            run_focus_update(send_email=False)
        elif task_name == "check_emails":
            from scheduler.jobs import check_emails
            check_emails()
        elif task_name == "build_email_memory":
            from scanner.email_memory_builder import build_email_memory
            build_email_memory()
        elif task_name == "build_wechat_memory":
            from scanner.wechat_memory_builder import build_wechat_memory
            build_wechat_memory(top_contacts=100, top_groups=100)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"ok": True, "task": task_name, "status": "started"}

# ── 设置 API ────────────────────────────────────────────────────────────────

def _mask_sensitive(s: dict) -> dict:
    import copy, json
    d = json.loads(json.dumps(s, ensure_ascii=False))
    _SENSITIVE = [
        ("api", "volc_api_key"),
        ("email_163", "auth_code"),
        ("email_gmail", "app_password"),
    ]
    for section, field in _SENSITIVE:
        if d.get(section, {}).get(field):
            d[section][field] = ""
    return d

@app.get("/api/settings")
async def get_settings():
    from settings_manager import load
    s = load()
    return _mask_sensitive(s)

@app.post("/api/settings")
async def save_settings(request: Request):
    from settings_manager import save
    body = await request.json()
    save(body)
    from settings_manager import load
    merged = load()
    if "scan" in merged and "roots" in merged["scan"]:
        config.SCAN_ROOTS = merged["scan"]["roots"]
    return {"ok": True}

@app.post("/api/settings/scan-roots")
async def add_scan_root(request: Request):
    body = await request.json()
    path = body.get("path", "").strip()
    if not path:
        raise HTTPException(400, "path 不能为空")
    from settings_manager import load, save
    s = load()
    roots = s.setdefault("scan", {}).setdefault("roots", [])
    if path not in roots:
        roots.append(path)
        save(s)
        config.SCAN_ROOTS = roots
    return s

@app.delete("/api/settings/scan-roots")
async def remove_scan_root(request: Request):
    body = await request.json()
    path = body.get("path", "").strip()
    from settings_manager import load, save
    s = load()
    roots = s.setdefault("scan", {}).setdefault("roots", [])
    if path in roots:
        roots.remove(path)
        save(s)
        config.SCAN_ROOTS = roots
    return s

@app.get("/api/files/logs")
async def get_file_logs(limit: int = Query(50, le=200), operation: str = Query(None)):
    """获取文件操作日志"""
    if operation:
        logs = file_logger.get_logs_by_operation(operation, limit)
    else:
        logs = file_logger.get_recent_logs(limit)
    return {"logs": logs, "total": len(logs)}

# ── 启动入口 ────────────────────────────────────────────────────────────────

def start_web(host: str = "127.0.0.1", port: int = 8077):
    import uvicorn
    main_db.init_db()
    
    # 启动定时任务调度器
    from tools.scraper_handler import start_scheduler
    start_scheduler()
    
    print(f"\nAegis Web UI 启动中...")
    print(f"  地址: http://localhost:{port}")
    print(f"  定时任务调度器已启动，每分钟检查一次")
    print(f"  按 Ctrl+C 停止\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")