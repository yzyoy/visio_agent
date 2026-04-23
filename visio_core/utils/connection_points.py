# -*- coding: utf-8 -*-
"""
Connection Points Management for Visio Connectors

This module defines connection point positions and provides utilities
for managing glue points on shapes for precise connector placement.

Visio Connection Point System:
- Shapes have a Connection section with indexed rows (IX="0", "1", etc.)
- Each row defines X and Y coordinates relative to the shape's local origin
- Standard shapes typically have connection points at edges and center

Standard Connection Point Indices (for basic rectangular shapes):
0: Top center
1: Bottom center  
2: Left center
3: Right center
4-7: Corner points (if defined)

Note: The actual indices vary by shape master. This module provides
utilities to calculate edge positions from shape geometry when
explicit connection points are not available.
"""
from enum import Enum
from typing import Dict, Optional, Tuple, Any


class GluePointPosition(Enum):
    """Connection point positions on shapes."""
    TOP = "Top"
    BOTTOM = "Bottom"
    LEFT = "Left"
    RIGHT = "Right"
    TOP_LEFT = "TopLeft"
    TOP_RIGHT = "TopRight"
    BOTTOM_LEFT = "BottomLeft"
    BOTTOM_RIGHT = "BottomRight"
    CENTER = "Center"

    @property
    def visio_index(self) -> int:
        """Get the Visio glue point index for this position."""
        return GLUE_POINT_MAPPING[self]

    @classmethod
    def from_string(cls, value: str) -> Optional['GluePointPosition']:
        """Convert string to GluePointPosition enum."""
        if not value:
            return None
        
        # Normalize input
        normalized = value.strip().replace("_", "").replace("-", "").lower()
        
        # Try exact matches first
        for position in cls:
            if position.value.lower() == value.lower():
                return position
            if position.name.lower() == value.lower():
                return position
        
        # Try normalized matches
        normalized_mapping = {
            'top': cls.TOP,
            'bottom': cls.BOTTOM,
            'left': cls.LEFT,
            'right': cls.RIGHT,
            'topleft': cls.TOP_LEFT,
            'topright': cls.TOP_RIGHT,
            'bottomleft': cls.BOTTOM_LEFT,
            'bottomright': cls.BOTTOM_RIGHT,
            'center': cls.CENTER,
            'centre': cls.CENTER,  # British spelling
            'middle': cls.CENTER,
        }
        
        return normalized_mapping.get(normalized)

    def __str__(self) -> str:
        return self.value


# Mapping from enum to standard Visio connection point indices
# Note: These are typical indices; actual shapes may vary
GLUE_POINT_MAPPING: Dict[GluePointPosition, int] = {
    GluePointPosition.TOP: 0,      # Top center
    GluePointPosition.BOTTOM: 1,   # Bottom center
    GluePointPosition.LEFT: 2,     # Left center (or use formula)
    GluePointPosition.RIGHT: 3,    # Right center (or use formula)
    GluePointPosition.TOP_LEFT: 4,
    GluePointPosition.TOP_RIGHT: 5,
    GluePointPosition.BOTTOM_LEFT: 6,
    GluePointPosition.BOTTOM_RIGHT: 7,
    GluePointPosition.CENTER: -1,  # -1 means use PinX/PinY (center)
}

# Reverse mapping from Visio index to enum
INDEX_TO_GLUE_POINT: Dict[int, GluePointPosition] = {
    index: position for position, index in GLUE_POINT_MAPPING.items()
}


def get_glue_point_index(position: Optional[str]) -> Optional[int]:
    """Convert position string to Visio glue point index.
    
    Args:
        position: Position string (e.g., 'Top', 'Bottom', 'Left', etc.)
    
    Returns:
        Visio glue point index or None if invalid
    """
    if not position:
        return None
    
    glue_point = GluePointPosition.from_string(position)
    return glue_point.visio_index if glue_point else None


