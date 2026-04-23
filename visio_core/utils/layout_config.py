"""
Professional layout configuration for Visio diagrams
Following Microsoft Visio best practices for print-ready flowcharts
"""

# ===========================
# GRID AND SPACING CONSTANTS
# ===========================
# Grid spacing in inches (6mm ≈ 0.236 inches)
GRID_SPACING_IN = 0.25  # Quarter-inch grid (6.35mm) for precise alignment
MIN_SHAPE_SPACING_IN = 0.5  # Minimum 0.5 inch between shapes (12.7mm)

# Standard page dimensions (US Letter)
PAGE_WIDTH_IN = 8.5
PAGE_HEIGHT_IN = 11.0
PAGE_MARGIN_IN = 0.5  # Half-inch margins on all sides

# Page auto-fit configuration
AUTO_FIT_MARGIN_IN = 0.5  # Margin to add when auto-fitting page to content
MIN_PAGE_SIZE_IN = 4.0    # Minimum page size (width or height)
MAX_PAGE_SIZE_IN = 34.0   # Maximum page size (Visio limitation)

# ===========================
# SHAPE DIMENSIONS CONSTANTS
# ===========================
# Standard flowchart shape sizes (width × height in inches)
SHAPE_SIZES = {
    'terminator': {'width': 1.5, 'height': 0.6},   # Start/End ovals
    'process': {'width': 1.5, 'height': 0.75},     # Rectangle process boxes
    'decision': {'width': 1.5, 'height': 1.0},     # Diamond decision nodes
    'data': {'width': 1.5, 'height': 0.75},        # Parallelogram I/O
    'preparation': {'width': 1.5, 'height': 0.75}, # Hexagon preparation
    'document': {'width': 1.5, 'height': 0.75},    # Document shape
}

# ===========================
# TYPOGRAPHY CONSTANTS
# ===========================
# Minimum font size for readability (14-16 pt for print)
MIN_FONT_SIZE_PT = 14
PREFERRED_FONT_SIZE_PT = 16
# Font family with CJK (Chinese-Japanese-Korean) support
# Priority order: Microsoft YaHei (best CJK), SimSun (fallback), Arial Unicode MS (universal fallback)
FONT_FAMILY = "Microsoft YaHei"  # 微软雅黑 - Best for Chinese text
FONT_FAMILY_FALLBACKS = ["SimSun", "Arial Unicode MS", "Calibri"]  # Fallback fonts

# Text alignment
TEXT_ALIGN_HORIZONTAL = 0  # 0=center, 1=left, 2=right
TEXT_ALIGN_VERTICAL = 1     # 0=top, 1=middle, 2=bottom

# Text margins (in inches)
TEXT_MARGIN_IN = 0.05  # Small margins inside shapes

# ===========================
# COLOR AND THEME CONSTANTS
# ===========================
# High-contrast color scheme (RGB hex format)
COLORS = {
    # Shape fill colors (muted, professional)
    'terminator_fill': '#D4E6F1',  # Light blue for Start/End
    'process_fill': '#E8F5E9',     # Light green for Process
    'decision_fill': '#FFF3E0',    # Light amber for Decision
    'data_fill': '#F3E5F5',        # Light purple for Data
    'default_fill': '#FFFFFF',     # White background
    
    # Line/border colors (high contrast)
    'line_color': '#212121',       # Dark gray/black
    'connector_color': '#424242',  # Medium dark gray
    
    # Text colors
    'text_color': '#000000',       # Pure black for maximum readability
}

# Line weights (in points)
LINE_WEIGHT_PT = 1.5  # Slightly heavier for print visibility
CONNECTOR_WEIGHT_PT = 1.0

# ===========================
# CONNECTOR ROUTING CONSTANTS
# ===========================
# Visio routing style values
ROUTING_STYLES = {
    'straight': '1',           # Direct line
    'right_angle': '16',       # Right-angle/orthogonal (BEST for flowcharts)
    'curved': '2',             # Curved routing
}

# Default routing for flowcharts
DEFAULT_ROUTING_STYLE = 'right_angle'

# Connector appearance
CONNECTOR_ARROW_SIZE = 2  # Medium arrow heads
CONNECTOR_LINE_PATTERN = 1  # Solid line

