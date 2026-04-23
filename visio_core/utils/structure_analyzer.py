"""
Structure Analyzer - 分析Visio图表的结构信息
提取连接关系图谱、拓扑模式和布局模式
"""
from typing import Dict, List, Any, Set, Tuple, Optional
from collections import defaultdict, deque
import math


class StructureAnalyzer:
    """分析Visio图表的结构信息"""
    
    @staticmethod
    def analyze_structure(diagram) -> Dict[str, Any]:
        """
        分析图表的完整结构信息
        
        Args:
            diagram: DiagramBuilder实例
            
        Returns:
            包含连接图谱、拓扑模式和布局模式的字典
        """
        if not diagram or not diagram.current_page:
            return StructureAnalyzer._empty_structure()
        
        # 提取连接关系图谱
        connection_graph = StructureAnalyzer.extract_connection_graph(diagram)
        
        # 分析拓扑模式
        topology_pattern = StructureAnalyzer.analyze_topology_pattern(connection_graph)
        
        # 分析布局模式
        layout_pattern = StructureAnalyzer.analyze_layout_pattern(diagram, connection_graph)
        
        return {
            'connection_graph': connection_graph,
            'topology_pattern': topology_pattern,
            'layout_pattern': layout_pattern,
        }
    
    @staticmethod
    def extract_connection_graph(diagram) -> Dict[str, Any]:
        """
        提取连接关系图谱（直接处理连接器）
        
        Args:
            diagram: DiagramBuilder实例
            
        Returns:
            连接图谱字典，包含节点、边和度数信息
        """
        if not diagram.current_page:
            return {'node_count': 0, 'edge_count': 0, 'edges': [], 'node_degrees': {}}
        
        nodes = set()
        edges = []
        node_degrees = defaultdict(lambda: {'in': 0, 'out': 0})
        connector_types = defaultdict(int)
        
        # 首先收集所有非连接器形状作为潜在节点
        all_shapes = {}
        for shape in diagram.current_page.child_shapes:
            if not diagram._is_connector(shape):
                shape_id = str(shape.ID) if hasattr(shape, 'ID') else None
                if shape_id:
                    all_shapes[shape_id] = shape
                    nodes.add(shape_id)
        
        # 直接遍历连接器，提取连接关系
        for shape in diagram.current_page.child_shapes:
            if not diagram._is_connector(shape):
                continue
            
            connector_id = str(shape.ID) if hasattr(shape, 'ID') else None
            if not connector_id:
                continue
            
            # 获取连接器类型
            connector_type = 'Connector'
            if hasattr(shape, 'master') and shape.master:
                connector_type = getattr(shape.master, 'name', 'Connector')
            
            # 方法1: 尝试从connects属性提取（如果有正式连接数据）
            from_shape_id = None
            to_shape_id = None
            
            if hasattr(shape, 'connects') and shape.connects:
                # 遍历所有连接，收集 from_sheet 和 to_sheet
                for conn in shape.connects:
                    try:
                        from_sheet = getattr(conn, 'from_sheet', None)
                        to_sheet = getattr(conn, 'to_sheet', None)
                        
                        # from_sheet 和 to_sheet 可能都指向连接的形状
                        # 我们需要识别哪个是源，哪个是目标
                        if from_sheet and hasattr(from_sheet, 'ID'):
                            potential_id = str(from_sheet.ID)
                            if potential_id in all_shapes:
                                # 使用 from_cell 来判断这是连接器的哪一端
                                from_cell = getattr(conn, 'from_cell', None)
                                if from_cell:
                                    cell_name = str(from_cell.name) if hasattr(from_cell, 'name') else str(from_cell)
                                    if 'BeginX' in cell_name or 'Begin' in cell_name:
                                        from_shape_id = potential_id
                                    elif 'EndX' in cell_name or 'End' in cell_name:
                                        to_shape_id = potential_id
                        
                        if to_sheet and hasattr(to_sheet, 'ID'):
                            potential_id = str(to_sheet.ID)
                            if potential_id in all_shapes:
                                # to_sheet 通常也需要检查 from_cell
                                from_cell = getattr(conn, 'from_cell', None)
                                if from_cell:
                                    cell_name = str(from_cell.name) if hasattr(from_cell, 'name') else str(from_cell)
                                    if 'BeginX' in cell_name or 'Begin' in cell_name:
                                        from_shape_id = potential_id
                                    elif 'EndX' in cell_name or 'End' in cell_name:
                                        to_shape_id = potential_id
                    except Exception:
                        continue
            
            # 方法2: 如果connects为空，尝试基于空间位置推断连接
            # 某些Visio文件中连接器没有正式连接数据，只是视觉上的线条
            if not from_shape_id or not to_shape_id:
                try:
                    # 获取连接器的起点和终点坐标
                    begin_x = getattr(shape, 'begin_x', None)
                    begin_y = getattr(shape, 'begin_y', None)
                    end_x = getattr(shape, 'end_x', None)
                    end_y = getattr(shape, 'end_y', None)
                    
                    if all(v is not None for v in [begin_x, begin_y, end_x, end_y]):
                        # 在起点和终点附近查找形状（容差：0.2英寸）
                        tolerance = 0.2
                        
                        for shape_id, target_shape in all_shapes.items():
                            try:
                                # 获取形状的位置（PinX, PinY是形状中心点）
                                target_x = float(target_shape.cell_value('PinX')) if hasattr(target_shape, 'cell_value') else None
                                target_y = float(target_shape.cell_value('PinY')) if hasattr(target_shape, 'cell_value') else None
                                
                                if target_x is None or target_y is None:
                                    continue
                                
                                # 获取形状的宽度和高度以计算边界
                                target_w = float(target_shape.cell_value('Width')) if hasattr(target_shape, 'cell_value') else 0
                                target_h = float(target_shape.cell_value('Height')) if hasattr(target_shape, 'cell_value') else 0
                                
                                # 检查连接器起点是否在该形状附近
                                if not from_shape_id:
                                    if (abs(begin_x - target_x) <= target_w/2 + tolerance and 
                                        abs(begin_y - target_y) <= target_h/2 + tolerance):
                                        from_shape_id = shape_id
                                
                                # 检查连接器终点是否在该形状附近
                                if not to_shape_id:
                                    if (abs(end_x - target_x) <= target_w/2 + tolerance and 
                                        abs(end_y - target_y) <= target_h/2 + tolerance):
                                        to_shape_id = shape_id
                                
                                # 如果两端都找到了，可以提前退出
                                if from_shape_id and to_shape_id:
                                    break
                            except Exception:
                                continue
                except Exception:
                    pass
            
            # 如果找到了完整的连接（from -> to）
            if from_shape_id and to_shape_id and from_shape_id != to_shape_id:
                if from_shape_id in all_shapes and to_shape_id in all_shapes:
                    edges.append({
                        'from': from_shape_id,
                        'to': to_shape_id,
                        'connector_id': connector_id,
                        'connector_type': connector_type
                    })
                    node_degrees[from_shape_id]['out'] += 1
                    node_degrees[to_shape_id]['in'] += 1
                    connector_types[connector_type] += 1
        
        return {
            'node_count': len(nodes),
            'edge_count': len(edges),
            'edges': edges[:100],  # Limit to first 100 edges to avoid bloat
            'node_degrees': dict(node_degrees),
            'connector_types': dict(connector_types),
        }
    
    @staticmethod
    def _find_connector_target(diagram, connector_id: str, source_id: str) -> Optional[str]:
        """查找连接器的目标形状ID"""
        connector = diagram.get_shape_by_id(connector_id)
        if not connector or not hasattr(connector, 'connects'):
            return None
        
        for conn in connector.connects:
            from_sheet = getattr(conn, 'from_sheet', None)
            to_sheet = getattr(conn, 'to_sheet', None)
            
            # 如果source是from，返回to
            if from_sheet and str(from_sheet.ID) == source_id and to_sheet:
                return str(to_sheet.ID)
        
        return None
    
    @staticmethod
    def analyze_topology_pattern(connection_graph: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析拓扑模式
        
        Args:
            connection_graph: 连接图谱
            
        Returns:
            拓扑模式分析结果
        """
        node_count = connection_graph['node_count']
        edge_count = connection_graph['edge_count']
        edges = connection_graph['edges']
        node_degrees = connection_graph['node_degrees']
        
        if node_count == 0:
            return {
                'pattern_type': 'empty',
                'has_cycles': False,
                'max_depth': 0,
                'branching_factor': 0,
                'description': '空图表'
            }
        
        if edge_count == 0:
            return {
                'pattern_type': 'isolated_nodes',
                'has_cycles': False,
                'max_depth': 0,
                'branching_factor': 0,
                'description': f'{node_count}个独立节点，无连接'
            }
        
        # 检测是否有环
        has_cycles = StructureAnalyzer._detect_cycles(edges)
        
        # 计算分支因子（平均出度，排除叶子节点）
        out_degrees = [deg['out'] for deg in node_degrees.values() if deg['out'] > 0]
        avg_branching = sum(out_degrees) / len(out_degrees) if out_degrees else 0
        
        # 计算最大深度（从根节点）
        max_depth = StructureAnalyzer._calculate_max_depth(edges, node_degrees)
        
        # 识别模式类型
        pattern_type = StructureAnalyzer._identify_topology_pattern(
            node_count, edge_count, node_degrees, has_cycles, avg_branching
        )
        
        # 生成描述
        description = StructureAnalyzer._generate_topology_description(
            pattern_type, node_count, edge_count, max_depth, avg_branching, has_cycles
        )
        
        return {
            'pattern_type': pattern_type,
            'has_cycles': has_cycles,
            'max_depth': max_depth,
            'branching_factor': round(avg_branching, 2),
            'description': description
        }
    
    @staticmethod
    def _detect_cycles(edges: List[Dict[str, str]]) -> bool:
        """使用DFS检测是否有环"""
        if not edges:
            return False
        
        # 构建邻接表
        graph = defaultdict(list)
        for edge in edges:
            graph[edge['from']].append(edge['to'])
        
        visited = set()
        rec_stack = set()
        
        def dfs(node):
            visited.add(node)
            rec_stack.add(node)
            
            for neighbor in graph[node]:
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True
            
            rec_stack.remove(node)
            return False
        
        # 从每个未访问的节点开始DFS
        for node in list(graph.keys()):
            if node not in visited:
                if dfs(node):
                    return True
        
        return False
    
    @staticmethod
    def _calculate_max_depth(edges: List[Dict[str, str]], 
                            node_degrees: Dict[str, Dict[str, int]]) -> int:
        """计算图的最大深度（从根节点开始的最长路径）"""
        if not edges:
            return 0
        
        # 找到所有根节点（入度为0）
        roots = [node for node, deg in node_degrees.items() if deg['in'] == 0]
        
        if not roots:
            # 如果没有根节点（可能有环），返回节点数作为上界
            return len(node_degrees)
        
        # 构建邻接表
        graph = defaultdict(list)
        for edge in edges:
            graph[edge['from']].append(edge['to'])
        
        # BFS计算深度
        max_depth = 0
        for root in roots:
            queue = deque([(root, 1)])
            visited = set([root])
            
            while queue:
                node, depth = queue.popleft()
                max_depth = max(max_depth, depth)
                
                for neighbor in graph[node]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append((neighbor, depth + 1))
        
        return max_depth
    
    @staticmethod
    def _identify_topology_pattern(node_count: int, edge_count: int,
                                   node_degrees: Dict[str, Dict[str, int]],
                                   has_cycles: bool, avg_branching: float) -> str:
        """识别拓扑模式类型"""
        
        # 线性链：每个节点最多一个入边和一个出边
        if all(deg['in'] <= 1 and deg['out'] <= 1 for deg in node_degrees.values()):
            if has_cycles:
                return 'circular_chain'
            else:
                return 'linear_chain'
        
        # 星型：一个中心节点连接到多个叶子节点
        high_degree_nodes = [
            node for node, deg in node_degrees.items() 
            if deg['in'] + deg['out'] >= node_count * 0.5
        ]
        if len(high_degree_nodes) == 1:
            return 'star'
        
        # 树状：无环且分支明显
        if not has_cycles and avg_branching > 1.3:
            return 'hierarchical_tree'
        
        # 网状：有环或高度互联
        if has_cycles or edge_count > node_count * 1.5:
            return 'network'
        
        # 混合型
        return 'hybrid'
    
    @staticmethod
    def _generate_topology_description(pattern_type: str, node_count: int,
                                       edge_count: int, max_depth: int,
                                       avg_branching: float, has_cycles: bool) -> str:
        """生成拓扑模式的中文描述"""
        pattern_names = {
            'linear_chain': '线性链式',
            'circular_chain': '环形链式',
            'hierarchical_tree': '层级树状',
            'star': '星型',
            'network': '网状',
            'hybrid': '混合型',
            'isolated_nodes': '孤立节点',
            'empty': '空图表'
        }
        
        name = pattern_names.get(pattern_type, pattern_type)
        
        parts = [f"{name}结构"]
        parts.append(f"{node_count}个节点")
        parts.append(f"{edge_count}个连接")
        
        if max_depth > 0:
            parts.append(f"最大深度{max_depth}")
        
        if avg_branching > 1:
            parts.append(f"平均分支{avg_branching:.1f}")
        
        if has_cycles:
            parts.append("包含循环")
        
        return "，".join(parts)
    
    @staticmethod
    def analyze_layout_pattern(diagram, connection_graph: Dict[str, Any]) -> Dict[str, Any]:
        """
        分析布局模式
        
        Args:
            diagram: DiagramBuilder实例
            connection_graph: 连接图谱
            
        Returns:
            布局模式分析结果
        """
        if not diagram.current_page:
            return {
                'pattern_type': 'empty',
                'primary_direction': 'none',
                'alignment': 'none',
                'has_groups': False,
                'group_count': 0,
                'description': '空布局'
            }
        
        # 收集所有非连接器形状的位置信息
        positions = []
        groups = []
        
        for shape in diagram.current_page.child_shapes:
            if diagram._is_connector(shape):
                continue
            
            # 检查是否是分组
            is_group = hasattr(shape, 'child_shapes') and shape.child_shapes and len(shape.child_shapes) > 0
            if is_group:
                groups.append(shape)
            
            # 获取位置
            try:
                x = float(shape.cell_value('PinX') if hasattr(shape, 'cell_value') else getattr(shape, 'x', 0) or 0)
                y = float(shape.cell_value('PinY') if hasattr(shape, 'cell_value') else getattr(shape, 'y', 0) or 0)
                shape_id = str(shape.ID) if hasattr(shape, 'ID') else None
                
                if shape_id:
                    positions.append({
                        'id': shape_id,
                        'x': x,
                        'y': y,
                        'is_group': is_group
                    })
            except Exception:
                continue
        
        if not positions:
            return {
                'pattern_type': 'empty',
                'primary_direction': 'none',
                'alignment': 'none',
                'has_groups': False,
                'group_count': 0,
                'description': '空布局'
            }
        
        # 分析主要方向
        primary_direction = StructureAnalyzer._detect_primary_direction(
            positions, connection_graph
        )
        
        # 检测对齐方式
        alignment = StructureAnalyzer._detect_alignment(positions)
        
        # 识别布局模式
        pattern_type = StructureAnalyzer._identify_layout_pattern(
            positions, primary_direction, alignment, len(groups)
        )
        
        # 生成描述
        description = StructureAnalyzer._generate_layout_description(
            pattern_type, primary_direction, alignment, len(groups)
        )
        
        return {
            'pattern_type': pattern_type,
            'primary_direction': primary_direction,
            'alignment': alignment,
            'has_groups': len(groups) > 0,
            'group_count': len(groups),
            'description': description
        }
    
    @staticmethod
    def _detect_primary_direction(positions: List[Dict], 
                                  connection_graph: Dict[str, Any]) -> str:
        """检测主要流向（基于连接关系和位置）"""
        edges = connection_graph.get('edges', [])
        
        if not edges:
            # 没有连接，基于位置分布判断
            return StructureAnalyzer._detect_direction_from_positions(positions)
        
        # 基于连接关系判断方向
        vertical_score = 0
        horizontal_score = 0
        
        pos_map = {p['id']: p for p in positions}
        
        for edge in edges:
            from_pos = pos_map.get(edge['from'])
            to_pos = pos_map.get(edge['to'])
            
            if not from_pos or not to_pos:
                continue
            
            dx = abs(to_pos['x'] - from_pos['x'])
            dy = abs(to_pos['y'] - from_pos['y'])
            
            if dy > dx:
                vertical_score += 1
                # 判断上下方向
                if to_pos['y'] < from_pos['y']:
                    vertical_score += 0.5  # 向下流动（Visio Y轴向下）
            else:
                horizontal_score += 1
        
        if vertical_score > horizontal_score * 1.5:
            return 'top_to_bottom'
        elif horizontal_score > vertical_score * 1.5:
            return 'left_to_right'
        else:
            return 'mixed'
    
    @staticmethod
    def _detect_direction_from_positions(positions: List[Dict]) -> str:
        """从位置分布检测方向"""
        if len(positions) < 2:
            return 'none'
        
        # 计算位置的标准差
        x_coords = [p['x'] for p in positions]
        y_coords = [p['y'] for p in positions]
        
        x_range = max(x_coords) - min(x_coords)
        y_range = max(y_coords) - min(y_coords)
        
        if y_range > x_range * 1.5:
            return 'vertical'
        elif x_range > y_range * 1.5:
            return 'horizontal'
        else:
            return 'mixed'
    
    @staticmethod
    def _detect_alignment(positions: List[Dict]) -> str:
        """检测对齐方式"""
        if len(positions) < 2:
            return 'none'
        
        x_coords = [p['x'] for p in positions]
        y_coords = [p['y'] for p in positions]
        
        # 检查是否有多个形状在相同的x或y坐标上
        x_alignment_count = 0
        y_alignment_count = 0
        
        tolerance = 0.1  # 允许0.1英寸的误差
        
        for i, pos in enumerate(positions):
            x_aligned = sum(1 for p in positions if abs(p['x'] - pos['x']) < tolerance)
            y_aligned = sum(1 for p in positions if abs(p['y'] - pos['y']) < tolerance)
            
            if x_aligned > 1:
                x_alignment_count += 1
            if y_aligned > 1:
                y_alignment_count += 1
        
        if x_alignment_count > len(positions) * 0.6:
            return 'vertical_aligned'
        elif y_alignment_count > len(positions) * 0.6:
            return 'horizontal_aligned'
        else:
            return 'mixed'
    
    @staticmethod
    def _identify_layout_pattern(positions: List[Dict], primary_direction: str,
                                alignment: str, group_count: int) -> str:
        """识别布局模式类型"""
        
        # 垂直流程
        if primary_direction in ['top_to_bottom', 'vertical'] and 'vertical' in alignment:
            return 'vertical_flow'
        
        # 水平流程
        if primary_direction in ['left_to_right', 'horizontal'] and 'horizontal' in alignment:
            return 'horizontal_flow'
        
        # 分层架构
        if group_count >= 2:
            return 'layered_architecture'
        
        # 网格布局
        if 'aligned' in alignment and len(positions) >= 9:
            return 'grid_layout'
        
        # 矩阵布局
        if primary_direction == 'mixed' and len(positions) >= 6:
            return 'matrix_layout'
        
        # 自由布局
        return 'free_layout'
    
    @staticmethod
    def _generate_layout_description(pattern_type: str, primary_direction: str,
                                     alignment: str, group_count: int) -> str:
        """生成布局模式的中文描述"""
        pattern_names = {
            'vertical_flow': '垂直流程',
            'horizontal_flow': '水平流程',
            'layered_architecture': '分层架构',
            'grid_layout': '网格布局',
            'matrix_layout': '矩阵布局',
            'free_layout': '自由布局',
            'empty': '空布局'
        }
        
        direction_names = {
            'top_to_bottom': '从上到下',
            'left_to_right': '从左到右',
            'vertical': '垂直方向',
            'horizontal': '水平方向',
            'mixed': '混合方向',
            'none': '无方向'
        }
        
        alignment_names = {
            'vertical_aligned': '垂直对齐',
            'horizontal_aligned': '水平对齐',
            'mixed': '混合对齐',
            'none': '无对齐'
        }
        
        parts = [pattern_names.get(pattern_type, pattern_type)]
        
        if primary_direction != 'none':
            parts.append(direction_names.get(primary_direction, primary_direction))
        
        if alignment != 'none':
            parts.append(alignment_names.get(alignment, alignment))
        
        if group_count > 0:
            parts.append(f"包含{group_count}个分组")
        
        return "，".join(parts)
    
    @staticmethod
    def _empty_structure() -> Dict[str, Any]:
        """返回空结构"""
        return {
            'connection_graph': {
                'node_count': 0,
                'edge_count': 0,
                'edges': [],
                'node_degrees': {},
            },
            'topology_pattern': {
                'pattern_type': 'empty',
                'has_cycles': False,
                'max_depth': 0,
                'branching_factor': 0,
                'description': '空图表'
            },
            'layout_pattern': {
                'pattern_type': 'empty',
                'primary_direction': 'none',
                'alignment': 'none',
                'has_groups': False,
                'group_count': 0,
                'description': '空布局'
            }
        }

