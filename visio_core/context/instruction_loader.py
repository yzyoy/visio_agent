"""
Instruction Loader - 指令加载和组合系统
根据会话状态和任务类型动态加载和组合指令模板
"""
import os
from typing import List, Optional, Dict, Any
from pathlib import Path


class InstructionLoader:
    """动态加载和组合指令模板"""
    
    def __init__(self, templates_dir: Optional[str] = None):
        """
        初始化指令加载器
        
        Args:
            templates_dir: 指令模板目录路径，默认为 visio_core/templates/instructions/
        """
        if templates_dir is None:
            # Default to templates/instructions/ relative to this file
            base_dir = Path(__file__).parent.parent
            templates_dir = base_dir / "templates" / "instructions"
        
        self.templates_dir = Path(templates_dir)
        
        # 可用的模板文件
        self.available_templates = {
            'core': 'core.txt',
            'visio_basics': 'visio_basics.txt',
            'constraints': 'constraints.txt',
            'chinese_mapping': 'chinese_mapping.txt',
            'workflows': 'workflows.txt',
            'prompt_generation': 'prompt_generation.txt',
            'template_evaluation': 'template_evaluation.txt',
            'keyword_extraction': 'keyword_extraction.txt',
        }
        
        # 缓存已加载的模板内容
        self._cache: Dict[str, str] = {}
    
    def load_template(self, template_name: str) -> str:
        """
        加载单个指令模板
        
        Args:
            template_name: 模板名称（如 'core', 'visio_basics'）
            
        Returns:
            模板内容字符串
        """
        # 检查缓存
        if template_name in self._cache:
            return self._cache[template_name]
        
        # 获取模板文件名
        if template_name not in self.available_templates:
            print(f"⚠️ 警告: 未知的模板名称 '{template_name}'")
            return ""
        
        filename = self.available_templates[template_name]
        filepath = self.templates_dir / filename
        
        # 加载模板文件
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 缓存内容
            self._cache[template_name] = content
            return content
        except Exception as e:
            print(f"❌ 加载指令模板失败 '{template_name}': {e}")
            return ""
    
    def build_instructions(self, 
                          profile: str = 'default',
                          include_chinese: bool = True,
                          include_workflows: bool = False,
                          include_prompt_gen: bool = True,
                          library_stats: Optional[Dict[str, Any]] = None,
                          template_list_preview: Optional[str] = None) -> List[str]:
        """
        根据配置动态构建指令列表
        
        Args:
            profile: 指令配置档案
                - 'minimal': 最小化指令（仅核心）
                - 'default': 默认指令（核心 + Visio基础 + 约束）
                - 'full': 完整指令（包含所有模板）
            include_chinese: 是否包含中文指令映射
            include_workflows: 是否包含工作流示例
            include_prompt_gen: 是否包含 Prompt 生成功能说明
            library_stats: 模板库统计信息
            template_list_preview: 模板列表预览（可选，用于显示部分模板）
            
        Returns:
            指令字符串列表
        """
        instructions = []
        
        # 基于 profile 加载核心模板
        if profile == 'minimal':
            # 最小化：仅核心指令
            templates_to_load = ['core']
        elif profile == 'full':
            # 完整：所有模板
            templates_to_load = ['core', 'visio_basics', 'constraints']
        else:  # default
            # 默认：核心 + Visio基础 + 约束
            templates_to_load = ['core', 'visio_basics', 'constraints']
        
        # 加载基础模板
        for template_name in templates_to_load:
            content = self.load_template(template_name)
            if content:
                instructions.append(content)
        
        # 按需加载额外模板
        if include_chinese:
            content = self.load_template('chinese_mapping')
            if content:
                instructions.append(content)
        
        if include_workflows:
            content = self.load_template('workflows')
            if content:
                instructions.append(content)
        
        if include_prompt_gen:
            content = self.load_template('prompt_generation')
            if content:
                # 如果提供了库统计信息，插入到 prompt_generation 中
                if library_stats:
                    stats_text = self._format_library_stats(library_stats)
                    content = content.replace(
                        "🎯 核心职责：",
                        f"{stats_text}\n\n🎯 核心职责："
                    )
                instructions.append(content)
        
        # 添加模板列表预览（如果提供）
        if template_list_preview:
            instructions.append("\n" + "="*80)
            instructions.append("📚 当前可用模板（部分预览）：")
            instructions.append("="*80)
            instructions.append(template_list_preview)
        
        return instructions
    
    def _format_library_stats(self, stats: Dict[str, Any]) -> str:
        """格式化模板库统计信息"""
        lines = [
            "📊 模板库统计：",
            f"  - 总模板数：{stats.get('total_templates', 0)}",
        ]
        
        if 'by_category' in stats and stats['by_category']:
            categories = ', '.join([f"{k}({v})" for k, v in list(stats['by_category'].items())[:5]])
            lines.append(f"  - 分类：{categories}")
        
        if 'by_complexity' in stats and stats['by_complexity']:
            complexity = ', '.join([f"{k}({v})" for k, v in stats['by_complexity'].items()])
            lines.append(f"  - 复杂度：{complexity}")
        
        return '\n'.join(lines)
    
    def get_minimal_instructions(self, include_chinese: bool = True) -> List[str]:
        """获取最小化指令集（仅核心功能）"""
        return self.build_instructions(
            profile='minimal',
            include_chinese=include_chinese,
            include_workflows=False,
            include_prompt_gen=False
        )
    
    def get_default_instructions(self, 
                                 include_chinese: bool = True,
                                 library_stats: Optional[Dict[str, Any]] = None) -> List[str]:
        """获取默认指令集（常用功能）"""
        return self.build_instructions(
            profile='default',
            include_chinese=include_chinese,
            include_workflows=False,
            include_prompt_gen=True,
            library_stats=library_stats
        )
    
    def get_full_instructions(self,
                             library_stats: Optional[Dict[str, Any]] = None,
                             template_list_preview: Optional[str] = None) -> List[str]:
        """获取完整指令集（所有功能）"""
        return self.build_instructions(
            profile='full',
            include_chinese=True,
            include_workflows=True,
            include_prompt_gen=True,
            library_stats=library_stats,
            template_list_preview=template_list_preview
        )
    
    def clear_cache(self):
        """清除模板缓存"""
        self._cache.clear()


# 全局实例（单例模式）
_global_loader: Optional[InstructionLoader] = None


def get_instruction_loader() -> InstructionLoader:
    """获取全局指令加载器实例"""
    global _global_loader
    if _global_loader is None:
        _global_loader = InstructionLoader()
    return _global_loader

