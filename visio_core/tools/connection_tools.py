# -*- coding: utf-8 -*-
"""
Connection Tools for Advanced Connector Management

This module provides helper functions for managing shape connections,
auto-selecting optimal connection points, and listing connection details.
"""
from typing import List, Dict, Any, Optional, Tuple
from ..utils.connection_points import GluePointPosition, get_glue_point_index, get_opposite_position
from ..utils.shape_identity import get_shape_prop


def get_shape_coordinates(shape: Any) -> Tuple[float, float]:
    """Get the center coordinates of a shape.
    
    Args:
        shape: Visio shape object
    
    Returns:
        Tuple of (x, y) center coordinates in inches
    """
    try:
        # Try to get PinX and PinY properties (center coordinates)
        if hasattr(shape, 'cell_value'):
            pin_x = shape.cell_value('PinX')
            pin_y = shape.cell_value('PinY')
            if pin_x not in (None, '') and pin_y not in (None, ''):
                return float(pin_x), float(pin_y)

        if hasattr(shape, 'x') and hasattr(shape, 'y'):
            return float(shape.x), float(shape.y)
        
        # Fallback: try to extract from shape properties
        pin_x = getattr(shape, 'PinX', None)
        pin_y = getattr(shape, 'PinY', None)
        
        if pin_x is not None and pin_y is not None:
            return float(pin_x), float(pin_y)
        
        # Last resort: try bounding box center
        if hasattr(shape, 'bounding_box'):
            bbox = shape.bounding_box
            if bbox and len(bbox) >= 4:
                x = (bbox[0] + bbox[2]) / 2
                y = (bbox[1] + bbox[3]) / 2
                return x, y
        
        # Default to origin if all else fails
        return 0.0, 0.0
    
    except (ValueError, AttributeError, TypeError):
        return 0.0, 0.0


def calculate_relative_position(from_coords: Tuple[float, float], 
                              to_coords: Tuple[float, float]) -> Tuple[str, str]:
    """Calculate optimal connection points based on relative positions.
    
    Args:
        from_coords: Source shape center coordinates (x, y)
        to_coords: Target shape center coordinates (x, y)
    
    Returns:
        Tuple of (from_connection_point, to_connection_point) as strings
    """
    from_x, from_y = from_coords
    to_x, to_y = to_coords
    
    # Calculate deltas
    dx = to_x - from_x
    dy = to_y - from_y
    
    # Determine primary direction (horizontal vs vertical)
    if abs(dx) > abs(dy):
        # Primarily horizontal layout
        if dx > 0:
            # Source is left of target
            return "Right", "Left"
        else:
            # Source is right of target
            return "Left", "Right"
    else:
        # Primarily vertical layout
        if dy > 0:
            # Source is below target (Visio Y coordinates)
            return "Top", "Bottom"
        else:
            # Source is above target
            return "Bottom", "Top"


def auto_select_connection_points(from_shape: Any, to_shape: Any) -> Tuple[Optional[str], Optional[str]]:
    """Automatically select optimal connection points for two shapes.
    
    Args:
        from_shape: Source shape object
        to_shape: Target shape object
    
    Returns:
        Tuple of (from_glue_point, to_glue_point) as strings or None if auto-select failed
    """
    try:
        from_coords = get_shape_coordinates(from_shape)
        to_coords = get_shape_coordinates(to_shape)
        
        # If coordinates are the same or invalid, use center connections
        if from_coords == to_coords or from_coords == (0.0, 0.0) or to_coords == (0.0, 0.0):
            return "Center", "Center"
        
        from_point, to_point = calculate_relative_position(from_coords, to_coords)
        return from_point, to_point
    
    except Exception as e:
        print(f"Warning: Auto-selection failed, using Center connections: {e}")
        return "Center", "Center"


def get_shape_connection_points(shape: Any, diagram_builder: Any = None) -> List[Dict[str, Any]]:
    """List all available connection points for a shape.
    
    Args:
        shape: Visio shape object
        diagram_builder: Optional DiagramBuilder instance for additional context
    
    Returns:
        List of connection point dictionaries with name, index, and coordinates
    """
    try:
        node_key = get_shape_prop(shape, 'NodeKey')
        shape_id = getattr(shape, 'ID', 'unknown')
        shape_text = getattr(shape, 'text', '').strip()
        
        connection_points = []
        
        # Add all standard connection points
        for position in GluePointPosition:
            connection_points.append({
                'name': position.value,
                'index': position.visio_index,
                'position': position.name,
                'node_key': node_key,
                'shape_id': shape_id,
                'shape_text': shape_text
            })
        
        return connection_points
    
    except Exception as e:
        print(f"Warning: Failed to get connection points for shape: {e}")
        return []