# ===========================
# LAYER ORGANIZATION
# ===========================
LAYERS = {
    'connectors': 'Connectors',
    'shapes': 'Shapes',
    'swimlanes': 'Swimlanes',
    'annotations': 'Annotations',
}

# ===========================
# LAYOUT ALGORITHM PARAMETERS
# ===========================
# Vertical spacing between shapes in flowchart
VERTICAL_SPACING_IN = 1.0  # 1 inch vertical gap

# Horizontal spacing for parallel branches
HORIZONTAL_SPACING_IN = 2.0  # 2 inch horizontal gap

# Decision branch offsets
DECISION_YES_OFFSET_X = 2.0   # Right branch
DECISION_NO_OFFSET_Y = 1.5    # Down branch

# ===========================
# EXPORT QUALITY SETTINGS
# ===========================
# DPI for exported images (PDF, PNG, SVG)
EXPORT_DPI = 300  # Print quality
EXPORT_FORMATS = ['pdf', 'svg', 'png']

# ===========================
# VALIDATION THRESHOLDS
# ===========================
# Minimum acceptable spacing before warnings
WARNING_MIN_SPACING_IN = 0.3
WARNING_MIN_FONT_SIZE_PT = 12

# Maximum shape count per page before recommending split
MAX_SHAPES_PER_PAGE = 50


def snap_to_grid(value: float, grid_size: float = GRID_SPACING_IN) -> float:
    """
    Snap a position value to the nearest grid point.
    
    Args:
        value: Position value in inches
        grid_size: Grid spacing in inches
    
    Returns:
        Snapped value aligned to grid
    """
    return round(value / grid_size) * grid_size


def validate_position(x: float, y: float) -> tuple[float, float]:
    """
    Validate and clamp position within page boundaries with margins.
    
    Args:
        x: X position in inches
        y: Y position in inches
    
    Returns:
        Validated (x, y) tuple
    """
    min_x = PAGE_MARGIN_IN
    max_x = PAGE_WIDTH_IN - PAGE_MARGIN_IN
    min_y = PAGE_MARGIN_IN
    max_y = PAGE_HEIGHT_IN - PAGE_MARGIN_IN
    
    x = max(min_x, min(x, max_x))
    y = max(min_y, min(y, max_y))
    
    return (x, y)


def get_shape_size(shape_type: str) -> dict:
    """
    Get standard dimensions for a shape type.
    
    Args:
        shape_type: Type of shape (terminator, process, decision, etc.)
    
    Returns:
        Dictionary with 'width' and 'height' in inches
    """
    shape_type_lower = shape_type.lower()
    
    # Map common aliases to standard types
    if 'rounded' in shape_type_lower or 'terminator' in shape_type_lower:
        return SHAPE_SIZES['terminator']
    elif 'diamond' in shape_type_lower or 'decision' in shape_type_lower:
        return SHAPE_SIZES['decision']
    elif 'rectangle' in shape_type_lower or 'process' in shape_type_lower:
        return SHAPE_SIZES['process']
    elif 'parallelogram' in shape_type_lower or 'data' in shape_type_lower:
        return SHAPE_SIZES['data']
    elif 'hexagon' in shape_type_lower or 'preparation' in shape_type_lower:
        return SHAPE_SIZES['preparation']
    elif 'document' in shape_type_lower:
        return SHAPE_SIZES['document']
    else:
        # Default to process box size
        return SHAPE_SIZES['process']


def normalize_shape_type(shape_type: str) -> str:
    """
    Normalize a shape type using aliases.
    
    Args:
        shape_type: Input shape type (can be alias)
    
    Returns:
        Normalized shape type name
    """
    shape_type_lower = shape_type.lower()
    
    # Check direct alias match
    if shape_type_lower in SHAPE_TYPE_ALIASES:
        return SHAPE_TYPE_ALIASES[shape_type_lower]
    
    # Check if already in standard form
    for standard_type in DEFAULT_SHAPE_SIZES.keys():
        if shape_type_lower == standard_type.lower():
            return standard_type

    # Fallback: substring alias matching (prefer longer aliases first)
    try:
        alias_keys = sorted(SHAPE_TYPE_ALIASES.keys(), key=lambda k: len(k), reverse=True)
        for alias in alias_keys:
            # Avoid overly short Latin aliases to reduce false positives
            if alias.isascii() and alias.isalpha() and len(alias) < 3:
                continue
            if alias in shape_type_lower:
                return SHAPE_TYPE_ALIASES[alias]
    except Exception:
        pass
    
    # Return as-is if not found (let caller handle)
    return shape_type


