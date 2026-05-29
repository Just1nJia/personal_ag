"""
文件清洗工具
支持删除空行、特殊字符、重复行、格式规范化等
"""
import re
import os
from pathlib import Path
from typing import Dict, List, Optional

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
    
    def clean_file(self, filepath: str, rules: Dict) -> Dict:
        """
        清洗文件
        rules 示例:
        {
            "remove_empty_lines": True,      # 删除空行
            "remove_special_chars": True,    # 删除特殊字符（保留中文、英文、数字、常用标点）
            "remove_duplicate_lines": True,  # 删除重复行
            "strip_lines": True,             # 去除每行首尾空白
            "convert_to_utf8": True,         # 转换为UTF-8
            "custom_replace": [              # 自定义替换
                {"from": "旧文本", "to": "新文本"}
            ]
        }
        """
        full_path = self.base_dir / filepath
        
        if not full_path.exists():
            return {"success": False, "message": f"文件不存在: {filepath}"}
        
        try:
            # 读取文件
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            original_length = len(content)
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
                # 保留：中文、英文、数字、常用标点（。，！？；：""''、（）【】《》）
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
            
            # 6. 转换为 UTF-8（如果需要）
            if rules.get("convert_to_utf8", False):
                # 已经是 UTF-8，不需要额外处理
                pass
            
            # 保存清洗后的内容（覆盖原文件或另存为新文件）
            output_path = full_path
            if rules.get("save_as_new", False):
                stem = full_path.stem
                suffix = full_path.suffix
                output_path = full_path.parent / f"{stem}_cleaned{suffix}"
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            return {
                "success": True,
                "message": f"文件清洗完成",
                "filepath": str(output_path.relative_to(self.base_dir)),
                "original_length": original_length,
                "new_length": len(new_content),
                "original_lines": len(content.splitlines()),
                "new_lines": len(lines)
            }
            
        except Exception as e:
            return {"success": False, "message": f"清洗失败: {str(e)}"}
    
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