"""
Stencil Importer - Import master shapes from VSSX stencil files into VSDX diagrams

This module provides functionality to properly import master shapes from external
VSSX stencil files into VSDX diagram files, addressing the issue where shapes
would be incorrectly replaced instead of properly imported.
"""
import os
import zipfile
import xml.etree.ElementTree as ET
import shutil
import tempfile
from typing import Optional, Dict, Any, List
from pathlib import Path


class StencilImporter:
    """Imports master shapes from VSSX stencil files into VSDX diagrams"""
    
    # Visio XML namespaces
    NAMESPACES = {
        'v': 'http://schemas.microsoft.com/office/visio/2012/main',
        'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
        'rel': 'http://schemas.openxmlformats.org/package/2006/relationships'
    }
    
    def __init__(self, vsdx_path: str):
        """
        Initialize the StencilImporter
        
        Args:
            vsdx_path: Path to the target VSDX file where masters will be imported
        """
        self.vsdx_path = vsdx_path
        self._imported_masters_cache: Dict[str, str] = {}  # master_name -> master_id in VSDX
        
    def import_master_from_vssx(self, vssx_path: str, master_name: str) -> Optional[Dict[str, Any]]:
        """
        Import a master shape from VSSX stencil into the VSDX diagram
        
        This method:
        1. Opens the VSSX stencil file
        2. Finds the requested master by name
        3. Extracts the master's XML definition
        4. Imports it into the VSDX document's master collection
        5. Updates all necessary relationships and indices
        
        Args:
            vssx_path: Path to the VSSX stencil file
            master_name: Name of the master shape to import
            
        Returns:
            Dictionary with import result:
            {
                'success': bool,
                'master_id': str,  # ID of the imported master in VSDX
                'master_name': str,
                'message': str
            }
        """
        # Check if already imported
        cache_key = f"{vssx_path}::{master_name}"
        if cache_key in self._imported_masters_cache:
            return {
                'success': True,
                'master_id': self._imported_masters_cache[cache_key],
                'master_name': master_name,
                'message': 'Master already imported (cached)'
            }
        
        # Validate files exist
        if not os.path.exists(vssx_path):
            return {
                'success': False,
                'message': f'VSSX file not found: {vssx_path}'
            }
        
        if not os.path.exists(self.vsdx_path):
            return {
                'success': False,
                'message': f'VSDX file not found: {self.vsdx_path}'
            }
        
        try:
            # Step 1: Extract master from VSSX
            master_info = self._extract_master_from_vssx(vssx_path, master_name)
            if not master_info:
                return {
                    'success': False,
                    'message': f"Master '{master_name}' not found in {os.path.basename(vssx_path)}"
                }
            
            # Step 2: Import master into VSDX
            result = self._import_master_to_vsdx(master_info, vssx_path)
            
            if result['success']:
                # Cache the successful import
                self._imported_masters_cache[cache_key] = result['master_id']
            
            return result
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Error importing master: {str(e)}'
            }
    
    def _extract_master_from_vssx(self, vssx_path: str, master_name: str) -> Optional[Dict[str, Any]]:
        """
        Extract master shape definition from VSSX file
        
        Args:
            vssx_path: Path to VSSX stencil file
            master_name: Name of the master to extract
            
        Returns:
            Dictionary containing master information and XML data
        """
        try:
            with zipfile.ZipFile(vssx_path, 'r') as vssx_zip:
                # Read masters.xml to find the master
                with vssx_zip.open('visio/masters/masters.xml') as f:
                    masters_tree = ET.parse(f)
                    masters_root = masters_tree.getroot()
                    
                    # Register namespaces
                    for prefix, uri in self.NAMESPACES.items():
                        ET.register_namespace(prefix, uri)
                    
                    # Find master by name (check both Name and NameU attributes)
                    master_element = None
                    for master in masters_root.findall('.//v:Master', self.NAMESPACES):
                        name = master.get('Name', '')
                        name_u = master.get('NameU', '')
                        if name == master_name or name_u == master_name:
                            master_element = master
                            break
                    
                    if not master_element:
                        return None
                    
                    master_id = master_element.get('ID')
                    # Resolve masterN.xml via masters.xml.rels using the relationship id on the Master element
                    rel_id = master_element.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
                    master_filename = None
                    try:
                        with vssx_zip.open('visio/masters/_rels/masters.xml.rels') as rels_f:
                            rels_tree = ET.parse(rels_f)
                            rels_root = rels_tree.getroot()
                            for rel in rels_root.findall('{http://schemas.openxmlformats.org/package/2006/relationships}Relationship'):
                                if rel.get('Id') == rel_id:
                                    target = rel.get('Target')
                                    if target:
                                        # Target is relative to visio/masters/
                                        master_filename = f"visio/masters/{target}"
                                    break
                    except Exception:
                        master_filename = None
                    
                    # Fallback to index-based mapping if rels is missing
                    if not master_filename:
                        master_filename = self._find_master_xml_file_by_id(vssx_zip, master_id, masters_root)
                    if not master_filename:
                        return None
                    
                    with vssx_zip.open(master_filename) as mf:
                        master_xml = mf.read()
                    
                    return {
                        'master_id': master_id,
                        'master_name': master_name,
                        'master_element': master_element,
                        'master_xml': master_xml,
                        'master_filename': master_filename,
                        'masters_tree': masters_tree,
                        'masters_root': masters_root
                    }
                    
        except Exception as e:
            print(f"Error extracting master from VSSX: {e}")
            return None
    
    def _find_master_xml_file_by_id(self, vssx_zip: zipfile.ZipFile, master_id: str, 
                                     masters_root: ET.Element) -> Optional[str]:
        """
        Find the master XML file by master ID
        
        In VSSX files, masters are stored in master1.xml, master2.xml, etc.
        We use the order in masters.xml to map to the correct file.
        
        Args:
            vssx_zip: Open ZipFile object for VSSX
            master_id: Master ID to find
            masters_root: Root element of masters.xml
            
        Returns:
            Path to master XML file within the zip
        """
        try:
            # Get all masters in order from masters.xml
            all_masters = masters_root.findall('.//v:Master', self.NAMESPACES)
            
            # Find the index of our target master
            target_index = None
            for i, master in enumerate(all_masters):
                if master.get('ID') == master_id:
                    target_index = i
                    break
            
            if target_index is None:
                return None
            
            # Get sorted list of master files (master1.xml, master2.xml, etc.)
            master_files = sorted([f for f in vssx_zip.namelist() 
                                  if f.startswith('visio/masters/master') 
                                  and f.endswith('.xml') 
                                  and f != 'visio/masters/masters.xml'])
            
            # Map by index (assuming they're in the same order)
            if target_index < len(master_files):
                return master_files[target_index]
            
            # Fallback: return first master file
            if master_files:
                return master_files[0]
            
            return None
        except Exception as e:
            print(f"Error finding master XML file: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _import_master_to_vsdx(self, master_info: Dict[str, Any], vssx_path: str) -> Dict[str, Any]:
        """
        Import the extracted master into the VSDX document
        
        This creates a temporary working directory, modifies the VSDX structure,
        and rebuilds the file with the new master included.
        
        Args:
            master_info: Master information from _extract_master_from_vssx
            vssx_path: Path to source VSSX file (for error messages)
            
        Returns:
            Dictionary with import result
        """
        temp_dir = None
        try:
            # Create temporary directory for VSDX manipulation
            temp_dir = tempfile.mkdtemp(prefix='vsdx_import_')
            
            # Extract VSDX to temp directory
            with zipfile.ZipFile(self.vsdx_path, 'r') as vsdx_zip:
                vsdx_zip.extractall(temp_dir)
            
            # Get the next available master ID in VSDX
            vsdx_masters_xml = os.path.join(temp_dir, 'visio', 'masters', 'masters.xml')
            
            # Create masters directory if it doesn't exist
            masters_dir = os.path.join(temp_dir, 'visio', 'masters')
            os.makedirs(masters_dir, exist_ok=True)
            os.makedirs(os.path.join(masters_dir, '_rels'), exist_ok=True)
            
            # Load or create masters.xml
            if os.path.exists(vsdx_masters_xml):
                vsdx_masters_tree = ET.parse(vsdx_masters_xml)
                vsdx_masters_root = vsdx_masters_tree.getroot()
            else:
                # Create new masters.xml structure
                vsdx_masters_root = ET.Element('{http://schemas.microsoft.com/office/visio/2012/main}Masters')
                vsdx_masters_tree = ET.ElementTree(vsdx_masters_root)
            
            # Find next available master ID
            existing_ids = [int(m.get('ID', 0)) for m in vsdx_masters_root.findall('.//v:Master', self.NAMESPACES)]
            next_master_id = str(max(existing_ids) + 1 if existing_ids else 1)
            
            # Find next available master file number
            existing_master_files = [f for f in os.listdir(masters_dir) if f.startswith('master') and f.endswith('.xml') and f != 'masters.xml']
            next_master_num = len(existing_master_files) + 1
            new_master_filename = f'master{next_master_num}.xml'
            
            # Copy master element and update ID
            new_master_element = ET.fromstring(ET.tostring(master_info['master_element']))
            new_master_element.set('ID', next_master_id)
            
            # Create new relationship ID
            new_rel_id = f'rId{next_master_num}'
            new_master_element.set('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id', new_rel_id)
            
            # Add master element to VSDX masters.xml
            vsdx_masters_root.append(new_master_element)
            
            # Write updated masters.xml
            self._write_xml_with_declaration(vsdx_masters_tree, vsdx_masters_xml)
            
            # Copy master XML file
            new_master_path = os.path.join(masters_dir, new_master_filename)
            with open(new_master_path, 'wb') as f:
                f.write(master_info['master_xml'])
            
            # Update masters.xml.rels
            self._update_masters_rels(temp_dir, new_rel_id, new_master_filename)
            
            # Copy master rels and referenced assets if present
            self._copy_master_relationships_and_assets(vssx_path, master_info, temp_dir)
            
            # Update [Content_Types].xml to include new master
            self._update_content_types(temp_dir, new_master_filename)
            
            # Rebuild VSDX file
            self._rebuild_vsdx(temp_dir, self.vsdx_path)
            
            return {
                'success': True,
                'master_id': next_master_id,
                'master_name': master_info['master_name'],
                'message': f"Successfully imported master '{master_info['master_name']}' from {os.path.basename(vssx_path)}"
            }
            
        except Exception as e:
            import traceback
            return {
                'success': False,
                'message': f'Error during master import: {str(e)}\n{traceback.format_exc()}'
            }
        finally:
            # Clean up temporary directory
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass

    def _copy_master_relationships_and_assets(self, vssx_path: str, master_info: Dict[str, Any], temp_dir: str):
        """Copy masterN.xml.rels and any referenced assets (e.g., media) into the VSDX structure."""
        try:
            master_filename = os.path.basename(master_info.get('master_filename', ''))
            if not master_filename:
                return
            rels_name = f"visio/masters/_rels/{master_filename}.rels"
            with zipfile.ZipFile(vssx_path, 'r') as vssx_zip:
                if rels_name not in vssx_zip.namelist():
                    return
                # Copy the rels file itself
                dest_rels_path = os.path.join(temp_dir, 'visio', 'masters', '_rels', f'{master_filename}.rels')
                with vssx_zip.open(rels_name) as src, open(dest_rels_path, 'wb') as dst:
                    dst.write(src.read())
                # Parse rels to copy referenced parts (e.g., media)
                rels_tree = ET.parse(dest_rels_path)
                rels_root = rels_tree.getroot()
                for rel in rels_root.findall('{http://schemas.openxmlformats.org/package/2006/relationships}Relationship'):
                    target = rel.get('Target')
                    if not target:
                        continue
                    # Targets are relative to visio/masters/
                    # Normalize to VSDX root
                    target_path = os.path.normpath(os.path.join('visio/masters', target))
                    # We only handle visio/media/* or visio/masters/* here
                    if not target_path.startswith('visio/'):
                        continue
                    # Ensure destination directory exists
                    dest_abs = os.path.join(temp_dir, target_path)
                    os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
                    # If source exists in vssx, copy it
                    if target_path in vssx_zip.namelist():
                        with vssx_zip.open(target_path) as s, open(dest_abs, 'wb') as d:
                            d.write(s.read())
        except Exception:
            # Best-effort only
            return
    
    def _update_masters_rels(self, temp_dir: str, rel_id: str, master_filename: str):
        """Update masters.xml.rels with new relationship"""
        rels_path = os.path.join(temp_dir, 'visio', 'masters', '_rels', 'masters.xml.rels')
        
        if os.path.exists(rels_path):
            rels_tree = ET.parse(rels_path)
            rels_root = rels_tree.getroot()
        else:
            # Create new rels structure
            rels_root = ET.Element('{http://schemas.openxmlformats.org/package/2006/relationships}Relationships')
            rels_tree = ET.ElementTree(rels_root)
        
        # Add new relationship
        new_rel = ET.SubElement(rels_root, '{http://schemas.openxmlformats.org/package/2006/relationships}Relationship')
        new_rel.set('Id', rel_id)
        new_rel.set('Type', 'http://schemas.microsoft.com/visio/2010/relationships/master')
        new_rel.set('Target', master_filename)
        
        self._write_xml_with_declaration(rels_tree, rels_path)
    
    def _update_content_types(self, temp_dir: str, master_filename: str):
        """Update [Content_Types].xml to include new master"""
        content_types_path = os.path.join(temp_dir, '[Content_Types].xml')
        
        if not os.path.exists(content_types_path):
            return
        
        tree = ET.parse(content_types_path)
        root = tree.getroot()
        
        # Check if override already exists
        part_name = f'/visio/masters/{master_filename}'
        existing = root.find(f".//{{http://schemas.openxmlformats.org/package/2006/content-types}}Override[@PartName='{part_name}']")
        
        if not existing:
            # Add new override
            override = ET.SubElement(root, '{http://schemas.openxmlformats.org/package/2006/content-types}Override')
            override.set('PartName', part_name)
            override.set('ContentType', 'application/vnd.ms-visio.master+xml')
            
            self._write_xml_with_declaration(tree, content_types_path)
    
    def _rebuild_vsdx(self, temp_dir: str, output_path: str):
        """Rebuild VSDX file from temporary directory"""
        # Create new zip file
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as vsdx_zip:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, temp_dir)
                    vsdx_zip.write(file_path, arcname)
    
    def _write_xml_with_declaration(self, tree: ET.ElementTree, filepath: str):
        """Write XML with proper declaration"""
        with open(filepath, 'wb') as f:
            tree.write(f, encoding='utf-8', xml_declaration=True)
    
    def clear_cache(self):
        """Clear the imported masters cache"""
        self._imported_masters_cache.clear()
    
    def list_imported_masters(self) -> List[str]:
        """Get list of imported master names"""
        return [key.split('::')[1] for key in self._imported_masters_cache.keys()]