def list_all_connections(node_key: str, diagram_builder: Any) -> Dict[str, List[Dict[str, Any]]]:
    """Show all incoming and outgoing connections for a shape.
    
    Args:
        node_key: Node key of the shape to analyze
        diagram_builder: DiagramBuilder instance
    
    Returns:
        Dictionary with 'incoming' and 'outgoing' connection lists
    """
    if not diagram_builder or not diagram_builder.current_page:
        return {'incoming': [], 'outgoing': []}
    
    try:
        from .shape_identity import index_shapes_by_key
        
        # Index all shapes
        nodes_by_key, edges_by_key = index_shapes_by_key(diagram_builder.current_page, diagram_builder)
        
        incoming = []
        outgoing = []
        
        # Analyze all connectors
        for edge_key, connector in edges_by_key.items():
            # Parse edge key to get connection details
            from ..utils.shape_identity import extract_edge_key_components
            
            try:
                from_key, to_key, label = extract_edge_key_components(edge_key)
                
                if to_key == node_key:
                    # Incoming connection
                    incoming.append({
                        'edge_key': edge_key,
                        'from_node': from_key,
                        'to_node': to_key,
                        'label': label,
                        'connector_id': getattr(connector, 'ID', 'unknown')
                    })
                
                if from_key == node_key:
                    # Outgoing connection
                    outgoing.append({
                        'edge_key': edge_key,
                        'from_node': from_key,
                        'to_node': to_key,
                        'label': label,
                        'connector_id': getattr(connector, 'ID', 'unknown')
                    })
            
            except Exception as e:
                print(f"Warning: Failed to parse edge key '{edge_key}': {e}")
                continue
        
        return {
            'incoming': incoming,
            'outgoing': outgoing
        }
    
    except Exception as e:
        print(f"Warning: Failed to list connections for node '{node_key}': {e}")
        return {'incoming': [], 'outgoing': []}


def get_optimal_connection_points(from_node_key: str, to_node_key: str, 
                                diagram_builder: Any) -> Tuple[Optional[str], Optional[str]]:
    """Auto-calculate best connection points for two nodes.
    
    Args:
        from_node_key: Source node key
        to_node_key: Target node key
        diagram_builder: DiagramBuilder instance
    
    Returns:
        Tuple of (from_glue_point, to_glue_point) as strings
    """
    if not diagram_builder or not diagram_builder.current_page:
        return "Center", "Center"
    
    try:
        from ..utils.shape_identity import index_shapes_by_key
        
        # Get shapes by key
        nodes_by_key, _ = index_shapes_by_key(diagram_builder.current_page, diagram_builder)
        
        from_shape = nodes_by_key.get(from_node_key)
        to_shape = nodes_by_key.get(to_node_key)
        
        if not from_shape or not to_shape:
            print(f"Warning: Could not find shapes for keys '{from_node_key}' -> '{to_node_key}'")
            return "Center", "Center"
        
        return auto_select_connection_points(from_shape, to_shape)
    
    except Exception as e:
        print(f"Warning: Failed to calculate optimal connection points: {e}")
        return "Center", "Center"


def format_connection_summary(node_key: str, connections: Dict[str, List[Dict[str, Any]]]) -> str:
    """Format connection information for display.
    
    Args:
        node_key: Node key being analyzed
        connections: Connection data from list_all_connections
    
    Returns:
        Formatted string summary
    """
    incoming = connections.get('incoming', [])
    outgoing = connections.get('outgoing', [])
    
    summary = [f"Connection Summary for '{node_key}':"]
    summary.append(f"  Incoming: {len(incoming)} connections")
    
    for conn in incoming:
        summary.append(f"    ← {conn['from_node']} (label: '{conn['label']}', ID: {conn['connector_id']})")
    
    summary.append(f"  Outgoing: {len(outgoing)} connections")
    
    for conn in outgoing:
        summary.append(f"    → {conn['to_node']} (label: '{conn['label']}', ID: {conn['connector_id']})")
    
    return "\n".join(summary)
