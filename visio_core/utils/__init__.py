"""Utility functions for Visio system"""
from .diagram_builder import DiagramBuilder
from .logger import (
    VisioLogger,
    get_logger,
    log_operation,
    log_file_operation,
    save_diagram_copy,
    get_session_summary,
)
from .shape_identity import (
    get_shape_prop,
    set_shape_prop,
    index_shapes_by_key,
    find_shape_by_fallback,
    compute_edge_key,
    extract_edge_key_components,
)
from .edge_manager import EdgeCentricManager, EdgeDirection, EdgeType
from .layout_validator import (
    VisioLayoutValidator,
    LayoutIssue,
    QualityMetrics,
    validate_layout_file,
)

__all__ = [
    'DiagramBuilder',
    'VisioLogger',
    'get_logger',
    'log_operation',
    'log_file_operation',
    'save_diagram_copy',
    'get_session_summary',
    'get_shape_prop',
    'set_shape_prop',
    'index_shapes_by_key',
    'find_shape_by_fallback',
    'compute_edge_key',
    'extract_edge_key_components',
    'VisioLayoutValidator',
    'LayoutIssue',
    'QualityMetrics',
    'validate_layout_file',
]


