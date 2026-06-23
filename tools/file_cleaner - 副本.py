"""
文件清洗工具
支持删除空行、特殊字符、重复行、格式规范化等
"""
import re
import os
import json  # 确保有这一行
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime


class FileCleaner:
    def __init__(self):
        # 文件仓库根目录
        self.base_dir = Path("C:/Users/hp/Desktop/upload")
    
    def list_available_files(self) -> List[str]:
        """列出所有可清洗的文件"""
        files = []
        for ext in ['*.txt', '*.md', '*.csv', '*.json', '*.xml']:
            files.extend(self.base_dir.rglob(ext))
        # 排除目录
        files = [f for f in files if f.is_file()]
        return [str(f.relative_to(self.base_dir)) for f in files]
    
    def _log_operation(self, operation: str, success: bool, details: Dict, error: str = None, command_text: str = None):
        """记录操作日志"""
        try:
            from web.file_logger import file_logger
            file_logger.log_operation(
                operation=operation,
                success=success,
                details=details,
                error=error,
                command_text=command_text
            )
        except ImportError:
            # 如果没有 file_logger，打印到控制台
            status = "✅ 成功" if success else "❌ 失败"
            print(f"[FileCleaner] {status} | {operation} | {details}")
            if command_text:
                print(f"[FileCleaner] 指令: {command_text[:100]}...")
            if error:
                print(f"[FileCleaner] 错误: {error}")
    
    def clean_file(self, filepath: str, rules: Dict, command_text: str = None) -> Dict:
        """
        清洗文件
        rules 示例:
        {
            "remove_empty_lines": True,      # 删除空行
            "remove_special_chars": True,    # 删除特殊字符（保留中文、英文、数字、常用标点）
            "remove_duplicate_lines": True,  # 删除重复行
            "strip_lines": True,             # 去除每行首尾空白
            "convert_to_utf8": True,         # 转换为UTF-8
            "save_as_new": False,            # 另存为新文件
            "custom_replace": [              # 自定义替换
                {"from": "旧文本", "to": "新文本"}
            ]
        }
        """
        start_time = datetime.now()
        full_path = self.base_dir / filepath
        
        if not full_path.exists():
            self._log_operation(
                operation="clean_file",
                success=False,
                details={"filepath": filepath},
                error=f"文件不存在: {filepath}",
                command_text=command_text
            )
            return {"success": False, "message": f"文件不存在: {filepath}"}
        
        try:
            # 读取文件
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            original_length = len(content)
            original_lines = len(content.splitlines())
            lines = content.splitlines()
            
            # 应用清洗规则
            # 1. 去除每行首尾空白
            if rules.get("strip_lines", False):
                lines = [line.strip() for line in lines]
            
            # 2. 删除空行
            if rules.get("remove_empty_lines", False):
                lines = [line for line in lines if line]
            
            # 3. 删除重复行（保留第一次出现）
            if rules.get("remove_duplicate_lines", False):
                seen = set()
                unique_lines = []
                for line in lines:
                    if line not in seen:
                        seen.add(line)
                        unique_lines.append(line)
                lines = unique_lines
            
            # 4. 删除特殊字符
            if rules.get("remove_special_chars", False):
                # 保留：中文、英文、数字、常用标点
                cleaned_lines = []
                for line in lines:
                    cleaned = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9\s\.\,\!\?\;:\"\'\(\)\【\】\《\》\、\。\，\！\？\；\：\“\”]', '', line)
                    cleaned_lines.append(cleaned)
                lines = cleaned_lines
            
            # 5. 自定义替换
            custom_replace = rules.get("custom_replace", [])
            for cr in custom_replace:
                from_text = cr.get("from", "")
                to_text = cr.get("to", "")
                if from_text:
                    lines = [line.replace(from_text, to_text) for line in lines]
            
            # 重新组合内容
            new_content = '\n'.join(lines)
            
            # 保存清洗后的内容
            output_path = full_path
            if rules.get("save_as_new", False):
                stem = full_path.stem
                suffix = full_path.suffix
                output_path = full_path.parent / f"{stem}_cleaned{suffix}"
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            
            # 记录成功日志
            self._log_operation(
                operation="clean_file",
                success=True,
                details={
                    "filepath": str(output_path.relative_to(self.base_dir)),
                    "original_length": original_length,
                    "new_length": len(new_content),
                    "original_lines": original_lines,
                    "new_lines": len(lines),
                    "rules_applied": [k for k, v in rules.items() if v and k != "custom_replace"],
                    "duration_ms": round(duration_ms, 2)
                },
                command_text=command_text
            )
            
            return {
                "success": True,
                "message": f"文件清洗完成",
                "filepath": str(output_path.relative_to(self.base_dir)),
                "original_length": original_length,
                "new_length": len(new_content),
                "original_lines": original_lines,
                "new_lines": len(lines)
            }
            
        except Exception as e:
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            error_msg = str(e)
            self._log_operation(
                operation="clean_file",
                success=False,
                details={"filepath": filepath, "duration_ms": round(duration_ms, 2)},
                error=error_msg,
                command_text=command_text
            )
            return {"success": False, "message": f"清洗失败: {error_msg}"}
    
    async def ai_clean_file(self, filepath: str, instruction: str, **kwargs) -> Dict:
        """使用 AI 智能清洗文件内容，支持重命名"""
        command_text = kwargs.get('command_text')  # 兼容获取
        start_time = datetime.now()
        full_path = self.base_dir / filepath
        
        if not full_path.exists():
            self._log_operation(
                operation="ai_clean_file",
                success=False,
                details={"filepath": filepath},
                error=f"文件不存在: {filepath}",
                command_text=command_text
            )
            return {"success": False, "message": f"文件不存在: {filepath}"}
        
        try:
            # 读取文件内容
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            if not content.strip():
                self._log_operation(
                    operation="ai_clean_file",
                    success=False,
                    details={"filepath": filepath},
                    error="文件内容为空",
                    command_text=command_text
                )
                return {"success": False, "message": "文件内容为空"}
            
            # 限制内容长度
            max_chars = 8000
            original_length = len(content)
            if len(content) > max_chars:
                content = content[:max_chars] + "\n\n...(内容过长，已截取前8000字符)"
            
            # 调用 AI 处理内容
            from ai import client as ai_client
            
            # 1. 先让 AI 解析指令，提取目标文件名
            parse_prompt = f"""从以下指令中提取：
1. 要处理的内容要求
2. 目标文件名（如果用户指定了新文件名，如“命名为temp2.txt”则提取；否则返回None）

用户指令：{instruction}

请输出JSON格式：
{{
    "content_instruction": "要如何处理文件内容",
    "target_filename": "新文件名.txt（如果用户指定了则填，否则填null）"
}}"""

            parse_result = ai_client.chat(
                messages=[{"role": "user", "content": parse_prompt}],
                system_prompt="你是指令解析助手，只输出纯JSON。",
                temperature=0.1,
            )
            
            # 解析JSON
            parse_result = parse_result.strip()
            if parse_result.startswith("```json"):
                parse_result = parse_result[7:]
            if parse_result.startswith("```"):
                parse_result = parse_result[3:]
            if parse_result.endswith("```"):
                parse_result = parse_result[:-3]
            parse_result = parse_result.strip()
            
            parsed = json.loads(parse_result)
            content_instruction = parsed.get("content_instruction", instruction)
            target_filename = parsed.get("target_filename")
            
            # 2. 处理内容
            content_prompt = f"""请根据以下指令处理文本内容：

指令：{content_instruction}

原始文本：
{content}

要求：
1. 只输出处理后的结果，不要添加任何解释
2. 严格按照指令要求处理
3. 如果指令要求删除非中文内容，只保留中文"""

            result_content = ai_client.chat(
                messages=[{"role": "user", "content": content_prompt}],
                system_prompt="你是文档处理助手，严格按照用户指令处理文本，只输出处理结果，不添加任何额外说明。",
                temperature=0.3,
            )
            
            # 3. 确定输出文件路径
            if target_filename:
                output_filename = target_filename
            else:
                stem = full_path.stem
                suffix = full_path.suffix
                output_filename = f"{stem}_ai_cleaned{suffix}"
            
            output_path = full_path.parent / output_filename
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(result_content)
            
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            new_length = len(result_content)
            
            # 记录成功日志
            self._log_operation(
                operation="ai_clean_file",
                success=True,
                details={
                    "filepath": str(output_path.relative_to(self.base_dir)),
                    "original_length": original_length,
                    "new_length": new_length,
                    "instruction": instruction[:200] + "..." if len(instruction) > 200 else instruction,
                    "duration_ms": round(duration_ms, 2)
                },
                command_text=command_text
            )
            
            # 如果有重命名，额外记录
            if target_filename:
                self._log_operation(
                    operation="ai_clean_file_with_rename",
                    success=True,
                    details={
                        "source_file": filepath,
                        "target_file": output_filename,
                        "original_length": original_length,
                        "new_length": new_length
                    },
                    command_text=command_text
                )
            
            return {
                "success": True,
                "message": f"AI智能清洗完成",
                "filepath": str(output_path.relative_to(self.base_dir)),
                "original_length": original_length,
                "new_length": new_length,
                "instruction": instruction,
                "target_filename": target_filename
            }
            
        except Exception as e:
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            error_msg = str(e)
            self._log_operation(
                operation="ai_clean_file",
                success=False,
                details={"filepath": filepath, "duration_ms": round(duration_ms, 2)},
                error=error_msg,
                command_text=command_text
            )
            return {"success": False, "message": f"AI清洗失败: {error_msg}"}
    
    def get_file_preview(self, filepath: str, lines: int = 20) -> Dict:
        """获取文件预览"""
        full_path = self.base_dir / filepath
        if not full_path.exists():
            return {"success": False, "message": "文件不存在"}
        
        try:
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content_lines = f.readlines()[:lines]
            return {
                "success": True,
                "preview": ''.join(content_lines),
                "total_lines": len(open(full_path, 'r', encoding='utf-8', errors='ignore').readlines())
            }
        except Exception as e:
            return {"success": False, "message": str(e)}


# 全局实例
file_cleaner = FileCleaner()