def get_position_name(index: int) -> Optional[str]:
    """Get position name from Visio glue point index.
    
    Args:
        index: Visio glue point index
    
    Returns:
        Position name or None if invalid index
    """
    position = INDEX_TO_GLUE_POINT.get(index)
    return position.value if position else None


def get_all_positions() -> Dict[str, int]:
    """Get all available connection point positions and their indices.
    
    Returns:
        Dictionary mapping position names to Visio indices
    """
    return {pos.value: pos.visio_index for pos in GluePointPosition}


def validate_glue_point(position: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Validate a glue point position string.
    
    Args:
        position: Position string to validate
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    if position is None:
        return True, None  # None is valid (auto-select)
    
    if not isinstance(position, str):
        return False, f"Glue point must be a string, got {type(position).__name__}"
    
    glue_point = GluePointPosition.from_string(position)
    if glue_point is None:
        valid_positions = [pos.value for pos in GluePointPosition]
        return False, f"Invalid glue point '{position}'. Valid options: {', '.join(valid_positions)}"
    
    return True, None


def get_opposite_position(position: GluePointPosition) -> GluePointPosition:
    """Get the opposite connection point for optimal routing.
    
    Args:
        position: Source connection point
    
    Returns:
        Opposite connection point
    """
    opposites = {
        GluePointPosition.TOP: GluePointPosition.BOTTOM,
        GluePointPosition.BOTTOM: GluePointPosition.TOP,
        GluePointPosition.LEFT: GluePointPosition.RIGHT,
        GluePointPosition.RIGHT: GluePointPosition.LEFT,
        GluePointPosition.TOP_LEFT: GluePointPosition.BOTTOM_RIGHT,
        GluePointPosition.TOP_RIGHT: GluePointPosition.BOTTOM_LEFT,
        GluePointPosition.BOTTOM_LEFT: GluePointPosition.TOP_RIGHT,
        GluePointPosition.BOTTOM_RIGHT: GluePointPosition.TOP_LEFT,
        GluePointPosition.CENTER: GluePointPosition.CENTER,
    }
    return opposites.get(position, GluePointPosition.CENTER)


def calculate_edge_coordinates(shape: Any, position: GluePointPosition) -> Tuple[float, float]:
    """
    Calculate the actual X, Y coordinates for a connection point on a shape's edge.
    
    This is CRITICAL for connector visibility - connectors must connect to actual
    edge positions, not just the shape center (PinX/PinY).
    
    Args:
        shape: Visio shape object with x, y, width, height properties
        position: The edge position to calculate coordinates for
    
    Returns:
        Tuple of (x, y) coordinates in page units (inches)
    """
    # Get shape geometry
    pin_x = float(getattr(shape, 'x', 0) or 0)
    pin_y = float(getattr(shape, 'y', 0) or 0)
    width = float(getattr(shape, 'width', 1) or 1)
    height = float(getattr(shape, 'height', 0.75) or 0.75)
    
    # Calculate half dimensions
    half_width = width / 2
    half_height = height / 2
    
    # Calculate edge coordinates based on position
    if position == GluePointPosition.TOP:
        return (pin_x, pin_y + half_height)
    elif position == GluePointPosition.BOTTOM:
        return (pin_x, pin_y - half_height)
    elif position == GluePointPosition.LEFT:
        return (pin_x - half_width, pin_y)
    elif position == GluePointPosition.RIGHT:
        return (pin_x + half_width, pin_y)
    elif position == GluePointPosition.TOP_LEFT:
        return (pin_x - half_width, pin_y + half_height)
    elif position == GluePointPosition.TOP_RIGHT:
        return (pin_x + half_width, pin_y + half_height)
    elif position == GluePointPosition.BOTTOM_LEFT:
        return (pin_x - half_width, pin_y - half_height)
    elif position == GluePointPosition.BOTTOM_RIGHT:
        return (pin_x + half_width, pin_y - half_height)
    else:  # CENTER
        return (pin_x, pin_y)


def calculate_edge_coordinates_from_string(shape: Any, position_str: Optional[str]) -> Tuple[float, float]:
    """
    Calculate edge coordinates from a position string.
    
    Args:
        shape: Visio shape object
        position_str: Position string (e.g., 'Top', 'Bottom')
    
    Returns:
        Tuple of (x, y) coordinates
    """
    if not position_str:
        # Default to center
        pin_x = float(getattr(shape, 'x', 0) or 0)
        pin_y = float(getattr(shape, 'y', 0) or 0)
        return (pin_x, pin_y)
    
    position = GluePointPosition.from_string(position_str)
    if position is None:
        print(f"Warning: Invalid position '{position_str}', using center")
        pin_x = float(getattr(shape, 'x', 0) or 0)
        pin_y = float(getattr(shape, 'y', 0) or 0)
        return (pin_x, pin_y)
    
    return calculate_edge_coordinates(shape, position)


def get_connection_formula(shape_id: str, position: Optional[GluePointPosition]) -> Tuple[str, str]:
    """
    Get the Visio formula strings for connecting to a shape at a specific position.
    
    For proper connector visibility, we use formulas that reference the shape's
    geometry rather than just PinX/PinY.
    
    Args:
        shape_id: The shape ID to connect to
        position: The connection position (or None for center)
    
    Returns:
        Tuple of (x_formula, y_formula) for BeginX/EndX and BeginY/EndY cells
    """
    if position is None or position == GluePointPosition.CENTER:
        # Center connection - use Pin coordinates
        return (f"Sheet.{shape_id}!PinX", f"Sheet.{shape_id}!PinY")
    
    # Edge connections - use formulas that calculate edge positions
    # These formulas reference the shape's geometry to find the edge
    if position == GluePointPosition.TOP:
        x_formula = f"Sheet.{shape_id}!PinX"
        y_formula = f"Sheet.{shape_id}!PinY+Sheet.{shape_id}!Height*0.5"
    elif position == GluePointPosition.BOTTOM:
        x_formula = f"Sheet.{shape_id}!PinX"
        y_formula = f"Sheet.{shape_id}!PinY-Sheet.{shape_id}!Height*0.5"
    elif position == GluePointPosition.LEFT:
        x_formula = f"Sheet.{shape_id}!PinX-Sheet.{shape_id}!Width*0.5"
        y_formula = f"Sheet.{shape_id}!PinY"
    elif position == GluePointPosition.RIGHT:
        x_formula = f"Sheet.{shape_id}!PinX+Sheet.{shape_id}!Width*0.5"
        y_formula = f"Sheet.{shape_id}!PinY"
    elif position == GluePointPosition.TOP_LEFT:
        x_formula = f"Sheet.{shape_id}!PinX-Sheet.{shape_id}!Width*0.5"
        y_formula = f"Sheet.{shape_id}!PinY+Sheet.{shape_id}!Height*0.5"
    elif position == GluePointPosition.TOP_RIGHT:
        x_formula = f"Sheet.{shape_id}!PinX+Sheet.{shape_id}!Width*0.5"
        y_formula = f"Sheet.{shape_id}!PinY+Sheet.{shape_id}!Height*0.5"
    elif position == GluePointPosition.BOTTOM_LEFT:
        x_formula = f"Sheet.{shape_id}!PinX-Sheet.{shape_id}!Width*0.5"
        y_formula = f"Sheet.{shape_id}!PinY-Sheet.{shape_id}!Height*0.5"
    elif position == GluePointPosition.BOTTOM_RIGHT:
        x_formula = f"Sheet.{shape_id}!PinX+Sheet.{shape_id}!Width*0.5"
        y_formula = f"Sheet.{shape_id}!PinY-Sheet.{shape_id}!Height*0.5"
    else:
        # Fallback to center
        x_formula = f"Sheet.{shape_id}!PinX"
        y_formula = f"Sheet.{shape_id}!PinY"
    
    return (x_formula, y_formula)
