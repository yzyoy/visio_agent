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
                        if new_connector.xml.tag.endswith('Shape'):
                            if 'Type' not in new_connector.xml.attrib:
                                new_connector.xml.set('Type', 'Shape')
                            # Style attributes ensure inherited line/fill/text styles resolve.
                            if 'LineStyle' not in new_connector.xml.attrib:
                                new_connector.xml.set('LineStyle', '3')
                            if 'FillStyle' not in new_connector.xml.attrib:
                                new_connector.xml.set('FillStyle', '3')
                            if 'TextStyle' not in new_connector.xml.attrib:
                                new_connector.xml.set('TextStyle', '3')

                            # NOTE: We deliberately do NOT synthesize <Line>,
                            # <XForm> or <XForm1D> wrapper elements here.
                            # The vsdx 2012/main schema flattens those into
                            # top-level Cell elements. Wrapper elements
                            # historically caused Microsoft Visio to refuse
                            # to open the file. Visibility-critical Cells
                            # are added by ``DiagramBuilder
                            # ._ensure_connector_visibility_cells`` after
                            # the connector is constructed.

                            shapes_elem.append(new_connector.xml)
                            print(f"[OK] Connector XML added to page's Shapes element (ID: {connector_id})")

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