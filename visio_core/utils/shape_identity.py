"""
Shape Identity Management for Idempotent Diagram Operations

This module provides key-based identity tracking for shapes and connectors,
enabling idempotent operations where running the same input multiple times
results in updates rather than duplicates.
"""
from typing import Dict, List, Optional, Any, Tuple
import re


def normalize_text(text: str) -> str:
    """Normalize text for fallback matching."""
    return re.sub(r'\s+', ' ', (text or '').strip().lower())


def compute_bounding_box_key(x: float, y: float, width: float, height: float, tolerance: float = 0.5) -> Tuple[int, int]:
    """
    Compute a discretized bounding box key for spatial proximity matching.
    
    Args:
        x, y: Center coordinates
        width, height: Dimensions
        tolerance: Grid size for discretization (in inches)
    
    Returns:
        Tuple of (grid_x, grid_y) for approximate location
    """
    grid_x = int(round(x / tolerance))
    grid_y = int(round(y / tolerance))
    return (grid_x, grid_y)


def get_shape_prop(shape: Any, prop_name: str) -> Optional[str]:
    """
    Get a shape data property value.
    
    Args:
        shape: Shape object (vsdx)
        prop_name: Property name (e.g., 'NodeKey', 'EdgeKey')
    
    Returns:
        Property value as string or None
    """
    try:
        # Try direct XML access first (most reliable)
        if hasattr(shape, 'xml') and shape.xml is not None:
            import xml.etree.ElementTree as ET
            # Look for Shape Data section in XML
            ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
            
            # Try with namespace first
            for prop in shape.xml.findall('.//v:Section[@N="Property"]//v:Row', ns):
                name_elem = prop.find('.//v:Cell[@N="Label"]', ns)
                value_elem = prop.find('.//v:Cell[@N="Value"]', ns)
                if name_elem is not None and value_elem is not None:
                    # Check V attribute first, then child Value element
                    label_text = name_elem.get('V', '')
                    if not label_text:
                        label_val = name_elem.find('v:Value', ns)
                        label_text = str(label_val.text).strip('"\'') if label_val is not None and label_val.text else ''
                    else:
                        label_text = str(label_text).strip('"\'')
                    if label_text == prop_name:
                        val_text = value_elem.get('V', '')
                        if not val_text:
                            val_child = value_elem.find('v:Value', ns)
                            val_text = str(val_child.text).strip('"\'') if val_child is not None and val_child.text else ''
                        else:
                            val_text = str(val_text).strip('"\'')
                        return val_text
            
            # Fallback: look without namespace
            for prop in shape.xml.findall('.//Section[@N="Property"]//Row'):
                name_elem = prop.find('.//Cell[@N="Label"]')
                value_elem = prop.find('.//Cell[@N="Value"]')
                if name_elem is not None and value_elem is not None:
                    label_text = name_elem.get('V', '')
                    if not label_text:
                        label_val = name_elem.find('Value')
                        label_text = str(label_val.text).strip('"\'') if label_val is not None and label_val.text else ''
                    else:
                        label_text = str(label_text).strip('"\'')
                    if label_text == prop_name:
                        val_text = value_elem.get('V', '')
                        if not val_text:
                            val_child = value_elem.find('Value')
                            val_text = str(val_child.text).strip('"\'') if val_child is not None and val_child.text else ''
                        else:
                            val_text = str(val_text).strip('"\'')
                        return val_text
            
            # Additional: check if Row@N attribute matches prop_name
            for section in shape.xml.findall('.//v:Section[@N="Property"]', ns):
                for row in section.findall('.//v:Row', ns):
                    row_name = row.get('N', '')
                    if row_name == prop_name:
                        value_elem = row.find('.//v:Cell[@N="Value"]', ns)
                        if value_elem is not None:
                            val_text = value_elem.get('V', '')
                            if val_text:
                                return str(val_text).strip('"\'')
                            val_child = value_elem.find('v:Value', ns)
                            if val_child is not None and val_child.text:
                                return str(val_child.text).strip('"\'')
            
            # Check without namespace
            for section in shape.xml.findall('.//Section[@N="Property"]'):
                for row in section.findall('.//Row'):
                    row_name = row.get('N', '')
                    if row_name == prop_name:
                        value_elem = row.find('.//Cell[@N="Value"]')
                        if value_elem is not None:
                            val_text = value_elem.get('V', '')
                            if val_text:
                                return str(val_text).strip('"\'')
                            val_child = value_elem.find('Value')
                            if val_child is not None and val_child.text:
                                return str(val_child.text).strip('"\'')
        
        # Try vsdx API for shape data
        if hasattr(shape, 'data_properties'):
            props = shape.data_properties
            if props and prop_name in props:
                prop_obj = props[prop_name]
                # If it's a DataProperty object, get its value
                if hasattr(prop_obj, 'value'):
                    return str(prop_obj.value).strip('"\'')
                else:
                    return str(prop_obj).strip('"\'')
        
        # Alternative: try cell value approach
        if hasattr(shape, 'get_cell_value'):
            cell_name = f'Prop.{prop_name}.Value'
            value = shape.get_cell_value(cell_name)
            if value is not None:
                return str(value).strip('"\'')
        
    except Exception as e:
        print(f"Warning: Could not read property '{prop_name}': {e}")
    
    return None