def get_default_size(shape_type: str) -> dict:
    """
    Get default size for a shape type.
    
    Args:
        shape_type: Type of shape
    
    Returns:
        Dictionary with 'width' and 'height' in inches
    """
    normalized = normalize_shape_type(shape_type)
    return DEFAULT_SHAPE_SIZES.get(normalized, {'width': 1.5, 'height': 0.75})


def get_fill_color(shape_type: str) -> str:
    """
    Get recommended fill color for a shape type.
    
    Args:
        shape_type: Type of shape
    
    Returns:
        Hex color code
    """
    # Normalize first
    normalized = normalize_shape_type(shape_type)
    shape_type_lower = normalized.lower()
    
    if 'rounded' in shape_type_lower or 'terminator' in shape_type_lower:
        return COLORS['terminator_fill']
    elif 'diamond' in shape_type_lower or 'decision' in shape_type_lower:
        return COLORS['decision_fill']
    elif 'rectangle' in shape_type_lower or 'process' in shape_type_lower:
        return COLORS['process_fill']
    elif 'parallelogram' in shape_type_lower or 'data' in shape_type_lower:
        return COLORS['data_fill']
    else:
        return COLORS['default_fill']


# ===========================
# SHAPE TYPE ALIASES
# ===========================
# Map common shape names to standard types
SHAPE_TYPE_ALIASES = {
    # Rectangle variants
    'rect': 'Rectangle',
    'box': 'Rectangle',
    'square': 'Rectangle',
    'process': 'Rectangle',
    
    # Rounded rectangle variants
    'rounded': 'RoundedRectangle',
    'roundedrect': 'RoundedRectangle',
    'roundedbox': 'RoundedRectangle',
    'terminator': 'RoundedRectangle',
    'terminal': 'RoundedRectangle',
    'start': 'RoundedRectangle',
    'end': 'RoundedRectangle',
    
    # Diamond variants
    'rhombus': 'Diamond',
    'decision': 'Diamond',
    
    # Ellipse variants
    'oval': 'Ellipse',
    'circle': 'Ellipse',
    
    # Parallelogram variants
    'data': 'Parallelogram',
    'io': 'Parallelogram',
    'input': 'Parallelogram',
    'output': 'Parallelogram',
    
    # Hexagon variants
    'preparation': 'Hexagon',
    'prep': 'Hexagon',
    
    # Additional shapes
    'tri': 'Triangle',
    'trap': 'Trapezoid',
    'pent': 'Pentagon',

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

# ===========================
# DEFAULT SHAPE SIZES BY TYPE
# ===========================
DEFAULT_SHAPE_SIZES = {
    'Rectangle': {'width': 1.5, 'height': 0.75},
    'RoundedRectangle': {'width': 1.5, 'height': 0.6},
    'Diamond': {'width': 1.5, 'height': 1.0},
    'Ellipse': {'width': 1.2, 'height': 1.2},
    'Parallelogram': {'width': 1.5, 'height': 0.75},
    'Hexagon': {'width': 1.5, 'height': 0.75},
    'Triangle': {'width': 1.5, 'height': 1.0},
    'Pentagon': {'width': 1.5, 'height': 1.0},
    'Trapezoid': {'width': 1.5, 'height': 0.75},
}

# ===========================
# PROFESSIONAL LAYOUT PRESETS
# ===========================
LAYOUT_PRESETS = {
    'flowchart_vertical': {
        'description': 'Top-down flowchart with vertical progression',
        'start_x': PAGE_WIDTH_IN / 2,
        'start_y': PAGE_HEIGHT_IN - 1.5,
        'direction': 'down',
        'spacing': VERTICAL_SPACING_IN,
    },
    'flowchart_horizontal': {
        'description': 'Left-right flowchart with horizontal progression',
        'start_x': 1.5,
        'start_y': PAGE_HEIGHT_IN / 2,
        'direction': 'right',
        'spacing': HORIZONTAL_SPACING_IN,
    },
    'swimlane_vertical': {
        'description': 'Swimlane diagram with vertical lanes',
        'lane_width': 2.5,
        'lane_margin': 0.25,
        'header_height': 0.75,
    },
}

