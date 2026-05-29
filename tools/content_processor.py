"""
内容整理模块
调用 AI 对爬取的内容进行整理
"""
from ai import client as ai_client


async def process_content(
    content: str,
    requirement: str,
    title: str = "",
    url: str = ""
) -> dict:
    """
    使用 AI 对内容进行整理
    
    Args:
        content: 原始内容
        requirement: 整理要求
        title: 网页标题
        url: 网页地址
    
    Returns:
        整理后的结果
    """
    if not requirement or not content:
        return {
            "success": False,
            "message": "缺少内容或整理要求",
            "processed_content": content
        }
    
    # 限制内容长度
    max_content_length = 8000
    if len(content) > max_content_length:
        content = content[:max_content_length] + "\n\n... (内容已截断)"
    
    # 构建提示词
    system_prompt = """你是一个专业的内容整理助手。根据用户的要求对爬取的网页内容进行整理。
要求：
1. 严格按照用户的要求处理内容
2. 保持信息的准确性，不要编造不存在的信息
3. 输出格式清晰易读
4. 如果用户要求提取特定信息，只输出提取的内容
5. 如果用户要求过滤，只输出过滤后的内容
6. 直接输出整理后的结果，不要添加额外的解释"""

    user_prompt = f"""请根据以下要求整理网页内容：

【网页标题】：{title}
【网页地址】：{url}

【整理要求】：
{requirement}

【原始内容】：
{content}

请按要求输出整理后的内容。"""

    try:
        result = ai_client.chat(
            messages=[{"role": "user", "content": user_prompt}],
            system_prompt=system_prompt,
            temperature=0.3,
        )
        
        return {
            "success": True,
            "processed_content": result.strip(),
            "original_length": len(content),
            "processed_length": len(result.strip()),
            "message": "内容整理完成"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"AI 整理失败: {str(e)}",
            "processed_content": content
        }