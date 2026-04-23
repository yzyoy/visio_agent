"""
Template scanner utility for analyzing Visio diagrams
Extracts shape information, connectors, and metadata from .vsdx files
"""
import os
from typing import Dict, List, Any
from datetime import datetime
from ..utils.diagram_builder import DiagramBuilder
from ..utils.layout_config import normalize_shape_type


class TemplateScanner:
    """Scans Visio templates and extracts structural information"""
    
    @staticmethod
    def scan_template(vsdx_path: str) -> Dict[str, Any]:
        """
        Scan a .vsdx template file and extract information
        
        Args:
            vsdx_path: Path to the .vsdx file
            
        Returns:
            Dictionary with template metadata and structure
        """
        try:
            # Load the diagram
            diagram = DiagramBuilder.load_from_file(vsdx_path)
            
            if not diagram.visio_file or not diagram.visio_file.pages:
                return {
                    'filename': os.path.basename(vsdx_path),
                    'error': 'No pages found in file',
                    'scan_date': datetime.now().isoformat(),
                }
            
            # Get all pages
            pages_info = []
            pages_detail = []  # New detailed structure
            total_shapes = {}
            total_connectors = 0
            all_shape_texts = []
            
            for page_idx in range(len(diagram.visio_file.pages)):
                page = diagram.visio_file.pages[page_idx]
                diagram.current_page = page
                
                # Get shapes on this page (old format for backward compatibility)
                shapes = []
                connectors = []
                
                # New detailed page structure (structure-focused, no text bloat)
                page_detail = {
                    'name': page.name if hasattr(page, 'name') else f'Page-{page_idx}',
                    'groups': [],
                    'ungrouped_shapes': {
                        'shapes': {},
                        'total': 0
                    }
                }
                
                # Iterate through child_shapes (the actual shapes on the page)
                if hasattr(page, 'child_shapes'):
                    for shape in page.child_shapes:
                        # Check if shape is a group
                        is_group = TemplateScanner._is_group(shape)
                        
                        if is_group:
                            # Process group
                            group_info = TemplateScanner._process_group(shape, diagram)
                            if group_info:
                                page_detail['groups'].append(group_info)
                                
                                # Update totals for backward compatibility
                                for shape_type, count in group_info['shapes'].items():
                                    total_shapes[shape_type] = total_shapes.get(shape_type, 0) + count
                                
                                # Add group title to texts (keep for metadata generation)
                                if group_info['title']:
                                    all_shape_texts.append(group_info['title'])
                        else:
                            # Process individual shape
                            shape_text = shape.text.strip() if hasattr(shape, 'text') and shape.text else ''
                            shape_id = shape.ID if hasattr(shape, 'ID') else 'unknown'
                            shape_type = TemplateScanner._infer_shape_type(shape)
                            
                            # Use robust connector detection from DiagramBuilder
                            if hasattr(diagram, '_is_connector') and diagram._is_connector(shape):
                                total_connectors += 1
                            else:
                                # Skip shapes with Unknown type (no useful type information)
                                if shape_type != 'Unknown':
                                    total_shapes[shape_type] = total_shapes.get(shape_type, 0) + 1
                                    
                                    # Add to detailed ungrouped shapes (count only, no text)
                                    page_detail['ungrouped_shapes']['shapes'][shape_type] = \
                                        page_detail['ungrouped_shapes']['shapes'].get(shape_type, 0) + 1
                                    page_detail['ungrouped_shapes']['total'] += 1
                                    
                                    # Collect text for metadata generation (sample only)
                                    if shape_text and len(all_shape_texts) < 30:
                                        all_shape_texts.append(shape_text)
                
                # Old format for backward compatibility (minimal data)
                pages_info.append({
                    'name': page.name if hasattr(page, 'name') else f'Page-{page_idx}',
                    'shape_count': sum(total_shapes.values()),
                    'connector_count': total_connectors,
                })
                
                pages_detail.append(page_detail)
            
            # Calculate complexity
            complexity = TemplateScanner._calculate_complexity(
                len(all_shape_texts), total_connectors
            )
            
            # Extract structure information (connection graph, topology, layout)
            try:
                from .structure_analyzer import StructureAnalyzer
                structure_info = StructureAnalyzer.analyze_structure(diagram)
                connection_graph = structure_info.get('connection_graph', {})
                topology_pattern = structure_info.get('topology_pattern', {})
                layout_pattern = structure_info.get('layout_pattern', {})
            except Exception as e:
                print(f"  Warning: Structure analysis failed: {e}")
                # Provide empty structure if analysis fails
                connection_graph = {'node_count': 0, 'edge_count': 0, 'edges': [], 'node_degrees': {}}
                topology_pattern = {'pattern_type': 'unknown', 'description': 'Structure analysis unavailable'}
                layout_pattern = {'pattern_type': 'unknown', 'description': 'Layout analysis unavailable'}
            
            return {
                'filename': os.path.basename(vsdx_path),
                'scan_date': datetime.now().isoformat(),
                # Old format for backward compatibility
                'pages': pages_info,
                'total_pages': len(pages_info),
                'total_shapes': total_shapes,
                'total_connectors': total_connectors,
                'sample_texts': all_shape_texts[:30],  # First 30 texts for metadata generation
                'complexity': complexity,
                'has_multiple_pages': len(pages_info) > 1,
                # New detailed format with groups (structure only, no text bloat)
                'pages_detail': pages_detail,
                # New structure information (Phase 2 enhancement)
                'connection_graph': connection_graph,
                'topology_pattern': topology_pattern,
                'layout_pattern': layout_pattern,
            }
            
        except Exception as e:
            return {
                'filename': os.path.basename(vsdx_path),
                'error': str(e),
                'scan_date': datetime.now().isoformat(),
            }
    
    @staticmethod
    def _is_group(shape) -> bool:
        """
        Check if a shape is a group containing other shapes
        
        Args:
            shape: Shape object to check
            
        Returns:
            True if shape is a group, False otherwise
        """
        try:
            # Check if shape has child_shapes attribute and it's not empty
            if hasattr(shape, 'child_shapes') and shape.child_shapes:
                return len(shape.child_shapes) > 0
            
            # Alternative: check if shape type indicates it's a group
            if hasattr(shape, 'Type') and shape.Type == 'Group':
                return True
                
            return False
        except Exception:
            return False
    
    @staticmethod
    def _process_group(shape, diagram) -> Dict[str, Any]:
        """
        Process a group shape and extract its child shapes (structure only)
        
        Args:
            shape: Group shape object
            diagram: DiagramBuilder instance for connector detection
            
        Returns:
            Dictionary with group information including title and shape type counts
        """
        try:
            # Get group title from shape text
            group_title = shape.text.strip() if hasattr(shape, 'text') and shape.text else 'Untitled Group'
            
            # Initialize group info (no shape_details, only counts)
            group_info = {
                'title': group_title,
                'id': shape.ID if hasattr(shape, 'ID') else 'unknown',
                'shapes': {},
                'total': 0
            }
            
            # Process child shapes (count types only)
            if hasattr(shape, 'child_shapes'):
                for child_shape in shape.child_shapes:
                    # Skip connectors in groups
                    if hasattr(diagram, '_is_connector') and diagram._is_connector(child_shape):
                        continue
                    
                    child_type = TemplateScanner._infer_shape_type(child_shape)
                    
                    # Skip Unknown types
                    if child_type != 'Unknown':
                        group_info['shapes'][child_type] = \
                            group_info['shapes'].get(child_type, 0) + 1
                        group_info['total'] += 1
            
            return group_info if group_info['total'] > 0 else None
            
        except Exception as e:
            return None
    
    @staticmethod
    def _infer_shape_type(shape) -> str:
        """Infer shape type from shape object with robust fallbacks"""
        try:
            master = getattr(shape, 'master', None)
            master_name = (getattr(master, 'name', '') or '').strip()
            shape_type_attr = (getattr(shape, 'shape_type', '') or '').strip()
            text = (getattr(shape, 'text', '') or '').strip()

            # 1) Master name based
            if master_name:
                norm = normalize_shape_type(master_name)
                if norm and norm.lower() not in ('', 'shape', 'unknown'):
                    return norm

            # 2) shape.shape_type based
            if shape_type_attr:
                norm2 = normalize_shape_type(shape_type_attr)
                if norm2 and norm2.lower() not in ('', 'shape', 'unknown'):
                    return norm2

            # 3) Text heuristics (common flowchart cues)
            text_lower = text.lower()
            if any(k in text_lower for k in ['start', 'end']) or any(k in text for k in ['开始', '结束']):
                return 'RoundedRectangle'
            if '?' in text or any(k in text for k in ['条件', '判断']):
                return 'Diamond'
            if any(k in text_lower for k in ['data', 'input', 'output']) or any(k in text for k in ['数据', '输入', '输出']):
                return 'Parallelogram'
            if any(k in text for k in ['流程', '子流程']) or 'process' in text_lower:
                return 'Rectangle'

            # 4) Geometry hint (very rough)
            try:
                w = float(getattr(shape, 'width', 0) or 0)
                h = float(getattr(shape, 'height', 0) or 0)
                if w > 0 and h > 0:
                    ratio = w / h
                    if 0.85 <= ratio <= 1.15:
                        return 'Rectangle'
                    elif ratio > 1.25:
                        return 'Rectangle'
                    elif ratio < 0.8:
                        return 'Rectangle'
            except Exception:
                pass

            # 5) Fallback - skip unknown shapes
            return 'Unknown'
        except Exception:
            return 'Unknown'
    
    @staticmethod
    def _calculate_complexity(num_shapes: int, num_connectors: int) -> str:
        """Calculate template complexity"""
        total = num_shapes + num_connectors
        
        if total <= 5:
            return 'simple'
        elif total <= 15:
            return 'medium'
        else:
            return 'complex'
    
    @staticmethod
    def scan_page_detailed(page, page_idx: int, diagram) -> Dict[str, Any]:
        """
        Scan a single page in detail with structure analysis
        
        Args:
            page: Page object from visio file
            page_idx: Page index number (0-based)
            diagram: DiagramBuilder instance for connector detection
            
        Returns:
            Dictionary with detailed page information including structure
        """
        try:
            # Set current page for analysis
            diagram.current_page = page
            
            # Initialize page data
            page_name = page.name if hasattr(page, 'name') else f'Page-{page_idx}'
            page_shapes = {}
            page_connectors = 0
            page_texts = []
            groups_info = []
            ungrouped_shapes_info = {'shapes': {}, 'total': 0}
            
            # Process all shapes on the page
            if hasattr(page, 'child_shapes'):
                for shape in page.child_shapes:
                    # Check if shape is a group
                    is_group = TemplateScanner._is_group(shape)
                    
                    if is_group:
                        # Process group
                        group_info = TemplateScanner._process_group(shape, diagram)
                        if group_info:
                            groups_info.append(group_info)
                            
                            # Update page totals
                            for shape_type, count in group_info['shapes'].items():
                                page_shapes[shape_type] = page_shapes.get(shape_type, 0) + count
                            
                            # Collect group title text
                            if group_info['title'] and group_info['title'] != 'Untitled Group':
                                page_texts.append(group_info['title'])
                    else:
                        # Process individual shape
                        shape_text = shape.text.strip() if hasattr(shape, 'text') and shape.text else ''
                        
                        # Check if connector
                        if hasattr(diagram, '_is_connector') and diagram._is_connector(shape):
                            page_connectors += 1
                        else:
                            shape_type = TemplateScanner._infer_shape_type(shape)
                            
                            # Skip Unknown types
                            if shape_type != 'Unknown':
                                page_shapes[shape_type] = page_shapes.get(shape_type, 0) + 1
                                ungrouped_shapes_info['shapes'][shape_type] = \
                                    ungrouped_shapes_info['shapes'].get(shape_type, 0) + 1
                                ungrouped_shapes_info['total'] += 1
                                
                                # Collect text
                                if shape_text and len(page_texts) < 50:
                                    page_texts.append(shape_text)
            
            # Calculate page complexity
            total_shapes = sum(page_shapes.values())
            complexity = TemplateScanner._calculate_complexity(total_shapes, page_connectors)
            
            # Extract per-page structure information
            try:
                from .structure_analyzer import StructureAnalyzer
                structure_info = StructureAnalyzer.analyze_structure(diagram)
                connection_graph = structure_info.get('connection_graph', {})
                topology_pattern = structure_info.get('topology_pattern', {})
                layout_pattern = structure_info.get('layout_pattern', {})
            except Exception as e:
                print(f"    Warning: Page structure analysis failed: {e}")
                connection_graph = {'node_count': 0, 'edge_count': 0, 'edges': [], 'node_degrees': {}}
                topology_pattern = {'pattern_type': 'unknown', 'description': 'Structure analysis unavailable'}
                layout_pattern = {'pattern_type': 'unknown', 'description': 'Layout analysis unavailable'}
            
            # Build page result
            page_result = {
                'page_number': page_idx + 1,
                'name': page_name,
                'shape_count': total_shapes,
                'connector_count': page_connectors,
                'complexity': complexity,
                'shapes': page_shapes,
                'groups': groups_info,
                'ungrouped_shapes': ungrouped_shapes_info,
                'sample_texts': page_texts[:50],  # First 50 texts for analysis
                'connection_graph': connection_graph,
                'topology_pattern': topology_pattern,
                'layout_pattern': layout_pattern,
            }
            
            return page_result
            
        except Exception as e:
            print(f"    Error scanning page {page_idx}: {e}")
            return {
                'page_number': page_idx + 1,
                'name': f'Page-{page_idx}',
                'error': str(e)
            }
    
    @staticmethod
    def scan_template_enhanced(vsdx_path: str, model=None) -> Dict[str, Any]:
        """
        Enhanced scan with per-page analysis including LLM-generated metadata
        
        Args:
            vsdx_path: Path to the .vsdx file
            model: Optional LLM model for keyword/use case generation
            
        Returns:
            Dictionary with enhanced per-page template metadata
        """
        try:
            # Load the diagram
            diagram = DiagramBuilder.load_from_file(vsdx_path)
            
            if not diagram.visio_file or not diagram.visio_file.pages:
                return {
                    'filename': os.path.basename(vsdx_path),
                    'error': 'No pages found in file',
                    'scan_date': datetime.now().isoformat(),
                }
            
            # Scan each page in detail
            pages_enhanced = []
            print(f"  Scanning {len(diagram.visio_file.pages)} pages...")
            
            for page_idx in range(len(diagram.visio_file.pages)):
                page = diagram.visio_file.pages[page_idx]
                print(f"    Page {page_idx + 1}: {page.name if hasattr(page, 'name') else f'Page-{page_idx}'}")
                
                # Get detailed page scan
                page_data = TemplateScanner.scan_page_detailed(page, page_idx, diagram)
                
                # Add LLM-based analysis if model is provided
                if model and 'error' not in page_data:
                    try:
                        from .template_analyzer import TemplateAnalyzer
                        
                        sample_texts = page_data.get('sample_texts', [])
                        
                        # Create temporary template info for the page
                        page_template_info = {
                            'total_pages': 1,
                            'total_shapes': page_data.get('shapes', {}),
                            'complexity': page_data.get('complexity', 'unknown'),
                            'sample_texts': sample_texts
                        }
                        
                        print(f"      Extracting keywords...")
                        keywords = TemplateAnalyzer.extract_keywords(sample_texts, model, max_keywords=10)
                        
                        print(f"      Generating use cases...")
                        use_cases = TemplateAnalyzer.generate_use_cases(
                            sample_texts, page_template_info, model, max_cases=5
                        )
                        
                        print(f"      Generating summary...")
                        summary = TemplateAnalyzer.generate_summary(page_template_info, model)
                        
                        # Add to page data
                        page_data['keywords'] = keywords
                        page_data['use_cases'] = use_cases
                        page_data['summary'] = summary
                        
                    except Exception as e:
                        print(f"      Warning: LLM analysis failed: {e}")
                        page_data['keywords'] = []
                        page_data['use_cases'] = []
                        page_data['summary'] = 'Analysis unavailable'
                
                # Remove sample_texts from final output to reduce size
                if 'sample_texts' in page_data:
                    del page_data['sample_texts']
                
                pages_enhanced.append(page_data)
            
            # Build final result
            result = {
                'filename': os.path.basename(vsdx_path),
                'scan_date': datetime.now().isoformat(),
                'total_pages': len(pages_enhanced),
                'pages': pages_enhanced
            }
            
            return result
            
        except Exception as e:
            return {
                'filename': os.path.basename(vsdx_path),
                'error': str(e),
                'scan_date': datetime.now().isoformat(),
            }
    
    @staticmethod
    def scan_directory(directory_path: str, pattern: str = "*.vsdx", recursive: bool = True) -> Dict[str, Dict[str, Any]]:
        """
        Scan all .vsdx files in a directory (recursively by default)
        
        Args:
            directory_path: Path to directory containing templates
            pattern: File pattern to match (default: *.vsdx)
            recursive: If True, scan subdirectories recursively (default: True)
            
        Returns:
            Dictionary mapping relative file path to scan results
        """
        results = {}
        
        if not os.path.exists(directory_path):
            return results
        
        if recursive:
            # Recursively scan all subdirectories
            for root, dirs, files in os.walk(directory_path):
                for filename in files:
                    if filename.endswith('.vsdx'):
                        filepath = os.path.join(root, filename)
                        # Use relative path from the base directory as key
                        rel_path = os.path.relpath(filepath, directory_path)
                        print(f"  扫描: {rel_path}")
                        scan_result = TemplateScanner.scan_template(filepath)
                        results[rel_path] = scan_result
        else:
            # Only scan the top-level directory
            for filename in os.listdir(directory_path):
                filepath = os.path.join(directory_path, filename)
                if os.path.isfile(filepath) and filename.endswith('.vsdx'):
                    print(f"  扫描: {filename}")
                    scan_result = TemplateScanner.scan_template(filepath)
                    results[filename] = scan_result
        
        return results

