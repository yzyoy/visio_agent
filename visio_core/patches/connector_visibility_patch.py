"""Patch to fix connector visibility issue in Visio diagrams

This patch ensures that connectors created via vsdx.Connect.create() are properly
added to the page's Shapes XML element and persisted when saving.
"""
import xml.etree.ElementTree as ET
from typing import Any, Optional

def apply_connector_visibility_patch():
    """Apply patch to ensure connectors are visible in saved VSDX files"""
    
    # Import at runtime to avoid circular imports
    from visio_core.utils.diagram_builder import DiagramBuilder
    
    # Store original connect_shapes method
    original_connect_shapes = DiagramBuilder.connect_shapes
    
    def patched_connect_shapes(self, from_shape_id: str, to_shape_id: str, 
                              from_glue_point: Optional[str] = None, 
                              to_glue_point: Optional[str] = None) -> Optional[Any]:
        """Patched version of connect_shapes that ensures connector persistence"""
        
        # Call original method
        new_connector = original_connect_shapes(self, from_shape_id, to_shape_id, 
                                               from_glue_point, to_glue_point)
        
        if new_connector and hasattr(new_connector, 'xml') and new_connector.xml is not None:
            # CRITICAL FIX: Ensure connector is added to page's Shapes element
            if hasattr(self.current_page, 'xml') and self.current_page.xml is not None:
                ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
                
                # Find the Shapes element in page XML
                shapes_elem = self.current_page.xml.find('.//v:Shapes', ns)
                if shapes_elem is None:
                    shapes_elem = self.current_page.xml.find('.//Shapes')
                
                if shapes_elem is not None:
                    # Check if connector XML is already in shapes_elem
                    connector_id = str(getattr(new_connector, 'ID', ''))
                    already_added = False
                    
                    for child in shapes_elem:
                        if child.get('ID') == connector_id:
                            already_added = True
                            break
                    
                    if not already_added:
                        # Ensure connector XML has proper structure
                        if new_connector.xml.tag.endswith('Shape'):
                            # Add Type='Shape' attribute if missing
                            if 'Type' not in new_connector.xml.attrib:
                                new_connector.xml.set('Type', 'Shape')
                            
                            # Add Line element if missing to ensure visibility
                            line_elem = new_connector.xml.find('.//v:Line', ns)
                            if line_elem is None:
                                line_elem = new_connector.xml.find('.//Line')
                            
                            if line_elem is None:
                                # Create Line element with visible properties
                                line_elem = ET.SubElement(new_connector.xml, 
                                                        '{http://schemas.microsoft.com/office/visio/2012/main}Line')
                                
                                # Add essential Line cells for visibility
                                line_cells = [
                                    ('LineWeight', '0.01041667'),  # Standard thickness
                                    ('LineColor', '0'),            # Black
                                    ('LinePattern', '1'),          # Solid line
                                    ('EndArrow', '4'),             # Arrow head
                                ]
                                
                                for cell_name, cell_value in line_cells:
                                    cell = ET.SubElement(line_elem, 
                                                       '{http://schemas.microsoft.com/office/visio/2012/main}Cell')
                                    cell.set('N', cell_name)
                                    cell.set('V', cell_value)
                            else:
                                # Ensure critical visibility properties are set
                                for cell in line_elem:
                                    if cell.get('N') == 'LinePattern' and cell.get('V', '') in ['', '0']:
                                        cell.set('V', '1')  # Force solid line
                                    elif cell.get('N') == 'LineWeight' and not cell.get('V'):
                                        cell.set('V', '0.01041667')
                                    elif cell.get('N') == 'LineColor' and not cell.get('V'):
                                        cell.set('V', '0')
                            
                            # Ensure connector has proper style attributes
                            if 'LineStyle' not in new_connector.xml.attrib:
                                new_connector.xml.set('LineStyle', '3')  # Use a visible line style
                            if 'FillStyle' not in new_connector.xml.attrib:
                                new_connector.xml.set('FillStyle', '3')  # Use a standard fill style
                            if 'TextStyle' not in new_connector.xml.attrib:
                                new_connector.xml.set('TextStyle', '3')  # Use a standard text style
                            
                            # Append connector to shapes
                            shapes_elem.append(new_connector.xml)
                            print(f"[OK] Connector XML added to page's Shapes element (ID: {connector_id})")
                            
                            # CRITICAL: Ensure XForm section has proper coordinate values
                            xform_elem = new_connector.xml.find('.//v:XForm', ns)
                            if xform_elem is None:
                                xform_elem = new_connector.xml.find('.//XForm')
                            
                            if xform_elem is not None:
                                # Check critical cells
                                for cell_name in ['PinX', 'PinY', 'Width', 'Height']:
                                    cell = xform_elem.find(f'.//v:Cell[@N="{cell_name}"]', ns) or xform_elem.find(f'.//Cell[@N="{cell_name}"]')
                                    if cell is not None and not cell.get('V') and not cell.get('F'):
                                        # Set default values to prevent zero-size connector
                                        if cell_name in ['PinX', 'PinY']:
                                            cell.set('V', '0')
                                        elif cell_name == 'Width':
                                            cell.set('V', '1')
                                        elif cell_name == 'Height':
                                            cell.set('V', '0')
                            
                            # Ensure XForm1D has proper Begin/End coordinates
                            xform1d_elem = new_connector.xml.find('.//v:XForm1D', ns)
                            if xform1d_elem is None:
                                xform1d_elem = new_connector.xml.find('.//XForm1D')
                                
                            if xform1d_elem is not None:
                                # Check Begin/End coordinates
                                for coord in ['BeginX', 'BeginY', 'EndX', 'EndY']:
                                    cell = xform1d_elem.find(f'.//v:Cell[@N="{coord}"]', ns) or xform1d_elem.find(f'.//Cell[@N="{coord}"]')
                                    if cell is not None and not cell.get('V') and not cell.get('F'):
                                        # Prevent zero-length connector
                                        default_val = '0' if coord.endswith('Y') else ('1' if coord.startswith('End') else '0')
                                        cell.set('V', default_val)
                            # Force page to recognize new shape
                            # NOTE: _shapes is a @property on Page, not a cached attribute.
                            # Setting it to None shadows the property and breaks child_shapes.
                            # Instead, just let the property re-read from XML naturally.
                                
                            # Mark visio file as modified
                            if hasattr(self.visio_file, '_modified'):
                                self.visio_file._modified = True
                                
                        else:
                            print(f"Warning: Connector XML has unexpected tag: {new_connector.xml.tag}")
                else:
                    print("Warning: Could not find Shapes element in page XML - creating one")
                    # Create Shapes element if it doesn't exist
                    shapes_elem = ET.SubElement(self.current_page.xml, 
                                              '{http://schemas.microsoft.com/office/visio/2012/main}Shapes')
                    shapes_elem.append(new_connector.xml)
        
        return new_connector
    
    # Apply patch
    DiagramBuilder.connect_shapes = patched_connect_shapes
    # print("✓ Connector visibility patch applied successfully")

# Auto-apply patch when module is imported
apply_connector_visibility_patch()