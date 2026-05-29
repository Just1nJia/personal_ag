import httpx
import json
import re
from typing import Dict, Optional, List, Union

class CommandParser:
    def __init__(self, api_url: str = None, api_key: str = None):
        self.api_url = api_url or "http://10.60.2.31/ai-gateway/szzx_openclaw/qianwen/chat/completions"
        self.api_key = api_key or "sk-jkqs13LnOsLORohQ4Ui84845Drl1rIsg"
    
    async def parse_command(self, command: str) -> Dict:
        """使用AI解析用户命令（文件操作）"""
        
        system_prompt = """你是一个文件操作命令解析器。请分析用户的自然语言命令，提取以下信息：

1. 操作类型（action）：必须是以下之一：
   - create（创建文件）
   - read（读取文件）
   - update（更新文件内容）
   - rename（重命名文件）
   - copy（复制文件）
   - list（列出所有文件）
   - search（搜索文件内容）
   - merge（合并多个文件的内容）

2. 名称（name）：要操作的文件名
   - 如果是 merge 操作，name 可以是多个文件名的数组

3. 新名称（new_name）：如果是重命名操作，提取新文件名

4. 目标名称（dest_name）：如果是复制或合并操作，提取目标文件名

5. 内容描述（content_description）：如果是创建或更新操作，提取要写入的内容

6. 搜索关键词（keyword）：如果是搜索操作，提取关键词

7. 需要生成内容（need_generate）：如果需要AI生成内容，标记为true

重要规则：
- 用户说"把A.txt和B.txt内容合并新建C.txt" → action: merge, name: ["A.txt", "B.txt"], dest_name: "C.txt"
- 用户说"合并 1.txt 2.txt 到 3.txt" → action: merge, name: ["1.txt", "2.txt"], dest_name: "3.txt"
- 用户说"新建 123.txt" → action: create, name: "123.txt"
- 用户说"读取 123.txt" → action: read, name: "123.txt"
- 用户说"修改 123.txt 改成 hello" → action: update, name: "123.txt", content_description: "hello"
- 用户说"重命名 123.txt 为 456.txt" → action: rename, name: "123.txt", new_name: "456.txt"
- 用户说"复制 123.txt 到 456.txt" → action: copy, name: "123.txt", dest_name: "456.txt"
- 用户说"列出所有文件" → action: list
- 用户说"搜索 岳阳楼记" → action: search, keyword: "岳阳楼记"

请以JSON格式返回，格式如下：
{
    "action": "操作类型",
    "name": "文件名 或 [文件名列表]",
    "new_name": "新文件名",
    "dest_name": "目标文件名",
    "content_description": "内容描述",
    "keyword": "关键词",
    "need_generate": true/false
}

只返回JSON，不要有其他解释。"""

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.api_url,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}"
                    },
                    json={
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": command}
                        ],
                        "model": "Qwen2.5-32B-Instruct",
                        "temperature": 0.1,
                        "top_p": 0.8,
                        "stream": False
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    ai_response = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    
                    try:
                        ai_response = ai_response.strip()
                        if ai_response.startswith("```json"):
                            ai_response = ai_response[7:]
                        if ai_response.startswith("```"):
                            ai_response = ai_response[3:]
                        if ai_response.endswith("```"):
                            ai_response = ai_response[:-3]
                        
                        parsed_command = json.loads(ai_response.strip())
                        return {"success": True, "command": parsed_command}
                    except json.JSONDecodeError:
                        local_result = self._local_parse_file(command)
                        if local_result:
                            return {"success": True, "command": local_result}
                        return {"success": False, "error": "无法解析AI响应", "response": ai_response}
                else:
                    local_result = self._local_parse_file(command)
                    if local_result:
                        return {"success": True, "command": local_result}
                    return {"success": False, "error": f"API请求失败: {response.status_code}"}
                    
            except Exception as e:
                local_result = self._local_parse_file(command)
                if local_result:
                    return {"success": True, "command": local_result}
                return {"success": False, "error": f"解析命令失败: {str(e)}"}
    
    def _local_parse_file(self, command: str) -> Optional[Dict]:
        """本地解析文件操作命令（当AI不可用时）"""
        cmd_lower = command.lower()
        
        import re
        
        # 合并操作
        merge_match = re.search(r'合并\s+(.+?)\s+到\s+(.+?)$', command)
        if not merge_match:
            merge_match = re.search(r'把\s+(.+?)\s+合并\s+到\s+(.+?)$', command)
        if merge_match:
            sources = [s.strip() for s in merge_match.group(1).split('和')]
            dest = merge_match.group(2).strip()
            return {
                "action": "merge",
                "name": sources,
                "dest_name": dest if '.' in dest else dest + '.txt',
                "new_name": None,
                "content_description": None,
                "keyword": None,
                "need_generate": False
            }
        
        # 读取操作
        read_match = re.search(r'读取\s+([^\s,，。！？]+)', command)
        if read_match:
            name = read_match.group(1).strip()
            return {
                "action": "read",
                "name": name if '.' in name else name + '.txt',
                "new_name": None,
                "dest_name": None,
                "content_description": None,
                "keyword": None,
                "need_generate": False
            }
        
        # 修改/更新操作
        update_match = re.search(r'修改\s+([^\s,，。！？]+)\s+改成\s+(.+)', command)
        if update_match:
            name = update_match.group(1).strip()
            new_content = update_match.group(2).strip()
            return {
                "action": "update",
                "name": name if '.' in name else name + '.txt',
                "new_name": None,
                "dest_name": None,
                "content_description": new_content,
                "keyword": None,
                "need_generate": len(new_content) > 10
            }
        
        # 重命名操作
        rename_match = re.search(r'重命名\s+([^\s,，。！？]+)\s+为\s+([^\s,，。！？]+)', command)
        if rename_match:
            old_name = rename_match.group(1).strip()
            new_name = rename_match.group(2).strip()
            return {
                "action": "rename",
                "name": old_name if '.' in old_name else old_name + '.txt',
                "new_name": new_name if '.' in new_name else new_name + '.txt',
                "dest_name": None,
                "content_description": None,
                "keyword": None,
                "need_generate": False
            }
        
        # 复制操作
        copy_match = re.search(r'复制\s+([^\s,，。！？]+)\s+到\s+([^\s,，。！？]+)', command)
        if copy_match:
            source = copy_match.group(1).strip()
            dest = copy_match.group(2).strip()
            return {
                "action": "copy",
                "name": source if '.' in source else source + '.txt',
                "new_name": None,
                "dest_name": dest if '.' in dest else dest + '.txt',
                "content_description": None,
                "keyword": None,
                "need_generate": False
            }
        
        # 创建操作
        create_match = re.search(r'新建\s+([^\s,，。！？]+)', command)
        if create_match:
            name = create_match.group(1).strip()
            return {
                "action": "create",
                "name": name if '.' in name else name + '.txt',
                "new_name": None,
                "dest_name": None,
                "content_description": None,
                "keyword": None,
                "need_generate": False
            }
        
        # 列出操作
        if re.search(r'列出|所有文件|有哪些文件', command):
            return {
                "action": "list",
                "name": None,
                "new_name": None,
                "dest_name": None,
                "content_description": None,
                "keyword": None,
                "need_generate": False
            }
        
        # 搜索操作
        search_match = re.search(r'搜索\s+([^\s,，。！？]+)', command)
        if search_match:
            keyword = search_match.group(1).strip()
            return {
                "action": "search",
                "name": None,
                "new_name": None,
                "dest_name": None,
                "content_description": None,
                "keyword": keyword,
                "need_generate": False
            }
        
        return None
    
    def parse_email_command(self, command: str) -> Optional[Dict]:
        """解析邮件发送命令"""
        import re
        
        command = command.strip()
        
        # 提取收件人邮箱
        to_patterns = [
            r'发邮件给\s*([a-zA-Z0-9@._-]+)',
            r'发送邮件给\s*([a-zA-Z0-9@._-]+)',
            r'给\s*([a-zA-Z0-9@._-]+)\s*发邮件',
            r'邮件给\s*([a-zA-Z0-9@._-]+)',
            r'回复\s*([a-zA-Z0-9@._-]+)',
        ]
        
        to_email = None
        for pattern in to_patterns:
            match = re.search(pattern, command)
            if match:
                to_email = match.group(1)
                break
        
        if not to_email:
            return None
        
        # 提取主题
        subject = ""
        subject_match = re.search(r'主题[是为:：]\s*([^，,。！？\n]+)', command)
        if subject_match:
            subject = subject_match.group(1).strip()
        else:
            subject_match = re.search(r'主题\s+([^，,。！？\n]+)', command)
            if subject_match:
                subject = subject_match.group(1).strip()
        
        # 提取内容
        content = ""
        content_match = re.search(r'内容[是为:：]\s*([^，,。！？\n]+)', command)
        if content_match:
            content = content_match.group(1).strip()
        else:
            content_match = re.search(r'内容\s+([^，,。！？\n]+)', command)
            if content_match:
                content = content_match.group(1).strip()
        
        # 如果没有单独的内容，尝试从命令末尾提取
        if not content:
            # 移除已解析的部分
            remaining = command
            if to_email:
                remaining = remaining.replace(to_email, '')
            if subject:
                remaining = remaining.replace(f"主题{subject}", '').replace(f"主题是{subject}", '')
            # 提取剩余的非关键词部分作为内容
            content = re.sub(r'发邮件给|发送邮件给|给.*?发邮件|主题|内容|附件|，|、|。', '', remaining).strip()
        
        # 提取附件
        attachments = []
        attach_match = re.search(r'附件[是为:：]\s*([^，,。！？\n]+)', command)
        if attach_match:
            attach_str = attach_match.group(1).strip()
            for sep in ['，', ',', '、', ' ']:
                if sep in attach_str:
                    attachments = [a.strip() for a in attach_str.split(sep)]
                    break
            if not attachments:
                attachments = [attach_str]
        
        return {
            "action": "send_email",
            "to": to_email,
            "subject": subject or "来自 Aegis 的邮件",
            "content": content,
            "attachments": attachments
        }
    
    def _local_parse(self, command: str) -> Optional[Dict]:
        """本地解析命令（兼容旧接口）"""
        return self._local_parse_file(command)
    
    async def generate_content(self, content_description: str) -> str:
        """使用AI生成文件内容"""
        
        system_prompt = """你是一个内容生成助手。根据用户的描述，生成符合要求的完整内容。
要求：
1. 如果用户要求经典文章（如岳阳楼记、出师表等），请提供完整的原文
2. 如果用户要求特定主题的文章，请生成相关内容
3. 内容要完整、准确、高质量
4. 直接返回生成的内容，不要有任何额外的解释或标记"""
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    self.api_url,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {self.api_key}"
                    },
                    json={
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"请生成：{content_description}"}
                        ],
                        "model": "Qwen2.5-32B-Instruct",
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "stream": False
                    },
                    timeout=60.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    generated_content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    return generated_content
                else:
                    return f"[生成失败] 无法生成内容: {content_description}"
                    
            except Exception as e:
                return f"[生成失败] {str(e)}"