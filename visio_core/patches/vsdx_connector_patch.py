"""
Patch for vsdx library to fix connector attachment issues.

This module monkey-patches the vsdx.connectors.Connect.create method to properly
create all four required Connect elements (BeginX, BeginY, EndX, EndY) instead of
just two (BeginX, EndX).

Without this patch, connectors appear offset or floating because they are only
glued in the X dimension, not the Y dimension.

VISIBILITY FIX (2024-12):
- Connectors now use actual edge coordinates, not just shape centers
- Proper glue formulas reference shape geometry for dynamic attachment
- Line properties ensure connectors are visible (weight, color, pattern)
- Connects table entries use proper connection point references

Usage:
    import visio_core.patches.vsdx_connector_patch
    # The patch is automatically applied on import
"""

import threading
import xml.etree.ElementTree as ET
import math
import uuid
import vsdx
from vsdx.connectors import Connect
from vsdx.shapes import Shape
from typing import Optional, Tuple

# Serialize connector creation: parallel tool calls share the same page XML; concurrent
# Connect.create + orphan cleanup corrupts shapes another call is building.
_connect_create_lock = threading.RLock()


# Save the original method
_original_create = Connect.create


def _calculate_edge_point(shape: Shape, edge: Optional[str] = None) -> Tuple[float, float]:
    """
    Calculate the actual edge coordinate for a shape.
    
    This is CRITICAL for connector visibility - connectors must connect to 
    actual edge positions, not just shape centers.
    
    Args:
        shape: The Visio shape
        edge: Edge name ('Top', 'Bottom', 'Left', 'Right') or None for center
    
    Returns:
        Tuple of (x, y) coordinates
    """
    pin_x = float(getattr(shape, 'x', 0) or 0)
    pin_y = float(getattr(shape, 'y', 0) or 0)
    width = float(getattr(shape, 'width', 1) or 1)
    height = float(getattr(shape, 'height', 0.75) or 0.75)
    
    if edge is None:
        return (pin_x, pin_y)
    
    edge_lower = edge.lower().strip()
    half_w = width / 2
    half_h = height / 2
    
    if edge_lower == 'top':
        return (pin_x, pin_y + half_h)
    elif edge_lower == 'bottom':
        return (pin_x, pin_y - half_h)
    elif edge_lower == 'left':
        return (pin_x - half_w, pin_y)
    elif edge_lower == 'right':
        return (pin_x + half_w, pin_y)
    else:
        return (pin_x, pin_y)


def _get_connection_point_cell(edge: Optional[str]) -> Tuple[str, str]:
    """
    Get the proper Visio connection point cell names for an edge.
    
    Visio uses Connections.X{n} and Connections.Y{n} for connection points.
    Standard indices:
    - 0: Top center
    - 1: Bottom center
    - 2: Left center
    - 3: Right center
    
    Args:
        edge: Edge name or None for center (PinX/PinY)
    
    Returns:
        Tuple of (x_cell, y_cell) names
    """
    if edge is None:
        return ("PinX", "PinY")
    
    edge_lower = edge.lower().strip()
    
    # Map edges to connection point indices
    edge_to_index = {
        'top': 0,
        'bottom': 1,
        'left': 2,
        'right': 3,
    }
    
    idx = edge_to_index.get(edge_lower)
    if idx is not None:
        return (f"Connections.X{idx}", f"Connections.Y{idx}")
    
    return ("PinX", "PinY")


