"""
Aegis邮件指令系统 — 通过邮件下达命令

检测规则（二选一即可）:
  1. 主题以 "Aegis:" 或 "Aegis:" 开头（新邮件指令）
  2. 收到来自用户自己的回复邮件（In-Reply-To 包含Aegis发送的邮件 ID）

支持的指令（AI 自由解析，以下是核心动作）:
  - 发送邮件 / 回复 [联系人] [内容]
  - 查询 [关键词]  — 语义搜索知识库
  - 总结 [话题]   — 汇总近期相关邮件
  - 简报          — 立即生成今日简报
  - 状态          — 系统运行状态
  - 记住 [信息]   — 写入个人档案
  - 联系人 [查询] — 查询联系人信息
  - 运行脚本      — 执行 Python/Shell 脚本
"""
from __future__ import annotations

import email
import hashlib
import imaplib
import re
import time
from email.utils import parseaddr
from pathlib import Path
from typing import Optional

import config
from email_module.reader import _connect, _decode_header_value, _extract_body, _safe_print
from email_module.sender import send_email, find_file_in_upload_dir
from memory import db
from ai import client as ai

# 指令触发前缀
COMMAND_PREFIXES = ("aegis:", "jv:", "jarvis:")


def _is_command_email(subject: str, from_addr: str, in_reply_to: str = "") -> bool:
    """判断是否是用户给Aegis的指令邮件"""
    subject_lower = subject.lower().strip()
    if any(subject_lower.startswith(p) for p in COMMAND_PREFIXES):
        return True
    if from_addr in (config.NETEASE_EMAIL, config.GMAIL_EMAIL or ""):
        if in_reply_to:
            return True
    return False


def fetch_commands() -> list[dict]:
    """拉取用户发给Aegis的指令邮件"""
    mail = _connect()
    if not mail:
        return []

    commands = []
    try:
        mail.select("INBOX")
        status, data = mail.search(None, "UNSEEN")
        if status != "OK":
            return []

        all_unread = data[0].split()
        for eid in reversed(all_unread[-100:]):
            try:
                status, hdr_data = mail.fetch(eid, "(RFC822.HEADER)")
                if status != "OK":
                    continue
                msg = email.message_from_bytes(hdr_data[0][1])
                subject    = _decode_header_value(msg.get("Subject", ""))
                from_raw   = _decode_header_value(msg.get("From", ""))
                _, from_addr = parseaddr(from_raw)
                in_reply_to = msg.get("In-Reply-To", "")
                date_str   = msg.get("Date", "")
                msg_id     = msg.get("Message-ID", "")

                if not _is_command_email(subject, from_addr, in_reply_to):
                    continue

                status2, full_data = mail.fetch(eid, "(RFC822)")
                if status2 != "OK":
                    continue
                full_msg = email.message_from_bytes(full_data[0][1])
                body = _extract_body(full_msg)

                uid = hashlib.md5(
                    (msg_id or f"{from_addr}{subject}{date_str}").encode()
                ).hexdigest()

                if db.command_exists(uid):
                    continue

                commands.append({
                    "id": uid,
                    "imap_id": eid,
                    "from_addr": from_addr,
                    "subject": subject,
                    "body": body.strip(),
                    "date": date_str,
                    "in_reply_to": in_reply_to,
                })

            except Exception as e:
                _safe_print(f"[Cmd] 解析失败: {e}")

        mail.logout()

    except Exception as e:
        _safe_print(f"[Cmd] 拉取失败: {e}")

    return commands


def _extract_command_text(subject: str, body: str) -> str:
    """从邮件中提取指令文本"""
    subject_lower = subject.lower().strip()
    cmd_from_subject = subject
    for p in COMMAND_PREFIXES:
        if subject_lower.startswith(p):
            cmd_from_subject = subject[len(p):].strip()
            break

    clean_body = []
    for line in body.splitlines():
        if line.strip().startswith(">"):
            break
        clean_body.append(line)
    body_text = "\n".join(clean_body).strip()

    return body_text if body_text else cmd_from_subject


