"""
Template manager for Visio diagrams
Handles template listing, loading, and management
"""
import os
import json
import shutil
from typing import List, Dict, Any, Optional
from ..utils.diagram_builder import DiagramBuilder
from ..utils.template_scanner import TemplateScanner
from ..utils.template_analyzer import TemplateAnalyzer
from ..utils.metadata_generator import MetadataGenerator


class TemplateManager:
    """Manages Visio diagram templates"""
    
    # Common template subdirectories (for fast path resolution)
    COMMON_SUBDIRS = [
        "",  # Root level
        "basic",
        "flowchart",
        "network",
        "business",
        "software",
        "IT_Vendors",
        "Microsoft",
        "AWS",
        "Azure",
        "diagrams",
    ]
    
    def __init__(self, template_dir: str = "assets/templates"):
        """
        Initialize template manager
        
        Args:
            template_dir: Canonical template root (assets/templates) or
                explicit library directory (assets/templates/library)
        """
        # Use absolute path; remember repository root for controlled prefix attempts
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        self.repo_root = base_dir

        if not os.path.isabs(template_dir):
            template_dir = os.path.join(base_dir, template_dir)

        normalized = os.path.normpath(template_dir)
        # Accept either assets/templates (root) or assets/templates/library.
        if os.path.basename(normalized).lower() == "library":
            self.template_root = os.path.dirname(normalized)
            self.template_dir = normalized
        else:
            self.template_root = normalized
            self.template_dir = os.path.join(self.template_root, "library")

        # Canonical index location: assets/indexes/template_library.json
        self.index_dir = os.path.normpath(os.path.join(self.template_root, "..", "indexes"))
        self.library_file = os.path.join(self.index_dir, "template_library.json")

        # Create directories if they don't exist
        os.makedirs(self.template_dir, exist_ok=True)
        os.makedirs(self.index_dir, exist_ok=True)
        
        # Load template library
        self.library = self._load_library()
    
    def list_templates(self, include_shapes: bool = True) -> List[Dict[str, Any]]:
        """
        List all available templates with detailed information
        
        Args:
            include_shapes: If True, include detailed shape information from library
        
        Returns:
            List of template information dictionaries with shape details
        """
        templates = []
        
        # Directly read from library JSON (already contains all recursively scanned results)
        # No file system I/O needed - all data comes from template_library.json
        for filename, library_info in self.library.items():
            # Build template info from library
            # filename may contain subdirectory paths (e.g., "Microsoft/xxx.vsdx")
            template_info = {
                'filename': filename,
                'name': library_info.get('name', os.path.basename(filename).replace('.vsdx', '')),
                'category': library_info.get('category', 'general'),
                'path': os.path.join(self.template_dir, filename)
            }
            
            # Add detailed information if requested
            if include_shapes:
                template_info.update({
                    'shapes': library_info.get('shapes', {}),
                    'shape_total': library_info.get('shape_total', 0),
                    'shape_types': library_info.get('shape_types', []),
                    'total_connectors': library_info.get('total_connectors', 0),
                    'complexity': library_info.get('complexity', 'unknown'),
                    'pages': library_info.get('pages', 1),
                    'keywords': library_info.get('keywords', []),
                    'use_cases': library_info.get('use_cases', []),
                    'sample_texts': library_info.get('sample_texts', []),
                    'scan_date': library_info.get('scan_date', '')
                })
            
            templates.append(template_info)
        
        return templates
    
    def get_template(self, template_name: str) -> Optional[str]:
        """
        Get the full path to a template file (strict path enforcement - no fallback searching)
        
        Args:
            template_name: Exact path to template (absolute or relative to template_dir)
        
        Returns:
            Full path to template file or None if not found
            
        Note:
            This method enforces strict path usage without fallback mechanisms:
            - If absolute path provided, only that path is checked
            - If relative path provided, only checks relative to template_dir
            - No subdirectory searching, no library lookup, no alternatives
            - Raises clear error if template not found (see calling methods)
        """
        # 1) If absolute path is provided, use it exactly (no prefixes)
        if os.path.isabs(template_name):
            return template_name if os.path.exists(template_name) else None

        # 2) Use the given template path exactly as provided relative to the primary
        #    template directory (this is the canonical location).
        exact_primary = os.path.join(self.template_dir, template_name)
        if os.path.exists(exact_primary):
            return exact_primary

        # 3) Also allow the exact given path relative to the repository root
        exact_repo = os.path.join(self.repo_root, template_name)
        if os.path.exists(exact_repo):
            return exact_repo

        # 4) If not found, retry by prefixing the provided path with a small, controlled
        #    set of allowed prefixes (in this specific order). Do NOT perform any
        #    global or recursive search — only these prefixes are allowed.
        prefixes = [
            os.path.join("assets", "templates"),
            os.path.join("assets", "templates", "library"),
            "templates",
            "library",
            os.path.join("templates", "library"),
        ]

        for prefix in prefixes:
            # Try relative to repository root
            candidate = os.path.join(self.repo_root, prefix, template_name)
            if os.path.exists(candidate):
                return candidate
            # Try relative to configured template_dir as a secondary base
            candidate2 = os.path.join(self.template_dir, prefix, template_name)
            if os.path.exists(candidate2):
                return candidate2

        # If still not found, return None so callers can handle the explicit error
        return None
    
    def load_template(self, template_name: str) -> Optional[DiagramBuilder]:
        """
        Load a template and return a DiagramBuilder instance (strict path enforcement)
        
        Args:
            template_name: Exact path to template (absolute or relative to template_dir)
        
        Returns:
            DiagramBuilder instance
            
        Raises:
            FileNotFoundError: If template path doesn't exist (no fallback alternatives)
        """
        template_path = self.get_template(template_name)
        if not template_path:
            # Clear user-facing message per strict requirement and stop further actions
            raise FileNotFoundError(
                f'Error: Template "{template_name}" not found.\n'
                f'The operation has been terminated. No further actions were executed.'
            )
        
        try:
            return DiagramBuilder.load_from_file(template_path)
        except Exception as e:
            raise RuntimeError(f"Error loading template from {template_path}: {e}")
    
    def create_from_template(self, template_name: str, output_path: str) -> bool:
        """
        Create a new diagram from a template (strict path enforcement)
        
        Args:
            template_name: Exact path to template (absolute or relative to template_dir)
            output_path: Path for the new diagram file
        
        Returns:
            True if successful
            
        Raises:
            FileNotFoundError: If template path doesn't exist (no fallback alternatives)
        """
        template_path = self.get_template(template_name)
        if not template_path:
            # Clear user-facing message per strict requirement and stop further actions
            raise FileNotFoundError(
                f'Error: Template "{template_name}" not found.\n'
                f'The operation has been terminated. No further actions were executed.'
            )
        
        try:
            # Copy template file to output location
            shutil.copy2(template_path, output_path)
            print(f"Created diagram from template: {output_path}")
            return True
        except Exception as e:
            raise RuntimeError(f"Error creating diagram from template {template_path}: {e}")
    
    def add_template(self, source_path: str, template_name: str, 
                     description: str = "", category: str = "general") -> bool:
        """
        Add a new template to the library
        
        Args:
            source_path: Path to the source .vsdx file
            template_name: Name for the template
            description: Description of the template
            category: Category (e.g., 'flowchart', 'org_chart', 'network')
        
        Returns:
            True if successful
        """
        if not os.path.exists(source_path):
            print(f"Source file not found: {source_path}")
            return False
        
        # Determine filename
        filename = os.path.basename(source_path)
        if not filename.endswith('.vsdx'):
            filename += '.vsdx'
        
        dest_path = os.path.join(self.template_dir, filename)
        
        try:
            # Copy file to template directory
            shutil.copy2(source_path, dest_path)
            
            # Update library with basic info (will be scanned later for shapes)
            self.library[filename] = {
                'name': template_name,
                'category': category,
                'keywords': [],
                'use_cases': [],
                'shapes': {},
                'shape_total': 0,
                'shape_types': [],
                'total_connectors': 0,
                'complexity': 'unknown',
                'pages': 1,
                'sample_texts': [],
                'scan_date': ''
            }
            self._save_library()
            
            print(f"Added template: {template_name}")
            print(f"Run scan_templates.py to extract shape information")
            return True
        except Exception as e:
            print(f"Error adding template: {e}")
            return False
    
    def remove_template(self, template_name: str) -> bool:
        """
        Remove a template from the library
        
        Args:
            template_name: Name or filename of the template
        
        Returns:
            True if successful
        """
        template_path = self.get_template(template_name)
        if not template_path:
            print(f"Template not found: {template_name}")
            return False
        
        try:
            # Remove file
            os.remove(template_path)
            
            # Remove from library
            filename = os.path.basename(template_path)
            if filename in self.library:
                del self.library[filename]
                self._save_library()
            
            print(f"Removed template: {template_name}")
            return True
        except Exception as e:
            print(f"Error removing template: {e}")
            return False
    
    def get_template_info(self, template_name: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a template including shape statistics
        
        Args:
            template_name: Name or filename of the template
        
        Returns:
            Template information dictionary with detailed shape info or None
        """
        template_path = self.get_template(template_name)
        if not template_path:
            return None
        
        filename = os.path.basename(template_path)
        library_info = self.library.get(filename, {})
        
        # Build info from library
        info = {
            'filename': filename,
            'name': library_info.get('name', filename.replace('.vsdx', '')),
            'category': library_info.get('category', 'general'),
            'path': template_path,
            'size': os.path.getsize(template_path),
            'shapes': library_info.get('shapes', {}),
            'shape_total': library_info.get('shape_total', 0),
            'shape_types': library_info.get('shape_types', []),
            'total_connectors': library_info.get('total_connectors', 0),
            'complexity': library_info.get('complexity', 'unknown'),
            'pages': library_info.get('pages', 1),
            'keywords': library_info.get('keywords', []),
            'use_cases': library_info.get('use_cases', []),
            'sample_texts': library_info.get('sample_texts', []),
            'scan_date': library_info.get('scan_date', '')
        }
        
        return info
    
    def _load_library(self) -> Dict[str, Any]:
        """Load template library from JSON file"""
        if os.path.exists(self.library_file):
            try:
                with open(self.library_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading library: {e}")
                return {}
        return {}
    
    def _save_library(self):
        """Save template library to JSON file"""
        try:
            with open(self.library_file, 'w', encoding='utf-8') as f:
                json.dump(self.library, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving library: {e}")
    
    def scan_template_with_llm(self, template_path: str, model) -> Dict[str, Any]:
        """
        Scan a single template with LLM analysis for keywords, use cases, and summary
        
        Args:
            template_path: Path to the .vsdx template file
            model: LLM model instance for analysis
            
        Returns:
            Dictionary with complete scan results including LLM analysis
        """
        print(f"Scanning template: {template_path}")
        
        # Perform basic scan
        scan_data = TemplateScanner.scan_template(template_path)
        
        if 'error' in scan_data:
            print(f"  Error: {scan_data['error']}")
            return scan_data
        
        # Perform LLM analysis if model is provided
        if model:
            print("  Performing LLM analysis...")
            llm_analysis = TemplateAnalyzer.analyze_template(scan_data, model)
            
            # Merge LLM results into scan data
            scan_data['keywords'] = llm_analysis.get('keywords', [])
            scan_data['use_cases'] = llm_analysis.get('use_cases', [])
            scan_data['summary'] = llm_analysis.get('summary', 'No description available')
        
        return scan_data
    
    def scan_all_templates(self, update_metadata: bool = True, use_llm: bool = False, model=None) -> Dict[str, Any]:
        """
        Scan all templates in the directory and update the library
        
        Args:
            update_metadata: If True, merge scan results with existing metadata
            use_llm: If True, use LLM to analyze templates for keywords, use cases, and summaries
            model: LLM model instance (required if use_llm=True)
            
        Returns:
            Dictionary of scan results with 'library' and 'removed' keys
        """
        print(f"Scanning templates in {self.template_dir}...")
        scan_results = TemplateScanner.scan_directory(self.template_dir)
        
        # Check for removed files and clean up library
        removed_files = []
        existing_filenames = list(self.library.keys())
        for filename in existing_filenames:
            file_path = os.path.join(self.template_dir, filename)
            if not os.path.exists(file_path):
                removed_files.append(filename)
                del self.library[filename]
                print(f"  Removed deleted file: {filename}")
        
        # Update library with scan results
        for filename, scan_data in scan_results.items():
            if 'error' in scan_data:
                print(f"  Error scanning {filename}: {scan_data['error']}")
                continue
            
            # Get existing library entry to preserve manual edits
            existing = self.library.get(filename, {})
            
            # Auto-generate keywords and use_cases
            category = existing.get('category', 'general')
            
            # Perform LLM analysis if requested, otherwise use auto-generation
            if use_llm and model:
                print(f"  Analyzing {filename} with LLM...")
                llm_analysis = TemplateAnalyzer.analyze_template(scan_data, model)
                generated_keywords = llm_analysis.get('keywords', [])
                generated_use_cases = llm_analysis.get('use_cases', [])
            else:
                # Auto-generate metadata from scan data
                print(f"  Auto-generating metadata for {filename}...")
                metadata = MetadataGenerator.generate_template_metadata(scan_data, category)
                generated_keywords = metadata['keywords']
                generated_use_cases = metadata['use_cases']
            
            # Merge scan data with existing library entry
            # Preserve manual edits (name, category)
            # Update auto-scanned data (shapes, connectors, keywords, use_cases, structure)
            # Store only structural data, no text bloat
            shape_counts = scan_data.get('total_shapes', {}) or {}
            library_entry = {
                'name': existing.get('name', filename.replace('.vsdx', '')),
                'category': existing.get('category', 'general'),
                'keywords': generated_keywords,
                'use_cases': generated_use_cases,
                'shapes': shape_counts,
                'shape_total': sum(shape_counts.values()) if isinstance(shape_counts, dict) else 0,
                'shape_types': sorted(list(shape_counts.keys())) if isinstance(shape_counts, dict) else [],
                'total_connectors': scan_data.get('total_connectors', 0),
                'complexity': scan_data.get('complexity', 'unknown'),
                'scan_date': scan_data.get('scan_date', ''),
                'pages': scan_data.get('total_pages', 1),
                'sample_texts': scan_data.get('sample_texts', [])[:10],  # Limit to 10 for library
                # Store structure-focused pages_detail (no shape_details with text)
                'pages_detail': TemplateManager._simplify_pages_detail(scan_data.get('pages_detail', [])),
                # Structure information (enhanced with connections)
                'connection_graph': TemplateManager._simplify_connection_graph(scan_data.get('connection_graph', {})),
                'topology_pattern': scan_data.get('topology_pattern', {}),
                'layout_pattern': scan_data.get('layout_pattern', {}),
            }
            
            self.library[filename] = library_entry
        
        # Save the updated library
        self._save_library()
        print(f"Scanned {len(scan_results)} templates")
        if removed_files:
            print(f"Removed {len(removed_files)} deleted files from library")
        
        return {
            'library': self.library,
            'removed': removed_files
        }

    def list_template_shapes(self, template_name: str, use_cache: bool = True) -> Optional[Dict[str, int]]:
        """
        List shape counts for a given template.
        
        Args:
            template_name: Name or filename of the template
            use_cache: If True, use cached data from library; if False, rescan
        
        Returns:
            Mapping of shape type/master name to count, or None if error
        """
        template_path = self.get_template(template_name)
        if not template_path:
            print(f"Template not found: {template_name}")
            return None
        
        filename = os.path.basename(template_path)
        
        # Try to use cached data from library
        if use_cache and filename in self.library:
            return self.library[filename].get('shapes', {})
        
        # Otherwise, scan the template
        try:
            from ..utils.template_scanner import TemplateScanner
            scan = TemplateScanner.scan_template(template_path)
            if 'error' in scan:
                print(f"Error scanning template '{template_name}': {scan.get('error')}")
                return None
            return scan.get('total_shapes', {}) or {}
        except Exception as e:
            print(f"Error listing shapes: {e}")
            return None
    
    def print_template_shapes(self, template_name: str) -> bool:
        """
        Print formatted shape statistics for a template
        
        Args:
            template_name: Name or filename of the template
            
        Returns:
            True if successful
        """
        info = self.get_template_info(template_name)
        if not info:
            print(f"Template not found: {template_name}")
            return False
        
        print(f"\n模板: {info['name']}")
        print(f"文件: {info['filename']}")
        print(f"类别: {info['category']}")
        print(f"复杂度: {info['complexity']}")
        print(f"页数: {info['pages']}")
        print(f"\n形状统计:")
        print(f"  总形状数: {info['shape_total']}")
        print(f"  连接器数: {info['total_connectors']}")
        
        shapes = info.get('shapes', {})
        if shapes:
            print(f"\n  各类型形状:")
            for shape_type, count in sorted(shapes.items(), key=lambda x: x[1], reverse=True):
                print(f"    - {shape_type}: {count}")
        else:
            print(f"  (无形状信息，请运行 scan_all_templates 更新)")
        
        if info.get('sample_texts'):
            print(f"\n  示例文本: {', '.join(info['sample_texts'][:5])}")
        
        if info.get('keywords'):
            print(f"\n关键词: {', '.join(info['keywords'])}")
        
        if info.get('use_cases'):
            print(f"适用场景: {', '.join(info['use_cases'])}")
        
        if info.get('scan_date'):
            print(f"\n扫描时间: {info['scan_date']}")
        
        return True
    
    def search_templates(self, keywords: Optional[List[str]] = None, 
                        category: Optional[str] = None,
                        complexity: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search templates by keywords, category, or complexity
        
        Args:
            keywords: List of keywords to match (case-insensitive)
            category: Category to filter by
            complexity: Complexity level ('simple', 'medium', 'complex')
            
        Returns:
            List of matching template information
        """
        results = []
        
        for filename, info in self.library.items():
            # Trust the JSON data - no file system check needed here
            # File existence will be validated only when actually loading the template
            template_path = os.path.join(self.template_dir, filename)
            
            # Filter by category
            if category and info.get('category', '').lower() != category.lower():
                continue
            
            # Filter by complexity
            if complexity and info.get('complexity', '').lower() != complexity.lower():
                continue
            
            # Filter by keywords
            if keywords:
                # Search in name, keywords, use_cases
                searchable_text = ' '.join([
                    info.get('name', ''),
                    ' '.join(info.get('keywords', [])),
                    ' '.join(info.get('use_cases', [])),
                ]).lower()
                
                # Check if any keyword matches
                if not any(kw.lower() in searchable_text for kw in keywords):
                    continue
            
            # Add to results
            result = {
                'filename': filename,
                'path': template_path,
                **info
            }
            results.append(result)
        
        return results
    
    def get_library_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the template library
        
        Returns:
            Dictionary with library statistics
        """
        total = len(self.library)
        by_category = {}
        by_complexity = {}
        
        for info in self.library.values():
            category = info.get('category', 'general')
            by_category[category] = by_category.get(category, 0) + 1
            
            complexity = info.get('complexity', 'unknown')
            by_complexity[complexity] = by_complexity.get(complexity, 0) + 1
        
        return {
            'total_templates': total,
            'by_category': by_category,
            'by_complexity': by_complexity,
        }
    
    @staticmethod
    def _simplify_pages_detail(pages_detail: List[Dict]) -> List[Dict]:
        """
        Simplify pages_detail to remove text bloat
        Keep only structure: group titles and shape type counts
        """
        simplified = []
        for page in pages_detail:
            simplified_page = {
                'name': page.get('name', 'Unknown'),
                'groups': []
            }
            
            # Simplify groups (keep title and shape counts only)
            for group in page.get('groups', []):
                simplified_page['groups'].append({
                    'title': group.get('title', 'Untitled'),
                    'shapes': group.get('shapes', {}),
                    'total': group.get('total', 0)
                })
            
            # Simplify ungrouped shapes (keep counts only)
            ungrouped = page.get('ungrouped_shapes', {})
            simplified_page['ungrouped_shapes'] = {
                'shapes': ungrouped.get('shapes', {}),
                'total': ungrouped.get('total', 0)
            }
            
            simplified.append(simplified_page)
        
        return simplified
    
    @staticmethod
    def _simplify_connection_graph(connection_graph: Dict) -> Dict:
        """
        Simplify connection graph to reduce size
        Keep summary stats and edge samples
        """
        if not connection_graph:
            return {}
        
        edges = connection_graph.get('edges', [])
        
        # Create connection summary
        simplified = {
            'node_count': connection_graph.get('node_count', 0),
            'edge_count': connection_graph.get('edge_count', 0),
            'connector_types': connection_graph.get('connector_types', {}),
            # Store only first 20 edges as samples
            'edge_samples': edges[:20] if edges else [],
            'node_degrees_summary': {
                'max_in': max([d.get('in', 0) for d in connection_graph.get('node_degrees', {}).values()] or [0]),
                'max_out': max([d.get('out', 0) for d in connection_graph.get('node_degrees', {}).values()] or [0]),
                'avg_degree': sum([d.get('in', 0) + d.get('out', 0) for d in connection_graph.get('node_degrees', {}).values()]) / max(len(connection_graph.get('node_degrees', {})), 1) if connection_graph.get('node_degrees') else 0
            }
        }
        
        return simplified

