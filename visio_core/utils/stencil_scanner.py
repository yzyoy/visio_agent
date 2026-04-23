"""
Stencil scanner utility for analyzing Visio stencil files
Extracts master shape information and metadata from .vssx files
"""
import os
import sys
from typing import Dict, List, Any
from datetime import datetime

# Add project root to path to import StencilParser
project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from .stencil_parser import StencilParser


class StencilScanner:
    """Scans Visio stencils and extracts master shape information"""
    
    @staticmethod
    def scan_stencil(vssx_path: str) -> Dict[str, Any]:
        """
        Scan a .vssx stencil file and extract information
        
        Args:
            vssx_path: Path to the .vssx file
            
        Returns:
            Dictionary with stencil metadata and master shape information
        """
        try:
            # Load the stencil using StencilParser
            parser = StencilParser(vssx_path)
            masters_list = parser.list_masters()
            
            # Build masters dictionary (id -> info)
            masters = {}
            master_names = []
            
            for master in masters_list:
                master_id = master.get('id', '')
                master_name = master.get('name', '') or master.get('nameU', '') or f"Master-{master_id}"
                
                masters[master_id] = {
                    'name': master_name,
                    'nameU': master.get('nameU', ''),
                    'master_type': master.get('master_type', '2'),
                    'base_id': master.get('base_id', ''),
                    'unique_id': master.get('unique_id', ''),
                }
                
                master_names.append(master_name)
            
            master_count = len(masters)
            
            # Calculate complexity based on master count
            complexity = StencilScanner._calculate_complexity(master_count)
            
            return {
                'filename': os.path.basename(vssx_path),
                'scan_date': datetime.now().isoformat(),
                'masters': masters,
                'master_count': master_count,
                'master_names': master_names,
                'complexity': complexity,
            }
            
        except Exception as e:
            return {
                'filename': os.path.basename(vssx_path),
                'error': str(e),
                'scan_date': datetime.now().isoformat(),
            }
    
    @staticmethod
    def _calculate_complexity(master_count: int) -> str:
        """
        Calculate stencil complexity based on number of masters
        
        Args:
            master_count: Number of master shapes in stencil
            
        Returns:
            Complexity level: 'simple', 'medium', or 'complex'
        """
        if master_count < 10:
            return 'simple'
        elif master_count <= 50:
            return 'medium'
        else:
            return 'complex'
    
    @staticmethod
    def scan_directory(directory_path: str, pattern: str = "*.vssx", recursive: bool = True) -> Dict[str, Dict[str, Any]]:
        """
        Scan all .vssx files in a directory (recursively by default)
        
        Args:
            directory_path: Path to directory containing stencils
            pattern: File pattern to match (default: *.vssx)
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
                    if filename.endswith('.vssx'):
                        filepath = os.path.join(root, filename)
                        # Use relative path from the base directory as key
                        rel_path = os.path.relpath(filepath, directory_path)
                        print(f"  扫描: {rel_path}")
                        scan_result = StencilScanner.scan_stencil(filepath)
                        results[rel_path] = scan_result
        else:
            # Only scan the top-level directory
            for filename in os.listdir(directory_path):
                filepath = os.path.join(directory_path, filename)
                if os.path.isfile(filepath) and filename.endswith('.vssx'):
                    print(f"  扫描: {filename}")
                    scan_result = StencilScanner.scan_stencil(filepath)
                    results[filename] = scan_result
        
        return results