def _lookup_contact_email(name: str) -> str:
    """按姓名/备注模糊搜索联系人邮件地址"""
    try:
        with db.get_conn() as conn:
            rows = conn.execute("""
                SELECT email, display_name FROM contacts
                WHERE display_name LIKE ? AND email IS NOT NULL AND email != ''
                ORDER BY importance DESC LIMIT 3
            """, (f"%{name}%",)).fetchall()
            if rows:
                return rows[0]["email"]
            rows2 = conn.execute("""
                SELECT from_addr FROM emails
                WHERE (from_name LIKE ? OR from_addr LIKE ?)
                  AND from_addr NOT LIKE '%noreply%'
                ORDER BY importance DESC LIMIT 1
            """, (f"%{name}%", f"%{name}%")).fetchone()
            return rows2["from_addr"] if rows2 else ""
    except Exception:
        return ""


def _lookup_contact_wxid(name: str) -> str:
    """按姓名备注搜索微信 wxid"""
    try:
        from memory import db as _db
        with _db.get_conn() as conn:
            row = conn.execute("""
                SELECT wxid FROM wechat_contacts
                WHERE remark LIKE ? OR nickname LIKE ?
                LIMIT 1
            """, (f"%{name}%", f"%{name}%")).fetchone()
            return row[0] if row else ""
    except Exception:
        return ""


def _search_knowledge(query: str) -> str:
    """两阶段混合搜索（FTS5 + 向量 RRF 融合）"""
    try:
        from memory.context_inject import search_knowledge
        return search_knowledge(query, top_k=8)
    except Exception as e:
        return f"搜索失败: {e}"


def _summarize_topic(topic: str) -> str:
    """汇总近期某话题的邮件"""
    with db.get_conn() as conn:
        rows = conn.execute("""
            SELECT from_addr, subject, summary, importance, date
            FROM emails
            WHERE (subject LIKE ? OR summary LIKE ?)
              AND importance >= 2
            ORDER BY importance DESC, date DESC
            LIMIT 10
        """, (f"%{topic}%", f"%{topic}%")).fetchall()

    if not rows:
        return f"未找到与「{topic}」相关的邮件。"

    lines = [f"关于「{topic}」的近期邮件（共{len(rows)}封）：\n"]
    for r in rows:
        lines.append(f"  ★{r[3]} [{r[0]}] {r[1]}\n  摘要: {r[2] or '—'}")
    summary_text = "\n".join(lines)

    condensed = ai.chat(
        messages=[{"role": "user", "content": f"请用100字内汇总以下邮件列表的核心信息：\n\n{summary_text}"}],
        system_prompt="你是Aegis，简洁专业。",
        temperature=0.3,
    )
    return summary_text + f"\n\nAI汇总：{condensed}"


def _query_contacts(query: str) -> str:
    """查询联系人信息"""
    with db.get_conn() as conn:
        rows = conn.execute("""
            SELECT email, name, institution, institution_type, role, importance, notes
            FROM contacts
            WHERE email LIKE ? OR name LIKE ? OR institution LIKE ?
            ORDER BY importance DESC
            LIMIT 5
        """, (f"%{query}%", f"%{query}%", f"%{query}%")).fetchall()

    if not rows:
        return f"未找到「{query}」相关联系人。"

    lines = [f"联系人查询「{query}」：\n"]
    for r in rows:
        lines.append(
            f"  ★{r[5]} {r[1]} <{r[0]}>\n"
            f"  机构: {r[2] or '—'} [{r[3]}/{r[4]}]\n"
            f"  备注: {r[6] or '—'}"
        )
    return "\n".join(lines)