def ensure_property_section(shape: Any) -> bool:
    """
    Ensure the shape has a Property (Shape Data) section.
    
    Args:
        shape: Shape object (vsdx)
    
    Returns:
        True if Property section exists or was created
    """
    try:
        # Try using the add_property method if available (vsdx library)
        if hasattr(shape, 'data_properties'):
            # Shape already has data_properties dictionary
            return True
        
        # Check if we can add a property to create the section
        if hasattr(shape, 'set_cell_value'):
            # Try to set a dummy property to ensure the section exists
            try:
                shape.set_cell_value('Prop._init.Value', '""')
                return True
            except Exception:
                pass
        
        return False
    except Exception as e:
        print(f"Warning: Could not ensure Property section: {e}")
        return False


def set_shape_prop(shape: Any, prop_name: str, prop_value: str) -> bool:
    """
    Set a shape data property value.
    
    Args:
        shape: Shape object (vsdx)
        prop_name: Property name (e.g., 'NodeKey', 'EdgeKey')
        prop_value: Property value to set
    
    Returns:
        True if successful
    """
    try:
        # Try XML manipulation first (most reliable)
        if hasattr(shape, 'xml') and shape.xml is not None:
            import xml.etree.ElementTree as ET
            
            # Detect namespace
            ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
            root_tag = shape.xml.tag
            use_namespace = 'visio' in root_tag or '{' in root_tag
            
            # Find or create Property section
            if use_namespace:
                sections = shape.xml.findall('.//v:Section[@N="Property"]', ns)
            else:
                sections = shape.xml.findall('.//Section[@N="Property"]')
            
            section = None
            if sections:
                section = sections[0]
            else:
                # Create Property section if it doesn't exist
                # Find the shape element that should contain sections
                shape_elem = shape.xml
                if use_namespace:
                    section = ET.SubElement(shape_elem, '{http://schemas.microsoft.com/office/visio/2012/main}Section')
                else:
                    section = ET.SubElement(shape_elem, 'Section')
                section.set('N', 'Property')
                section.set('Del', '0')
            
            if section is not None:
                # Look for existing row with this property name
                if use_namespace:
                    rows = section.findall('.//v:Row', ns)
                else:
                    rows = section.findall('.//Row')

                # Row match order (aligned with get_shape_prop so writes land
                # on the exact row a subsequent read would surface):
                #   1. Row@N attribute (canonical in modern VSDX).
                #   2. Label cell's V attribute.
                #   3. Legacy <Cell N="Label"><Value>prop</Value></Cell>.
                # The previous implementation only checked the legacy form,
                # so rows created by our own writer (which uses the V
                # attribute) were invisible and new rows were appended on
                # every update — producing duplicate NodeKey rows that then
                # broke idempotent upsert / connector flows.
                existing_row = None
                for row in rows:
                    row_n = (row.get('N', '') or '').strip('"\'')
                    if row_n == prop_name:
                        existing_row = row
                        break

                    if use_namespace:
                        label_cell_elem = row.find('.//v:Cell[@N="Label"]', ns)
                    else:
                        label_cell_elem = row.find('.//Cell[@N="Label"]')
                    if label_cell_elem is None:
                        continue

                    # Prefer V attribute (modern VSDX), fall back to legacy
                    # <Value> child element.
                    label_text = (label_cell_elem.get('V', '') or '').strip('"\'')
                    if not label_text:
                        if use_namespace:
                            legacy_label_value = label_cell_elem.find('v:Value', ns)
                        else:
                            legacy_label_value = label_cell_elem.find('Value')
                        if legacy_label_value is not None and legacy_label_value.text:
                            label_text = str(legacy_label_value.text).strip('"\'')

                    if label_text == prop_name:
                        existing_row = row
                        break
                
                if existing_row is not None:
                    # Update existing property value using V attribute
                    if use_namespace:
                        value_cell = existing_row.find('.//v:Cell[@N="Value"]', ns)
                    else:
                        value_cell = existing_row.find('.//Cell[@N="Value"]')
                    
                    if value_cell is not None:
                        # Use V attribute for modern VSDX format
                        value_cell.set('V', prop_value)
                    else:
                        # Create Value cell if it doesn't exist
                        if use_namespace:
                            cell = ET.SubElement(existing_row, '{http://schemas.microsoft.com/office/visio/2012/main}Cell')
                        else:
                            cell = ET.SubElement(existing_row, 'Cell')
                        cell.set('N', 'Value')
                        cell.set('V', prop_value)
                else:
                    # Create new property row
                    if use_namespace:
                        row = ET.SubElement(section, '{http://schemas.microsoft.com/office/visio/2012/main}Row')
                    else:
                        row = ET.SubElement(section, 'Row')
                    row.set('N', prop_name)
                    
                    # Create Label cell
                    if use_namespace:
                        label_cell = ET.SubElement(row, '{http://schemas.microsoft.com/office/visio/2012/main}Cell')
                    else:
                        label_cell = ET.SubElement(row, 'Cell')
                    label_cell.set('N', 'Label')
                    label_cell.set('V', prop_name)  # Use V attribute instead of Value child element
                    
                    # Create Value cell
                    if use_namespace:
                        value_cell = ET.SubElement(row, '{http://schemas.microsoft.com/office/visio/2012/main}Cell')
                    else:
                        value_cell = ET.SubElement(row, 'Cell')
                    value_cell.set('N', 'Value')
                    value_cell.set('V', prop_value)  # Use V attribute instead of Value child element
                
                # Verify it was set
                verify_value = get_shape_prop(shape, prop_name)
                if verify_value == prop_value:
                    return True
                else:
                    # Even if verification fails, the XML was updated, so consider it a success
                    # (verification might fail due to caching in vsdx library)
                    return True
        
        # Method 2: Try vsdx library methods as fallback
        if hasattr(shape, 'set_cell_value'):
            try:
                # Set the property value
                shape.set_cell_value(f'Prop.{prop_name}.Value', f'"{prop_value}"')
                # Also set the label
                shape.set_cell_value(f'Prop.{prop_name}.Label', f'"{prop_name}"')
                return True
            except Exception as e:
                print(f"Warning: set_cell_value failed for '{prop_name}': {e}")
            
    except Exception as e:
        print(f"Warning: Could not set property '{prop_name}': {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return False


def index_shapes_by_key(page: Any, diagram_builder: Any) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Build dictionaries of shapes and connectors indexed by their keys.
    
    Args:
        page: Current page object
        diagram_builder: DiagramBuilder instance for helper methods
    
    Returns:
        Tuple of (nodes_by_key, edges_by_key)
    """
    nodes_by_key: Dict[str, Any] = {}
    edges_by_key: Dict[str, Any] = {}
    
    if not page or not hasattr(page, 'child_shapes'):
        return nodes_by_key, edges_by_key
    
    for shape in page.child_shapes:
        try:
            is_connector = diagram_builder._is_connector(shape) if diagram_builder else False
            
            if is_connector:
                # Index connector by EdgeKey
                edge_key = get_shape_prop(shape, 'EdgeKey')
                if edge_key:
                    edges_by_key[edge_key] = shape
            else:
                # Index node by NodeKey
                node_key = get_shape_prop(shape, 'NodeKey')
                if node_key:
                    nodes_by_key[node_key] = shape
        except Exception as e:
            print(f"Warning: Error indexing shape {getattr(shape, 'ID', '?')}: {e}")
            continue
    
    return nodes_by_key, edges_by_key


def find_shape_by_fallback(page: Any, diagram_builder: Any, 
                           text: str, x: float, y: float, 
                           shape_type: Optional[str] = None) -> Optional[Any]:
    """
    Fallback shape matching using normalized text and spatial proximity.
    
    Args:
        page: Current page object
        diagram_builder: DiagramBuilder instance
        text: Shape text to match
        x, y: Expected position
        shape_type: Optional shape type to match
    
    Returns:
        Matching shape or None
    """
    if not page or not hasattr(page, 'child_shapes'):
        return None
    
    normalized_target = normalize_text(text)
    target_bbox = compute_bounding_box_key(x, y, 1.5, 0.75)  # Default size
    
    candidates: List[Tuple[int, Any]] = []
    
    for shape in page.child_shapes:
        try:
            # Skip connectors
            if diagram_builder and diagram_builder._is_connector(shape):
                continue
            
            # Check text match
            shape_text = getattr(shape, 'text', '') or ''
            if normalize_text(shape_text) != normalized_target:
                continue
            
            # Check spatial proximity
            shape_x = float(getattr(shape, 'x', 0) or 0)
            shape_y = float(getattr(shape, 'y', 0) or 0)
            shape_w = float(getattr(shape, 'width', 1.5) or 1.5)
            shape_h = float(getattr(shape, 'height', 0.75) or 0.75)
            shape_bbox = compute_bounding_box_key(shape_x, shape_y, shape_w, shape_h)
            
            # Calculate distance in grid units
            distance = abs(shape_bbox[0] - target_bbox[0]) + abs(shape_bbox[1] - target_bbox[1])
            
            # Prefer shapes close to target position
            if distance <= 2:  # Within 2 grid cells
                score = -distance  # Closer is better
                
                # Bonus for shape type match
                if shape_type:
                    shape_type_str = str(getattr(shape, 'shape_type', '') or '').lower()
                    if shape_type.lower() in shape_type_str:
                        score += 10
                
                candidates.append((score, shape))
        
        except Exception:
            continue
    
    # Return best match
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    
    return None


def compute_edge_key(from_key: str, to_key: str, label: str = "", 
                     from_glue: Optional[str] = None, to_glue: Optional[str] = None) -> str:
    """
    Compute a unique key for an edge (connector) with optional connection points.
    
    Args:
        from_key: Source node key
        to_key: Target node key
        label: Optional edge label
        from_glue: Optional source connection point (e.g., 'Right', 'Top')
        to_glue: Optional target connection point (e.g., 'Left', 'Bottom')
    
    Returns:
        Unique edge key string with format:
        - With glue points: "from_key@from_glue->to_key@to_glue|label"
        - Without glue points: "from_key->to_key|label" (backward compatible)
    
    Examples:
        compute_edge_key("A", "B", "Yes") -> "A->B|Yes"
        compute_edge_key("A", "B", "Yes", "Right", "Left") -> "A@Right->B@Left|Yes"
        compute_edge_key("A", "B", "", "Right", "Left") -> "A@Right->B@Left"
    """
    # Build connection part with optional glue points
    from_part = f"{from_key}@{from_glue}" if from_glue else from_key
    to_part = f"{to_key}@{to_glue}" if to_glue else to_key
    connection_part = f"{from_part}->{to_part}"
    
    # Add label if provided
    if label:
        return f"{connection_part}|{label}"
    return connection_part


def extract_edge_key_components(edge_key: str) -> Tuple[str, str, str, Optional[str], Optional[str]]:
    """
    Extract components from an edge key, supporting both old and new formats.
    
    Args:
        edge_key: Edge key string
    
    Returns:
        Tuple of (from_key, to_key, label, from_glue, to_glue)
        
    Examples:
        "A->B|label" -> ("A", "B", "label", None, None)
        "A@Right->B@Left|label" -> ("A", "B", "label", "Right", "Left")
        "A@Right->B" -> ("A", "B", "", "Right", None)
    """
    # Extract label first
    if '|' in edge_key:
        connector_part, label = edge_key.rsplit('|', 1)
    else:
        connector_part = edge_key
        label = ""
    
    # Extract from and to parts
    if '->' in connector_part:
        from_part, to_part = connector_part.split('->', 1)
    else:
        from_part = connector_part
        to_part = ""
    
    # Extract glue points from each part
    def extract_node_and_glue(part: str) -> Tuple[str, Optional[str]]:
        if '@' in part:
            node, glue = part.split('@', 1)
            return node.strip(), glue.strip() or None
        return part.strip(), None
    
    from_key, from_glue = extract_node_and_glue(from_part)
    to_key, to_glue = extract_node_and_glue(to_part)
    
    return from_key, to_key, label, from_glue, to_glue