def _get_glue_formula(shape_id: str, edge: Optional[str] = None) -> Tuple[str, str]:
    """
    Get Visio formulas for gluing to a shape edge.
    
    Returns formulas that dynamically calculate edge position based on shape geometry.
    This ensures connectors stay attached when shapes are moved or resized.
    
    Args:
        shape_id: Target shape ID
        edge: Edge name or None for center
    
    Returns:
        Tuple of (x_formula, y_formula)
    """
    if edge is None:
        return (f"Sheet.{shape_id}!PinX", f"Sheet.{shape_id}!PinY")
    
    edge_lower = edge.lower().strip()
    
    if edge_lower == 'top':
        return (f"Sheet.{shape_id}!PinX", 
                f"Sheet.{shape_id}!PinY+Sheet.{shape_id}!Height*0.5")
    elif edge_lower == 'bottom':
        return (f"Sheet.{shape_id}!PinX", 
                f"Sheet.{shape_id}!PinY-Sheet.{shape_id}!Height*0.5")
    elif edge_lower == 'left':
        return (f"Sheet.{shape_id}!PinX-Sheet.{shape_id}!Width*0.5", 
                f"Sheet.{shape_id}!PinY")
    elif edge_lower == 'right':
        return (f"Sheet.{shape_id}!PinX+Sheet.{shape_id}!Width*0.5", 
                f"Sheet.{shape_id}!PinY")
    else:
        return (f"Sheet.{shape_id}!PinX", f"Sheet.{shape_id}!PinY")


