import httpx
import json
import re
from typing import Dict, Optional

class CommandParser:
    def __init__(self, api_url: str = None, api_key: str = None):
        self.api_url = api_url or "http://10.60.2.31/ai-gateway/szzx_openclaw/qianwen/chat/completions"
        self.api_key = api_key or "sk-jkqs13LnOsLORohQ4Ui84845Drl1rIsg"
    
    async def parse_command(self, command: str) -> Dict:
        """使用AI解析用户命令"""
        
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

3. 目标名称（dest_name）：如果是复制或合并操作，提取目标文件名

4. 内容描述（content_description）：如果是创建或更新操作，提取要写入的内容

5. 搜索关键词（keyword）：如果是搜索操作，提取关键词

6. 需要生成内容（need_generate）：如果需要AI生成内容，标记为true

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
                        # 如果AI解析失败，使用本地解析
                        local_result = self._local_parse(command)
                        if local_result:
                            return {"success": True, "command": local_result}
                        return {"success": False, "error": "无法解析AI响应", "response": ai_response}
                else:
                    local_result = self._local_parse(command)
                    if local_result:
                        return {"success": True, "command": local_result}
                    return {"success": False, "error": f"API请求失败: {response.status_code}"}
                    
            except Exception as e:
                local_result = self._local_parse(command)
                if local_result:
                    return {"success": True, "command": local_result}
                return {"success": False, "error": f"解析命令失败: {str(e)}"}
    
    def _local_parse(self, command: str) -> Optional[Dict]:
        """本地解析命令（当AI不可用时）"""
        cmd_lower = command.lower()
        
        # 判断类型
        is_folder = "文件夹" in command or "目录" in command or "folder" in cmd_lower
        is_file = ".txt" in command or ".docx" in command or "文件" in command
        
        # 提取名称
        import re
        
        # 读取操作
        if re.search(r'读取|查看|打开|读一下|看看', command):
            # 提取名称
            name_match = re.search(r'[读取查看打开读一下看看]\s*[:：]?\s*([^\s,，。！？]+)', command)
            if name_match:
                name = name_match.group(1).strip()
                return {
                    "action": "read",
                    "type": "folder" if "文件夹" in name or ("文件夹" in command and not is_file) else "file",
                    "name": name,
                    "new_name": None,
                    "dest_name": None,
                    "content_description": None,
                    "keyword": None,
                    "need_generate": False
                }
        
        # 修改/更新操作
        if re.search(r'修改|更新|编辑|改成|替换成', command):
            name_match = re.search(r'([^\s,，。！？]+)\s*改成\s*([^\s,，。！？]+)', command)
            if name_match:
                name = name_match.group(1).strip()
                new_content = name_match.group(2).strip()
                return {
                    "action": "update",
                    "type": "file",
                    "name": name,
                    "new_name": None,
                    "dest_name": None,
                    "content_description": new_content,
                    "keyword": None,
                    "need_generate": True if len(new_content) > 5 else False
                }
        
        # 重命名操作
        if re.search(r'重命名|改名为', command):
            rename_match = re.search(r'([^\s,，。！？]+)\s*改名为\s*([^\s,，。！？]+)', command)
            if rename_match:
                old_name = rename_match.group(1).strip()
                new_name = rename_match.group(2).strip()
                return {
                    "action": "rename",
                    "type": "folder" if "文件夹" in command else "file",
                    "name": old_name,
                    "new_name": new_name,
                    "dest_name": None,
                    "content_description": None,
                    "keyword": None,
                    "need_generate": False
                }
        
        # 创建操作
        if re.search(r'创建|新建|建立一个|创建一个', command):
            if "文件夹" in command:
                name_match = re.search(r'新建文件夹\s*[:：]?\s*([^\s,，。！？]+)', command)
                if name_match:
                    name = name_match.group(1).strip()
                    return {
                        "action": "create",
                        "type": "folder",
                        "name": name,
                        "new_name": None,
                        "dest_name": None,
                        "content_description": None,
                        "keyword": None,
                        "need_generate": False
                    }
            else:
                name_match = re.search(r'新建\s*[:：]?\s*([^\s,，。！？]+)', command)
                if name_match:
                    name = name_match.group(1).strip()
                    return {
                        "action": "create",
                        "type": "file",
                        "name": name if '.' in name else name + ".txt",
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
                "type": None,
                "name": None,
                "new_name": None,
                "dest_name": None,
                "content_description": None,
                "keyword": None,
                "need_generate": False
            }
        
        # 搜索操作
        if re.search(r'搜索|查找', command):
            keyword_match = re.search(r'搜索\s*[:：]?\s*([^\s,，。！？]+)', command)
            if keyword_match:
                keyword = keyword_match.group(1).strip()
                return {
                    "action": "search",
                    "type": None,
                    "name": None,
                    "new_name": None,
                    "dest_name": None,
                    "content_description": None,
                    "keyword": keyword,
                    "need_generate": False
                }
        
        return None
    
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