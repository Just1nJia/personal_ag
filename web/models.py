from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class FileInfo(BaseModel):
    name: str
    type: str  # file or folder
    size: Optional[int] = None
    content: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class FileCreate(BaseModel):
    filename: str
    content: str

class FileUpdate(BaseModel):
    content: str

class RenameRequest(BaseModel):
    old_name: str
    new_name: str

class CopyRequest(BaseModel):
    source: str
    destination: str

class CommandRequest(BaseModel):
    command: str
    filename: Optional[str] = None
    content: Optional[str] = None

class CommandResponse(BaseModel):
    action: str
    name: str
    success: bool
    message: str
    data: Optional[dict] = None