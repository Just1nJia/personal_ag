from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import os
import uvicorn

from models import FileCreate, FileUpdate, CommandRequest, CommandResponse
from file_operations import FileOperationManager
from command_parser import CommandParser

app = FastAPI(title="文件管理系统API", description="支持txt和word文件的增删查改")

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化管理器
file_manager = FileOperationManager()
command_parser = CommandParser()

# ========== 基础文件操作API ==========

@app.post("/files/create")
async def create_file(file_create: FileCreate):
    """创建文件"""
    # 确保文件扩展名正确
    if not (file_create.filename.endswith('.txt') or file_create.filename.endswith('.docx')):
        raise HTTPException(status_code=400, detail="文件类型必须是.txt或.docx")
    
    result = await file_manager.create_file(file_create.filename, file_create.content)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    
    return result

@app.get("/files/read/{filename}")
async def read_file(filename: str):
    """读取文件内容"""
    result = await file_manager.read_file(filename)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    
    return result

@app.put("/files/update/{filename}")
async def update_file(filename: str, file_update: FileUpdate):
    """更新文件内容"""
    result = await file_manager.update_file(filename, file_update.content)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    
    return result

@app.delete("/files/delete/{filename}")
async def delete_file(filename: str):
    """删除文件"""
    result = await file_manager.delete_file(filename)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result["message"])
    
    return result

@app.get("/files/list")
async def list_files():
    """列出所有文件"""
    result = await file_manager.list_files()
    return result

@app.get("/files/search")
async def search_files(keyword: str):
    """搜索文件内容"""
    result = await file_manager.search_files(keyword)
    return result

# ========== 智能命令API ==========

@app.post("/command", response_model=CommandResponse)
async def execute_command(command_request: CommandRequest):
    """执行自然语言命令"""
    
    # 解析命令
    parse_result = await command_parser.parse_command(command_request.command)
    
    if not parse_result["success"]:
        raise HTTPException(status_code=400, detail=f"命令解析失败: {parse_result.get('error', '未知错误')}")
    
    parsed = parse_result["command"]
    action = parsed.get("action")
    filename = parsed.get("filename")
    content_description = parsed.get("content_description")
    keyword = parsed.get("keyword")
    need_generate = parsed.get("need_generate", False)
    
    # 如果需要生成内容，调用AI生成
    actual_content = None
    if need_generate and content_description and action in ["create", "update"]:
        # 调用AI生成真实内容
        actual_content = await command_parser.generate_content(content_description)
    elif content_description and not need_generate:
        # 直接使用提供的内容
        actual_content = content_description
    
    # 执行相应的操作
    try:
        if action == "create":
            if not filename:
                raise HTTPException(status_code=400, detail="创建操作需要提供文件名")
            if not actual_content:
                actual_content = ""  # 允许创建空文件
            
            result = await file_manager.create_file(filename, actual_content)
            
        elif action == "read":
            if not filename:
                raise HTTPException(status_code=400, detail="读取操作需要提供文件名")
            result = await file_manager.read_file(filename)
            
        elif action == "update":
            if not filename:
                raise HTTPException(status_code=400, detail="更新操作需要提供文件名")
            if not actual_content:
                raise HTTPException(status_code=400, detail="更新操作需要提供新内容")
            result = await file_manager.update_file(filename, actual_content)
            
        elif action == "delete":
            if not filename:
                raise HTTPException(status_code=400, detail="删除操作需要提供文件名")
            result = await file_manager.delete_file(filename)
            
        elif action == "list":
            result = await file_manager.list_files()
            
        elif action == "search":
            if not keyword:
                raise HTTPException(status_code=400, detail="搜索操作需要提供关键词")
            result = await file_manager.search_files(keyword)
            
        else:
            raise HTTPException(status_code=400, detail=f"不支持的操作类型: {action}")
        
        # 添加额外信息到响应
        response_data = result.get("data")
        if need_generate and actual_content and action in ["create", "update"]:
            if response_data is None:
                response_data = {}
            response_data["generated_content_preview"] = actual_content[:200] + "..." if len(actual_content) > 200 else actual_content
        
        return CommandResponse(
            action=action,
            filename=filename or "",
            success=result["success"],
            message=result["message"],
            data=response_data
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"执行操作失败: {str(e)}")

# ========== 健康检查 ==========

@app.get("/health")
async def health_check():
    return {"status": "healthy", "message": "文件管理系统运行正常"}

# ========== 启动配置 ==========

if __name__ == "__main__":
    # 方式1：直接运行（推荐用于开发调试）
    uvicorn.run(
        "main:app",  # 使用导入字符串格式
        host="localhost",
        port=8000,
        reload=True,  # 开发模式下启用自动重载
        log_level="info"
    )