"""
Library Cache - 库文件 LRU 缓存系统
缓存模板库和形状库的加载内容，避免重复读取大文件
"""
import json
import os
from typing import Dict, Any, Optional, Tuple
from collections import OrderedDict
from pathlib import Path
import time


class LRUCache:
    """LRU (Least Recently Used) 缓存实现"""
    
    def __init__(self, capacity: int = 50):
        """
        初始化 LRU 缓存
        
        Args:
            capacity: 最大缓存容量
        """
        self.capacity = capacity
        self.cache: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self.hits = 0
        self.misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存值
        
        Args:
            key: 缓存键
            
        Returns:
            缓存的值，如果不存在返回 None
        """
        if key not in self.cache:
            self.misses += 1
            return None
        
        # 移动到末尾（最近使用）
        value, timestamp = self.cache.pop(key)
        self.cache[key] = (value, time.time())
        self.hits += 1
        return value
    
    def put(self, key: str, value: Any):
        """
        设置缓存值
        
        Args:
            key: 缓存键
            value: 要缓存的值
        """
        # 如果已存在，先删除
        if key in self.cache:
            self.cache.pop(key)
        
        # 如果达到容量上限，删除最旧的项
        elif len(self.cache) >= self.capacity:
            self.cache.popitem(last=False)
        
        # 添加新项
        self.cache[key] = (value, time.time())
    
    def clear(self):
        """清空缓存"""
        self.cache.clear()
        self.hits = 0
        self.misses = 0
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        total_requests = self.hits + self.misses
        hit_rate = self.hits / total_requests if total_requests > 0 else 0.0
        
        return {
            'capacity': self.capacity,
            'size': len(self.cache),
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': round(hit_rate * 100, 2),
            'total_requests': total_requests
        }


class LibraryCache:
    """模板库和形状库的缓存管理器"""
    
    def __init__(self, capacity: int = 10):
        """
        初始化库文件缓存
        
        Args:
            capacity: 缓存容量（最多缓存多少个库文件）
        """
        # 缓存完整的库文件内容
        self._full_cache = LRUCache(capacity=capacity)
        # 缓存精简版库文件内容
        self._lite_cache = LRUCache(capacity=capacity)
        # 缓存单个模板/形状库的详细信息
        self._item_cache = LRUCache(capacity=capacity * 5)
    
    def load_library(self, filepath: str, lite: bool = False) -> Dict[str, Any]:
        """
        加载库文件（带缓存）
        
        Args:
            filepath: 库文件路径
            lite: 是否是精简版
            
        Returns:
            库文件内容字典
        """
        # 选择缓存
        cache = self._lite_cache if lite else self._full_cache
        
        # 生成缓存键
        cache_key = f"{filepath}:{lite}"
        
        # 尝试从缓存获取
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return cached_data
        
        # 缓存未命中，从文件加载
        try:
            if not os.path.exists(filepath):
                print(f"⚠️ 库文件不存在: {filepath}")
                return {}
            
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 存入缓存
            cache.put(cache_key, data)
            
            version = "精简版" if lite else "完整版"
            size_mb = os.path.getsize(filepath) / (1024 * 1024)
            print(f"✓ 已加载并缓存{version}库文件: {Path(filepath).name} ({size_mb:.1f} MB)")
            
            return data
        
        except Exception as e:
            print(f"❌ 加载库文件失败 {filepath}: {e}")
            return {}
    
    def get_item_details(self, library_data: Dict[str, Any], 
                        item_name: str) -> Optional[Dict[str, Any]]:
        """
        获取单个模板/形状库的详细信息（带缓存）
        
        Args:
            library_data: 库文件数据
            item_name: 项目名称（文件名）
            
        Returns:
            项目详细信息
        """
        # 尝试从缓存获取
        cached_item = self._item_cache.get(item_name)
        if cached_item is not None:
            return cached_item
        
        # 从库数据中获取
        if item_name in library_data:
            item_data = library_data[item_name]
            # 存入缓存
            self._item_cache.put(item_name, item_data)
            return item_data
        
        return None
    
    def clear_all(self):
        """清空所有缓存"""
        self._full_cache.clear()
        self._lite_cache.clear()
        self._item_cache.clear()
        print("✓ 已清空所有库文件缓存")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return {
            'full_library_cache': self._full_cache.get_stats(),
            'lite_library_cache': self._lite_cache.get_stats(),
            'item_cache': self._item_cache.get_stats(),
        }
    
    def print_stats(self):
        """打印缓存统计信息"""
        stats = self.get_stats()
        
        print("\n" + "="*60)
        print("📊 库文件缓存统计")
        print("="*60)
        
        for cache_name, cache_stats in stats.items():
            print(f"\n{cache_name}:")
            print(f"  容量: {cache_stats['size']}/{cache_stats['capacity']}")
            print(f"  命中: {cache_stats['hits']} 次")
            print(f"  未命中: {cache_stats['misses']} 次")
            print(f"  命中率: {cache_stats['hit_rate']}%")
        
        print("="*60 + "\n")


# 全局缓存实例（单例模式）
_global_library_cache: Optional[LibraryCache] = None


def get_library_cache(capacity: int = 10) -> LibraryCache:
    """
    获取全局库文件缓存实例
    
    Args:
        capacity: 缓存容量（仅在首次创建时有效）
        
    Returns:
        LibraryCache 实例
    """
    global _global_library_cache
    if _global_library_cache is None:
        _global_library_cache = LibraryCache(capacity=capacity)
    return _global_library_cache


def clear_global_cache():
    """清空全局缓存"""
    global _global_library_cache
    if _global_library_cache is not None:
        _global_library_cache.clear_all()


def print_cache_stats():
    """打印全局缓存统计"""
    global _global_library_cache
    if _global_library_cache is not None:
        _global_library_cache.print_stats()
    else:
        print("⚠️ 缓存尚未初始化")