def _create_connector_manually(page: vsdx.Page, from_shape: Shape, to_shape: Shape,
                               from_edge: Optional[str] = None, 
                               to_edge: Optional[str] = None) -> Shape:
    """Manually create a connector when the original vsdx method fails.
    
    This function creates a basic dynamic connector with proper connections
    when the vsdx library's Connect.create() fails due to master shape issues.
    
    IMPORTANT: 
    - Visio expects Cell elements with N="name" V="value" F="formula" format
    - Connectors MUST have visible line properties (LineWeight, LineColor, LinePattern)
    - Geometry section defines the actual line path
    - Connect entries must reference proper connection point cells
    
    Args:
        page: Target Visio page
        from_shape: Source shape
        to_shape: Target shape
        from_edge: Optional edge on source shape ('Top', 'Bottom', 'Left', 'Right')
        to_edge: Optional edge on target shape
    
    Returns:
        Created connector Shape or None on failure
    """
    try:
        ns = 'http://schemas.microsoft.com/office/visio/2012/main'
        ns_prefix = f'{{{ns}}}'
        
        # Get next available shape ID
        existing_ids = [int(s.ID) for s in page.child_shapes if hasattr(s, 'ID') and str(s.ID).isdigit()]
        new_id = str(max(existing_ids) + 1 if existing_ids else 1)
        
        # Generate unique ID
        unique_id = str(uuid.uuid4()).upper()
        
        # Calculate connector coordinates using actual edge positions
        from_x, from_y = _calculate_edge_point(from_shape, from_edge)
        to_x, to_y = _calculate_edge_point(to_shape, to_edge)
        
        # Get glue formulas for dynamic attachment
        begin_x_formula, begin_y_formula = _get_glue_formula(str(from_shape.ID), from_edge)
        end_x_formula, end_y_formula = _get_glue_formula(str(to_shape.ID), to_edge)
        
        # Get connection point cells for Connects table
        from_x_cell, from_y_cell = _get_connection_point_cell(from_edge)
        to_x_cell, to_y_cell = _get_connection_point_cell(to_edge)
        
        # Calculate connector properties
        dx = to_x - from_x
        dy = to_y - from_y
        length = math.sqrt(dx**2 + dy**2)
        pin_x = (from_x + to_x) / 2
        pin_y = (from_y + to_y) / 2
        angle = math.atan2(dy, dx)
        
        # Ensure minimum length for visibility
        if length < 0.1:
            length = 0.1
        
        # Create proper connector shape XML with Cell elements (N, V, F attributes)
        # CRITICAL: Include all visibility properties!
        # Use 1D connector geometry (straight line from 0,0 to Width,0 in local coords)
        connector_xml = f'''<Shape xmlns="{ns}" ID="{new_id}" NameU="Dynamic connector" Name="Dynamic connector" Type="Shape" LineStyle="3" FillStyle="3" TextStyle="3" UniqueID="{{{unique_id}}}">
    <Cell N="PinX" V="{pin_x}" F="(BeginX+EndX)/2"/>
    <Cell N="PinY" V="{pin_y}" F="(BeginY+EndY)/2"/>
    <Cell N="Width" V="{length}" F="GUARD(SQRT((EndX-BeginX)^2+(EndY-BeginY)^2))"/>
    <Cell N="Height" V="0" F="GUARD(0)"/>
    <Cell N="LocPinX" V="{length/2}" F="Width*0.5"/>
    <Cell N="LocPinY" V="0" F="Height*0.5"/>
    <Cell N="Angle" V="{angle}" F="ATAN2(EndY-BeginY,EndX-BeginX)"/>
    <Cell N="BeginX" V="{from_x}" F="{begin_x_formula}"/>
    <Cell N="BeginY" V="{from_y}" F="{begin_y_formula}"/>
    <Cell N="EndX" V="{to_x}" F="{end_x_formula}"/>
    <Cell N="EndY" V="{to_y}" F="{end_y_formula}"/>
    <Cell N="LayerMember" V="0"/>
    <Cell N="BegTrigger" V="2" F="_XFTRIGGER(Sheet.{from_shape.ID}!EventXFMod)"/>
    <Cell N="EndTrigger" V="2" F="_XFTRIGGER(Sheet.{to_shape.ID}!EventXFMod)"/>
    <Cell N="ShapeRouteStyle" V="1"/>
    <Cell N="ConFixedCode" V="6"/>
    <Cell N="ConLineRouteExt" V="1"/>
    <Cell N="LineWeight" V="0.01388889"/>
    <Cell N="LineColor" V="0"/>
    <Cell N="LinePattern" V="1"/>
    <Cell N="LineCap" V="1"/>
    <Cell N="BeginArrow" V="0"/>
    <Cell N="EndArrow" V="4"/>
    <Cell N="BeginArrowSize" V="2"/>
    <Cell N="EndArrowSize" V="2"/>
    <Cell N="Rounding" V="0"/>
    <Cell N="Transparency" V="0"/>
    <Cell N="LineColorTrans" V="0"/>
    <Section N="XForm1D">
        <Cell N="BeginX" V="{from_x}" F="{begin_x_formula}"/>
        <Cell N="BeginY" V="{from_y}" F="{begin_y_formula}"/>
        <Cell N="EndX" V="{to_x}" F="{end_x_formula}"/>
        <Cell N="EndY" V="{to_y}" F="{end_y_formula}"/>
    </Section>
    <Section N="Geometry" IX="0">
        <Cell N="NoFill" V="1"/>
        <Cell N="NoLine" V="0"/>
        <Cell N="NoShow" V="0"/>
        <Cell N="NoSnap" V="0"/>
        <Row T="MoveTo" IX="1">
            <Cell N="X" V="0" F="Width*0"/>
            <Cell N="Y" V="0" F="Height*0.5"/>
        </Row>
        <Row T="LineTo" IX="2">
            <Cell N="X" V="{length}" F="Width*1"/>
            <Cell N="Y" V="0" F="Height*0.5"/>
        </Row>
    </Section>
</Shape>'''
        
        # Parse the shape element
        shape_element = ET.fromstring(connector_xml)
        
        # Find the Shapes container in the page XML
        shapes_container = page.xml.find(f'.//{ns_prefix}Shapes')
        if shapes_container is None:
            shapes_container = page.xml.find('.//Shapes')
        if shapes_container is None:
            # Create Shapes container if it doesn't exist
            shapes_container = ET.SubElement(page.xml, f'{ns_prefix}Shapes')
        
        # Append the connector shape to the XML tree
        shapes_container.append(shape_element)
        
        # Create the Shape object and add to child_shapes list
        connector_shape = Shape(xml=shape_element, page=page, parent=page)
        page.child_shapes.append(connector_shape)
        
        # Create the connection elements with proper namespace
        # CRITICAL: These Connect elements tell Visio which shapes are connected
        # Use proper connection point cell references (not just PinX/PinY)
        connections = [
            (new_id, "BeginX", "9", from_shape.ID, from_x_cell, "3"),
            (new_id, "BeginY", "9", from_shape.ID, from_y_cell, "3"),
            (new_id, "EndX", "12", to_shape.ID, to_x_cell, "3"),
            (new_id, "EndY", "12", to_shape.ID, to_y_cell, "3"),
        ]
        
        # Add connections to page
        for from_sheet, from_cell, from_part, to_sheet, to_cell, to_part in connections:
            conn_xml = f'<Connect xmlns="{ns}" FromSheet="{from_sheet}" FromCell="{from_cell}" FromPart="{from_part}" ToSheet="{to_sheet}" ToCell="{to_cell}" ToPart="{to_part}"/>'
            conn_element = ET.fromstring(conn_xml) 
            page.add_connect(Connect(xml=conn_element, page=page))
        
        print(f"[OK] Created connector ID {new_id}: ({from_x:.2f},{from_y:.2f}) -> ({to_x:.2f},{to_y:.2f})")
        print(f"  Edge connections: {from_edge or 'center'} -> {to_edge or 'center'}")
        return connector_shape
        
    except Exception as e:
        print(f"Error in manual connector creation: {e}")
        import traceback
        traceback.print_exc()
        return None