def _parse_send_email(instruction: str) -> dict | None:
    """
    解析发送邮件指令。
    支持格式：
    - 发邮件给 xxx@xx.com，主题是xxx，内容是xxx
    - 发送邮件给 xxx@xx.com，主题xxx，内容xxx，附件xxx
    - 给 xxx@xx.com 发邮件，主题xxx，内容xxx
    """
    import re
    
    instruction = instruction.strip()
    
    # 提取收件人邮箱 - 多种模式
    to_patterns = [
        r'发邮件给\s*([a-zA-Z0-9@._-]+)',
        r'发送邮件给\s*([a-zA-Z0-9@._-]+)',
        r'给\s*([a-zA-Z0-9@._-]+)\s*发邮件',
        r'邮件给\s*([a-zA-Z0-9@._-]+)',
        r'发给\s*([a-zA-Z0-9@._-]+)',
    ]
    
    to_email = None
    for pattern in to_patterns:
        match = re.search(pattern, instruction)
        if match:
            to_email = match.group(1)
            break
    
    if not to_email:
        # 尝试直接匹配邮箱格式
        email_match = re.search(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', instruction)
        if email_match:
            to_email = email_match.group(1)
    
    if not to_email:
        return None
    
    # 提取主题
    subject = ""
    subject_match = re.search(r'主题[是为:：]\s*([^，,。！？\n]+)', instruction)
    if subject_match:
        subject = subject_match.group(1).strip()
    else:
        subject_match = re.search(r'主题\s+([^，,。！？\n]+)', instruction)
        if subject_match:
            subject = subject_match.group(1).strip()
    
    if not subject:
        subject = "来自 Aegis 的邮件"
    
    # 提取内容
    content = ""
    content_match = re.search(r'内容[是为:：]\s*([^，,。！？\n]+)', instruction)
    if content_match:
        content = content_match.group(1).strip()
    else:
        content_match = re.search(r'内容\s+([^，,。！？\n]+)', instruction)
        if content_match:
            content = content_match.group(1).strip()
    
    if not content:
        # 从命令中提取剩余部分作为内容
        remaining = instruction
        if to_email:
            remaining = remaining.replace(to_email, '')
        if subject and subject != "来自 Aegis 的邮件":
            remaining = remaining.replace(f"主题{subject}", '').replace(f"主题是{subject}", '')
        # 移除关键词
        for kw in ["发邮件给", "发送邮件给", "给", "发邮件", "邮件给", "发给", "主题", "内容", "附件", "，", "、", "。"]:
            remaining = remaining.replace(kw, '')
        content = remaining.strip()
    
    if not content:
        content = subject
    
    # 提取附件
    attachments = []
    attach_match = re.search(r'附件[是为:：]\s*([^，,。！？\n]+)', instruction)
    if attach_match:
        attach_str = attach_match.group(1).strip()
        for sep in ['，', ',', '、', ' ']:
            if sep in attach_str:
                attachments = [a.strip() for a in attach_str.split(sep)]
                break
        if not attachments:
            attachments = [attach_str]
    
    return {
        "to": to_email,
        "subject": subject,
        "content": content,
        "attachments": attachments
    }


def _parse_send_attachment(instruction: str) -> dict | None:
    """解析附件发送指令"""
    patterns = [
        r"^发送附件?\s+(.+?)\s+给\s+(\S{1,30})",
        r"^发送文件\s+(.+?)\s+给\s+(\S{1,30})",
        r"^把\s+(.+?)\s+发送给\s+(\S{1,30})",
        r"^附上\s+(.+?)\s+发给\s+(\S{1,30})",
    ]
    for pattern in patterns:
        m = re.match(pattern, instruction.strip())
        if m:
            return {
                "file_keyword": m.group(1).strip(),
                "contact_hint": m.group(2).strip()
            }
    return None


def _handle_send_attachment(file_keyword: str, contact_hint: str) -> str:
    """搜索文件并发送给指定联系人（邮件）"""
    file_path = find_file_in_upload_dir(file_keyword)
    
    if not file_path:
        doc_dir = config.DATA_DIR / "documents"
        if doc_dir.exists():
            matches = list(doc_dir.glob(f"*{file_keyword}*"))
            if matches:
                file_path = matches[0]
    
    if not file_path or not file_path.exists():
        return (
            f"⚠️ 未找到含「{file_keyword}」的文件。\n"
            f"请确认文件在 C:\\Users\\hp\\Desktop\\upload 目录下。"
        )

    to_addr = _lookup_contact_email(contact_hint)
    if not to_addr:
        return (
            f"⚠️ 未找到 '{contact_hint}' 的邮件地址。\n"
            f"找到文件: {file_path.name}\n"
            f"请指定完整姓名或邮件地址重试。"
        )

    subject = f"📎 Aegis发送文件: {file_path.name}"
    body = f"Aegis 代发附件\n\n文件名: {file_path.name}\n文件大小: {file_path.stat().st_size // 1024} KB"
    
    ok = send_email(to_addr, subject, body, attachments=[str(file_path)])
    
    if ok:
        return (
            f"✅ 文件已发送给 {contact_hint} <{to_addr}>\n"
            f"文件: {file_path.name} ({file_path.stat().st_size // 1024}KB)"
        )
    else:
        return f"❌ 发送失败，文件: {file_path.name}"


def _parse_reply_instruction(instruction: str) -> dict | None:
    """解析快速回复指令"""
    patterns = [
        (r"^(邮件回复|邮件 回复)\s+(\S{1,20})\s+(.{2,})", "email"),
        (r"^(微信回复|微信 回复)\s+(\S{1,20})\s+(.{2,})", "wechat"),
        (r"^回复\s+(\S{1,20})\s+(.{2,})", "auto"),
    ]
    for pattern, channel in patterns:
        m = re.match(pattern, instruction.strip(), re.DOTALL)
        if m:
            if channel == "auto":
                return {
                    "channel": "auto",
                    "contact_hint": m.group(1).strip(),
                    "core_message": m.group(2).strip(),
                }
            else:
                return {
                    "channel": channel,
                    "contact_hint": m.group(2).strip(),
                    "core_message": m.group(3).strip(),
                }
    return None


def _draft_reply(contact_name: str, core_message: str, channel: str,
                 original_subject: str = "") -> str:
    """用 AI 将核心要点扩写成完整回复"""
    channel_hint = "邮件" if channel == "email" else "微信消息" if channel == "wechat" else "消息"
    subject_hint = f"邮件主题: {original_subject}\n" if original_subject else ""
    prompt = (
        f"用户要给 {contact_name} 回复一条{channel_hint}。\n"
        f"{subject_hint}"
        f"核心要点：{core_message}\n\n"
        f"请代用户起草一条完整、自然、专业的{channel_hint}正文。"
        f"直接输出正文内容，不要加说明或引导语。"
        f"{'篇幅控制在3-5句话，适合即时消息。' if channel == 'wechat' else '格式参照正式邮件正文。'}"
    )
    try:
        draft = ai.chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="你是Aegis，简洁专业，代替用户撰写回复。",
            temperature=0.4,
        )
        return draft.strip()
    except Exception:
        return core_message


