"""
Session context persistence for Visio agent.

Stores session metadata, operation history, and intent tracking
in the dialog directory for context-aware conversations.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
from collections import deque


class SessionContext:
    """增强的会话上下文，包含操作历史和意图跟踪"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.current_file_path: Optional[str] = None
        self.current_page_index: int = 0
        self.operation_history: deque = deque(maxlen=20)  # 最多保留20条操作
        self.user_intent: Optional[str] = None  # 用户当前意图
        self.task_type: Optional[str] = None  # 当前任务类型
        self.key_decisions: List[Dict[str, Any]] = []  # 关键决策点
        self.created_at: str = datetime.now().isoformat()
        self.updated_at: str = datetime.now().isoformat()
    
    def add_operation(self, operation_type: str, description: str, 
                     details: Optional[Dict[str, Any]] = None):
        """添加操作到历史"""
        operation = {
            'type': operation_type,
            'description': description,
            'timestamp': datetime.now().isoformat(),
            'details': details or {}
        }
        self.operation_history.append(operation)
        self.updated_at = datetime.now().isoformat()
    
    def add_decision(self, decision_type: str, description: str,
                    choice: Any):
        """记录关键决策"""
        decision = {
            'type': decision_type,
            'description': description,
            'choice': choice,
            'timestamp': datetime.now().isoformat()
        }
        self.key_decisions.append(decision)
        # 限制决策数量
        if len(self.key_decisions) > 10:
            self.key_decisions = self.key_decisions[-10:]
    
    def set_intent(self, intent: str):
        """设置用户意图"""
        self.user_intent = intent
        self.updated_at = datetime.now().isoformat()
    
    def set_task_type(self, task_type: str):
        """设置任务类型"""
        self.task_type = task_type
        self.updated_at = datetime.now().isoformat()
    
    def get_recent_operations(self, count: int = 5) -> List[Dict[str, Any]]:
        """获取最近的操作"""
        return list(self.operation_history)[-count:]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'session_id': self.session_id,
            'current_file_path': self.current_file_path,
            'current_page_index': self.current_page_index,
            'operation_history': list(self.operation_history),
            'user_intent': self.user_intent,
            'task_type': self.task_type,
            'key_decisions': self.key_decisions,
            'created_at': self.created_at,
            'updated_at': self.updated_at
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SessionContext':
        """从字典创建"""
        session_id = data.get('session_id', 'default')
        ctx = cls(session_id)
        ctx.current_file_path = data.get('current_file_path')
        ctx.current_page_index = data.get('current_page_index', 0)
        ctx.user_intent = data.get('user_intent')
        ctx.task_type = data.get('task_type')
        ctx.key_decisions = data.get('key_decisions', [])
        ctx.created_at = data.get('created_at', datetime.now().isoformat())
        ctx.updated_at = data.get('updated_at', datetime.now().isoformat())
        
        # 恢复操作历史
        history = data.get('operation_history', [])
        ctx.operation_history = deque(history, maxlen=20)
        
        return ctx
    
    def get_summary(self) -> str:
        """生成会话摘要"""
        lines = []
        
        if self.current_file_path:
            lines.append(f"当前文件: {self.current_file_path}")
        
        if self.user_intent:
            lines.append(f"用户意图: {self.user_intent}")
        
        if self.task_type:
            lines.append(f"任务类型: {self.task_type}")
        
        recent_ops = self.get_recent_operations(3)
        if recent_ops:
            lines.append(f"最近操作: {', '.join([op['description'] for op in recent_ops])}")
        
        if self.key_decisions:
            last_decision = self.key_decisions[-1]
            lines.append(f"最近决策: {last_decision['description']}")
        
        return '; '.join(lines) if lines else "无上下文"


class DialogContextStore:
    """Enhanced JSON-backed context store with rich session context."""

    def __init__(self, dialog_dir: str = ".state/dialog"):
        self.dialog_dir = Path(dialog_dir)
        self.dialog_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.dialog_dir / f"{session_id}.json"

    def load(self, session_id: str) -> Dict[str, Any]:
        """加载会话上下文（兼容旧格式）"""
        path = self._path(session_id)
        if not path.exists() or path.stat().st_size == 0:
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            # Corrupt or partially written file; ignore to keep workflow resilient
            return {}
    
    def load_context(self, session_id: str) -> SessionContext:
        """加载增强的会话上下文对象"""
        data = self.load(session_id)
        if data:
            return SessionContext.from_dict(data)
        else:
            return SessionContext(session_id)

    def save(self, session_id: str, ctx: Dict[str, Any]):
        """保存会话上下文（兼容旧格式）"""
        payload = dict(ctx or {})
        payload.setdefault("updated_at", datetime.now().isoformat())
        path = self._path(session_id)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    
    def save_context(self, ctx: SessionContext):
        """保存增强的会话上下文对象"""
        self.save(ctx.session_id, ctx.to_dict())

    def delete(self, session_id: str):
        path = self._path(session_id)
        try:
            path.unlink(missing_ok=True)
        except Exception:
            # Ignore delete errors
            pass



class DisabledDialogContextStore:
    """Context store that disables writes while allowing reads/deletes.

    Useful when you want to turn off automatic recording to the dialog directory
    without breaking code paths that load existing context.
    """

    def __init__(self, dialog_dir: str = ".state/dialog"):
        self._delegate = DialogContextStore(dialog_dir)

    def load(self, session_id: str) -> Dict[str, Any]:
        return self._delegate.load(session_id)

    def load_context(self, session_id: str) -> SessionContext:
        return self._delegate.load_context(session_id)

    def save(self, session_id: str, ctx: Dict[str, Any]):
        # No-op: disable persistence
        return

    def save_context(self, ctx: SessionContext):
        # No-op: disable persistence
        return

    def delete(self, session_id: str):
        # Allow deletes so callers like reset_session can still clean up
        self._delegate.delete(session_id)

