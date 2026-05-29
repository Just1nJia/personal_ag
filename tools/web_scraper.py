import asyncio
import re
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
import feedparser  # 确保已安装

class WebScraper:
    def __init__(self):
        self.client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
        )

    async def close(self):
        await self.client.aclose()

    async def fetch_page(self, url: str) -> Dict:
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            content_type = response.headers.get('content-type', '').lower()
            return {
                "success": True,
                "url": url,
                "content": response.text,
                "status_code": response.status_code,
                "content_type": content_type
            }
        except Exception as e:
            return {
                "success": False,
                "url": url,
                "error": str(e)
            }

    def extract_text(self, html: str, max_length: int = 5000) -> str:
        soup = BeautifulSoup(html, 'html.parser')
        for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
            script.decompose()
        text = soup.get_text(separator='\n', strip=True)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        content = '\n'.join(lines)
        if len(content) > max_length:
            content = content[:max_length] + "\n\n... (内容已截断)"
        return content

    def extract_links(self, html: str, base_url: str) -> List[Dict]:
        soup = BeautifulSoup(html, 'html.parser')
        links = []
        seen = set()
        for a in soup.find_all('a', href=True):
            href = a['href']
            text = a.get_text(strip=True)
            if not text or len(text) > 100:
                continue
            full_url = urljoin(base_url, href)
            if full_url not in seen and full_url.startswith(('http://', 'https://')):
                seen.add(full_url)
                links.append({"text": text[:80], "url": full_url})
        return links[:50]

    async def _fetch_normal_page(self, url: str) -> Optional[Dict]:
        fetch_result = await self.fetch_page(url)
        if not fetch_result["success"]:
            return None
        html = fetch_result["content"]
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.find('title')
        title_text = title.get_text(strip=True) if title else "无标题"
        content = self.extract_text(html, max_length=8000)
        return {"title": title_text, "content": content}

    async def scrape_article(self, url: str) -> Dict:
        fetch_result = await self.fetch_page(url)
        if not fetch_result["success"]:
            return {
                "success": False,
                "message": fetch_result.get("error", "爬取失败"),
                "url": url
            }

        html = fetch_result["content"]
        soup = BeautifulSoup(html, 'html.parser')
        content_type = fetch_result.get("content_type", "")

        # 判断是否为 RSS/Atom 源
        is_feed = False
        if 'application/rss' in content_type or 'application/atom' in content_type or 'text/xml' in content_type:
            is_feed = True
        elif soup.find('rss') or soup.find('feed'):
            is_feed = True

        # 核心修复：对 RSS/Atom 源进行深度抓取
        if is_feed:
            feed = feedparser.parse(html)
            feed_title = feed.feed.get('title', 'RSS 订阅源')
            entries = feed.entries

            all_links = []
            all_full_content = []

            # 处理 RSS 源中的每一条新闻
            for entry in entries[:10]:
                entry_title = entry.get('title', '无标题')
                entry_link = entry.get('link', '')
                if entry_link:
                    all_links.append({"text": entry_title, "url": entry_link})
                    print(f"[RSS] 抓取完整文章: {entry_title} -> {entry_link}")

                    # 访问新闻链接，抓取完整页面内容
                    article = await self._fetch_normal_page(entry_link)
                    if article:
                        all_full_content.append(f"## {article['title']}\n\n{article['content']}\n\n---\n\n")
                    else:
                        all_full_content.append(f"## {entry_title}\n\n（抓取详细内容失败）\n\n---\n\n")
                else:
                    # 如果 feed 条目没有提供链接，则回退使用 RSS 摘要
                    summary = entry.get('summary', '') or entry.get('description', '')
                    all_full_content.append(f"## {entry_title}\n\n{summary}\n\n---\n\n")

            combined_content = "".join(all_full_content) if all_full_content else "（未找到任何文章条目）"

            return {
                "success": True,
                "url": url,
                "title": feed_title,
                "content": combined_content,
                "content_length": len(combined_content),
                "links_count": len(all_links),
                "links": all_links[:20],
                "is_rss": True
            }

        # 普通网页处理
        title = soup.find('title')
        title_text = title.get_text(strip=True) if title else "无标题"
        content = self.extract_text(html, max_length=8000)
        links = self.extract_links(html, url)

        return {
            "success": True,
            "url": url,
            "title": title_text,
            "content": content,
            "content_length": len(content),
            "links_count": len(links),
            "links": links[:20],
            "is_rss": False
        }

    def format_as_markdown(self, data: Dict, custom_content: str = None) -> str:
        content = custom_content if custom_content is not None else data.get('content', '无内容')
        md = f"""# {data.get('title', '网页内容')}

**来源网址**: {data.get('url', '未知')}
**抓取时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**内容长度**: {len(content)} 字符

---

## 📄 正文内容

{content}

---

## 🔗 相关链接 ({data.get('links_count', 0)})

"""
        for link in data.get('links', [])[:20]:
            md += f"- [{link['text']}]({link['url']})\n"
        return md

    def format_as_txt(self, data: Dict, custom_content: str = None) -> str:
        content = custom_content if custom_content is not None else data.get('content', '无内容')
        text = f"""网页内容抓取报告
{'='*50}

标题: {data.get('title', '无标题')}
来源: {data.get('url', '未知')}
抓取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
内容长度: {len(content)} 字符

{'='*50}

【正文内容】

{content}

{'='*50}

【相关链接】（共 {data.get('links_count', 0)} 条）

"""
        for i, link in enumerate(data.get('links', [])[:20], 1):
            text += f"{i}. {link['text']}\n   {link['url']}\n\n"
        return text

scraper = WebScraper()