def _find_focus_source(contact_hint: str) -> dict:
    """从 focus.md 条目中找含 contact_hint 的条目"""
    from memory.layers import get_focus
    content = get_focus()
    hint_lower = contact_hint.lower()
    for line in content.splitlines():
        if hint_lower in line.lower() and line.startswith("- "):
            source = "email" if "📧" in line else "wechat" if "💬" in line else "unknown"
            ref_m = re.search(r"→ (\S+)", line)
            db_ref = ref_m.group(1) if ref_m else ""
            return {"source": source, "db_ref": db_ref, "found": True, "line": line}
    return {"source": "unknown", "db_ref": "", "found": False, "line": ""}


def _handle_reply_instruction(
    channel: str, contact_hint: str, core_message: str, context: dict
) -> str:
    """执行快速回复指令"""
    focus_info = _find_focus_source(contact_hint)
    detected_source = focus_info["source"]

    if channel == "auto":
        channel = detected_source if detected_source in ("email", "wechat") else "email"

    original_subject = ""
    if channel == "email" and focus_info.get("db_ref"):
        try:
            with db.get_conn() as conn:
                row = conn.execute(
                    "SELECT subject FROM emails WHERE id=? LIMIT 1",
                    (focus_info["db_ref"].replace("email:", ""),)
                ).fetchone()
                if row:
                    original_subject = row[0]
        except Exception:
            pass

    draft = _draft_reply(contact_hint, core_message, channel, original_subject)

    if channel == "email":
        to_addr = _lookup_contact_email(contact_hint)
        if not to_addr:
            return (
                f"⚠️ 未找到 '{contact_hint}' 的邮件地址，草稿如下：\n\n{draft}\n\n"
                f"请用 Aegis: 邮件回复 [完整姓名] [内容] 重试。"
            )
        reply_subject = f"Re: {original_subject}" if original_subject else f"回复: {contact_hint}"
        ok = send_email(to_addr, reply_subject, draft)
        result = (
            f"✅ 邮件已发送给 {contact_hint} <{to_addr}>\n主题: {reply_subject}\n\n{draft}"
            if ok else f"❌ 邮件发送失败，草稿：\n\n{draft}"
        )

    elif channel == "wechat":
        try:
            from scheduler.wechat_commander import send_wechat_msg
            ok = send_wechat_msg(contact_hint, draft)
            result = (
                f"✅ 微信消息已发送给 {contact_hint}：\n\n{draft}"
                if ok else f"❌ 微信发送失败，草稿：\n\n{draft}"
            )
        except Exception as e:
            result = f"❌ 微信发送异常: {e}\n\n草稿：{draft}"
    else:
        result = f"⚠️ 无法确定发送渠道，草稿：\n\n{draft}"

    if "✅" in result:
        try:
            from memory.layers import complete_focus_item
            complete_focus_item(contact_hint)
        except Exception:
            pass

    return result


