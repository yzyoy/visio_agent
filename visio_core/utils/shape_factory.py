"""
Shape Factory for creating basic Visio shapes without templates

This module enables shape creation from scratch using Visio geometry formulas,
removing the dependency on existing template shapes.
"""
from typing import Any, Optional
from .layout_config import (
    PREFERRED_FONT_SIZE_PT, FONT_FAMILY, LINE_WEIGHT_PT, COLORS,
    TEXT_ALIGN_HORIZONTAL, TEXT_ALIGN_VERTICAL, TEXT_MARGIN_IN
)


# Visio Geometry Section definitions for basic shapes
# Format: List of geometry rows with MoveTo, LineTo, ArcTo, etc.

SHAPE_GEOMETRIES = {
    'Rectangle': {
        'description': 'Basic rectangle',
        'geometry': [
            {'type': 'MoveTo', 'X': '0', 'Y': 'Height'},
            {'type': 'LineTo', 'X': 'Width', 'Y': 'Height'},
            {'type': 'LineTo', 'X': 'Width', 'Y': '0'},
            {'type': 'LineTo', 'X': '0', 'Y': '0'},
            {'type': 'LineTo', 'X': '0', 'Y': 'Height'},
        ],
    },
    'RoundedRectangle': {
        'description': 'Rectangle with rounded corners',
        'geometry': [
            {'type': 'MoveTo', 'X': 'Width*0.1', 'Y': 'Height'},
            {'type': 'LineTo', 'X': 'Width*0.9', 'Y': 'Height'},
            {'type': 'ArcTo', 'X': 'Width', 'Y': 'Height*0.9', 'A': 'Width*0.95+Height*0.95'},
            {'type': 'LineTo', 'X': 'Width', 'Y': 'Height*0.1'},
            {'type': 'ArcTo', 'X': 'Width*0.9', 'Y': '0', 'A': 'Width*0.95'},
            {'type': 'LineTo', 'X': 'Width*0.1', 'Y': '0'},
            {'type': 'ArcTo', 'X': '0', 'Y': 'Height*0.1', 'A': 'Width*0.05'},
            {'type': 'LineTo', 'X': '0', 'Y': 'Height*0.9'},
            {'type': 'ArcTo', 'X': 'Width*0.1', 'Y': 'Height', 'A': 'Width*0.05+Height*0.95'},
        ],
    },
    'Ellipse': {
        'description': 'Ellipse or circle',
        'geometry': [
            {'type': 'Ellipse', 'X': 'Width*0.5', 'Y': 'Height*0.5', 'A': 'Width*0.5', 'B': 'Height*0.5', 'C': 'Width*0.5+Height*0.5', 'D': 'Width*0.5'},
        ],
    },
    'Diamond': {
        'description': 'Diamond (rotated square)',
        'geometry': [
            {'type': 'MoveTo', 'X': 'Width*0.5', 'Y': 'Height'},
            {'type': 'LineTo', 'X': 'Width', 'Y': 'Height*0.5'},
            {'type': 'LineTo', 'X': 'Width*0.5', 'Y': '0'},
            {'type': 'LineTo', 'X': '0', 'Y': 'Height*0.5'},
            {'type': 'LineTo', 'X': 'Width*0.5', 'Y': 'Height'},
        ],
    },
    'Triangle': {
        'description': 'Equilateral triangle',
        'geometry': [
            {'type': 'MoveTo', 'X': 'Width*0.5', 'Y': 'Height'},
            {'type': 'LineTo', 'X': 'Width', 'Y': '0'},
            {'type': 'LineTo', 'X': '0', 'Y': '0'},
            {'type': 'LineTo', 'X': 'Width*0.5', 'Y': 'Height'},
        ],
    },
    'Hexagon': {
        'description': 'Regular hexagon',
        'geometry': [
            {'type': 'MoveTo', 'X': 'Width*0.25', 'Y': 'Height'},
            {'type': 'LineTo', 'X': 'Width*0.75', 'Y': 'Height'},
            {'type': 'LineTo', 'X': 'Width', 'Y': 'Height*0.5'},
            {'type': 'LineTo', 'X': 'Width*0.75', 'Y': '0'},
            {'type': 'LineTo', 'X': 'Width*0.25', 'Y': '0'},
            {'type': 'LineTo', 'X': '0', 'Y': 'Height*0.5'},
            {'type': 'LineTo', 'X': 'Width*0.25', 'Y': 'Height'},
        ],
    },
    'Parallelogram': {
        'description': 'Parallelogram (for data/IO)',
        'geometry': [
            {'type': 'MoveTo', 'X': 'Width*0.15', 'Y': 'Height'},
            {'type': 'LineTo', 'X': 'Width', 'Y': 'Height'},
            {'type': 'LineTo', 'X': 'Width*0.85', 'Y': '0'},
            {'type': 'LineTo', 'X': '0', 'Y': '0'},
            {'type': 'LineTo', 'X': 'Width*0.15', 'Y': 'Height'},
        ],
    },
    'Pentagon': {
        'description': 'Regular pentagon',
        'geometry': [
            {'type': 'MoveTo', 'X': 'Width*0.5', 'Y': 'Height'},
            {'type': 'LineTo', 'X': 'Width', 'Y': 'Height*0.618'},
            {'type': 'LineTo', 'X': 'Width*0.809', 'Y': '0'},
            {'type': 'LineTo', 'X': 'Width*0.191', 'Y': '0'},
            {'type': 'LineTo', 'X': '0', 'Y': 'Height*0.618'},
            {'type': 'LineTo', 'X': 'Width*0.5', 'Y': 'Height'},
        ],
    },
    'Trapezoid': {
        'description': 'Trapezoid',
        'geometry': [
            {'type': 'MoveTo', 'X': 'Width*0.2', 'Y': 'Height'},
            {'type': 'LineTo', 'X': 'Width*0.8', 'Y': 'Height'},
            {'type': 'LineTo', 'X': 'Width', 'Y': '0'},
            {'type': 'LineTo', 'X': '0', 'Y': '0'},
            {'type': 'LineTo', 'X': 'Width*0.2', 'Y': 'Height'},
        ],
    },
}


