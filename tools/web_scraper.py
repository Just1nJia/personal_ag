import asyncio
import re
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
import feedparser

# 过滤 XML 解析警告
from bs4 import XMLParsedAsHTMLWarning
import warnings
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


class WebScraper:
    def __init__(self):
        pass

    async def close(self):
        pass

    async def fetch_page(self, url: str, retry: int = 2) -> Dict:
        """获取网页内容，带重试机制"""
        for attempt in range(retry + 1):
            try:
                async with httpx.AsyncClient(
                    follow_redirects=True,
                    timeout=30.0,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    }
                ) as client:
                    response = await client.get(url)
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
                if attempt == retry:
                    return {
                        "success": False,
                        "url": url,
                        "error": str(e)
                    }
                await asyncio.sleep(1)
        return {"success": False, "url": url, "error": "未知错误"}

    def extract_text(self, html: str, max_length: int = 100000) -> str:
        """提取纯文本内容，默认10万字符"""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            for script in soup(["script", "style", "nav", "footer", "header", "aside"]):
                script.decompose()
            
            # 尝试获取文章主体内容
            article = soup.find('article')
            if article:
                text = article.get_text(separator='\n', strip=True)
            else:
                text = soup.get_text(separator='\n', strip=True)
            
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            content = '\n'.join(lines)
            
            if max_length > 0 and len(content) > max_length:
                content = content[:max_length] + "\n\n... (内容已截断)"
            return content
        except Exception as e:
            print(f"提取文本失败: {e}")
            return ""

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

    async def _fetch_normal_page(self, url: str, max_retry: int = 2) -> Optional[Dict]:
        """抓取普通网页内容，支持重试"""
        for attempt in range(max_retry):
            fetch_result = await self.fetch_page(url)
            if not fetch_result["success"]:
                if attempt == max_retry - 1:
                    return None
                await asyncio.sleep(1)
                continue
            
            html = fetch_result["content"]
            
            # 如果 HTML 太短，可能是被屏蔽，重试一次
            if len(html) < 1000 and attempt < max_retry - 1:
                print(f"[FETCH] HTML 内容过短 ({len(html)} 字符)，重试...")
                await asyncio.sleep(2)
                continue
            
            soup = BeautifulSoup(html, 'html.parser')
            title = soup.find('title')
            title_text = title.get_text(strip=True) if title else "无标题"
            
            # 尝试获取文章主体内容
            content = ""
            
            # 方法1：查找 article 标签
            article = soup.find('article')
            if article:
                content = article.get_text(separator='\n', strip=True)
            
            # 方法2：查找常见正文容器
            if not content or len(content) < 200:
                for selector in ['.content', '.main-content', '.post-content', '.entry-content', '#content', '.article-content', '.body', '#main-content']:
                    container = soup.select_one(selector)
                    if container:
                        content = container.get_text(separator='\n', strip=True)
                        if len(content) > 200:
                            break
            
            # 方法3：提取所有文本
            if not content or len(content) < 200:
                content = self.extract_text(html, max_length=100000)
            
            # 如果内容仍然太少，可能是动态页面，返回 None
            if len(content) < 100:
                print(f"[FETCH] 内容提取失败，仅 {len(content)} 字符")
                return None
            
            return {"title": title_text, "content": content}
        
        return None

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

        # 处理 RSS/Atom 源
        if is_feed:
            feed = feedparser.parse(html)
            feed_title = feed.feed.get('title', 'RSS 订阅源')
            entries = feed.entries

            all_links = []
            all_full_content = []

            for entry in entries[:20]:
                entry_title = entry.get('title', '无标题')
                entry_link = entry.get('link', '')
                entry_summary = entry.get('summary', '') or entry.get('description', '')
                entry_published = entry.get('published', '') or entry.get('date', '')
                
                # 构建内容块
                content_block = f"## {entry_title}\n\n"
                if entry_published:
                    content_block += f"**发布时间**: {entry_published}\n\n"
                
                if entry_link:
                    all_links.append({"text": entry_title, "url": entry_link})
                    
                    # 尝试抓取完整文章
                    article = await self._fetch_normal_page(entry_link)
                    if article and len(article.get('content', '')) > 300:
                        # 有完整内容，使用完整内容
                        content_block += article['content']
                    else:
                        # 没有完整内容，使用 RSS 摘要
                        if entry_summary:
                            content_block += entry_summary
                        else:
                            content_block += "（无详细内容）"
                        content_block += f"\n\n**原文链接**: {entry_link}"
                else:
                    # 没有链接，直接使用摘要
                    if entry_summary:
                        content_block += entry_summary
                    else:
                        content_block += "（无详细内容）"
                
                content_block += "\n\n---\n\n"
                all_full_content.append(content_block)

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
        
        # 尝试获取文章主体
        content = ""
        article = soup.find('article')
        if article:
            content = article.get_text(separator='\n', strip=True)
        
        if not content or len(content) < 200:
            for selector in ['.content', '.main-content', '.post-content', '.entry-content', '#content', '.article-content']:
                container = soup.select_one(selector)
                if container:
                    content = container.get_text(separator='\n', strip=True)
                    if len(content) > 200:
                        break
        
        if not content or len(content) < 200:
            content = self.extract_text(html, max_length=100000)
        
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


# 全局实例
scraper = WebScraper()