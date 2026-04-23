"""
Stencil manager for Visio stencil files
Handles stencil listing, loading, and management
"""
import os
import json
import shutil
from typing import List, Dict, Any, Optional
from ..utils.stencil_scanner import StencilScanner
from ..utils.metadata_generator import MetadataGenerator


class StencilManager:
    """Manages Visio stencil files (.vssx)"""
    
    # Common stencil subdirectories (for fast path resolution)
    COMMON_SUBDIRS = [
        "",  # Root level
        "IT",
        "IT Vendors",
        "Business",
        "Network",
        "Software",
        "AWS",
        "Azure",
        "Microsoft",
        "Flowchart",
    ]
    
    def __init__(self, stencil_dir: str = "assets/templates/stencils"):
        """
        Initialize stencil manager
        
        Args:
            stencil_dir: Canonical stencil directory
                (assets/templates/stencils) or template root (assets/templates)
        """
        # Use absolute path
        if not os.path.isabs(stencil_dir):
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            stencil_dir = os.path.join(base_dir, stencil_dir)
        
        normalized = os.path.normpath(stencil_dir)
        # Accept either assets/templates/stencils or assets/templates root.
        if os.path.basename(normalized).lower() == "stencils":
            self.template_root = os.path.dirname(normalized)
            self.stencil_dir = normalized
        else:
            self.template_root = normalized
            self.stencil_dir = os.path.join(self.template_root, "stencils")

        # Canonical index location: assets/indexes/stencil_library.json
        self.index_dir = os.path.normpath(os.path.join(self.template_root, "..", "indexes"))
        self.library_file = os.path.join(self.index_dir, "stencil_library.json")

        # Create directories if they don't exist
        os.makedirs(self.stencil_dir, exist_ok=True)
        os.makedirs(self.index_dir, exist_ok=True)
        
        # Load stencil library
        self.library = self._load_library()
    
    def list_stencils(self, include_masters: bool = True) -> List[Dict[str, Any]]:
        """
        List all available stencils with detailed information
        
        Args:
            include_masters: If True, include detailed master information from library
        
        Returns:
            List of stencil information dictionaries
        """
        stencils = []
        
        # Directly read from library JSON (already contains all recursively scanned results)
        # No file system I/O needed - all data comes from stencil_library.json
        for filename, library_info in self.library.items():
            # Build stencil info from library
            # filename may contain subdirectory paths (e.g., "IT Vendors/xxx.vssx")
            stencil_info = {
                'filename': filename,
                'name': library_info.get('name', os.path.basename(filename).replace('.vssx', '')),
                'category': library_info.get('category', 'general'),
                'path': os.path.join(self.stencil_dir, filename)
            }
            
            # Add detailed information if requested
            if include_masters:
                stencil_info.update({
                    'masters': library_info.get('masters', {}),
                    'master_count': library_info.get('master_count', 0),
                    'master_names': library_info.get('master_names', []),
                    'complexity': library_info.get('complexity', 'unknown'),
                    'keywords': library_info.get('keywords', []),
                    'use_cases': library_info.get('use_cases', []),
                    'scan_date': library_info.get('scan_date', '')
                })
            
            stencils.append(stencil_info)
        
        return stencils
    
    def get_stencil(self, stencil_name: str) -> Optional[str]:
        """
        Get the full path to a stencil file (optimized for fast lookup)
        
        Args:
            stencil_name: Name or filename of the stencil
        
        Returns:
            Full path to stencil file or None if not found
        """
        # Allow absolute path directly
        if os.path.isabs(stencil_name) and os.path.exists(stencil_name):
            return stencil_name

        # Try exact filename match (supports subdirectories like IT Vendors/xxx.vssx)
        stencil_path = os.path.join(self.stencil_dir, stencil_name)
        if os.path.exists(stencil_path):
            return stencil_path
        
        # Try with .vssx extension
        if not stencil_name.endswith('.vssx'):
            stencil_path = os.path.join(self.stencil_dir, f"{stencil_name}.vssx")
            if os.path.exists(stencil_path):
                return stencil_path
        
        # Fast path: search in common subdirectories (avoid traversing entire library)
        base_name = os.path.basename(stencil_name)
        for subdir in self.COMMON_SUBDIRS:
            # Try with original name
            if subdir:
                candidate = os.path.join(self.stencil_dir, subdir, base_name)
            else:
                candidate = os.path.join(self.stencil_dir, base_name)
            
            if os.path.exists(candidate):
                return candidate
            
            # Try with .vssx extension if not present
            if not base_name.endswith('.vssx'):
                if subdir:
                    candidate = os.path.join(self.stencil_dir, subdir, f"{base_name}.vssx")
                else:
                    candidate = os.path.join(self.stencil_dir, f"{base_name}.vssx")
                
                if os.path.exists(candidate):
                    return candidate
        
        # Last resort: lookup in library (only if fast path failed)
        # This is kept minimal to avoid loading entire library into context
        if stencil_name in self.library:
            stencil_path = os.path.join(self.stencil_dir, stencil_name)
            if os.path.exists(stencil_path):
                return stencil_path
        
        return None
    
    def add_stencil(self, source_path: str, stencil_name: str, 
                    description: str = "", category: str = "general") -> bool:
        """
        Add a new stencil to the library
        
        Args:
            source_path: Path to the source .vssx file
            stencil_name: Name for the stencil
            description: Description of the stencil
            category: Category (e.g., 'network', 'cloud', 'flowchart', 'database')
        
        Returns:
            True if successful
        """
        if not os.path.exists(source_path):
            print(f"Source file not found: {source_path}")
            return False
        
        # Determine filename
        filename = os.path.basename(source_path)
        if not filename.endswith('.vssx'):
            filename += '.vssx'
        
        dest_path = os.path.join(self.stencil_dir, filename)
        
        try:
            # Copy file to stencil directory
            shutil.copy2(source_path, dest_path)
            
            # Update library with basic info (will be scanned later for masters)
            self.library[filename] = {
                'name': stencil_name,
                'category': category,
                'keywords': [],
                'use_cases': [],
                'masters': {},
                'master_count': 0,
                'master_names': [],
                'complexity': 'unknown',
                'scan_date': ''
            }
            self._save_library()
            
            print(f"Added stencil: {stencil_name}")
            print(f"Run scan_stencils.py to extract master information")
            return True
        except Exception as e:
            print(f"Error adding stencil: {e}")
            return False
    
    def remove_stencil(self, stencil_name: str) -> bool:
        """
        Remove a stencil from the library
        
        Args:
            stencil_name: Name or filename of the stencil
        
        Returns:
            True if successful
        """
        stencil_path = self.get_stencil(stencil_name)
        if not stencil_path:
            print(f"Stencil not found: {stencil_name}")
            return False
        
        try:
            # Remove file
            os.remove(stencil_path)
            
            # Remove from library
            filename = os.path.basename(stencil_path)
            if filename in self.library:
                del self.library[filename]
                self._save_library()
            
            print(f"Removed stencil: {stencil_name}")
            return True
        except Exception as e:
            print(f"Error removing stencil: {e}")
            return False
    
    def get_stencil_info(self, stencil_name: str, live_scan: bool = True) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a stencil including master statistics
        
        Args:
            stencil_name: Name or filename of the stencil
            live_scan: If True, scan the file directly when cached data is missing/incomplete
        
        Returns:
            Stencil information dictionary with detailed master info or None
        """
        stencil_path = self.get_stencil(stencil_name)
        if not stencil_path:
            return None
        
        filename = os.path.basename(stencil_path)
        
        # Determine relative path from stencil_dir for library lookup
        # This handles subdirectories like "IT Vendors/xxx.vssx"
        try:
            rel_path = os.path.relpath(stencil_path, self.stencil_dir)
        except ValueError:
            # If paths are on different drives (Windows), use filename
            rel_path = filename
        
        library_info = self.library.get(rel_path, {})
        
        # Check if we need to do a live scan
        # Scan if: library is empty OR master_count is 0 and live_scan is enabled
        need_scan = (not library_info or library_info.get('master_count', 0) == 0) and live_scan
        
        if need_scan:
            try:
                print(f"  扫描 VSSX 文件: {filename} ...")
                scan_data = StencilScanner.scan_stencil(stencil_path)
                
                if 'error' in scan_data:
                    print(f"  ✗ 扫描错误: {scan_data['error']}")
                else:
                    # Merge scan data with existing library info
                    # Preserve manual metadata (name, category) if exists
                    library_info = {
                        'name': library_info.get('name', filename.replace('.vssx', '').replace('.vss', '')),
                        'category': library_info.get('category', 'general'),
                        'keywords': library_info.get('keywords', []),
                        'use_cases': library_info.get('use_cases', []),
                        'masters': scan_data.get('masters', {}),
                        'master_count': scan_data.get('master_count', 0),
                        'master_names': scan_data.get('master_names', []),
                        'complexity': scan_data.get('complexity', 'unknown'),
                        'scan_date': scan_data.get('scan_date', ''),
                    }
                    
                    # Update library cache
                    self.library[rel_path] = library_info
                    self._save_library()
                    print(f"  ✓ 发现 {library_info['master_count']} 个主形状")
                    
            except Exception as e:
                print(f"  ✗ 扫描失败: {e}")
                # Continue with whatever library_info we have
        
        # Build info from library (now potentially updated with live scan)
        info = {
            'filename': filename,
            'name': library_info.get('name', filename.replace('.vssx', '').replace('.vss', '')),
            'category': library_info.get('category', 'general'),
            'path': stencil_path,
            'size': os.path.getsize(stencil_path),
            'description': library_info.get('description', ''),
            'masters': library_info.get('masters', {}),
            'master_count': library_info.get('master_count', 0),
            'master_names': library_info.get('master_names', []),
            'complexity': library_info.get('complexity', 'unknown'),
            'keywords': library_info.get('keywords', []),
            'use_cases': library_info.get('use_cases', []),
            'scan_date': library_info.get('scan_date', '')
        }
        
        return info
    
    def update_stencil_metadata(self, stencil_name: str, **metadata) -> bool:
        """
        Update metadata for a stencil in the library
        
        Args:
            stencil_name: Name or filename of the stencil
            **metadata: Metadata fields to update (e.g., keywords, use_cases, description)
        
        Returns:
            True if update successful, False otherwise
        """
        stencil_path = self.get_stencil(stencil_name)
        if not stencil_path:
            return False
        
        filename = os.path.basename(stencil_path)
        
        # Determine relative path from stencil_dir for library lookup
        try:
            rel_path = os.path.relpath(stencil_path, self.stencil_dir)
        except ValueError:
            # If paths are on different drives (Windows), use filename
            rel_path = filename
        
        # Get or create library entry
        if rel_path not in self.library:
            self.library[rel_path] = {
                'name': filename.replace('.vssx', '').replace('.vss', ''),
                'category': 'general',
            }
        
        # Update metadata
        for key, value in metadata.items():
            if value is not None:  # Only update non-None values
                self.library[rel_path][key] = value
        
        # Save to file
        self._save_library()
        return True
    
    def _load_library(self) -> Dict[str, Any]:
        """Load stencil library from JSON file"""
        if os.path.exists(self.library_file):
            try:
                with open(self.library_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading library: {e}")
                return {}
        return {}
    
    def _save_library(self):
        """Save stencil library to JSON file"""
        try:
            with open(self.library_file, 'w', encoding='utf-8') as f:
                json.dump(self.library, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving library: {e}")
    
    def scan_all_stencils(self, update_metadata: bool = True) -> Dict[str, Any]:
        """
        Scan all stencils in the directory and update the library
        
        Args:
            update_metadata: If True, merge scan results with existing metadata
            
        Returns:
            Dictionary of scan results with 'library' and 'removed' keys
        """
        print(f"Scanning stencils in {self.stencil_dir}...")
        scan_results = StencilScanner.scan_directory(self.stencil_dir)
        
        # Check for removed files and clean up library
        removed_files = []
        existing_filenames = list(self.library.keys())
        for filename in existing_filenames:
            file_path = os.path.join(self.stencil_dir, filename)
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
            print(f"  Auto-generating metadata for {filename}...")
            metadata = MetadataGenerator.generate_stencil_metadata(scan_data, category)
            
            # Merge scan data with existing library entry
            # Preserve manual edits (name, category)
            # Update auto-scanned data (masters, master_count, keywords, use_cases)
            library_entry = {
                'name': existing.get('name', filename.replace('.vssx', '')),
                'category': existing.get('category', 'general'),
                'keywords': metadata['keywords'],
                'use_cases': metadata['use_cases'],
                'masters': scan_data.get('masters', {}),
                'master_count': scan_data.get('master_count', 0),
                'master_names': scan_data.get('master_names', []),
                'complexity': scan_data.get('complexity', 'unknown'),
                'scan_date': scan_data.get('scan_date', ''),
            }
            
            self.library[filename] = library_entry
        
        # Save the updated library
        self._save_library()
        print(f"Scanned {len(scan_results)} stencils")
        if removed_files:
            print(f"Removed {len(removed_files)} deleted files from library")
        
        return {
            'library': self.library,
            'removed': removed_files
        }

    def list_stencil_masters(self, stencil_name: str, use_cache: bool = True) -> Optional[List[str]]:
        """
        List master names for a given stencil.
        
        Args:
            stencil_name: Name or filename of the stencil
            use_cache: If True, use cached data from library; if False, rescan
        
        Returns:
            List of master names, or None if error
        """
        stencil_path = self.get_stencil(stencil_name)
        if not stencil_path:
            print(f"Stencil not found: {stencil_name}")
            return None
        
        filename = os.path.basename(stencil_path)
        
        # Try to use cached data from library
        if use_cache and filename in self.library:
            return self.library[filename].get('master_names', [])
        
        # Otherwise, scan the stencil
        try:
            scan = StencilScanner.scan_stencil(stencil_path)
            if 'error' in scan:
                print(f"Error scanning stencil '{stencil_name}': {scan.get('error')}")
                return None
            return scan.get('master_names', [])
        except Exception as e:
            print(f"Error listing masters: {e}")
            return None
    
    def print_stencil_info(self, stencil_name: str) -> bool:
        """
        Print formatted information for a stencil
        
        Args:
            stencil_name: Name or filename of the stencil
            
        Returns:
            True if successful
        """
        info = self.get_stencil_info(stencil_name)
        if not info:
            print(f"Stencil not found: {stencil_name}")
            return False
        
        print(f"\n形状库: {info['name']}")
        print(f"文件: {info['filename']}")
        print(f"类别: {info['category']}")
        print(f"复杂度: {info['complexity']}")
        print(f"\n主形状统计:")
        print(f"  总数: {info['master_count']}")
        
        master_names = info.get('master_names', [])
        if master_names:
            print(f"\n  主形状列表 (前20个):")
            for i, name in enumerate(master_names[:20], 1):
                print(f"    {i:2}. {name}")
            if len(master_names) > 20:
                print(f"    ... 还有 {len(master_names) - 20} 个")
        else:
            print(f"  (无主形状信息，请运行 scan_all_stencils 更新)")
        
        if info.get('keywords'):
            print(f"\n关键词: {', '.join(info['keywords'])}")
        
        if info.get('use_cases'):
            print(f"适用场景: {', '.join(info['use_cases'])}")
        
        if info.get('scan_date'):
            print(f"\n扫描时间: {info['scan_date']}")
        
        return True
    
    def search_stencils(self, keywords: Optional[List[str]] = None, 
                        category: Optional[str] = None,
                        complexity: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search stencils by keywords, category, or complexity
        
        Args:
            keywords: List of keywords to match (case-insensitive)
            category: Category to filter by
            complexity: Complexity level ('simple', 'medium', 'complex')
            
        Returns:
            List of matching stencil information
        """
        results = []
        
        for filename, info in self.library.items():
            # Trust the JSON data - no file system check needed here
            # File existence will be validated only when actually loading the stencil
            stencil_path = os.path.join(self.stencil_dir, filename)
            
            # Filter by category
            if category and info.get('category', '').lower() != category.lower():
                continue
            
            # Filter by complexity
            if complexity and info.get('complexity', '').lower() != complexity.lower():
                continue
            
            # Filter by keywords
            if keywords:
                # Search in name, keywords, use_cases, master_names
                searchable_text = ' '.join([
                    info.get('name', ''),
                    ' '.join(info.get('keywords', [])),
                    ' '.join(info.get('use_cases', [])),
                    ' '.join(info.get('master_names', [])),
                ]).lower()
                
                # Check if any keyword matches
                if not any(kw.lower() in searchable_text for kw in keywords):
                    continue
            
            # Add to results
            result = {
                'filename': filename,
                'path': stencil_path,
                **info
            }
            results.append(result)
        
        return results
    
    def get_library_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the stencil library
        
        Returns:
            Dictionary with library statistics
        """
        total = len(self.library)
        by_category = {}
        by_complexity = {}
        total_masters = 0
        
        for info in self.library.values():
            category = info.get('category', 'general')
            by_category[category] = by_category.get(category, 0) + 1
            
            complexity = info.get('complexity', 'unknown')
            by_complexity[complexity] = by_complexity.get(complexity, 0) + 1
            
            total_masters += info.get('master_count', 0)
        
        return {
            'total_stencils': total,
            'total_masters': total_masters,
            'by_category': by_category,
            'by_complexity': by_complexity,
        }
