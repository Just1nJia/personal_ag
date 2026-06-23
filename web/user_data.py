"""
用户数据隔离管理 - 所有数据存在服务器
"""
from pathlib import Path
import sqlite3
import shutil
from typing import Optional

# 用户数据根目录
USERS_BASE_DIR = Path("data/users")


def get_user_dir(username: str) -> Path:
    """获取用户数据目录"""
    user_dir = USERS_BASE_DIR / username
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir


def init_user_data_dir(username: str) -> None:
    """初始化新用户的所有数据目录"""
    user_dir = get_user_dir(username)
    
    # 创建所有子目录
    subdirs = ["memory", "files", "scrape", "scripts", "logs", "config"]
    for subdir in subdirs:
        (user_dir / subdir).mkdir(exist_ok=True)
    
    # 初始化 memory 子目录结构
    memory_dir = user_dir / "memory"
    for subdir in ["contacts", "groups", "projects", "personal", "archive"]:
        (memory_dir / subdir).mkdir(exist_ok=True)
    
    # 初始化默认记忆文件
    _init_default_memory_files(memory_dir)
    
    # 初始化用户数据库
    _init_user_db(username)
    
    print(f"[UserData] 已初始化用户 {username} 的数据目录")


def _init_default_memory_files(memory_dir: Path):
    """初始化默认的记忆文件"""
    # focus.md
    focus_path = memory_dir / "focus.md"
    if not focus_path.exists():
        focus_path.write_text(
            "# 当前焦点清单\n> 更新: \n\n## 紧急\n\n## 常规\n\n## 等待/观察\n",
            encoding="utf-8"
        )
    
    # people.md
    people_path = memory_dir / "people.md"
    if not people_path.exists():
        people_path.write_text(
            "# 重要联系人\n\n*暂无重要联系人，新联系人会在邮件往来中自动添加。*\n",
            encoding="utf-8"
        )
    
    # self.md
    self_path = memory_dir / "self.md"
    if not self_path.exists():
        self_path.write_text(
            "# 我是谁\n> 最后更新: \n\n## 身份与职业\n\n## 专业领域\n\n## 当前目标\n",
            encoding="utf-8"
        )


def _init_user_db(username: str) -> None:
    """初始化用户的 SQLite 数据库（完整 schema）"""
    db_path = get_user_dir(username) / "user.db"
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 邮件表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS emails (
            id TEXT PRIMARY KEY,
            from_addr TEXT,
            from_name TEXT,
            subject TEXT,
            date TEXT,
            body TEXT,
            summary TEXT,
            importance INTEGER DEFAULT 3,
            category TEXT,
            needs_reply INTEGER DEFAULT 0,
            is_processed INTEGER DEFAULT 0,
            draft_reply TEXT,
            source TEXT DEFAULT '163',
            created_at TEXT
        )
    ''')
    
    # 联系人表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_name TEXT,
            email TEXT,
            wechat_id TEXT,
            role TEXT,
            importance INTEGER,
            institution TEXT,
            institution_type TEXT,
            notes TEXT,
            email_count INTEGER DEFAULT 0,
            wechat_msg_count INTEGER DEFAULT 0,
            last_seen TEXT,
            first_seen TEXT,
            tags TEXT
        )
    ''')
    
    # 微信消息表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS wechat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            talker_name TEXT,
            talker_wxid TEXT,
            content TEXT,
            is_sender INTEGER,
            create_time TEXT,
            msg_type TEXT,
            ts TEXT
        )
    ''')
    
    # 微信联系人表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS wechat_contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wxid TEXT UNIQUE,
            nickname TEXT,
            remark TEXT,
            is_group INTEGER DEFAULT 0,
            avatar TEXT,
            last_update TEXT
        )
    ''')
    
    # 文件索引表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS file_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            path TEXT,
            extension TEXT,
            size INTEGER,
            activity_tier TEXT,
            indexed_at TEXT
        )
    ''')
    
    # 待审核表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS memory_pending (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            source_ref TEXT,
            content TEXT,
            proposed_layer TEXT,
            proposed_target TEXT,
            item_type TEXT,
            confidence REAL,
            extracted_at TEXT,
            status TEXT,
            notes TEXT
        )
    ''')
    
    # 发件人画像表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sender_profiles (
            sender TEXT PRIMARY KEY,
            category TEXT,
            avg_importance REAL,
            email_count INTEGER DEFAULT 1,
            last_seen TEXT
        )
    ''')
    
    # 命令记录表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS command_log (
            id TEXT PRIMARY KEY,
            instruction TEXT,
            result TEXT,
            executed_at TEXT
        )
    ''')
    
    # 爬虫任务表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scrape_tasks (
            id TEXT PRIMARY KEY,
            urls TEXT,
            schedule_type TEXT,
            schedule_detail TEXT,
            schedule_time TEXT,
            email TEXT,
            format TEXT,
            need_process INTEGER DEFAULT 0,
            process_requirement TEXT,
            next_run TEXT,
            created_at TEXT,
            last_run TEXT,
            enabled INTEGER DEFAULT 1
        )
    ''')
    
    conn.commit()
    conn.close()
    
    print(f"[UserData] 已初始化用户 {username} 的数据库")


def get_user_db(username: str) -> sqlite3.Connection:
    """获取用户的数据库连接"""
    db_path = get_user_dir(username) / "user.db"
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ── 用户目录获取函数 ────────────────────────────────────────────────

def get_user_memory_dir(username: str) -> Path:
    return get_user_dir(username) / "memory"


def get_user_files_dir(username: str) -> Path:
    return get_user_dir(username) / "files"


def get_user_scrape_dir(username: str) -> Path:
    return get_user_dir(username) / "scrape"


def get_user_scripts_dir(username: str) -> Path:
    return get_user_dir(username) / "scripts"


def get_user_logs_dir(username: str) -> Path:
    return get_user_dir(username) / "logs"


def get_user_config_dir(username: str) -> Path:
    return get_user_dir(username) / "config"


# ── 用户设置读写 ────────────────────────────────────────────────────

def get_user_settings(username: str) -> dict:
    """获取用户的完整设置"""
    config_file = get_user_config_dir(username) / "settings.json"
    if config_file.exists():
        import json
        try:
            return json.loads(config_file.read_text(encoding='utf-8'))
        except:
            pass
    return {}


def save_user_settings(username: str, settings: dict):
    """保存用户的完整设置"""
    config_dir = get_user_config_dir(username)
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "settings.json"
    import json
    config_file.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')


def delete_user_data(username: str):
    """删除用户的所有数据"""
    user_dir = get_user_dir(username)
    if user_dir.exists():
        shutil.rmtree(user_dir)
        print(f"[UserData] 已删除用户 {username} 的所有数据")