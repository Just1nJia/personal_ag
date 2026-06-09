"""
智能网址搜索模块
使用 AI 大模型根据用户需求生成相关网址
"""
import asyncio
import json
import re
from typing import List, Dict, Optional
import httpx


class SmartSearcher:
    def __init__(self):
        # AI 接口配置（使用你的配置）
        self.ai_url = "http://10.60.2.31/ai-gateway/yyyy-szxz/qianwen/chat/completions"
        self.headers = {
            "Content-Type": "application/json",
            "authorization": "Bearer sk-xcEaeuXW6V9VcfjxzKvfyLvFnb3Cpnu5"
        }
    
    async def _call_ai(self, prompt: str) -> str:
        """调用 AI 接口"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.ai_url,
                    headers=self.headers,
                    json={
                        "messages": [
                            {"role": "system", "content": "你是一个专业的网址搜索助手，只输出 JSON 格式的结果，不要添加任何其他内容。"},
                            {"role": "user", "content": prompt}
                        ],
                        "model": "Qwen2.5-32B-Instruct",
                        "temperature": 0.3,
                        "stream": False
                    }
                )
                if response.status_code == 200:
                    result = response.json()
                    return result["choices"][0]["message"]["content"]
                return ""
        except Exception as e:
            print(f"AI 调用失败: {e}")
            return ""
    
    async def search_urls(self, query: str, max_results: int = 5) -> List[Dict]:
        """
        使用 AI 大模型搜索相关网址
        
        Args:
            query: 用户需求描述
            max_results: 返回的最大结果数
        
        Returns:
            包含 title, url, snippet 的列表
        """
        prompt = f"""请根据用户的搜索需求，搜索并提供相关的权威网站网址。

用户需求：{query}

请提供 {max_results} 个最相关的网站，这些网站应该：
1. 是权威、可信的官方网站或专业机构网站
2. 内容与用户需求高度相关
3. 网址必须是有效的 HTTPS 或 HTTP 链接

请严格按照以下 JSON 格式输出：
[
    {{
        "title": "网站标题",
        "url": "https://example.com",
        "snippet": "该网站的内容简介"
    }}
]

只输出 JSON 数组，不要添加任何其他内容。"""

        ai_result = await self._call_ai(prompt)
        
        if not ai_result:
            return []
        
        # 清理 AI 返回内容
        ai_result = ai_result.strip()
        # 去掉 markdown 代码块标记
        if ai_result.startswith("```json"):
            ai_result = ai_result[7:]
        if ai_result.startswith("```"):
            ai_result = ai_result[3:]
        if ai_result.endswith("```"):
            ai_result = ai_result[:-3]
        ai_result = ai_result.strip()
        
        try:
            results = json.loads(ai_result)
            if isinstance(results, list):
                # 验证并过滤结果
                valid_results = []
                for r in results[:max_results]:
                    if isinstance(r, dict) and r.get("url"):
                        valid_results.append({
                            "title": r.get("title", "无标题"),
                            "url": r.get("url", ""),
                            "snippet": r.get("snippet", "")[:200]
                        })
                return valid_results
        except json.JSONDecodeError as e:
            print(f"JSON 解析失败: {e}")
            # 尝试用正则提取网址
            urls = re.findall(r'https?://[^\s"\']+', ai_result)
            titles = re.findall(r'"title":\s*"([^"]+)"', ai_result)
            if urls:
                return [
                    {"title": titles[i] if i < len(titles) else url, "url": url, "snippet": ""}
                    for i, url in enumerate(urls[:max_results])
                ]
        
        return []
    
    async def search_news(self, topic: str, max_results: int = 5) -> List[Dict]:
        """搜索新闻类内容"""
        query = f"{topic} 最新疫情新闻 权威来源"
        return await self.search_urls(query, max_results)
    
    async def search_official(self, topic: str, max_results: int = 5) -> List[Dict]:
        """搜索官方机构内容"""
        query = f"{topic} 官方网站 WHO CDC 卫健委"
        return await self.search_urls(query, max_results)


smart_searcher = SmartSearcher()