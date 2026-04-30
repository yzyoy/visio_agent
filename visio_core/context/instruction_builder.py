"""
Instruction Builder - skill-backed 动态指令构建器
根据会话状态、任务类型和用户需求动态组合 Agent Skill 指令
"""
from typing import List, Optional, Dict, Any
from .instruction_loader import get_instruction_loader
from .session_context import SessionContext


class InstructionBuilder:
    """动态组合 skill 指令与会话上下文"""
    
    def __init__(self):
        self.loader = get_instruction_loader()
    
    def build_for_session(self,
                         session_context: Optional[SessionContext] = None,
                         library_stats: Optional[Dict[str, Any]] = None,
                         profile: str = 'default') -> List[str]:
        """
        根据会话上下文构建指令
        
        Args:
            session_context: 会话上下文对象
            library_stats: 模板库统计信息
            profile: 指令配置档案 ('minimal', 'default', 'full')
            
        Returns:
            指令列表
        """
        # 基础 skill 指令
        if profile == 'minimal':
            instructions = self.loader.get_minimal_instructions(include_chinese=True)
        elif profile == 'full':
            instructions = self.loader.get_full_instructions(
                library_stats=library_stats
            )
        else:  # default
            instructions = self.loader.get_default_instructions(
                include_chinese=True,
                library_stats=library_stats
            )
        
        # 如果有会话上下文，追加上下文摘要
        if session_context:
            context_summary = self._build_context_summary(session_context)
            if context_summary:
                instructions.append("\n" + "="*80)
                instructions.append("📋 当前会话上下文")
                instructions.append("="*80)
                instructions.append(context_summary)
        
        return instructions
    
    def build_for_task_type(self,
                           task_type: str,
                           library_stats: Optional[Dict[str, Any]] = None,
                           session_context: Optional[SessionContext] = None) -> List[str]:
        """
        根据任务类型构建优化的指令
        
        Args:
            task_type: 任务类型
                - 'translation': 翻译任务
                - 'browse_templates': 浏览模板
                - 'edit_diagram': 编辑图表
                - 'generate_prompt': 生成 Prompt
                - 'general': 通用对话
            library_stats: 模板库统计信息
            session_context: 会话上下文
            
        Returns:
            针对任务优化的指令列表
        """
        # 根据任务类型选择不同的指令组合
        if task_type == 'translation':
            # 翻译任务：最小化指令
            return self.loader.build_instructions(
                profile='minimal',
                include_chinese=False,
                include_workflows=False,
                include_prompt_gen=False
            )
        
        elif task_type == 'browse_templates':
            # 浏览模板：核心 + 模板管理 + Prompt生成
            return self.loader.build_instructions(
                profile='default',
                include_chinese=True,
                include_workflows=False,
                include_prompt_gen=True,
                library_stats=library_stats
            )
        
        elif task_type == 'edit_diagram':
            # 编辑图表：核心 + Visio基础 + 约束 + 工作流
            instructions = self.loader.build_instructions(
                profile='default',
                include_chinese=True,
                include_workflows=True,
                include_prompt_gen=False
            )
            
            # 添加会话上下文（如果有）
            if session_context:
                context_summary = self._build_context_summary(session_context)
                if context_summary:
                    instructions.append("\n" + "="*80)
                    instructions.append("📋 当前工作上下文")
                    instructions.append("="*80)
                    instructions.append(context_summary)
            
            return instructions
        
        elif task_type == 'generate_prompt':
            # 生成 Prompt：核心 + Prompt生成
            return self.loader.build_instructions(
                profile='default',
                include_chinese=True,
                include_workflows=False,
                include_prompt_gen=True,
                library_stats=library_stats
            )
        
        else:  # general
            # 通用对话：默认配置
            return self.loader.build_instructions(
                profile='default',
                include_chinese=True,
                include_workflows=False,
                include_prompt_gen=True,
                library_stats=library_stats
            )
    
    def _build_context_summary(self, session_context: SessionContext) -> str:
        """构建会话上下文摘要"""
        # ⭐ PERFORMANCE OPTIMIZATION: Only inject context if there's meaningful content
        # This avoids wasting tokens on empty context blocks
        has_meaningful_content = (
            session_context.current_file_path or  # Has a loaded file
            len(session_context.operation_history) > 0 or  # Has operation history
            session_context.user_intent or  # Has user intent
            session_context.task_type or  # Has task type
            len(session_context.key_decisions) > 0  # Has key decisions
        )
        
        if not has_meaningful_content:
            return ""  # Return empty string - no context to inject
        
        lines = []
        
        # 当前文件
        if session_context.current_file_path:
            lines.append(f"📂 当前工作文件: {session_context.current_file_path}")
            lines.append(f"   当前页面: {session_context.current_page_index}")
        
        # 用户意图
        if session_context.user_intent:
            lines.append(f"🎯 用户意图: {session_context.user_intent}")
        
        # 任务类型
        if session_context.task_type:
            lines.append(f"📝 任务类型: {session_context.task_type}")
        
        # 最近操作
        recent_ops = session_context.get_recent_operations(5)
        if recent_ops:
            lines.append(f"\n📜 最近操作:")
            for i, op in enumerate(recent_ops, 1):
                lines.append(f"   {i}. {op['description']} ({op['type']})")
        
        # 关键决策
        if session_context.key_decisions:
            lines.append(f"\n🔑 关键决策:")
            for decision in session_context.key_decisions[-3:]:  # 最多显示3个
                lines.append(f"   - {decision['description']}: {decision['choice']}")
        
        # 提示
        if session_context.current_file_path:
            lines.append("\n💡 提示: 用户已经加载了文件，后续操作默认在此文件上进行。")
        
        return '\n'.join(lines) if lines else ""
    
    def build_adaptive_instructions(self,
                                   session_context: Optional[SessionContext] = None,
                                   library_stats: Optional[Dict[str, Any]] = None,
                                   is_first_message: bool = False) -> List[str]:
        """
        自适应构建指令
        
        Args:
            session_context: 会话上下文
            library_stats: 模板库统计
            is_first_message: 是否是会话的第一条消息
            
        Returns:
            自适应优化的指令列表
        """
        # 第一条消息：使用完整指令
        if is_first_message:
            return self.loader.get_default_instructions(
                include_chinese=True,
                library_stats=library_stats
            )
        
        # 后续消息：根据任务类型优化
        if session_context and session_context.task_type:
            return self.build_for_task_type(
                session_context.task_type,
                library_stats=library_stats,
                session_context=session_context
            )
        
        # 默认：标准指令
        return self.build_for_session(
            session_context=session_context,
            library_stats=library_stats,
            profile='default'
        )


# 全局构建器实例
_global_builder: Optional[InstructionBuilder] = None


def get_instruction_builder() -> InstructionBuilder:
    """获取全局指令构建器实例"""
    global _global_builder
    if _global_builder is None:
        _global_builder = InstructionBuilder()
    return _global_builder