def get_fill_color_for_type(shape_type: str) -> str:
    """Get appropriate fill color for shape type"""
    shape_type_lower = shape_type.lower()
    
    if 'rounded' in shape_type_lower or 'terminator' in shape_type_lower:
        return COLORS.get('terminator_fill', '#D4E6F1')
    elif 'diamond' in shape_type_lower or 'decision' in shape_type_lower:
        return COLORS.get('decision_fill', '#FFF3E0')
    elif 'rectangle' in shape_type_lower or 'process' in shape_type_lower:
        return COLORS.get('process_fill', '#E8F5E9')
    elif 'parallelogram' in shape_type_lower or 'data' in shape_type_lower:
        return COLORS.get('data_fill', '#F3E5F5')
    else:
        return COLORS.get('default_fill', '#FFFFFF')


def create_basic_shape(visio_file: Any, page: Any, shape_type: str, 
                       text: str, x: float, y: float, 
                       width: float = 1.5, height: float = 0.75) -> Optional[Any]:
    """
    Create a basic shape from scratch without requiring a template.
    
    This is a fallback method when no template shapes are available.
    Uses Visio geometry formulas to create shapes programmatically.
    
    Args:
        visio_file: VisioFile object
        page: Page object to add shape to
        shape_type: Type of shape to create
        text: Text to display in shape
        x, y: Position coordinates (in inches)
        width, height: Shape dimensions (in inches)
    
    Returns:
        Created shape object or None if failed
    """
    try:
        # Normalize shape type
        normalized_type = normalize_shape_type(shape_type)
        
        if normalized_type not in SHAPE_GEOMETRIES:
            print(f"Warning: Shape type '{shape_type}' not in basic shapes. Using Rectangle.")
            normalized_type = 'Rectangle'
        
        # Create a basic shape using vsdx library's shape creation
        # Note: vsdx library doesn't directly support creating shapes from scratch
        # We'll create a minimal shape and configure it
        
        # Since vsdx doesn't support creating from scratch easily, we need to work
        # with the XML directly or use a minimal template approach
        
        # For now, return None to indicate factory creation isn't fully supported
        # The caller should still try to find a template
        print(f"Note: Shape factory is not yet fully implemented. Need existing template shapes.")
        return None
        
    except Exception as e:
        print(f"Error creating shape from factory: {e}")
        import traceback
        traceback.print_exc()
        return None


def normalize_shape_type(shape_type: str) -> str:
    """
    Normalize shape type name to match geometry definitions.
    
    Args:
        shape_type: Input shape type (can be various forms)
    
    Returns:
        Normalized shape type name
    """
    shape_type_lower = shape_type.lower()
    
    # Map common aliases to standard names
    type_mapping = {
        'rect': 'Rectangle',
        'box': 'Rectangle',
        'square': 'Rectangle',
        'rounded': 'RoundedRectangle',
        'roundedrect': 'RoundedRectangle',
        'terminator': 'RoundedRectangle',
        'oval': 'Ellipse',
        'circle': 'Ellipse',
        'rhombus': 'Diamond',
        'decision': 'Diamond',
        'data': 'Parallelogram',
        'io': 'Parallelogram',
        'preparation': 'Hexagon',
        'prep': 'Hexagon',

        # Chinese aliases
        '菱形': 'Diamond',
        '决策': 'Diamond',
        '判定': 'Diamond',
        '矩形': 'Rectangle',
        '圆角矩形': 'RoundedRectangle',
        '椭圆': 'Ellipse',
        '圆形': 'Ellipse',
        '平行四边形': 'Parallelogram',
        '六边形': 'Hexagon',
        '三角形': 'Triangle',
        '梯形': 'Trapezoid',
        '五边形': 'Pentagon',
    }
    
    # Try exact match first
    for key, value in SHAPE_GEOMETRIES.items():
        if shape_type_lower == key.lower():
            return key
    
    # Try alias mapping
    for alias, standard in type_mapping.items():
        if alias in shape_type_lower:
            return standard
    
    # Default to rectangle
    return 'Rectangle'


def is_shape_type_supported(shape_type: str) -> bool:
    """
    Check if a shape type is supported by the factory.
    
    Args:
        shape_type: Shape type to check
    
    Returns:
        True if supported
    """
    normalized = normalize_shape_type(shape_type)
    return normalized in SHAPE_GEOMETRIES


def list_supported_shapes() -> list:
    """
    List all shapes supported by the factory.
    
    Returns:
        List of dictionaries with shape information
    """
    return [
        {
            'name': name,
            'description': info['description']
        }
        for name, info in SHAPE_GEOMETRIES.items()
    ]