@staticmethod
def patched_create(page: vsdx.Page = None, from_shape: Shape = None, to_shape: Shape = None) -> Shape:
    """Patched version of Connect.create that properly creates all four connection relationships.
    
    Original implementation only created BeginX and EndX connections, which causes connectors
    to appear offset or floating. This patched version creates all four connections:
    - BeginX and BeginY to from_shape
    - EndX and EndY to to_shape
    
    This ensures proper "glue" behavior where connectors stay attached when shapes are moved.
    """
    if not (from_shape and to_shape):
        return _original_create(page, from_shape, to_shape)

    with _connect_create_lock:
        used_manual_creation = False

        ns_prefix = '{http://schemas.microsoft.com/office/visio/2012/main}'
        shapes_container = page.xml.find(f'.//{ns_prefix}Shapes')
        if shapes_container is None:
            shapes_container = page.xml.find('.//Shapes')
        pre_ids: set = set()
        if shapes_container is not None:
            pre_ids = {child.get('ID') for child in shapes_container if 'Shape' in child.tag}

        connector_shape = None
        try:
            connector_shape = _original_create(page, from_shape, to_shape)
        except Exception as e:
            # Remove any shapes appended after pre_ids snapshot, then fall back.
            if shapes_container is not None:
                for child in list(shapes_container):
                    if 'Shape' in child.tag and child.get('ID') not in pre_ids:
                        shapes_container.remove(child)
                        print(f"Cleaned up partially-created connector shape ID={child.get('ID')}")
            print(f"Warning: vsdx Connect.create failed ({type(e).__name__}: {e}), creating connector manually")
            connector_shape = _create_connector_manually(page, from_shape, to_shape)
            used_manual_creation = True

        if connector_shape is None and not used_manual_creation:
            connector_shape = _create_connector_manually(page, from_shape, to_shape)
            used_manual_creation = True

        if connector_shape is None:
            return None

        # Only add supplemental Y connections when the original library method
        # succeeded; _create_connector_manually already creates all four entries.
        if not used_manual_creation:
            beg_y_connect_xml = (
                f'<Connect xmlns="http://schemas.microsoft.com/office/visio/2012/main" '
                f'FromSheet="{connector_shape.ID}" FromCell="BeginY" FromPart="9" '
                f'ToSheet="{from_shape.ID}" ToCell="PinY" ToPart="3"/>'
            )
            page.add_connect(Connect(xml=ET.fromstring(beg_y_connect_xml), page=page))

            end_y_connect_xml = (
                f'<Connect xmlns="http://schemas.microsoft.com/office/visio/2012/main" '
                f'FromSheet="{connector_shape.ID}" FromCell="EndY" FromPart="12" '
                f'ToSheet="{to_shape.ID}" ToCell="PinY" ToPart="3"/>'
            )
            page.add_connect(Connect(xml=ET.fromstring(end_y_connect_xml), page=page))

        return connector_shape


# Apply the patch
Connect.create = patched_create

