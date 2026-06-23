"""SMTP 发送邮件（网易163）"""
import smtplib
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import List, Union, Optional
import config


def _safe_print(msg: str):
    """Windows GBK 终端安全输出，过滤无法编码的字符"""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


def _b64_header(text: str) -> str:
    """RFC 2047 base64 编码，兼容 emoji 和中文，避免 Windows GBK 问题"""
    return f"=?utf-8?b?{base64.b64encode(text.encode('utf-8')).decode('ascii')}?="


def find_file_in_upload_dir(filename: str, upload_dir: str = None) -> Optional[Path]:
    """在指定目录中查找文件（支持模糊匹配）"""
    if upload_dir is None:
        upload_dir = config.UPLOAD_DIR  # 从 config 读取
    
    upload_path = Path(upload_dir)
    if not upload_path.exists():
        return None
    
    # 先尝试精确匹配
    target = upload_path / filename
    if target.exists():
        return target
    
    # 再尝试模糊匹配（文件名包含关键词）
    name_lower = filename.lower()
    for f in upload_path.iterdir():
        if f.is_file() and name_lower in f.name.lower():
            return f
    
    return None


def send_email(
    to: str,
    subject: str,
    body: str,
    html: bool = False,
    attachments: List[Union[str, Path]] = None,
    auto_find_attachments: bool = True,
) -> bool:
    """
    发送邮件。
    to: 收件人地址
    subject: 主题
    body: 正文（纯文本或HTML）
    html: 是否为HTML格式
    attachments: 附件路径列表（str 或 Path），可选
    auto_find_attachments: 是否自动在 upload 目录查找附件文件
    """
    try:
        _safe_print(f"[Email] 开始发送: to={to}, subject={subject}")
        
        msg = MIMEMultipart("mixed")
        msg["From"]    = f"{_b64_header('Aegis')} <{config.NETEASE_EMAIL}>"
        msg["To"]      = to
        msg["Subject"] = _b64_header(subject)

        # 正文
        mime_type = "html" if html else "plain"
        part = MIMEText(body, mime_type, "utf-8")
        msg.attach(part)

        # 附件处理
        attached_count = 0
        for att_path in (attachments or []):
            p = Path(att_path)
            
            # 如果文件不存在且 auto_find_attachments 为 True，尝试在 upload 目录查找
            if not p.exists() and auto_find_attachments:
                found = find_file_in_upload_dir(att_path)
                if found:
                    p = found
                    _safe_print(f"[Email] 在 upload 目录找到附件: {p.name}")
            
            if not p.exists():
                _safe_print(f"[Email] 附件不存在，跳过: {att_path}")
                continue
            
            with open(p, "rb") as f:
                att = MIMEBase("application", "octet-stream")
                att.set_payload(f.read())
            encoders.encode_base64(att)
            
            # 使用 base64 编码的文件名（支持中文）
            att.add_header(
                "Content-Disposition",
                "attachment",
                filename=_b64_header(p.name),
            )
            msg.attach(att)
            attached_count += 1
            _safe_print(f"[Email] 附件已加载: {p.name} ({p.stat().st_size // 1024}KB)")

        if attached_count > 0:
            _safe_print(f"[Email] 共加载 {attached_count} 个附件")
        else:
            _safe_print(f"[Email] 无附件")

        _safe_print(f"[Email] 尝试连接 SMTP 服务器: {config.NETEASE_SMTP_HOST}:{config.NETEASE_SMTP_PORT}")
        
        with smtplib.SMTP_SSL(config.NETEASE_SMTP_HOST, config.NETEASE_SMTP_PORT) as server:
            _safe_print(f"[Email] 正在登录: {config.NETEASE_EMAIL}")
            server.login(config.NETEASE_EMAIL, config.NETEASE_AUTH_CODE)
            _safe_print(f"[Email] 登录成功，正在发送...")
            server.sendmail(config.NETEASE_EMAIL, to, msg.as_bytes())

        _safe_print(f"[Email] 发送成功 → {to} | {subject}")
        return True

    except smtplib.SMTPAuthenticationError as e:
        _safe_print(f"[Email] SMTP 认证失败: {e}")
        _safe_print(f"   请检查邮箱地址和授权码是否正确")
        return False
    except smtplib.SMTPException as e:
        _safe_print(f"[Email] SMTP 错误: {e}")
        return False
    except Exception as e:
        import traceback
        _safe_print(f"[Email] 发送失败: {e}")
        _safe_print(traceback.format_exc())
        return False


def send_daily_briefing(content: str, date: str) -> bool:
    subject = f"📋 Aegis日报 — {date}"
    return send_email(
        to=config.NETEASE_EMAIL,
        subject=subject,
        body=content,
    )