# ========== 脚本执行相关函数 ==========

def _parse_run_script(instruction: str) -> dict | None:
    """
    解析运行脚本指令。
    支持格式：
    - 运行 test.py
    - 执行 test.sh
    - 运行 test.sh arg1 arg2
    """
    import re
    
    instruction = instruction.strip()
    
    # 移除开头的"运行"、"执行"等关键词（支持中文和英文）
    # 注意：这里要匹配"运行"或"执行"后面可能有空格
    text = re.sub(r'^(运行|执行|run)\s*', '', instruction, flags=re.IGNORECASE)
    
    # 移除 "python"、"脚本文件"、"sh" 等修饰词
    text = re.sub(r'^(python|sh|脚本文件|文件)\s*', '', text, flags=re.IGNORECASE)
    
    # 提取脚本名和参数（脚本名不能包含空格）
    parts = text.strip().split()
    if not parts:
        return None
    
    script_name = parts[0]
    # 确保脚本名有扩展名（如果没有，默认加 .py？但最好让用户自己写）
    # 注意：这里不要自动加扩展名，因为可能是 .sh 或 .bat
    
    args = ' '.join(parts[1:]) if len(parts) > 1 else ''
    
    print(f"[DEBUG] 解析脚本: script_name={script_name}, args={args}")
    
    return {
        "script_name": script_name,
        "args": args
    }


def _handle_run_script(instruction: str) -> str:
    """执行脚本（同步版本）"""
    print(f"[DEBUG] _handle_run_script 收到: {instruction}")
    
    parsed = _parse_run_script(instruction)
    print(f"[DEBUG] 解析结果: {parsed}")
    
    if not parsed:
        return "⚠️ 无法解析脚本指令，格式：运行 <脚本名> [参数]\n示例：运行 test.sh"
    
    script_name = parsed["script_name"]
    args = parsed["args"]
    
    try:
        from tools.script_runner import script_runner
        import asyncio
        
        print(f"[DEBUG] 查找脚本: {script_name}")
        
        # 创建新的事件循环运行异步函数
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(script_runner.run_script(script_name, args))
        loop.close()
        
        print(f"[DEBUG] 执行结果: success={result['success']}")
        
    except ImportError as e:
        return f"❌ 脚本执行模块未安装: {e}\n请确保 tools/script_runner.py 存在"
    except Exception as e:
        import traceback
        return f"❌ 脚本执行失败: {e}\n{traceback.format_exc()}"
    
    if result["success"]:
        output = f"✅ {result['message']}\n\n"
        if result.get("stdout"):
            stdout_preview = result['stdout'][:2000]
            output += f"📤 输出：\n```\n{stdout_preview}\n```\n"
            if len(result['stdout']) > 2000:
                output += f"\n... (输出共 {len(result['stdout'])} 字符，已截断)\n"
        if result.get("stderr"):
            output += f"⚠️ 错误输出：\n```\n{result['stderr'][:500]}\n```\n"
        return output
    else:
        output = f"❌ {result['message']}\n"
        output += f"📁 脚本目录: {result.get('scripts_dir', 'C:\\Users\\hp\\Desktop\\upload\\scripts')}\n"
        output += f"🔍 查找的脚本名: {script_name}\n"
        if result.get("stderr"):
            output += f"\n错误详情：\n```\n{result['stderr']}\n```\n"
        if result.get("stdout"):
            output += f"\n输出：\n```\n{result['stdout'][:500]}\n```\n"
        return output


