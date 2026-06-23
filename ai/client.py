"""
火山引擎 Doubao API 封装
"""
import json
from openai import OpenAI


def get_client():
    """每次调用都重新创建客户端"""
    import config  # 动态导入
    
    if not config.VOLC_API_KEY or config.VOLC_API_KEY == "":
        raise ValueError("❌ API Key 未配置")
    if not config.VOLC_API_BASE or config.VOLC_API_BASE == "":
        raise ValueError("❌ API Base URL 未配置")
    if not config.VOLC_MODEL or config.VOLC_MODEL == "":
        raise ValueError("❌ 模型名称未配置")
    
    return OpenAI(
        api_key=config.VOLC_API_KEY,
        base_url=config.VOLC_API_BASE,
    )


def chat(messages: list[dict], system_prompt: str = None,
         temperature: float = 0.7, inject_knowledge: bool = False) -> str:
    import config  # 动态导入
    
    msgs = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    msgs.extend(messages)

    if inject_knowledge:
        try:
            from memory.context_inject import inject_context
            user_query = next(
                (m["content"] for m in reversed(messages) if m["role"] == "user"),
                ""
            )
            if user_query:
                msgs = inject_context(user_query, msgs)
        except Exception:
            pass

    client = get_client()
    resp = client.chat.completions.create(
        model=config.VOLC_MODEL,
        messages=msgs,
        temperature=temperature,
        stream=False,
    )
    return resp.choices[0].message.content.strip()


def summarize(text: str, max_chars: int = 4000) -> str:
    """将长文本压缩为摘要"""
    text = text[:max_chars]
    return chat(
        messages=[{"role": "user", "content": f"请用200字以内概括以下内容的核心信息：\n\n{text}"}],
        system_prompt="你是一个信息提炼助手，擅长抓住文本的核心要点。输出简洁、准确。",
        temperature=0.3,
    )


def extract_profile_info(text: str, source: str = "") -> dict:
    """从文本中提取可能对理解用户有价值的信息"""
    prompt = f"""分析以下文本，提取对理解文档作者有价值的信息。
来源: {source}

文本:
{text[:3000]}

请以JSON格式输出，包含以下字段（无相关信息则填null）：
{{
  "profession": "职业/专业方向",
  "expertise": ["专业领域列表"],
  "goals": ["提到的目标或计划"],
  "contacts": ["提到的重要联系人"],
  "topics": ["主要话题/关键词"],
  "insights": "关于此人的一句话洞察"
}}
只输出JSON，不要其他内容。"""

    result = chat(
        messages=[{"role": "user", "content": prompt}],
        system_prompt="你是一个用户画像分析专家，擅长从文本中提取关于作者的关键信息。",
        temperature=0.2,
    )
    try:
        result = result.strip().strip("```json").strip("```").strip()
        return json.loads(result)
    except Exception:
        return {}


def analyze_email(subject: str, sender: str, body: str) -> dict:
    """分析邮件，返回重要性、摘要、建议回复"""
    prompt = f"""分析以下邮件：

发件人: {sender}
主题: {subject}
正文:
{body[:2000]}

请以JSON格式输出：
{{
  "importance": <1-5的整数，5最重要>,
  "summary": "一句话摘要（30字内）",
  "category": "工作/学术/生活/广告/通知/其他",
  "needs_reply": <true/false>,
  "draft_reply": "如果需要回复，给出简洁的回复草稿（50字内），否则为null"
}}
只输出JSON。"""

    result = chat(
        messages=[{"role": "user", "content": prompt}],
        system_prompt="你是Aegis，用户的私人AI助理。帮助分析邮件优先级和内容。",
        temperature=0.2,
    )
    try:
        result = result.strip().strip("```json").strip("```").strip()
        return json.loads(result)
    except Exception:
        return {"importance": 2, "summary": subject, "category": "其他", "needs_reply": False, "draft_reply": None}


def generate_daily_briefing(context: dict) -> str:
    """生成每日简报"""
    import config
    from datetime import datetime
    now = datetime.now()

    system_prompt = (
        "你是Aegis，用户的全方位AI生活助理。说话简洁、有温度、专业。\n\n"
        f"今天是 {now.strftime('%Y年%m月%d日')}，{now.strftime('%H:%M')}。\n\n"
        "你收到的是来自用户各个渠道的结构化数据。数据已经收集好出现在用户消息中，"
        "你不需要自己去获取任何信息。\n\n"
        "请按重要性降序生成简报：\n\n"
        "1. 问候 + 优先事项 — 用一句话点出最需要处理的事\n\n"
        "2. 邮件摘要 — 按优先级处理所有渠道的邮件\n\n"
        "3. 重要联系人动态 — 有互动的重要联系人简要说明。\n\n"
        "4. 结语 — 一句前瞻性的话。\n\n"
        "绝对规则：只陈述数据中有的事实，零幻觉，严格限制400字以内"
    )

    wechat_active = context.get("wechat_active", "")
    wechat_summary = context.get("wechat_summary", "")
    wechat_block = ""
    if wechat_active or wechat_summary:
        wechat_block = (
            f"【微信近期活跃事项】\n{wechat_active[:800]}\n\n"
            + (f"【微信概况】\n{wechat_summary[:400]}\n\n" if wechat_summary else "")
        )

    user_content = (
        f"以下是今日收集到的数据：\n\n"
        f"【重要邮件（{context.get('email_count', 0)}封）】\n"
        f"{context.get('email_summaries', '暂无')}\n\n"
        f"【重要联系人】\n"
        f"{context.get('contacts_summary', '暂无')}\n\n"
        + wechat_block +
        f"【学术雷达 — 近期新论文】\n"
        f"{context.get('new_papers', '暂无')}\n\n"
        f"【个人档案】\n"
        f"{context.get('profile_summary', '暂无')}\n\n"
        "请生成今日简报。要求：严格400字以内"
    )

    return chat(
        messages=[{"role": "user", "content": user_content}],
        system_prompt=system_prompt,
        temperature=0.7,
        inject_knowledge=True,
    )


def evaluate_briefing(briefing: str, context: dict) -> tuple[float, str]:
    """日报质量评估"""
    score = 10.0
    issues: list[str] = []

    length = len(briefing.strip())
    if length < 100:
        score -= 3.0
        issues.append("内容过短（不足100字）")
    elif length > 3000:
        score -= 1.0
        issues.append("内容过长（超过3000字）")

    if context.get("email_count", 0) > 0:
        email_keywords = ("邮件", "邮", "mail", "收件", "发件", "回复")
        if not any(kw in briefing for kw in email_keywords):
            score -= 1.5
            issues.append("有邮件数据但简报未提及邮件内容")

    placeholders = ("{", "TODO", "待补充", "PLACEHOLDER")
    if any(p in briefing for p in placeholders):
        score -= 2.0
        issues.append("简报包含未填充的模板占位符")

    score = max(1.0, score)
    rule_feedback = "；".join(issues) if issues else ""

    if score >= 7.0:
        return score, rule_feedback

    try:
        prompt = (
            f"日报问题：{rule_feedback}\n\n"
            f"日报（前500字）：\n{briefing[:500]}\n\n"
            "请用一句话给出最重要的改进建议。只输出建议文字。"
        )
        ai_feedback = chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="你是日报质量审阅员，给出简短改进建议。",
            temperature=0.2,
        ).strip()
        combined = f"{rule_feedback}；AI建议：{ai_feedback}" if rule_feedback else f"AI建议：{ai_feedback}"
        return score, combined
    except Exception:
        return score, rule_feedback