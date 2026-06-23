"""
脚本执行模块
支持运行 Python、Shell、Batch、PowerShell 脚本
"""
import subprocess
import sys
import os
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

class ScriptRunner:
    def __init__(self):
        # 脚本目录
        self.scripts_dir = Path("C:/Users/hp/Desktop/upload/scripts")
        self.scripts_dir.mkdir(parents=True, exist_ok=True)
        print(f"[ScriptRunner] 脚本目录: {self.scripts_dir.absolute()}")
    
    def find_script(self, script_name: str) -> Optional[Path]:
        """查找脚本文件"""
        # 清理脚本名
        script_name = script_name.strip()
        
        print(f"[ScriptRunner] 查找脚本: {script_name}")
        
        # 定义搜索目录
        upload_dir = Path("C:/Users/hp/Desktop/upload")
        search_dirs = [
            self.scripts_dir,
            upload_dir,
            self.scripts_dir.resolve(),
            upload_dir.resolve(),
        ]
        
        # 去重
        unique_dirs = []
        for d in search_dirs:
            if d not in unique_dirs:
                unique_dirs.append(d)
        search_dirs = unique_dirs
        
        print(f"[ScriptRunner] 搜索目录: {search_dirs}")
        
        # 1. 精确匹配
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            target = search_dir / script_name
            if target.exists():
                print(f"[ScriptRunner] 找到: {target}")
                return target
        
        # 2. 去掉扩展名匹配
        name_without_ext = Path(script_name).stem
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for f in search_dir.iterdir():
                if f.is_file() and f.stem == name_without_ext:
                    print(f"[ScriptRunner] 找到（无扩展名匹配）: {f}")
                    return f
        
        # 3. 模糊匹配
        name_lower = script_name.lower()
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            for f in search_dir.iterdir():
                if f.is_file() and name_lower in f.name.lower():
                    print(f"[ScriptRunner] 找到（模糊匹配）: {f}")
                    return f
        
        print(f"[ScriptRunner] 未找到脚本: {script_name}")
        return None
    
    def run_python_script(self, script_path: Path, args: list = None) -> Tuple[str, str]:
        """运行 Python 脚本"""
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            
            cmd = [sys.executable, str(script_path)]
            if args:
                cmd.extend(args)
            
            print(f"[ScriptRunner] 执行: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=60,
                cwd=script_path.parent,
                env=env
            )
            
            stdout = result.stdout.decode('utf-8', errors='replace')
            stderr = result.stderr.decode('utf-8', errors='replace')
            return stdout, stderr
        except subprocess.TimeoutExpired:
            return "", "脚本执行超时（60秒）"
        except Exception as e:
            return "", str(e)
    
    def run_shell_script(self, script_path: Path, args: list = None) -> Tuple[str, str]:
        """运行 Shell/Batch 脚本"""
        try:
            script_path_str = str(script_path)
            
            if sys.platform == "win32":
                if script_path.suffix == '.ps1':
                    cmd = ["powershell", "-ExecutionPolicy", "Bypass", "-File", script_path_str]
                elif script_path.suffix in ['.bat', '.cmd']:
                    cmd = ["cmd", "/c", script_path_str]
                else:
                    # .sh 文件在 Windows 上使用 Git Bash
                    git_bash_paths = [
                        "C:/Program Files/Git/bin/bash.exe",
                        "C:/Program Files (x86)/Git/bin/bash.exe",
                    ]
                    bash_cmd = None
                    for path in git_bash_paths:
                        if Path(path).exists():
                            bash_cmd = path
                            break
                    
                    if bash_cmd:
                        cmd = [bash_cmd, script_path_str]
                    else:
                        # 尝试使用 WSL
                        cmd = ["wsl", "bash", script_path_str]
            else:
                cmd = ["bash", script_path_str]
            
            if args:
                cmd.extend(args)
            
            print(f"[ScriptRunner] 执行: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=60,
                cwd=script_path.parent
            )
            
            stdout = result.stdout.decode('utf-8', errors='replace')
            stderr = result.stderr.decode('utf-8', errors='replace')
            return stdout, stderr
        except subprocess.TimeoutExpired:
            return "", "脚本执行超时（60秒）"
        except FileNotFoundError as e:
            if '.sh' in str(script_path):
                return "", f"未找到 bash 解释器，请安装 Git Bash 或 WSL。错误: {e}"
            return "", str(e)
        except Exception as e:
            return "", str(e)
    
    async def run_script(self, script_name: str, args: str = "") -> Dict:
        """执行脚本的主入口"""
        script_path = self.find_script(script_name)
        
        if not script_path:
            return {
                "success": False,
                "message": f"未找到脚本: {script_name}",
                "scripts_dir": str(self.scripts_dir)
            }
        
        arg_list = args.split() if args else []
        ext = script_path.suffix.lower()
        
        print(f"[ScriptRunner] 运行脚本: {script_path}, 参数: {arg_list}")
        
        if ext == '.py':
            stdout, stderr = self.run_python_script(script_path, arg_list)
        elif ext in ['.sh', '.bat', '.cmd', '.ps1']:
            stdout, stderr = self.run_shell_script(script_path, arg_list)
        else:
            return {
                "success": False,
                "message": f"不支持的脚本类型: {ext}，支持: .py, .sh, .bat, .ps1",
                "scripts_dir": str(self.scripts_dir)
            }
        
        if stderr and "Error" in stderr:
            return {
                "success": False,
                "message": f"脚本执行出错",
                "stdout": stdout,
                "stderr": stderr,
                "scripts_dir": str(self.scripts_dir)
            }
        
        return {
            "success": True,
            "message": f"脚本 {script_path.name} 执行成功",
            "stdout": stdout,
            "stderr": stderr,
            "scripts_dir": str(self.scripts_dir)
        }
    
    def list_scripts(self) -> list:
        """列出所有可用脚本"""
        scripts = []
        upload_dir = Path("C:/Users/hp/Desktop/upload")
        
        for search_dir in [self.scripts_dir, upload_dir]:
            if not search_dir.exists():
                continue
            for f in search_dir.iterdir():
                if f.is_file() and f.suffix in ['.py', '.sh', '.bat', '.cmd', '.ps1']:
                    if not any(s['name'] == f.name for s in scripts):
                        scripts.append({
                            "name": f.name,
                            "type": f.suffix[1:],
                            "size": f.stat().st_size
                        })
        return scripts


# 全局实例
script_runner = ScriptRunner()