def _handle_list_scripts() -> str:
    """列出所有可用脚本"""
    try:
        from tools.script_runner import script_runner
        scripts = script_runner.list_scripts()
    except ImportError as e:
        return f"❌ 脚本执行模块未安装: {e}\n请确保 tools/script_runner.py 存在"
    
    if not scripts:
        return "📁 脚本目录为空，请将脚本文件放入 `C:\\Users\\hp\\Desktop\\upload\\scripts` 目录"
    
    output = f"📁 可用脚本（共 {len(scripts)} 个）：\n\n"
    for s in scripts:
        output += f"   📄 {s['name']} ({s['type']}, {s['size']} bytes)\n"
    output += f"\n💡 使用方法：运行 <脚本名> [参数]\n"
    output += f"📂 脚本存放位置: C:\\Users\\hp\\Desktop\\upload\\scripts"
    return output


def _execute_command(instruction: str, context: dict) -> str:
    """用 AI 解析并执行指令，返回结果文本。"""
    instr_lower = instruction.strip().lower()

    # 对账指令快速路由
    if instr_lower.startswith("对账"):
        try:
            from memory.importance_learner import handle_reconcile_reply
            return handle_reconcile_reply(instruction.strip())
        except Exception as e:
            return f"对账处理失败: {e}"

    # 列出脚本指令
    if instr_lower in ("列出脚本", "有哪些脚本", "脚本列表", "list scripts"):
        return _handle_list_scripts()

    # 运行脚本指令
    if instr_lower.startswith(("运行", "执行", "run")):
        return _handle_run_script(instruction.strip())
    
    # 发送邮件指令（优先解析 - 最高优先级）
    send_email_info = _parse_send_email(instruction.strip())
    if send_email_info:
        to = send_email_info.get("to")
        subject = send_email_info.get("subject", "来自 Aegis 的邮件")
        content = send_email_info.get("content", "")
        attachments = send_email_info.get("attachments", [])
        
        if not to:
            return "❌ 无法识别收件人地址，请提供邮箱地址"
        
        if not content:
            content = subject
        
        # 处理附件：在 upload 目录查找
        attachment_paths = []
        for att in attachments:
            found = find_file_in_upload_dir(att)
            if found:
                attachment_paths.append(str(found))
                _safe_print(f"[Cmd] 找到附件: {found.name}")
            else:
                _safe_print(f"[Cmd] 未找到附件: {att}")
        
        # 发送邮件
        ok = send_email(
            to=to,
            subject=subject,
            body=content,
            attachments=attachment_paths if attachment_paths else None
        )
        
        attach_msg = f"\n📎 附件: {', '.join([Path(p).name for p in attachment_paths])}" if attachment_paths else ""
        
        if ok:
            return f"✅ 邮件已发送给 {to}\n主题: {subject}\n内容: {content}{attach_msg}"
        else:
            return f"❌ 邮件发送失败，请检查邮箱配置和网络连接"

    # 附件发送指令
    _send_attach = _parse_send_attachment(instruction.strip())
    if _send_attach:
        return _handle_send_attachment(**_send_attach)

    # 焦点回复指令
    _reply_match = _parse_reply_instruction(instruction.strip())
    if _reply_match:
        return _handle_reply_instruction(**_reply_match, context=context)

    from memory import profile
    from memory.memory_manage import get_summary as mm_summary, add_fact

    system_prompt = (
        "你是Aegis，用户的AI助理。用户通过邮件给你下达了一条指令。\n"
        "你需要：\n"
        "1. 理解指令意图\n"
        "2. 决定执行哪个动作（见下方）\n"
        "3. 生成执行结果或回复内容\n\n"
        "可执行的动作类型：\n"
        "  REPLY_EMAIL   — 起草并发送邮件给某联系人\n"
        "  SEARCH        — 搜索知识库或邮件\n"
        "  SUMMARIZE     — 汇总某个话题的近期邮件\n"
        "  BRIEFING      — 生成今日简报\n"
        "  STATUS        — 系统状态报告\n"
        "  REMEMBER      — 记录到个人档案\n"
        "  CONTACT_QUERY — 查询联系人信息\n"
        "  WRITE_WORD    — 生成 Word 文档\n"
        "  SEND_FILE     — 发送文件附件\n"
        "  RUN_SCRIPT    — 运行 Python/Shell 脚本\n"
        "  CHAT          — 普通问答/对话\n\n"
        "以JSON格式输出：\n"
        '{"action": "ACTION_TYPE", "params": {...}, "response": "给用户的回复文本"}\n'
        "只输出JSON。"
    )

    user_content = f"用户指令：{instruction}\n\n当前个人档案摘要：\n{mm_summary()}\n\n请解析指令并生成回复。"

    import json
    try:
        raw = ai.chat(
            messages=[{"role": "user", "content": user_content}],
            system_prompt=system_prompt,
            temperature=0.3,
        )
        raw = raw.strip().strip("```json").strip("```").strip()
        parsed = json.loads(raw)
        action   = parsed.get("action", "CHAT")
        params   = parsed.get("params", {})
        response = parsed.get("response", "")
    except Exception:
        action, params, response = "CHAT", {}, ""

    result_text = response

    if action == "BRIEFING":
        try:
            from scheduler.jobs import send_daily_briefing
            send_daily_briefing()
            result_text = "✅ 今日简报已生成并发送，请查收邮件。"
        except Exception as e:
            result_text = f"简报生成失败: {e}"

    elif action == "STATUS":
        with db.get_conn() as conn:
            emails_c = conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
            imp_c    = conn.execute("SELECT COUNT(*) FROM emails WHERE importance>=4").fetchone()[0]
            files_c  = conn.execute("SELECT COUNT(*) FROM file_index").fetchone()[0]
            vec_c    = conn.execute("SELECT COUNT(*) FROM file_index WHERE status='indexed'").fetchone()[0]
            cont_c   = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
        result_text = (
            f"Aegis系统状态\n\n"
            f"邮件: {emails_c} 封已处理 | 重要(★4+): {imp_c} 封\n"
            f"联系人: {cont_c} 个\n"
            f"文件索引: {files_c} 个 | 已向量化: {vec_c} 个\n"
            f"调度器: 每30分钟检查邮件 | 每天08:00简报 | 每天03:00向量化\n"
        )

    elif action == "REMEMBER":
        fact = params.get("fact") or instruction
        try:
            add_fact(fact)
            result_text = f"✅ 已记录到个人档案：{fact}"
        except Exception as e:
            result_text = f"记录失败: {e}"

    elif action == "SEARCH":
        query = params.get("query", instruction)
        result_text = _search_knowledge(query)

    elif action == "SUMMARIZE":
        topic = params.get("topic", instruction)
        result_text = _summarize_topic(topic)

    elif action == "CONTACT_QUERY":
        query = params.get("query", instruction)
        result_text = _query_contacts(query)

    elif action == "RUN_SCRIPT":
        script_name = params.get("script_name", "")
        script_args = params.get("args", "")
        if not script_name:
            script_name = instruction.strip()
        result_text = _handle_run_script(f"运行 {script_name} {script_args}")

    elif action == "REPLY_EMAIL":
        to_addr  = params.get("to", "")
        to_name  = params.get("to_name", "")
        draft    = params.get("draft", response)
        subject  = params.get("subject", "")
        attachments = params.get("attachments", [])

        if to_name and not to_addr:
            to_addr = _lookup_contact_email(to_name)

        if not subject:
            subject = f"回复: {to_name or to_addr}"

        attachment_paths = []
        for att in attachments:
            found = find_file_in_upload_dir(att)
            if found:
                attachment_paths.append(str(found))
                _safe_print(f"[Cmd] 找到附件: {found.name}")
            else:
                _safe_print(f"[Cmd] 未找到附件: {att}")

        if to_addr and "@" in to_addr:
            ok = send_email(to_addr, subject, draft, attachments=attachment_paths if attachment_paths else None)
            attach_msg = f"\n📎 附件: {', '.join([Path(p).name for p in attachment_paths])}" if attachment_paths else ""
            result_text = (
                f"✅ 已发送邮件给 {to_name or to_addr} <{to_addr}>\n"
                f"主题: {subject}\n\n内容:\n{draft}{attach_msg}"
                if ok else f"❌ 发送失败: {to_addr}"
            )
        else:
            result_text = (
                f"⚠️ 未找到 '{to_name or to_addr}' 的邮件地址，草稿如下：\n\n"
                f"主题: {subject}\n\n{draft}"
            )

    elif action == "SEND_FILE":
        file_path_str = params.get("file_path", "")
        email_subject = params.get("subject", f"📎 Aegis发送文件")
        to_addr = params.get("to", config.NETEASE_EMAIL)
        
        p = find_file_in_upload_dir(file_path_str)
        if p and p.exists():
            ok = send_email(
                to=to_addr,
                subject=email_subject,
                body=f"Aegis附件发送\n文件: {p.name}",
                attachments=[str(p)],
            )
            result_text = (
                f"✅ 文件已发送到邮箱: {p.name} ({p.stat().st_size // 1024}KB)"
                if ok else f"❌ 发送失败，文件路径: {p}"
            )
        else:
            result_text = f"⚠️ 找不到文件: {file_path_str}\n提示: 文件应放在 C:\\Users\\hp\\Desktop\\upload 目录下"

    elif action == "WRITE_WORD":
        instruction_text = params.get("instruction", instruction)
        send_to_email = params.get("send_to_email", True)
        try:
            from tools.document_builder import ai_generate_doc
            doc_path, description = ai_generate_doc(instruction_text)
            result_text = f"✅ 文档已生成: {doc_path.name}\n描述: {description}"
            if send_to_email:
                ok = send_email(
                    to=config.NETEASE_EMAIL,
                    subject=f"📄 Aegis文档: {doc_path.stem}",
                    body=f"Aegis已根据您的指令生成文档，详见附件。\n\n指令: {instruction_text}",
                    attachments=[str(doc_path)],
                )
                result_text += f"\n{'✅ 文档已发送到您的邮箱' if ok else '❌ 邮件发送失败，文档保存在: ' + str(doc_path)}"
        except Exception as e:
            result_text = f"❌ 文档生成失败: {e}"

    # pending 审核指令
    from memory.pending import parse_review_command, approve_by_ids, approve_all, reject, apply_approved
    review_action, review_ids = parse_review_command(instruction)
    if review_action == "approve":
        n = approve_by_ids(review_ids)
        applied = apply_approved()
        result_text = f"✅ 已通过 {n} 条，写入记忆层 {applied} 条"
    elif review_action == "approve_all":
        n = approve_all()
        applied = apply_approved()
        result_text = f"✅ 已通过全部 {n} 条，写入记忆层 {applied} 条"
    elif review_action == "reject":
        n = sum(1 for i in review_ids if reject(i))
        result_text = f"✅ 已拒绝 {n} 条"

    # 微信角色/群类型设置指令
    if not result_text or result_text == "✅ 指令已执行":
        try:
            from scheduler.focus_updater import handle_role_command
            role_result = handle_role_command(instruction)
            if role_result:
                result_text = role_result
        except Exception:
            pass

    return result_text or "✅ 指令已执行"


def process_commands():
    """主入口：拉取并处理所有待执行的用户指令。由 scheduler 定期调用。"""
    commands = fetch_commands()
    if not commands:
        return

    _safe_print(f"[Cmd] 发现 {len(commands)} 条用户指令")

    for cmd in commands:
        try:
            instruction = _extract_command_text(cmd["subject"], cmd["body"])

            from email_module.injection_guard import is_safe, scan as iscan
            if not is_safe(instruction):
                scan_result = iscan(instruction)
                _safe_print(f"[Cmd] ⚠️ 拒绝执行（{scan_result}）: {instruction[:60]}")
                send_email(config.NETEASE_EMAIL,
                           "⚠️ Aegis安全警告",
                           f"拒绝执行可疑指令:\n{instruction[:200]}\n\n原因: {scan_result}")
                db.save_command(cmd["id"], f"[BLOCKED] {instruction}", str(scan_result))
                continue

            _safe_print(f"[Cmd] 执行: {instruction[:60]}...")

            result = _execute_command(instruction, context=cmd)

            db.save_command(cmd["id"], instruction, result)

            reply_subject = f"✅ Aegis回复: {cmd['subject'][:40]}"
            send_email(config.NETEASE_EMAIL, reply_subject, result)
            _safe_print(f"[Cmd] 已回复: {reply_subject}")

        except Exception as e:
            _safe_print(f"[Cmd] 处理失败: {e}")