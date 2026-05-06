"""
Agno-compatible tools for Visio diagram manipulation
These tools can be used by AI agents to modify Visio diagrams

Enhanced with SessionContext for multi-turn conversation memory
"""
from typing import Optional, List, Dict, Any, Tuple
import json
import re
from ..templates.template_manager import TemplateManager
from ..templates.stencil_manager import StencilManager
from ..utils.diagram_builder import DiagramBuilder
from ..utils.logger import log_operation, log_file_operation, save_diagram_copy, get_session_summary, get_logger
from ..utils.layout_config import normalize_shape_type
from ..utils.visio_render import render_vsdx_page_to_data_uri, render_and_save_png
from ..utils.shape_identity import get_shape_prop
from ..utils.stencil_parser import StencilParser
from ..utils.text_normalization import normalize_shape_text
from ..context.session_context import DialogContextStore, SessionContext, DisabledDialogContextStore


class VisioTools:
    """Collection of tools for Visio diagram manipulation with logging"""
    
    def __init__(self, session_id: str = "default", dialog_dir: str = ".state/dialog", auto_restore: bool = True, record_context: bool = True):
        """Initialize tools with default session context persistence."""
        self.diagram_builder: Optional[DiagramBuilder] = None
        self.current_file_path: Optional[str] = None
        # Session context
        self._session_id: str = session_id or "default"
        self._context_store = DialogContextStore(dialog_dir) if record_context else DisabledDialogContextStore(dialog_dir)
        self._restored_once: bool = False
        if auto_restore:
            self._try_restore()
        # Max inline image size to avoid token overflow
        self._max_inline_data_uri_chars: int = 120_000
        # Stencil cache: path -> StencilParser
        self._stencil_cache: Dict[str, StencilParser] = {}
        # Template and Stencil managers for library management
        self._template_manager: Optional[TemplateManager] = None
        self._stencil_manager: Optional[StencilManager] = None
        # Track unsaved changes to warn users
        self._has_unsaved_changes: bool = False
    
    def set_diagram(self, diagram_builder: DiagramBuilder, file_path: str):
        """Set the current diagram to work with"""
        self.diagram_builder = diagram_builder
        self.current_file_path = file_path
        try:
            self._persist()
        except Exception:
            pass

    # ---------- Session context helpers ----------
    def _current_page_index(self) -> int:
        try:
            if not self.diagram_builder:
                return 0
            pages = self.diagram_builder.list_pages() or []
            curr = getattr(self.diagram_builder.current_page, 'name', None)
            return pages.index(curr) if curr in pages else 0
        except Exception:
            return 0

    def _persist(self):
        """Persist current state to SessionContext"""
        if not self.diagram_builder:
            return
        try:
            # Load existing SessionContext or create new one
            session_ctx = self._context_store.load_context(self._session_id)
            
            # Update diagram state
            session_ctx.current_file_path = self.current_file_path
            session_ctx.current_page_index = self._current_page_index()
            
            # Save updated context
            self._context_store.save_context(session_ctx)
        except Exception:
            # Fallback to old dict-based save for backwards compatibility
            ctx = {
                "current_file_path": self.current_file_path,
                "current_page_index": self._current_page_index(),
            }
            self._context_store.save(self._session_id, ctx)

    def _try_restore(self):
        """Try to restore previous session state from SessionContext"""
        if self._restored_once:
            return
        self._restored_once = True
        try:
            # Try to load SessionContext
            session_ctx = self._context_store.load_context(self._session_id)
            fp = session_ctx.current_file_path
            idx = session_ctx.current_page_index
            
            if fp:
                self.diagram_builder = DiagramBuilder.load_from_file(fp)
                self.current_file_path = fp
                try:
                    self.diagram_builder.get_page(idx)
                except Exception:
                    pass
        except Exception:
            # Ignore restore errors to avoid blocking normal flows
            pass

    def _ensure_loaded_or_error(self, message: str) -> Optional[str]:
        if not self.diagram_builder:
            self._restored_once = False  # allow re-attempt when state is missing
            self._try_restore()
        if not self.diagram_builder:
            return message
        return None

    def _resolve_shape_id(self, shape_identifier: str) -> Optional[str]:
        """Convert node key to shape ID if needed, or return shape ID if already valid."""
        if not self.diagram_builder or not self.diagram_builder.current_page:
            return None
        
        # Check if it's already a valid shape ID
        try:
            if self.diagram_builder.get_shape_by_id(shape_identifier):
                return shape_identifier
        except Exception:
            pass
        
        # Try to find by node key using the proper indexing method
        from ..utils.shape_identity import index_shapes_by_key
        nodes_by_key, _ = index_shapes_by_key(self.diagram_builder.current_page, self.diagram_builder)
        
        if shape_identifier in nodes_by_key:
            shape = nodes_by_key[shape_identifier]
            shape_id = getattr(shape, 'ID', None)
            if shape_id:
                return str(shape_id)
        
        # Try to find in shapes with text matching the identifier
        try:
            shapes = self.diagram_builder.list_shapes()
            for shape in shapes:
                if shape.get('text') == shape_identifier:
                    return shape.get('id')
        except Exception:
            pass
        
        return None
        
        # Try to find by node key in shape_map
        shape_map = getattr(self.diagram_builder, 'shape_map', {})
        for shape_id, shape_info in shape_map.items():
            if isinstance(shape_info, dict) and shape_info.get('node_key') == shape_identifier:
                return shape_id
        
        # Try to find in shapes with text matching the identifier
        try:
            shapes = self.diagram_builder.list_shapes()
            for shape in shapes:
                if shape.get('text') == shape_identifier:
                    return shape.get('id')
        except Exception:
            pass
        
        return None

    # ---------- Public session APIs ----------
    def set_session(self, session_id: str) -> str:
        sid = (session_id or "default").strip()
        self._session_id = sid
        self._restored_once = False
        self._try_restore()
        if self.diagram_builder:
            return f"✓ Session set to '{sid}' and restored diagram"
        return f"✓ Session set to '{sid}' (no prior diagram)"

    def reset_session(self, session_id: Optional[str] = None) -> str:
        if session_id is not None:
            self._session_id = (session_id or "default").strip()
        try:
            self._context_store.delete(self._session_id)
        except Exception:
            pass
        self.diagram_builder = None
        self.current_file_path = None
        self._restored_once = True
        return f"✓ Session '{self._session_id}' reset"

    def get_session_context(self) -> str:
        """Get full session context including operation history and user intent"""
        try:
            session_ctx = self._context_store.load_context(self._session_id)
            
            # Build a comprehensive context summary
            summary_lines = [
                f"Session ID: {session_ctx.session_id}",
                f"Current File: {session_ctx.current_file_path or 'None'}",
                f"Current Page: {session_ctx.current_page_index}",
            ]
            
            if session_ctx.user_intent:
                summary_lines.append(f"User Intent: {session_ctx.user_intent}")
            
            if session_ctx.task_type:
                summary_lines.append(f"Task Type: {session_ctx.task_type}")
            
            # Recent operations
            recent_ops = session_ctx.get_recent_operations(5)
            if recent_ops:
                summary_lines.append("\nRecent Operations:")
                for i, op in enumerate(recent_ops, 1):
                    summary_lines.append(f"  {i}. {op['description']} ({op['type']})")
            
            # Key decisions
            if session_ctx.key_decisions:
                summary_lines.append("\nKey Decisions:")
                for decision in session_ctx.key_decisions[-3:]:
                    summary_lines.append(f"  - {decision['description']}: {decision['choice']}")
            
            return "\n".join(summary_lines)
        except Exception as e:
            # Fallback to simple context
            return f"Session ID: {self._session_id}\nCurrent File: {self.current_file_path or 'None'}\nError: {str(e)}"
    
    def load_diagram(self, filepath: str) -> str:
        """
        Load an existing Visio diagram file for viewing or editing.
        
        This tool opens a .vsdx Visio file and loads it into memory.
        You can use this to:
        - View/inspect template files (assets/templates/library/<name>.vsdx) without modifying them
        - Load diagrams for editing
        
        IMPORTANT: Loading a file does NOT modify it. The original file remains 
        unchanged until you explicitly call save_diagram(). This means you can 
        safely load template files to inspect their shapes without creating a copy.
        
        Args:
            filepath: Path to the .vsdx file to load (can be template or regular file)
        
        Returns:
            Status message with diagram information including pages and shape count
        
        Examples:
            load_diagram("assets/templates/library/example.vsdx")  # Safe to view template
            load_diagram("my_flowchart.vsdx")   # Load for editing
            
        After loading, use list_shapes() to see all shapes in the current page.
        """
        try:
            self.diagram_builder = DiagramBuilder.load_from_file(filepath)
            self.current_file_path = filepath
            info = self.diagram_builder.get_diagram_info()
            try:
                self._persist()
            except Exception:
                pass
            
            result = f"✓ Loaded diagram from {filepath}\n" + \
                   f"Pages: {', '.join(info['pages'])}\n" + \
                   f"Shapes in current page: {info['shapes_count']}"
            
            # Log operation
            log_operation(
                operation="load_diagram",
                details={"filepath": filepath},
                result=result,
                success=True
            )
            log_file_operation(filepath, "loaded")
            
            # Track operation in session context
            try:
                session_ctx = self._context_store.load_context(self._session_id)
                session_ctx.add_operation(
                    "load_diagram",
                    f"Loaded diagram: {filepath}",
                    {"filepath": filepath, "pages": info['pages'], "shape_count": info['shapes_count']}
                )
                self._context_store.save_context(session_ctx)
            except Exception:
                pass  # Don't fail operation if context tracking fails
            
            return result
        except Exception as e:
            error_msg = f"✗ Error loading diagram: {str(e)}"
            log_operation(
                operation="load_diagram",
                details={"filepath": filepath},
                result=error_msg,
                success=False
            )
            return error_msg
    
    def create_new_diagram(self, page_name: str = "Page-1") -> str:
        """
        Create a new empty Visio diagram.

        Note: Creating diagrams from scratch is not well supported.
        It's recommended to load an existing template instead.

        Args:
            page_name: Name for the first page

        Returns:
            Status message

        Example:
            create_new_diagram("My Diagram")
        """
        error_msg = "✗ Creating new diagrams from scratch is not supported. Please load an existing template file instead."
        log_operation(
            operation="create_new_diagram",
            details={"page_name": page_name},
            result=error_msg,
            success=False
        )
        return error_msg
    
    def get_diagram_info(self) -> str:
        """
        Get detailed information about the currently loaded diagram.
        获取当前加载图表的详细信息。
        
        This shows pages, current page name, number of shapes, and details
        about each shape including ID, text, and type.
        
        中文指令：获取信息、查看信息、显示详情、图表信息
        
        Returns:
            Formatted diagram information string
        
        Example:
            get_diagram_info()
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram or create_new_diagram first.")
        if err:
            return err
        
        info = self.diagram_builder.get_diagram_info()
        
        result = f"📊 Diagram Information:\n"
        result += f"File: {self.current_file_path or 'N/A'}\n"
        result += f"Pages: {', '.join(info['pages'])}\n"
        result += f"Current page: {info['current_page']}\n"
        result += f"Number of shapes: {len(info.get('shapes', []))}\n"
        result += f"Number of connectors: {info.get('connector_count', 0)}\n\n"
        
        if info.get('shapes'):
            result += "Shapes:\n"
            for shape in info['shapes']:
                result += f"  - ID: {shape['id']}, Text: '{shape['text']}', Type: {shape['type']}\n"
        
        if info.get('connectors'):
            result += "\nConnectors:\n"
            for conn in info['connectors']:
                result += f"  - ID: {conn['id']}, Label: '{conn['text']}', Key: {conn.get('edge_key', 'N/A')}\n"
        
        log_operation(
            operation="get_diagram_info",
            details={"file": self.current_file_path},
            result=f"Retrieved info for {info['shapes_count']} shapes",
            success=True
        )
        
        return result
    
    def add_shape(self, text: str, shape_type: str = "Rectangle", 
                  x: float = 4.0, y: float = 4.0,
                  width: float = 1.5, height: float = 0.75) -> str:
        """
        Add a new shape to the current diagram.
        添加新形状到当前图表。
        
        Creates a shape by copying an existing shape and modifying its properties.
        Position is specified in inches from bottom-left corner of the page.
        
        中文指令：添加形状、新增图形、创建形状、加个矩形/菱形
        
        Args:
            text: Text to display inside the shape
            shape_type: Type of shape (Rectangle, Ellipse, Diamond, RoundedRectangle, etc.)
            x: X position in inches (0-8.5 for letter size)
            y: Y position in inches (0-11 for letter size)
            width: Width of shape in inches
            height: Height of shape in inches
        
        Returns:
            Status message with the new shape's ID
        
        Example:
            add_shape("Process Step", "Rectangle", 4.0, 5.0, 1.5, 0.75)
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        
        shape = self.diagram_builder.add_shape(text, shape_type, x, y, width, height)
        if shape:
            shape_id = getattr(shape, 'ID', 'unknown')
            result = f"✓ Added {shape_type} shape '{text}' at ({x:.1f}, {y:.1f}). Shape ID: {shape_id}"
            
            log_operation(
                operation="add_shape",
                details={
                    "text": text,
                    "shape_type": shape_type,
                    "x": x, "y": y,
                    "width": width, "height": height,
                    "shape_id": str(shape_id)
                },
                result=result,
                success=True
            )
            
            # Track operation in session context
            try:
                session_ctx = self._context_store.load_context(self._session_id)
                session_ctx.add_operation(
                    "add_shape",
                    f"Added {shape_type} shape: {text}",
                    {"shape_type": shape_type, "text": text, "shape_id": str(shape_id)}
                )
                self._context_store.save_context(session_ctx)
            except Exception:
                pass  # Don't fail operation if context tracking fails
            
            return result
        else:
            error_msg = f"✗ Failed to add shape '{text}'. Possible reasons:\n"
            error_msg += "  - Current page has no shapes to use as template\n"
            error_msg += "  - Try loading a diagram with existing shapes first\n"
            error_msg += "  - Check console output for detailed error"
            
            log_operation(
                operation="add_shape",
                details={"text": text, "shape_type": shape_type, "x": x, "y": y},
                result=error_msg,
                success=False
            )
            return error_msg
    
    def update_shape_text(self, shape_id: str, new_text: str) -> str:
        """
        Update the text content of an existing shape.
        更新现有形状的文本内容。
        
        中文指令：修改文本、更新文字、改变内容、修改形状文字
        
        Args:
            shape_id: ID of the shape to update (use get_diagram_info to find IDs)
            new_text: New text content for the shape
        
        Returns:
            Status message
        
        Example:
            update_shape_text("5", "Updated Process Name")
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err

        normalized_text, normalized_changed = normalize_shape_text(new_text)
        success = self.diagram_builder.update_shape_text(shape_id, normalized_text)
        if success:
            result = f"✓ Updated shape {shape_id}: '{normalized_text}'"
            if normalized_changed:
                result += " (normalized embedded line breaks)"
            log_operation(
                operation="update_shape_text",
                details={
                    "shape_id": shape_id,
                    "new_text": normalized_text,
                    "normalized_line_breaks": normalized_changed,
                },
                result=result,
                success=True
            )
            
            # Track operation in session context
            try:
                session_ctx = self._context_store.load_context(self._session_id)
                session_ctx.add_operation(
                    "update_text",
                    f"Updated shape {shape_id} text to: {normalized_text[:50]}",
                    {
                        "shape_id": shape_id,
                        "new_text": normalized_text,
                        "normalized_line_breaks": normalized_changed,
                    }
                )
                self._context_store.save_context(session_ctx)
            except Exception:
                pass  # Don't fail operation if context tracking fails
            
            return result
        else:
            error_msg = f"✗ Failed to update shape {shape_id}. Possible reasons:\n"
            error_msg += f"  - Shape ID '{shape_id}' not found on current page\n"
            error_msg += f"  - Use list_shapes or get_diagram_info to find valid IDs\n"
            error_msg += f"  - Ensure you're on the correct page (use switch_page if needed)"
            
            log_operation(
                operation="update_shape_text",
                details={
                    "shape_id": shape_id,
                    "new_text": normalized_text,
                    "normalized_line_breaks": normalized_changed,
                },
                result=error_msg,
                success=False
            )
            return error_msg

    def set_node_key(self, shape_id: str, node_key: str) -> str:
        """Assign a stable NodeKey property to a shape by its numeric ID.

        Used internally by ``edit_shape`` when the caller provides
        ``patch["node_key"]``.  After this call the shape can be referenced
        by ``node_key`` in subsequent ``upsert_connector`` calls.

        Args:
            shape_id: Numeric string ID of the target shape.
            node_key: The key to assign (must be non-empty).

        Returns:
            Status message.
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        if not node_key:
            return "✗ node_key must be a non-empty string."
        from ..utils.shape_identity import set_shape_prop
        shape = self.diagram_builder.get_shape_by_id(shape_id)
        if not shape:
            msg = f"✗ Shape '{shape_id}' not found."
            log_operation("set_node_key", {"shape_id": shape_id, "node_key": node_key}, msg, False)
            return msg
        success = set_shape_prop(shape, "NodeKey", node_key)
        if success:
            result = f"✓ NodeKey '{node_key}' set on shape {shape_id}."
            log_operation("set_node_key", {"shape_id": shape_id, "node_key": node_key}, result, True)
            return result
        msg = f"✗ Failed to set NodeKey '{node_key}' on shape {shape_id}."
        log_operation("set_node_key", {"shape_id": shape_id, "node_key": node_key}, msg, False)
        return msg

    def connect_shapes(self, from_shape_id: str, to_shape_id: str) -> str:
        """
        Connect two shapes with a connector line.
        用连接线连接两个形状。
        
        Creates a connector between two shapes to show flow or relationship using
        the vsdx connector library directly. If the diagram already contains
        connectors, their styling is reused automatically, but no template is required.
        
        中文指令：连接形状、链接、画连接线、把...连到...
        
        Args:
            from_shape_id: ID of the source shape
            to_shape_id: ID of the target shape
        
        Returns:
            Status message
        
        Example:
            connect_shapes("3", "5")
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        
        success = self.diagram_builder.connect_shapes(from_shape_id, to_shape_id)
        if success:
            result = f"✓ Connected shape {from_shape_id} → {to_shape_id}"
            log_operation(
                operation="connect_shapes",
                details={"from_shape_id": from_shape_id, "to_shape_id": to_shape_id},
                result=result,
                success=True
            )
            return result
        else:
            error_msg = f"✗ Failed to connect shapes {from_shape_id} → {to_shape_id}. Possible reasons:\n"
            error_msg += f"  - One or both shape IDs not found\n"
            error_msg += f"  - Use list_shapes to verify shape IDs\n"
            error_msg += f"  - Check console output for detailed error"
            
            log_operation(
                operation="connect_shapes",
                details={"from_shape_id": from_shape_id, "to_shape_id": to_shape_id},
                result=error_msg,
                success=False
            )
            return error_msg
    
    def remove_shape(self, shape_id: str) -> str:
        """
        Remove a shape from the diagram.
        从图表中删除形状。
        
        Permanently deletes the specified shape from the current page.
        Connector targets are auto-routed to connector-specific deletion.
        
        中文指令：删除形状、移除、去掉、删掉
        
        Args:
            shape_id: ID of the shape or connector to remove
        
        Returns:
            Status message
        
        Example:
            remove_shape("7")
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err

        resolved_shape_id = self._resolve_shape_id(shape_id) or shape_id
        target_shape = self.diagram_builder.get_shape_by_id(resolved_shape_id)
        if target_shape and self.diagram_builder._is_connector(target_shape):
            return self._remove_connector_with_logging(
                resolved_shape_id,
                operation="remove_shape",
                details={
                    "requested_identifier": shape_id,
                    "resolved_shape_id": resolved_shape_id,
                    "target_type": "connector",
                    "routed_to": "remove_connector",
                },
            )

        outcome = self.diagram_builder.remove_shape(resolved_shape_id)
        if isinstance(outcome, tuple):
            success, reason = outcome
        else:
            success, reason = bool(outcome), ""
        if success:
            result = f"✓ Removed shape {shape_id}"
            log_operation(
                operation="remove_shape",
                details={
                    "shape_id": resolved_shape_id,
                    "requested_identifier": shape_id,
                },
                result=result,
                success=True
            )
            return result
        else:
            error_msg = f"✗ Failed to remove shape {shape_id}."
            if reason:
                error_msg += f" [{reason}]"
            error_msg += "\n  - Shape ID was not found, or connector cleanup failed"
            error_msg += f"\n  - Use list_shapes to find valid shape IDs"
            error_msg += f"\n  - Check console output for detailed error"
            
            log_operation(
                operation="remove_shape",
                details={
                    "shape_id": resolved_shape_id,
                    "requested_identifier": shape_id,
                    "reason": reason,
                },
                result=error_msg,
                success=False
            )
            return error_msg

    def _remove_connector_with_logging(
        self,
        connector_id: str,
        operation: str = "remove_connector",
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Remove a connector and record the routed operation."""
        connector = self.diagram_builder.get_shape_by_id(connector_id)
        op_details = {"connector_id": connector_id, **(details or {})}

        if not connector:
            result = f"✗ Connector '{connector_id}' not found"
            log_operation(operation, op_details, result, False)
            return result

        if not self.diagram_builder._is_connector(connector):
            result = f"✗ Shape '{connector_id}' is not a connector"
            log_operation(operation, op_details, result, False)
            return result

        success = self.diagram_builder.remove_connector(connector_id)
        if success:
            result = f"✓ Removed connector {connector_id}"
            log_operation(operation, op_details, result, True)
            return result

        error_msg = f"✗ Failed to remove connector {connector_id}. Possible reasons:\n"
        error_msg += "  - Connector ID was not found on current page\n"
        error_msg += "  - Connector XML could not be removed cleanly\n"
        error_msg += "  - Check console output for detailed error"
        log_operation(operation, op_details, error_msg, False)
        return error_msg

    def remove_connector(self, connector_id: str) -> str:
        """
        Remove a connector from the diagram.
        从图表中删除连接线。

        Args:
            connector_id: ID of the connector to remove

        Returns:
            Status message

        Example:
            remove_connector("12")
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err

        return self._remove_connector_with_logging(connector_id, operation="remove_connector")
    
    def remove_shape_smart(self, shape_identifier: str, reconnect_mode: str = "remove_connectors") -> str:
        """
        Remove a shape with advanced connector management options.
        智能删除形状，自动处理连接线。
        
        Provides enhanced control over how connectors are handled when removing
        shapes. Connector targets are auto-routed to connector deletion.
        
        Args:
            shape_identifier: ID or NodeKey of the shape or connector to remove
            reconnect_mode: Connector handling mode:
                - "remove_connectors": Remove connected connectors only (default, safest for scoped deletions)
                - "smart_reconnect": Reconnect through the deleted shape when the user explicitly wants to preserve flow
                - "validate_only": Check if safe to remove without actually removing
        
        Returns:
            Status message with details
        
        Example:
            remove_shape_smart("7")  # By shape ID, conservative connector cleanup
            remove_shape_smart("nodeA")  # By node key
            remove_shape_smart("7", "smart_reconnect")
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        
        # Validate reconnect_mode
        valid_modes = ["smart_reconnect", "remove_connectors", "validate_only"]
        if reconnect_mode not in valid_modes:
            return f"✗ Invalid reconnect_mode '{reconnect_mode}'. Must be one of: {', '.join(valid_modes)}"
        
        # Convert node key to shape ID if needed
        shape_id = self._resolve_shape_id(shape_identifier)
        if not shape_id:
            return f"✗ Shape '{shape_identifier}' not found"

        target_shape = self.diagram_builder.get_shape_by_id(shape_id)
        if target_shape and self.diagram_builder._is_connector(target_shape):
            if reconnect_mode == "validate_only":
                return (
                    f"✓ Connector {shape_identifier} is safe to remove. "
                    "remove_shape will route it to connector deletion."
                )
            return self._remove_connector_with_logging(
                shape_id,
                operation="remove_shape_smart",
                details={
                    "requested_identifier": shape_identifier,
                    "resolved_shape_id": shape_id,
                    "target_type": "connector",
                    "routed_to": "remove_connector",
                    "reconnect_mode": reconnect_mode,
                },
            )
        
        if reconnect_mode == "validate_only":
            # Just check if safe to remove
            connections = self.diagram_builder.get_shape_connections(shape_id)
            total_connections = len(connections.get('incoming', [])) + len(connections.get('outgoing', []))
            if total_connections == 0:
                return f"✓ Shape {shape_identifier} is safe to remove (no connections)"
            else:
                return f"⚠ Shape {shape_identifier} has {total_connections} connections. Use smart_reconnect to preserve flow."
        
        outcome = self.diagram_builder.remove_shape_with_connector_management(shape_id, reconnect_mode)
        # Support both old (bool) and new (bool, reason) return shapes
        if isinstance(outcome, tuple):
            success, reason = outcome
        else:
            success, reason = bool(outcome), ""
        if success:
            mode_desc = {
                "smart_reconnect": "with smart reconnection",
                "remove_connectors": "with connector cleanup"
            }
            result = f"✓ Removed shape {shape_identifier} {mode_desc.get(reconnect_mode, '')}"
            log_operation(
                operation="remove_shape_smart",
                details={"shape_id": shape_id, "reconnect_mode": reconnect_mode},
                result=result,
                success=True
            )
            return result
        else:
            _reason_hints = {
                "NO_SHAPE": "Shape ID not found on the current page. Call analyze_template to list valid IDs.",
                "IS_CONNECTOR": "Target resolved to a connector after lookup. Refresh the live shape list and retry.",
                "SAVE_REQUIRED": "Diagram must be saved and reloaded before shapes can be removed.",
                "EDGE_ERROR": "Connector-management step encountered an error (see detail below).",
            }
            base_code = reason.split(":")[0] if reason else ""
            hint = _reason_hints.get(base_code, "")
            reason_detail = f" [{reason}]" if reason else ""
            hint_detail = f" Hint: {hint}" if hint else ""
            error_msg = f"✗ Failed to remove shape {shape_identifier}.{reason_detail}{hint_detail}"
            log_operation(
                operation="remove_shape_smart",
                details={"shape_id": shape_id, "reconnect_mode": reconnect_mode, "reason": reason},
                result=error_msg,
                success=False
            )
            return error_msg
    
    def cleanup_diagram_connectors(self) -> str:
        """
        Clean up connector issues in the diagram.
        清理图表中的连接线问题。
        
        Removes orphaned connectors and resolves ambiguous paths.
        
        Returns:
            Status message with cleanup statistics
        
        Example:
            cleanup_diagram_connectors()
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        
        # Clean up orphaned connectors
        orphaned_cleaned = self.diagram_builder.cleanup_orphaned_connectors()
        
        # Resolve connector ambiguities
        ambiguity_results = self.diagram_builder.resolve_connector_ambiguity()
        
        result = f"✓ Connector cleanup complete:\n"
        result += f"  - Orphaned connectors removed: {orphaned_cleaned}\n"
        result += f"  - Ambiguities resolved: {ambiguity_results['resolved_ambiguities']}\n"
        result += f"  - Duplicate connectors removed: {ambiguity_results['removed_duplicates']}"
        
        log_operation(
            operation="cleanup_diagram_connectors",
            details={"orphaned_cleaned": orphaned_cleaned, "ambiguity_results": ambiguity_results},
            result=result,
            success=True
        )
        
        return result
    
    def validate_diagram_connectors(self) -> str:
        """
        Validate the integrity of all connectors in the diagram.
        验证图表中所有连接线的完整性。
        
        Checks for connector issues like missing endpoints, orphaned connectors, etc.
        
        Returns:
            Validation report with issues found
        
        Example:
            validate_diagram_connectors()
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        
        integrity = self.diagram_builder.validate_connector_integrity()
        
        result = f"📊 Connector Validation Report:\n"
        result += f"  Total connectors: {integrity['total_connectors']}\n"
        result += f"  Valid connectors: {integrity['valid_connectors']}\n"
        result += f"  Integrity score: {integrity['integrity_score']:.1%}\n"
        
        if integrity['issues']:
            result += f"\n⚠ Issues found ({len(integrity['issues'])}):\n"
            for issue in integrity['issues'][:10]:  # Show first 10 issues
                result += f"  - {issue['description']}\n"
            if len(integrity['issues']) > 10:
                result += f"  ... and {len(integrity['issues']) - 10} more issues\n"
        else:
            result += "\n✓ No connector issues found!"
        
        log_operation(
            operation="validate_diagram_connectors",
            details={"integrity": integrity},
            result=f"Validated {integrity['total_connectors']} connectors",
            success=True
        )
        
        return result
    
    def verify_connector_persisted(self, edge_key: str, file_path: str = None) -> str:
        """
        Verify that a connector has been successfully persisted to a saved Visio file.
        验证连接器是否已成功保存到文件中。
        
        This tool opens a saved .vsdx file and checks if the connector with the specified
        edge_key exists in the file. This is useful for confirming that connectors were
        properly saved after creation, not just created in memory.
        
        Args:
            edge_key: The EdgeKey of the connector to verify (e.g., "node1_node2_label")
            file_path: Path to the saved .vsdx file. If not provided, uses current loaded file.
        
        Returns:
            Verification result with connector details or error message
        
        Example:
            # After creating connector and saving
            add_or_update_connector("step1", "step2", "Yes")
            save_diagram("outputs/my_diagram.vsdx")
            verify_connector_persisted("step1_step2_Yes", "outputs/my_diagram.vsdx")
        """
        from ..utils.shape_identity import get_shape_prop
        import vsdx
        
        # Determine file path
        if file_path is None:
            if not self.diagram_builder or not self.diagram_builder.save_path:
                return "✗ No file_path provided and no currently loaded file"
            file_path = self.diagram_builder.save_path
        
        # Check if file exists
        import os
        if not os.path.exists(file_path):
            return f"✗ File not found: {file_path}"
        
        try:
            # Open the saved file (fresh load from disk)
            verification_file = vsdx.VisioFile(file_path)
            verification_page = verification_file.pages[0] if verification_file.pages else None
            
            if not verification_page:
                return f"✗ No pages found in file: {file_path}"
            
            # Search for connector with matching EdgeKey
            connector_found = False
            connector_info = None
            
            for shape in verification_page.child_shapes:
                try:
                    # Check if this is a connector
                    shape_type = getattr(shape, 'type', '')
                    if 'connect' not in shape_type.lower():
                        continue
                    
                    # Check EdgeKey property
                    shape_edge_key = get_shape_prop(shape, 'EdgeKey')
                    if shape_edge_key == edge_key:
                        connector_found = True
                        connector_id = getattr(shape, 'ID', 'unknown')
                        connector_text = getattr(shape, 'text', '')
                        
                        # Get connection info
                        begin_x = shape.cells.get('BeginX', {}).get('formula', 'N/A')
                        end_x = shape.cells.get('EndX', {}).get('formula', 'N/A')
                        
                        connector_info = {
                            'id': connector_id,
                            'edge_key': shape_edge_key,
                            'text': connector_text,
                            'begin_x': begin_x,
                            'end_x': end_x
                        }
                        break
                        
                except Exception as e:
                    # Skip shapes that can't be inspected
                    continue
            
            if connector_found:
                result = f"✓ Connector verified in file: {file_path}\n"
                result += f"  Edge Key: {edge_key}\n"
                result += f"  Connector ID: {connector_info['id']}\n"
                result += f"  Label: {connector_info['text']}\n"
                result += f"  BeginX: {connector_info['begin_x']}\n"
                result += f"  EndX: {connector_info['end_x']}\n"
                result += f"\n✓ Connector successfully persisted to file!"
                
                log_operation(
                    operation="verify_connector_persisted",
                    details={'edge_key': edge_key, 'file_path': file_path, 'found': True},
                    result="Connector verified",
                    success=True
                )
                return result
            else:
                result = f"✗ Connector NOT found in file: {file_path}\n"
                result += f"  Edge Key searched: {edge_key}\n"
                result += f"\n⚠️ This means the connector was created in memory but not saved to file.\n"
                result += f"💡 Make sure to call save_diagram() after add_or_update_connector()"
                
                log_operation(
                    operation="verify_connector_persisted",
                    details={'edge_key': edge_key, 'file_path': file_path, 'found': False},
                    result="Connector not found in saved file",
                    success=False
                )
                return result
                
        except Exception as e:
            error_msg = f"✗ Error verifying connector: {str(e)}"
            log_operation(
                operation="verify_connector_persisted",
                details={'edge_key': edge_key, 'file_path': file_path, 'error': str(e)},
                result=error_msg,
                success=False
            )
            return error_msg
    
    def clone_shape(self, shape_id: str, x: float = None, y: float = None, 
                    text: str = None) -> str:
        """
        Create an exact clone of an existing shape with perfect fidelity.
        创建现有形状的精确克隆副本。
        
        This creates a pixel-perfect copy of a shape, preserving all formatting,
        colors, styles, and visual properties. This is the BEST method for creating
        new shapes that match existing ones exactly.
        
        中文指令：克隆形状、复制形状、拷贝
        
        Args:
            shape_id: ID of the shape to clone (use list_shapes to find IDs)
            x: X position for the clone (in inches). If not provided, places 1 inch to the right
            y: Y position for the clone (in inches). If not provided, places 1 inch below
            text: Optional new text for the cloned shape (keeps original text if not provided)
        
        Returns:
            Status message with the new shape's ID
        
        Example:
            clone_shape("5", 6.0, 8.0, "New Process")
            clone_shape("5")  # Auto-offset position, keep same text
        
        Note:
            This is superior to add_shape() when you want to preserve exact formatting.
            Use this when you need shapes that look identical to existing ones.
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        
        new_shape = self.diagram_builder.clone_shape(shape_id, x, y, text)
        if new_shape:
            new_shape_id = getattr(new_shape, 'ID', 'unknown')
            pos_info = f"at ({x:.1f}, {y:.1f})" if x is not None and y is not None else "with auto-offset"
            text_info = f"with text '{text}'" if text else "preserving original text"
            result = f"✓ Cloned shape {shape_id} → new shape {new_shape_id} {pos_info} {text_info}"
            
            log_operation(
                operation="clone_shape",
                details={
                    "source_shape_id": shape_id,
                    "new_shape_id": str(new_shape_id),
                    "x": x, "y": y,
                    "text": text
                },
                result=result,
                success=True
            )
            return result
        else:
            error_msg = f"✗ Failed to clone shape {shape_id}. Possible reasons:\n"
            error_msg += f"  - Shape ID '{shape_id}' not found on current page\n"
            error_msg += f"  - Use list_shapes to find valid shape IDs\n"
            error_msg += f"  - Check console output for detailed error"
            
            log_operation(
                operation="clone_shape",
                details={"shape_id": shape_id, "x": x, "y": y, "text": text},
                result=error_msg,
                success=False
            )
            return error_msg
    
    def find_shape_by_text(self, text: str, mode: str = "contains") -> str:
        """
        Find a shape by searching for text content.
        通过文本内容查找形状。
        
        Searches all shapes in the current page for matching text.
        
        中文指令：查找形状、搜索、找到包含...的形状
        
        Args:
            text: Text to search for
            mode: Matching mode - "equals" (exact match), "contains" (partial match, default), or "regex" (regex pattern)
        
        Returns:
            Shape information if found, or error message
        
        Example:
            find_shape_by_text("Start")
            find_shape_by_text("Start", mode="equals")
            find_shape_by_text("Start.*", mode="regex")
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        
        # Validate mode
        if mode not in ["equals", "contains", "regex"]:
            return f"✗ Invalid mode '{mode}'. Must be one of: 'equals', 'contains', 'regex'"
        
        shape = self.diagram_builder.find_shape_by_text(text, mode)
        if shape:
            shape_id = getattr(shape, 'ID', 'unknown')
            shape_type = getattr(shape, 'shape_type', 'unknown')
            shape_text = getattr(shape, 'text', '').strip()
            result = f"✓ Found shape: ID={shape_id}, Type={shape_type}, Text='{shape_text}' (mode={mode})"
            
            log_operation(
                operation="find_shape_by_text",
                details={"text": text, "mode": mode, "found_id": str(shape_id)},
                result=f"Found shape ID={shape_id}",
                success=True
            )
            return result
        else:
            error_msg = f"✗ No shape found with text '{text}' (mode={mode}). Try:\n"
            error_msg += f"  - Use list_shapes to see all available shapes and their text\n"
            error_msg += f"  - Check if you're on the correct page (use get_diagram_info)\n"
            error_msg += f"  - Try different mode: 'equals', 'contains', or 'regex'"
            
            log_operation(
                operation="find_shape_by_text",
                details={"text": text, "mode": mode},
                result=error_msg,
                success=False
            )
            return error_msg
    
    def _translate_shape_type(self, shape_type: str) -> str:
        """Translate English shape type to Chinese"""
        type_mapping = {
            'Rectangle': '矩形',
            'RoundedRectangle': '圆角矩形',
            'Diamond': '菱形',
            'Ellipse': '椭圆',
            'Parallelogram': '平行四边形',
            'Hexagon': '六边形',
            'Connector': '连接器',
            'Triangle': '三角形',
            'Pentagon': '五边形',
            'Octagon': '八边形',
            'Circle': '圆形',
            'Cylinder': '圆柱',
            'Cloud': '云形',
            'Star': '星形',
        }
        return type_mapping.get(shape_type, shape_type)
    
    def _infer_display_type(self, shape: Any) -> str:
        """Infer a concrete, human-friendly shape type for display/filtering."""
        try:
            # Connector special-case
            if hasattr(self, 'diagram_builder') and self.diagram_builder and \
               hasattr(self.diagram_builder, '_is_connector') and \
               self.diagram_builder._is_connector(shape):
                return 'Connector'

            master = getattr(shape, 'master', None)
            master_name = (getattr(master, 'name', '') or '').strip()
            shape_type_attr = (getattr(shape, 'shape_type', '') or '').strip()
            text = (getattr(shape, 'text', '') or '').strip()

            # 1) Master name based
            if master_name:
                norm = normalize_shape_type(master_name)
                if norm and norm.lower() not in ('', 'shape', 'unknown'):
                    return norm

            # 2) shape.shape_type based
            if shape_type_attr:
                norm2 = normalize_shape_type(shape_type_attr)
                if norm2 and norm2.lower() not in ('', 'shape', 'unknown'):
                    return norm2

            # 3) Text heuristics (common flowchart cues)
            text_lower = text.lower()
            if any(k in text_lower for k in ['start', 'end']) or any(k in text for k in ['开始', '结束']):
                return 'RoundedRectangle'
            if '?' in text or any(k in text for k in ['条件', '判断']):
                return 'Diamond'
            if any(k in text_lower for k in ['data', 'input', 'output']) or any(k in text for k in ['数据', '输入', '输出']):
                return 'Parallelogram'
            if any(k in text for k in ['流程', '子流程']) or 'process' in text_lower:
                return 'Rectangle'

            # 4) Geometry hint (very rough)
            try:
                w = float(getattr(shape, 'width', 0) or 0)
                h = float(getattr(shape, 'height', 0) or 0)
                if w > 0 and h > 0:
                    ratio = w / h
                    if 0.85 <= ratio <= 1.15:
                        # Could be Diamond/Ellipse/Rectangle; prefer Rectangle fallback
                        return 'Rectangle'
                    elif ratio > 1.25:
                        return 'Rectangle'
                    elif ratio < 0.8:
                        return 'Rectangle'
            except Exception:
                pass

            # 5) Fallback - return Unknown instead of generic Shape
            return 'Unknown'
        except Exception:
            return 'Unknown'

    def list_shapes(self, shape_type: str = "") -> str:
        """
        List shapes in the current page, optionally filtered by type.
        列出当前页面的形状，可选按类型过滤。

        When shape_type is provided, filters shapes by semantic type
        (supports aliases like 'decision', 'rhombus' and Chinese like '菱形', '矩形').
        
        中文指令：列出形状、查看形状、显示图形、列表所有元素

        Returns:
            Formatted list of shapes (all or matching the filter)

        Examples:
            list_shapes()
            list_shapes("Diamond")
            list_shapes("菱形")
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded.")
        if err:
            return err
        
        shapes = self.diagram_builder.get_shapes()
        if not shapes:
            return "ℹ No shapes in the current page"
        
        # Precompute display types
        enriched: List[Tuple[Any, str]] = []
        for s in shapes:
            enriched.append((s, self._infer_display_type(s)))

        # Apply optional type filter
        filter_used = None
        if shape_type:
            # Normalize desired
            desired = (shape_type or '').strip()
            desired_lower = desired.lower()
            # Connector synonyms
            desired_is_connector = desired_lower in ('connector', 'dynamic connector', '连接线', '动态连接线')
            try:
                filter_used = normalize_shape_type(desired)
            except Exception:
                filter_used = desired
            filter_norm = (filter_used or '').lower()

            matching: List[Any] = []
            for s, dtype in enriched:
                try:
                    if desired_is_connector:
                        if hasattr(self.diagram_builder, '_is_connector') and self.diagram_builder._is_connector(s):
                            matching.append(s)
                            continue
                    # Use builder compatibility OR display type normalization match
                    if hasattr(self.diagram_builder, '_shape_types_compatible') and \
                       self.diagram_builder._shape_types_compatible(s, filter_used):
                        matching.append(s)
                        continue
                    dnorm = normalize_shape_type(dtype).lower()
                    if filter_norm and (filter_norm == dnorm or filter_norm in dnorm or dnorm in filter_norm):
                        matching.append(s)
                        continue
                    # Also compare against master/shape_type raw
                    st = (getattr(s, 'shape_type', '') or '').lower()
                    master = getattr(s, 'master', None)
                    mn = (getattr(master, 'name', '') or '').lower() if master else ''
                    if filter_norm and (filter_norm in st or filter_norm in mn):
                        matching.append(s)
                except Exception:
                    continue
            shapes_to_list = matching
        else:
            shapes_to_list = [s for s, _ in enriched]

        if shape_type and not shapes_to_list:
            return f"ℹ No shapes matched type '{filter_used}'"

        header = (
            f"📝 Shapes matching '{filter_used}' ({len(shapes_to_list)} of {len(shapes)}):\n"
            if shape_type else f"📝 Shapes in current page ({len(shapes)} total):\n"
        )

        result = header
        # Map IDs to display types for printing
        id_to_display: Dict[str, str] = {}
        for s, dtype in enriched:
            sid = str(getattr(s, 'ID', 'unknown'))
            id_to_display[sid] = dtype

        for s in shapes_to_list:
            s_id = str(getattr(s, 'ID', 'unknown'))
            s_text = (getattr(s, 'text', '') or '').strip()
            s_disp = id_to_display.get(s_id, self._infer_display_type(s))
            
            # Skip shapes with Unknown type (previously "Shape")
            if s_disp == 'Unknown':
                continue
            
            # Translate type to Chinese
            s_disp_cn = self._translate_shape_type(s_disp)
            
            # Format: ID: X - 类型名：\n文本内容
            result += f"\nID: {s_id} - {s_disp_cn}：\n{s_text}\n"
        
        log_operation(
            operation="list_shapes",
            details={"filter": filter_used} if shape_type else {},
            result=(
                f"Listed {len(shapes_to_list)} filtered shapes (of {len(shapes)})"
                if shape_type else f"Listed {len(shapes)} shapes"
            ),
            success=True
        )
        
        return result

    # ---------- Styling & geometry tools ----------
    def set_shape_position(self, shape_id: str, x: float, y: float) -> str:
        """Set absolute position of a shape (inches)."""
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        ok = self.diagram_builder.set_shape_position(shape_id, x, y)
        if ok:
            msg = f"✓ Moved shape {shape_id} to ({x:.2f}, {y:.2f})"
            log_operation("set_shape_position", {"shape_id": shape_id, "x": x, "y": y}, msg, True)
            return msg
        msg = f"✗ Failed to move shape {shape_id}"
        log_operation("set_shape_position", {"shape_id": shape_id, "x": x, "y": y}, msg, False)
        return msg

    def nudge_shape(self, shape_id: str, dx: float = 0.25, dy: float = 0.0) -> str:
        """Move a shape by delta (inches)."""
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        ok = self.diagram_builder.move_shape_by(shape_id, dx, dy)
        if ok:
            msg = f"✓ Nudged shape {shape_id} by ({dx:.2f}, {dy:.2f})"
            log_operation("nudge_shape", {"shape_id": shape_id, "dx": dx, "dy": dy}, msg, True)
            return msg
        msg = f"✗ Failed to nudge shape {shape_id}"
        log_operation("nudge_shape", {"shape_id": shape_id, "dx": dx, "dy": dy}, msg, False)
        return msg

    def set_shape_size(self, shape_id: str, width: float, height: float) -> str:
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        ok = self.diagram_builder.set_shape_size(shape_id, width, height)
        if ok:
            msg = f"✓ Resized shape {shape_id} to {width:.2f}×{height:.2f} in"
            log_operation("set_shape_size", {"shape_id": shape_id, "width": width, "height": height}, msg, True)
            return msg
        msg = f"✗ Failed to resize shape {shape_id}"
        log_operation("set_shape_size", {"shape_id": shape_id, "width": width, "height": height}, msg, False)
        return msg

    def set_line_width(self, shape_id: str, width_pt: float) -> str:
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        ok = self.diagram_builder.set_shape_line_width(shape_id, width_pt)
        if ok:
            msg = f"✓ Set line width of shape {shape_id} to {width_pt:.2f} pt"
            log_operation("set_line_width", {"shape_id": shape_id, "width_pt": width_pt}, msg, True)
            return msg
        msg = f"✗ Failed to set line width for shape {shape_id}"
        log_operation("set_line_width", {"shape_id": shape_id, "width_pt": width_pt}, msg, False)
        return msg

    def set_line_color(self, shape_id: str, color_hex: str) -> str:
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        ok = self.diagram_builder.set_shape_line_color(shape_id, color_hex)
        if ok:
            msg = f"✓ Set line color of shape {shape_id} to {color_hex}"
            log_operation("set_line_color", {"shape_id": shape_id, "color": color_hex}, msg, True)
            return msg
        msg = f"✗ Failed to set line color for shape {shape_id}"
        log_operation("set_line_color", {"shape_id": shape_id, "color": color_hex}, msg, False)
        return msg

    def set_fill_color(self, shape_id: str, color_hex: str) -> str:
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        ok = self.diagram_builder.set_shape_fill_color(shape_id, color_hex)
        if ok:
            msg = f"✓ Set fill color of shape {shape_id} to {color_hex}"
            log_operation("set_fill_color", {"shape_id": shape_id, "color": color_hex}, msg, True)
            return msg
        msg = f"✗ Failed to set fill color for shape {shape_id}"
        log_operation("set_fill_color", {"shape_id": shape_id, "color": color_hex}, msg, False)
        return msg

    # ---------- Stencil (.vssx) tools ----------
    def list_stencil_masters(self, stencil_path: str, limit: int = 50) -> str:
        """List master shapes available in a .vssx stencil file (read-only)."""
        try:
            parser = self._stencil_cache.get(stencil_path) or StencilParser(stencil_path)
            self._stencil_cache[stencil_path] = parser
            masters = parser.list_masters()
            names = [m.get('name') or m.get('nameU') or f"ID:{m.get('id')}" for m in masters]
            names = [n for n in names if n]
            shown = names[:max(1, int(limit))]
            msg = "📚 Stencil masters (first {}):\n".format(len(shown)) + "\n".join(f"- {n}" for n in shown)
            log_operation("list_stencil_masters", {"stencil": stencil_path, "count": len(names)}, msg, True)
            return msg
        except Exception as e:
            msg = f"✗ Failed to list masters: {e}"
            log_operation("list_stencil_masters", {"stencil": stencil_path}, msg, False)
            return msg

    def add_shape_from_stencil(self, stencil_path: str, master_name: str, x: float, y: float, text: str = None, prefer_existing_master: bool = False) -> str:
        """
        Add a shape from a VSSX stencil file by importing the master shape and creating an instance.
        
        This method properly imports master shapes from external VSSX stencil files into
        the current VSDX diagram, then creates a shape instance at the specified position.
        
        Args:
            stencil_path: Path to the VSSX stencil file
            master_name: Name of the master shape to import and use
            x: X coordinate for the new shape
            y: Y coordinate for the new shape
            text: Optional text content for the shape
            
        Returns:
            Success or error message
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        
        # Validate stencil file exists and is parsable
        try:
            parser = self._stencil_cache.get(stencil_path) or StencilParser(stencil_path)
            self._stencil_cache[stencil_path] = parser
        except Exception as e:
            msg = f"✗ Cannot parse stencil file '{stencil_path}': {str(e)}"
            log_operation("add_shape_from_stencil", {"stencil": stencil_path, "master": master_name, "x": x, "y": y}, msg, False)
            return msg

        # Optional fast path: only if explicitly preferred and only with exact match
        if prefer_existing_master:
            new_shape = self.diagram_builder.add_shape_from_master_name(master_name, x, y, text, allow_partial=False)
            if new_shape:
                sid = str(getattr(new_shape, 'ID', 'unknown'))
                msg = f"✓ Inserted shape from existing master (exact) '{master_name}' as ID {sid} at ({x:.2f}, {y:.2f})"
                log_operation("add_shape_from_stencil", {"stencil": stencil_path, "master": master_name, "x": x, "y": y, "shape_id": sid, "path": "existing-master"}, msg, True)
                return msg

        # Master not found in diagram - import from VSSX stencil
        result = self.diagram_builder.add_shape_from_vssx_stencil(stencil_path, master_name, x, y, text)
        
        if result['success']:
            shape = result['shape']
            sid = str(getattr(shape, 'ID', 'unknown')) if shape else 'unknown'
            msg = f"✓ Imported and inserted shape from master '{master_name}' as ID {sid} at ({x:.2f}, {y:.2f})"
            log_operation("add_shape_from_stencil", {"stencil": stencil_path, "master": master_name, "x": x, "y": y, "shape_id": sid, "path": "imported-master"}, msg, True)
            return msg
        else:
            msg = f"✗ Failed to import shape from stencil: {result['message']}"
            log_operation("add_shape_from_stencil", {"stencil": stencil_path, "master": master_name, "x": x, "y": y}, msg, False)
            return msg
    
    def list_library_stencils(self) -> str:
        """List all stencils available in the stencil library (assets/templates/stencils/)."""
        try:
            if not self._stencil_manager:
                self._stencil_manager = StencilManager()
            
            stencils = self._stencil_manager.list_stencils(include_masters=True)
            
            if not stencils:
                msg = "📚 No stencils found in library. Add .vssx files to assets/templates/stencils/"
                log_operation("list_library_stencils", {}, msg, True)
                return msg
            
            lines = [f"📚 Stencil Library ({len(stencils)} stencils):"]
            for i, s in enumerate(stencils, 1):
                name = s.get('name', 'Unknown')
                category = s.get('category', 'general')
                master_count = s.get('master_count', 0)
                complexity = s.get('complexity', 'unknown')
                lines.append(f"{i}. {name} [{category}] - {master_count} masters ({complexity})")
            
            msg = "\n".join(lines)
            log_operation("list_library_stencils", {"count": len(stencils)}, msg, True)
            return msg
        except Exception as e:
            msg = f"✗ Failed to list library stencils: {e}"
            log_operation("list_library_stencils", {}, msg, False)
            return msg
    
    def search_library_stencils(self, keywords: List[str]) -> str:
        """Search stencils in the library by keywords."""
        try:
            if not self._stencil_manager:
                self._stencil_manager = StencilManager()
            
            results = self._stencil_manager.search_stencils(keywords=keywords)
            
            if not results:
                msg = f"📚 No stencils found matching keywords: {', '.join(keywords)}"
                log_operation("search_library_stencils", {"keywords": keywords}, msg, True)
                return msg
            
            lines = [f"📚 Found {len(results)} matching stencil(s):"]
            for i, s in enumerate(results, 1):
                name = s.get('name', 'Unknown')
                category = s.get('category', 'general')
                master_count = s.get('master_count', 0)
                path = s.get('path', 'N/A')
                lines.append(f"{i}. {name} [{category}] - {master_count} masters")
                lines.append(f"   Path: {path}")
            
            msg = "\n".join(lines)
            log_operation("search_library_stencils", {"keywords": keywords, "count": len(results)}, msg, True)
            return msg
        except Exception as e:
            msg = f"✗ Failed to search stencils: {e}"
            log_operation("search_library_stencils", {"keywords": keywords}, msg, False)
            return msg
    
    def get_stencil_info(self, stencil_name: str) -> str:
        """
        获取形状库的详细信息
        Get detailed information about a specific stencil
        
        Args:
            stencil_name: Name or filename of the stencil
            
        Returns:
            Formatted string with stencil details including all master shapes
            
        Example:
            get_stencil_info("Files (mrpaulandrew) v2022.vssx")
        """
        try:
            if not self._stencil_manager:
                self._stencil_manager = StencilManager()
            
            info = self._stencil_manager.get_stencil_info(stencil_name)
            
            if not info:
                msg = f"✗ Stencil not found: {stencil_name}"
                log_operation("get_stencil_info", {"stencil": stencil_name}, msg, False)
                return msg
            
            lines = [f"📐 Stencil: {info.get('name', 'Unknown')}\n"]
            lines.append(f"File: {info.get('filename', '')}")
            lines.append(f"Description: {info.get('description', 'No description')}")
            lines.append(f"Category: {info.get('category', 'general')}")
            lines.append(f"Complexity: {info.get('complexity', 'unknown')}")
            lines.append(f"Master Shapes: {info.get('master_count', 0)}")
            
            # Master names
            master_names = info.get('master_names', [])
            if master_names:
                lines.append(f"\nAvailable Master Shapes:")
                for i, master_name in enumerate(master_names, 1):
                    lines.append(f"  {i}. {master_name}")
            
            # Keywords
            keywords = info.get('keywords', [])
            if keywords:
                lines.append(f"\nKeywords: {', '.join(keywords)}")
            
            # Use cases
            use_cases = info.get('use_cases', [])
            if use_cases:
                lines.append(f"\nUse Cases: {', '.join(use_cases)}")
            
            msg = "\n".join(lines)
            log_operation("get_stencil_info", {"stencil": stencil_name}, msg, True)
            return msg
        except Exception as e:
            msg = f"✗ Failed to get stencil info: {e}"
            log_operation("get_stencil_info", {"stencil": stencil_name}, msg, False)
            return msg

    def create_from_template_and_load(self, template_name: str, output_path: str) -> str:
        """
        Create a new diagram by copying a template file, then load it for editing.
        
        IMPORTANT: This method automatically loads the created diagram. However,
        you MUST call load_diagram(output_path) again before adding shapes or connectors
        to ensure proper initialization of the shape and connector system.
        
        Use this when you want to:
        - Create a NEW diagram based on a template
        - Edit the copy without affecting the original template
        
        Note: If you just want to VIEW/INSPECT a template's shapes, use 
        load_diagram("assets/templates/library/xxx.vsdx") instead - it's faster and doesn't 
        create a copy.
        
        Args:
            template_name: Name of template file (e.g., "try.vsdx")
            output_path: Where to save the new diagram
            
        Returns:
            Status message with reminder to call load_diagram()
            
        Example:
            create_from_template_and_load("try.vsdx", "outputs/my_diagram.vsdx")
            load_diagram("outputs/my_diagram.vsdx")  # REQUIRED before adding shapes!
        """
        try:
            manager = TemplateManager()
            # This will raise FileNotFoundError if template not found (strict path enforcement)
            created = manager.create_from_template(template_name, output_path)
            self.diagram_builder = DiagramBuilder.load_from_file(output_path)
            self.current_file_path = output_path
            try:
                self._persist()
            except Exception:
                pass
            info = self.diagram_builder.get_diagram_info()
            result = (
                f"✓ Created from template: {output_path}\n"
                f"Pages: {', '.join(info['pages'])}\n"
                f"Shapes in current page: {info['shapes_count']}\n"
                f"\n⚠️  IMPORTANT: Call load_diagram('{output_path}') before adding shapes or connectors!"
            )
            log_operation(
                operation="create_from_template_and_load",
                details={"template": template_name, "output": output_path},
                result=result,
                success=True,
            )
            log_file_operation(output_path, "created_from_template")
            
            # Track operation in session context
            try:
                session_ctx = self._context_store.load_context(self._session_id)
                session_ctx.add_operation(
                    "create_from_template",
                    f"Created diagram from template: {template_name}",
                    {"template": template_name, "output": output_path, "pages": info['pages'], "shape_count": info['shapes_count']}
                )
                session_ctx.add_decision(
                    "template_selection",
                    "Selected template for new diagram",
                    template_name
                )
                self._context_store.save_context(session_ctx)
            except Exception:
                pass  # Don't fail operation if context tracking fails
            
            return result
        except FileNotFoundError as e:
            # Template not found - provide exact error without suggesting alternatives
            error_msg = f"✗ Template not found: {str(e)}"
            log_operation(
                operation="create_from_template_and_load",
                details={"template": template_name, "output": output_path},
                result=error_msg,
                success=False,
            )
            return error_msg
        except Exception as e:
            error_msg = f"✗ Error: {e}"
            log_operation(
                operation="create_from_template_and_load",
                details={"template": template_name, "output": output_path},
                result=error_msg,
                success=False,
            )
            return error_msg
    
    # ========== Template Library Management ==========
    
    def list_library_templates(self) -> str:
        """
        列出模板库中所有可用的模板
        List all templates available in the template library (assets/templates/library/)
        
        Returns:
            Formatted string with template information
            
        Example:
            list_library_templates()
        """
        try:
            if not hasattr(self, '_template_manager') or not self._template_manager:
                self._template_manager = TemplateManager()
            
            templates = self._template_manager.list_templates(include_shapes=True)
            
            if not templates:
                msg = "📚 No templates found in library. Add .vsdx files to assets/templates/library/"
                log_operation("list_library_templates", {}, msg, True)
                return msg
            
            lines = [f"📚 Template Library ({len(templates)} templates):\n"]
            for i, t in enumerate(templates, 1):
                name = t.get('name', 'Unknown')
                category = t.get('category', 'general')
                complexity = t.get('complexity', 'unknown')
                shape_count = t.get('shape_total', 0)
                connector_count = t.get('total_connectors', 0)
                pages = t.get('pages', 1)
                filename = t.get('filename', '')
                
                lines.append(f"{i}. {name}")
                lines.append(f"   File: {filename}")
                lines.append(f"   Category: {category} | Complexity: {complexity}")
                lines.append(f"   Shapes: {shape_count} | Connectors: {connector_count} | Pages: {pages}")
                
                # Show keywords if available
                keywords = t.get('keywords', [])
                if keywords:
                    lines.append(f"   Keywords: {', '.join(keywords[:5])}")
                lines.append("")
            
            msg = "\n".join(lines)
            log_operation("list_library_templates", {"count": len(templates)}, msg, True)
            
            # Track operation in session context
            try:
                session_ctx = self._context_store.load_context(self._session_id)
                session_ctx.add_operation(
                    "browse_templates",
                    f"Listed {len(templates)} available templates",
                    {"count": len(templates)}
                )
                self._context_store.save_context(session_ctx)
            except Exception:
                pass  # Don't fail operation if context tracking fails
            
            return msg
        except Exception as e:
            msg = f"✗ Failed to list library templates: {e}"
            log_operation("list_library_templates", {}, msg, False)
            return msg
    
    def search_library_templates(self, keywords: List[str]) -> str:
        """
        根据关键词搜索模板库
        Search templates in the library by keywords
        
        Args:
            keywords: List of keywords to search for
            
        Returns:
            Formatted string with matching templates
            
        Example:
            search_library_templates(["flowchart", "process"])
        """
        try:
            if not hasattr(self, '_template_manager') or not self._template_manager:
                self._template_manager = TemplateManager()
            
            results = self._template_manager.search_templates(keywords=keywords)
            
            if not results:
                msg = f"📚 No templates found matching keywords: {', '.join(keywords)}"
                log_operation("search_library_templates", {"keywords": keywords}, msg, True)
                return msg
            
            lines = [f"📚 Found {len(results)} matching template(s):\n"]
            for i, t in enumerate(results, 1):
                name = t.get('name', 'Unknown')
                filename = t.get('filename', '')
                description = t.get('description', 'No description')
                complexity = t.get('complexity', 'unknown')
                shape_count = t.get('shape_total', 0)
                
                lines.append(f"{i}. {name} ({filename})")
                lines.append(f"   {description}")
                lines.append(f"   Complexity: {complexity} | Shapes: {shape_count}")
                lines.append("")
            
            msg = "\n".join(lines)
            log_operation("search_library_templates", {"keywords": keywords, "results": len(results)}, msg, True)
            
            # Track operation in session context
            try:
                session_ctx = self._context_store.load_context(self._session_id)
                session_ctx.add_operation(
                    "search_templates",
                    f"Searched for templates with keywords: {', '.join(keywords)} ({len(results)} found)",
                    {"keywords": keywords, "results_count": len(results)}
                )
                self._context_store.save_context(session_ctx)
            except Exception:
                pass  # Don't fail operation if context tracking fails
            
            return msg
        except Exception as e:
            msg = f"✗ Failed to search library templates: {e}"
            log_operation("search_library_templates", {"keywords": keywords}, msg, False)
            return msg
    
    def get_template_info(self, template_name: str) -> str:
        """
        获取模板的详细信息
        Get detailed information about a specific template
        
        Args:
            template_name: Name or filename of the template
            
        Returns:
            Formatted string with template details
            
        Example:
            get_template_info("try.vsdx")
        """
        try:
            if not hasattr(self, '_template_manager') or not self._template_manager:
                self._template_manager = TemplateManager()
            
            info = self._template_manager.get_template_info(template_name)
            
            if not info:
                msg = f"✗ Template not found: {template_name}"
                log_operation("get_template_info", {"template": template_name}, msg, False)
                return msg
            
            lines = [f"📄 Template: {info.get('name', 'Unknown')}\n"]
            lines.append(f"File: {info.get('filename', '')}")
            lines.append(f"Description: {info.get('description', 'No description')}")
            lines.append(f"Category: {info.get('category', 'general')}")
            lines.append(f"Complexity: {info.get('complexity', 'unknown')}")
            lines.append(f"Pages: {info.get('pages', 1)}")
            lines.append(f"Shapes: {info.get('shape_total', 0)}")
            lines.append(f"Connectors: {info.get('total_connectors', 0)}")
            
            # Shape distribution
            shapes = info.get('shapes', {})
            if shapes:
                lines.append(f"\nShape Distribution:")
                for shape_type, count in sorted(shapes.items(), key=lambda x: x[1], reverse=True):
                    lines.append(f"  - {shape_type}: {count}")
            
            # Keywords
            keywords = info.get('keywords', [])
            if keywords:
                lines.append(f"\nKeywords: {', '.join(keywords)}")
            
            # Use cases
            use_cases = info.get('use_cases', [])
            if use_cases:
                lines.append(f"\nUse Cases: {', '.join(use_cases)}")
            
            # Sample texts
            sample_texts = info.get('sample_texts', [])
            if sample_texts:
                lines.append(f"\nSample Texts:")
                for text in sample_texts[:5]:  # Show first 5
                    lines.append(f"  - {text}")
            
            msg = "\n".join(lines)
            log_operation("get_template_info", {"template": template_name}, msg, True)
            return msg
        except Exception as e:
            msg = f"✗ Failed to get template info: {e}"
            log_operation("get_template_info", {"template": template_name}, msg, False)
            return msg

    def update_text_by_match(self, match_text: str, new_text: str, mode: str = "contains") -> str:
        """
        Update the first shape whose text matches given criteria without requiring shape ID.
        mode: 'equals' | 'contains' | 'regex'
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded.")
        if err:
            return err
        ok = self.diagram_builder.update_shape_text_by_match(match_text, new_text, mode)
        if ok:
            result = f"✓ Updated text: '{match_text}' -> '{new_text}' (mode={mode})"
            log_operation(
                operation="update_text_by_match",
                details={"match": match_text, "new_text": new_text, "mode": mode},
                result=result,
                success=True,
            )
            return result
        error_msg = "✗ No matching shape found"
        log_operation(
            operation="update_text_by_match",
            details={"match": match_text, "new_text": new_text, "mode": mode},
            result=error_msg,
            success=False,
        )
        return error_msg

    def update_text_by_match_all(self, match_text: str, new_text: str, mode: str = "contains", 
                                 case_sensitive: bool = False) -> str:
        """
        Update ALL shapes whose text matches given criteria.
        mode: 'equals' | 'contains' | 'regex'
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded.")
        if err:
            return err
        count = self.diagram_builder.update_shape_text_by_match_all(
            match_text, new_text, mode, case_sensitive
        )
        if count > 0:
            result = f"✓ Updated text in {count} shape(s) (mode={mode}, case_sensitive={case_sensitive})"
            log_operation(
                operation="update_text_by_match_all",
                details={"match": match_text, "new_text": new_text, "mode": mode, "case_sensitive": case_sensitive},
                result=result,
                success=True,
            )
            return result
        result = "ℹ No shapes matched"
        log_operation(
            operation="update_text_by_match_all",
            details={"match": match_text, "new_text": new_text, "mode": mode, "case_sensitive": case_sensitive},
            result=result,
            success=True,
        )
        return result

    def batch_update_text_by_map(self, mapping_json: str, mode: str = "equals", case_sensitive: bool = False) -> str:
        """
        Batch apply multiple text replacements across ALL shapes in-place.
        mapping_json: JSON dict of pattern -> replacement
        mode: 'equals' | 'contains' | 'regex'
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded.")
        if err:
            return err
        try:
            mapping: Dict[str, Any]
            mapping = json.loads(mapping_json) if isinstance(mapping_json, str) else dict(mapping_json)
        except Exception as e:
            return f"✗ Invalid JSON: {e}"
        count = self.diagram_builder.batch_update_text_by_map(mapping, mode, case_sensitive)
        result = f"✓ Updated text for {count} shape(s) (mode={mode}, case_sensitive={case_sensitive})" if count > 0 else "ℹ No shapes matched"
        log_operation(
            operation="batch_update_text_by_map",
            details={"mode": mode, "case_sensitive": case_sensitive, "keys": list(mapping.keys())},
            result=result,
            success=True,
        )
        return result
    def fill_placeholders(self, mapping_json: str, pattern: str = r"\{\{(\w+)\}\}") -> str:
        """
        Batch replace placeholders like {{Title}} using a JSON mapping string.
        Example mapping_json: '{"Title":"Transformer 架构","Owner":"Team"}'
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded.")
        if err:
            return err
        try:
            mapping: Dict[str, Any]
            mapping = json.loads(mapping_json) if isinstance(mapping_json, str) else dict(mapping_json)
        except Exception as e:
            return f"✗ Invalid JSON: {e}"
        count = self.diagram_builder.fill_placeholders(mapping, pattern)
        result = f"✓ Replaced placeholders in {count} shapes" if count > 0 else "ℹ No placeholders matched"
        log_operation(
            operation="fill_placeholders",
            details={"keys": list(mapping.keys()), "pattern": pattern},
            result=result,
            success=True,
        )
        return result
    
    def fit_page_to_drawing(
        self,
        page: Optional[int] = None,
        margin: float = 0.5,
    ) -> str:
        """
        Resize the current page so all drawing content fits inside it.

        This mirrors Visio's "Fit to Drawing" behavior more closely than a
        plain page resize: it translates the drawing toward the page origin,
        applies the requested margin, and then updates the page size.

        Args:
            page: Optional zero-based page index. If provided, switches to that
                page before fitting.
            margin: Desired outer margin in inches around the drawing.

        Returns:
            Status summary with before/after page geometry.
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded.")
        if err:
            return err

        if margin < 0:
            return "✗ margin must be >= 0 inches."

        if page is not None:
            page_obj = self.diagram_builder.get_page(page)
            if not page_obj:
                pages = self.diagram_builder.list_pages()
                return (
                    f"✗ Page index {page} not found.\n"
                    f"  - Available pages: {', '.join(pages) if pages else 'none'}"
                )
            try:
                self._persist()
            except Exception:
                pass

        before = self.diagram_builder.check_content_bounds()
        if "error" in before and before["error"] == "No shapes to measure":
            return "✗ No shapes found on the target page; nothing to fit."

        old_width = float(getattr(self.diagram_builder.current_page, "width", 0) or 0)
        old_height = float(getattr(self.diagram_builder.current_page, "height", 0) or 0)

        from ..utils import layout_config

        original_margin = layout_config.AUTO_FIT_MARGIN_IN
        try:
            layout_config.AUTO_FIT_MARGIN_IN = float(margin)
            success = self.diagram_builder.auto_fit_page_to_content()
        finally:
            layout_config.AUTO_FIT_MARGIN_IN = original_margin

        after = self.diagram_builder.check_content_bounds()
        new_width = float(getattr(self.diagram_builder.current_page, "width", 0) or 0)
        new_height = float(getattr(self.diagram_builder.current_page, "height", 0) or 0)
        translate_x = float(after.get("min_x", 0) or 0) - float(before.get("min_x", 0) or 0)
        translate_y = float(after.get("min_y", 0) or 0) - float(before.get("min_y", 0) or 0)
        page_name = getattr(self.diagram_builder.current_page, "name", f"page {page or 0}")

        if success:
            self._has_unsaved_changes = True
            try:
                self._persist()
            except Exception:
                pass

            lines = [
                f"✓ Fitted page '{page_name}' to drawing",
                f"  Page size: {old_width:.2f} x {old_height:.2f} in -> {new_width:.2f} x {new_height:.2f} in",
                f"  Content bounds: {before.get('content_width', 0):.2f} x {before.get('content_height', 0):.2f} in",
                f"  Margin: {float(margin):.2f} in",
                f"  Translation: dx={translate_x:.2f}, dy={translate_y:.2f} in",
            ]
            if not after.get("fits", False):
                lines.append("  Warning: content still exceeds page bounds after fit.")
            result = "\n".join(lines)
            log_operation(
                operation="fit_page_to_drawing",
                details={
                    "page": page,
                    "page_name": page_name,
                    "margin": float(margin),
                    "old_width": old_width,
                    "old_height": old_height,
                    "new_width": new_width,
                    "new_height": new_height,
                    "translate_x": translate_x,
                    "translate_y": translate_y,
                    "fits_after": after.get("fits", False),
                },
                result=result,
                success=True,
            )
            return result

        result = (
            f"✗ Failed to fit page '{page_name}' to drawing.\n"
            f"  Page size remains {new_width:.2f} x {new_height:.2f} in"
        )
        log_operation(
            operation="fit_page_to_drawing",
            details={"page": page, "page_name": page_name, "margin": float(margin)},
            result=result,
            success=False,
        )
        return result
    
    def save_diagram(self, filepath: Optional[str] = None, validate_web_compatibility: bool = True) -> str:
        """
        Save the current diagram to a file.
        保存当前图表到文件。
        
        Saves all changes made to the diagram. If no filepath is provided,
        saves to the original file path. Also saves a copy to the log directory.
        Optionally validates and fixes VSDX structure for web viewer compatibility.
        
        中文指令：保存、存储、写入、保存图表、保存文件
        
        Args:
            filepath: Path to save the file (optional, defaults to original path)
            validate_web_compatibility: If True, validate and fix VSDX for web viewers (default: True)
        
        Returns:
            Status message
        
        Example:
            save_diagram("output.vsdx")
            save_diagram("output.vsdx", validate_web_compatibility=True)  # With validation
            save_diagram()  # Saves to original file
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded.")
        if err:
            return err
        
        save_path = filepath or self.current_file_path
        if not save_path:
            return "✗ No filepath specified and no original path available"
        
        try:
            self.diagram_builder.save(save_path, auto_fit=False, validate_compatibility=validate_web_compatibility)
            self.current_file_path = save_path
            
            # Clear unsaved changes flag after successful save
            self._has_unsaved_changes = False
            
            try:
                self._persist()
            except Exception:
                pass
            
            # Save copy to log directory
            save_diagram_copy(save_path, "saved")
            
            result = f"✓ Diagram saved to {save_path}"
            log_operation(
                operation="save_diagram",
                details={"filepath": save_path},
                result=result,
                success=True
            )
            log_file_operation(save_path, "saved")
            
            # Track operation in session context
            try:
                session_ctx = self._context_store.load_context(self._session_id)
                session_ctx.add_operation(
                    "save_diagram",
                    f"Saved diagram to: {save_path}",
                    {"filepath": save_path}
                )
                self._context_store.save_context(session_ctx)
            except Exception:
                pass  # Don't fail operation if context tracking fails
            
            return result
        except Exception as e:
            error_msg = f"✗ Error saving diagram: {str(e)}"
            log_operation(
                operation="save_diagram",
                details={"filepath": save_path},
                result=error_msg,
                success=False
            )
            return error_msg
    
    def add_page(self, page_name: str) -> str:
        """
        Add a new page to the diagram.
        
        Creates a new blank page with the specified name.
        
        Args:
            page_name: Name for the new page
        
        Returns:
            Status message
        
        Example:
            add_page("Network Architecture")
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded.")
        if err:
            return err
        
        try:
            self.diagram_builder.add_page(page_name)
            try:
                self._persist()
            except Exception:
                pass
            result = f"✓ Added page '{page_name}'"
            log_operation(
                operation="add_page",
                details={"page_name": page_name},
                result=result,
                success=True
            )
            return result
        except Exception as e:
            error_msg = f"✗ Error adding page: {str(e)}"
            log_operation(
                operation="add_page",
                details={"page_name": page_name},
                result=error_msg,
                success=False
            )
            return error_msg
    
    def switch_page(self, page_index: int) -> str:
        """
        Switch to a different page in the diagram.
        切换到图表中的不同页面。
        
        Changes the current working page. Use get_diagram_info to see available pages.
        Page indices start from 0.
        
        中文指令：切换页面、换页、转到第X页、看第X页
        
        Args:
            page_index: Index of the page (0 for first page, 1 for second, etc.)
        
        Returns:
            Status message with the page name
        
        Example:
            switch_page(1)  # Switch to second page
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        
        page = self.diagram_builder.get_page(page_index)
        if page:
            result = f"✓ Switched to page: '{page.name}' (index {page_index})"
            try:
                self._persist()
            except Exception:
                pass
            log_operation(
                operation="switch_page",
                details={"page_index": page_index, "page_name": page.name},
                result=result,
                success=True
            )
            
            # Track operation in session context
            try:
                session_ctx = self._context_store.load_context(self._session_id)
                session_ctx.add_operation(
                    "switch_page",
                    f"Switched to page: {page.name}",
                    {"page_index": page_index, "page_name": page.name}
                )
                self._context_store.save_context(session_ctx)
            except Exception:
                pass  # Don't fail operation if context tracking fails
            
            return result
        else:
            pages = self.diagram_builder.list_pages()
            error_msg = f"✗ Page index {page_index} not found.\n"
            error_msg += f"  - Available pages: {', '.join(pages) if pages else 'none'}\n"
            error_msg += f"  - Valid indices: 0 to {len(pages)-1 if pages else 0}\n"
            error_msg += f"  - Use get_diagram_info to see all pages"
            
            log_operation(
                operation="switch_page",
                details={"page_index": page_index},
                result=error_msg,
                success=False
            )
            return error_msg
    
    def get_log_summary(self) -> str:
        """
        Get a summary of the current logging session.
        
        Shows session information including operation count and files processed.
        
        Returns:
            Formatted session summary
        
        Example:
            get_log_summary()
        """
        summary = get_session_summary()
        
        result = f"📊 Logging Session Summary:\n"
        result += f"Session Index: {summary['session_index']}\n"
        result += f"Session Directory: {summary['session_dir']}\n"
        result += f"Operations Count: {summary['operations_count']}\n"
        result += f"Files Processed: {len(summary['files_processed'])}\n"
        
        if summary['files_processed']:
            result += "\nFiles:\n"
            for file in summary['files_processed']:
                result += f"  - {file}\n"
        
        result += f"\nStart Time: {summary.get('start_time', 'N/A')}\n"
        result += f"Last Updated: {summary.get('last_updated', 'N/A')}\n"
        
        # Add warning if there are unsaved changes
        if hasattr(self, '_has_unsaved_changes') and self._has_unsaved_changes:
            result += "\n" + "="*50 + "\n"
            result += "⚠️  WARNING: You have UNSAVED changes!\n"
            result += "💡 Call save_diagram() to persist changes to file.\n"
            result += "="*50
        
        return result

    def replace_shape(self, shape_id: str, template_shape_id: str,
                     preserve_text: bool = True, preserve_connections: bool = True) -> str:
        """
        Replace an existing shape with a copy of a template shape.
        
        This is the BEST way to change a shape's appearance while keeping its text
        and connections. Much better than removing and adding a new shape.
        
        Args:
            shape_id: ID of the shape to replace
            template_shape_id: ID of the template shape to copy style/formatting from
            preserve_text: If True, keeps the original shape's text (default: True)
            preserve_connections: If True, maintains all connections to/from the shape (default: True)
        
        Returns:
            Status message with the new shape's ID
        
        Example:
            replace_shape("5", "3", preserve_text=True, preserve_connections=True)
            
        Use Case:
            When you want to change a rectangle to a diamond but keep its text "Decision"
            and all arrows pointing to/from it.
        """
        if not self.diagram_builder:
            return "✗ No diagram loaded. Use load_diagram first."
        
        new_shape = self.diagram_builder.replace_shape(
            shape_id, template_shape_id, preserve_text, preserve_connections
        )
        
        if new_shape:
            new_shape_id = getattr(new_shape, 'ID', 'unknown')
            result = f"✓ Replaced shape {shape_id} with style from {template_shape_id}. New shape ID: {new_shape_id}"
            if preserve_text:
                result += " (text preserved)"
            if preserve_connections:
                result += " (connections preserved)"
            
            log_operation(
                operation="replace_shape",
                details={
                    "original_id": shape_id,
                    "template_id": template_shape_id,
                    "new_id": str(new_shape_id),
                    "preserve_text": preserve_text,
                    "preserve_connections": preserve_connections
                },
                result=result,
                success=True
            )
            return result
        else:
            error_msg = f"✗ Failed to replace shape {shape_id}. Possible reasons:\n"
            error_msg += f"  - Shape ID '{shape_id}' or template ID '{template_shape_id}' not found\n"
            error_msg += f"  - Use list_shapes to verify IDs\n"
            error_msg += f"  - Check console output for detailed error"
            
            log_operation(
                operation="replace_shape",
                details={
                    "original_id": shape_id,
                    "template_id": template_shape_id
                },
                result=error_msg,
                success=False
            )
            return error_msg
    
    def get_shape_connections(self, shape_id: str) -> str:
        """
        Get all connections to and from a shape.
        
        Shows which connectors are coming in and going out of a shape.
        Useful before replacing or modifying shapes.
        
        Args:
            shape_id: ID or node_key of the shape to check
        
        Returns:
            Formatted connection information
        
        Example:
            get_shape_connections("5")  # by shape ID
            get_shape_connections("encoder_layer_1")  # by node_key
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        
        # Try to resolve node_key to shape_id if needed
        resolved_shape = self.diagram_builder._resolve_shape_identifier(shape_id)
        if not resolved_shape:
            return f"✗ Shape not found: {shape_id} (tried as both ID and node_key)"
        
        actual_shape_id = str(getattr(resolved_shape, 'ID', shape_id))
        
        connections = self.diagram_builder.get_shape_connections(actual_shape_id)
        
        # Get shape name/text for better reporting
        shape_text = getattr(resolved_shape, 'text', '') or f"Shape {actual_shape_id}"
        
        result = f"🔗 Connections for {shape_text} (ID: {actual_shape_id}):\n"
        result += f"  Incoming: {len(connections['incoming'])} connector(s)\n"
        if connections['incoming']:
            result += f"    IDs: {', '.join(connections['incoming'])}\n"
        result += f"  Outgoing: {len(connections['outgoing'])} connector(s)\n"
        if connections['outgoing']:
            result += f"    IDs: {', '.join(connections['outgoing'])}\n"
        
        log_operation(
            operation="get_shape_connections",
            details={"shape_id": shape_id, "resolved_id": actual_shape_id},
            result=f"Found {len(connections['incoming'])} incoming, {len(connections['outgoing'])} outgoing",
            success=True
        )
        
        return result
    
    def analyze_diagram_connections(self, page_index: Optional[int] = None, include_connectors: bool = True) -> str:
        """
        Analyze all connections in the current diagram page.
        
        Provides comprehensive connection analysis including:
        - Shape IDs and text
        - Connection directions (incoming/outgoing)
        - Connector IDs and text
        - Connection statistics
        
        Args:
            page_index: Page index to analyze (None for current page)
            include_connectors: Whether to include connector shape details
        
        Returns:
            Formatted connection analysis report
        
        Example:
            analyze_diagram_connections()  # Analyze current page
            analyze_diagram_connections(0)  # Analyze first page
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        
        analysis = self.diagram_builder.analyze_diagram_connections(page_index, include_connectors)
        
        if 'error' in analysis and analysis['error']:
            error_msg = f"✗ Error: {analysis['error']}"
            log_operation(
                operation="analyze_diagram_connections",
                details={"page_index": page_index},
                result=error_msg,
                success=False
            )
            return error_msg
        
        # Format the report
        stats = analysis.get('statistics', {})
        shapes = analysis.get('shapes', [])
        connectors = analysis.get('connectors', [])
        page_name = analysis.get('page_name', 'Unknown')
        
        result = []
        result.append("=" * 60)
        result.append(f"📊 CONNECTION ANALYSIS - {page_name}")
        result.append("=" * 60)
        result.append("")
        
        # Statistics
        result.append("📈 STATISTICS:")
        result.append(f"  Total Shapes: {stats.get('total_shapes', 0)}")
        result.append(f"  Total Connectors: {stats.get('total_connectors', 0)}")
        result.append(f"  Total Connections: {stats.get('total_connections', 0)}")
        result.append(f"  Shapes with Incoming: {stats.get('shapes_with_incoming', 0)}")
        result.append(f"  Shapes with Outgoing: {stats.get('shapes_with_outgoing', 0)}")
        result.append(f"  Shapes with Both: {stats.get('shapes_with_both', 0)}")
        result.append(f"  Isolated Shapes: {stats.get('isolated_shapes', 0)}")
        result.append("")
        
        # Shapes with connections
        shapes_with_conn = [s for s in shapes if s.get('incoming') or s.get('outgoing')]
        if shapes_with_conn:
            result.append("🔗 SHAPES WITH CONNECTIONS:")
            result.append("-" * 60)
            for shape in shapes_with_conn:
                shape_text = shape.get('text', '') or '(no text)'
                result.append(f"\n  Shape ID {shape.get('id')}: {shape_text}")
                result.append(f"    Type: {shape.get('type', 'Unknown')}")
                
                incoming = shape.get('incoming', [])
                if incoming:
                    result.append(f"    📥 Incoming ({len(incoming)}):")
                    for conn in incoming[:5]:  # Limit to first 5
                        source_text = conn.get('source_shape_text', '') or '(no text)'
                        result.append(f"      ← from Shape {conn.get('source_shape_id')}: {source_text}")
                    if len(incoming) > 5:
                        result.append(f"      ... and {len(incoming) - 5} more")
                
                outgoing = shape.get('outgoing', [])
                if outgoing:
                    result.append(f"    📤 Outgoing ({len(outgoing)}):")
                    for conn in outgoing[:5]:  # Limit to first 5
                        target_text = conn.get('target_shape_text', '') or '(no text)'
                        result.append(f"      → to Shape {conn.get('target_shape_id')}: {target_text}")
                    if len(outgoing) > 5:
                        result.append(f"      ... and {len(outgoing) - 5} more")
        
        # Connector details if requested
        if include_connectors and connectors:
            result.append("")
            result.append("🔀 CONNECTOR DETAILS:")
            result.append("-" * 60)
            for conn in connectors[:20]:  # Limit to first 20
                from_text = conn.get('from_shape_text', '') or '(no text)'
                to_text = conn.get('to_shape_text', '') or '(no text)'
                label = (conn.get('connector_text', '') or '').strip()
                if label:
                    result.append(
                        f"  Connector {conn.get('connector_id')} [{label}]: "
                        f"{from_text} → {to_text}"
                    )
                else:
                    result.append(
                        f"  Connector {conn.get('connector_id')}: "
                        f"{from_text} → {to_text}"
                    )
            if len(connectors) > 20:
                result.append(f"  ... and {len(connectors) - 20} more connectors")
        
        result_str = "\n".join(result)
        
        log_operation(
            operation="analyze_diagram_connections",
            details={"page_index": page_index, "page_name": page_name},
            result=f"Analyzed {stats.get('total_shapes', 0)} shapes, {stats.get('total_connections', 0)} connections",
            success=True
        )
        
        return result_str
    
    def query_shape_connections(self, shape_id: str, depth: int = 2) -> str:
        """
        Surgical-level query for individual shape connectivity with comprehensive impact analysis.
        
        This tool provides deep visibility into connection relationships for a specific shape,
        addressing critical gaps in diagnosing and preventing connector corruption during
        diagram modifications.
        
        Key Features:
        - Direct connection analysis (immediate incoming/outgoing with full shape details)
        - Multi-hop dependency tracing (upstream sources and downstream targets)
        - Cycle and bidirectional connection detection
        - Deletion impact assessment (what breaks, orphaned shapes, broken paths)
        - Connection health diagnostics (orphaned connectors, duplicates, issues)
        - Recommended reconnection strategies
        
        Use Cases:
        - Before deleting a shape: preview what connections will break
        - Before modifying a shape: understand multi-node dependencies
        - Diagnosing connection issues: find orphaned or duplicate connectors
        - Understanding data flow: trace upstream/downstream pathways
        - Planning refactoring: assess ripple effects of changes
        
        Args:
            shape_id: ID of the shape to analyze
            depth: How many hops to trace dependencies (1-5, default 2)
        
        Returns:
            Comprehensive formatted report with connection analysis and impact assessment
        
        Examples:
            query_shape_connections("5")  # Analyze shape 5 with 2-hop depth
            query_shape_connections("12", depth=3)  # Deeper analysis (3 hops)
            query_shape_connections("7", depth=1)  # Just direct connections
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        
        # Get comprehensive connection analysis
        analysis = self.diagram_builder.query_shape_connections(shape_id, depth)
        
        if 'error' in analysis:
            error_msg = f"✗ Error: {analysis['error']}"
            log_operation(
                operation="query_shape_connections",
                details={"shape_id": shape_id, "depth": depth},
                result=error_msg,
                success=False
            )
            return error_msg
        
        # Format the comprehensive report
        shape = analysis['shape']
        direct = analysis['direct_connections']
        upstream = analysis['upstream_chain']
        downstream = analysis['downstream_chain']
        stats = analysis['dependency_stats']
        impact = analysis['impact_assessment']
        health = analysis['connection_health']
        cycles = analysis.get('cycles', [])
        bidirectional = analysis.get('bidirectional_connections', [])
        
        result = []
        result.append("=" * 80)
        result.append(f"🔍 SURGICAL CONNECTION ANALYSIS - Shape {shape_id}")
        result.append("=" * 80)
        result.append("")
        
        # Target shape information
        result.append("📦 TARGET SHAPE:")
        result.append(f"  ID: {shape['id']}")
        result.append(f"  Text: {shape['text'] or '(no text)'}")
        result.append(f"  Type: {shape['type']}")
        result.append(f"  Position: ({shape['position']['x']:.2f}, {shape['position']['y']:.2f})")
        result.append(f"  Size: {shape['size']['width']:.2f} × {shape['size']['height']:.2f}")
        if shape.get('node_key'):
            result.append(f"  Node Key: {shape['node_key']}")
        result.append("")
        
        # Dependency statistics
        result.append("📊 DEPENDENCY STATISTICS:")
        result.append(f"  Direct Incoming: {stats['direct_incoming_count']}")
        result.append(f"  Direct Outgoing: {stats['direct_outgoing_count']}")
        result.append(f"  Total Upstream Shapes: {stats['total_upstream_shapes']} (max depth: {stats['upstream_depth']})")
        result.append(f"  Total Downstream Shapes: {stats['total_downstream_shapes']} (max depth: {stats['downstream_depth']})")
        result.append(f"  Has Cycles: {'⚠️  YES' if stats['has_cycles'] else '✓ No'}")
        result.append(f"  Bidirectional Connections: {stats['bidirectional_count']}")
        result.append("")
        
        # Direct connections detail
        result.append("🔗 DIRECT CONNECTIONS:")
        result.append("-" * 80)
        
        if direct['incoming']:
            result.append(f"\n📥 INCOMING ({len(direct['incoming'])}):")
            for i, conn in enumerate(direct['incoming'], 1):
                result.append(f"  {i}. From Shape {conn['other_shape_id']}: {conn['other_shape_text'] or '(no text)'}")
                result.append(f"     Type: {conn['other_shape_type']}")
                result.append(f"     Position: ({conn['other_shape_position']['x']:.2f}, {conn['other_shape_position']['y']:.2f})")
                result.append(f"     Connector ID: {conn['connector_id']}")
                if conn['connector_text']:
                    result.append(f"     Connector Label: {conn['connector_text']}")
                result.append("")
        else:
            result.append("\n📥 INCOMING: None")
            result.append("")
        
        if direct['outgoing']:
            result.append(f"📤 OUTGOING ({len(direct['outgoing'])}):")
            for i, conn in enumerate(direct['outgoing'], 1):
                result.append(f"  {i}. To Shape {conn['other_shape_id']}: {conn['other_shape_text'] or '(no text)'}")
                result.append(f"     Type: {conn['other_shape_type']}")
                result.append(f"     Position: ({conn['other_shape_position']['x']:.2f}, {conn['other_shape_position']['y']:.2f})")
                result.append(f"     Connector ID: {conn['connector_id']}")
                if conn['connector_text']:
                    result.append(f"     Connector Label: {conn['connector_text']}")
                result.append("")
        else:
            result.append("📤 OUTGOING: None")
            result.append("")
        
        # Upstream chain
        if upstream['chain_by_level']:
            result.append("⬆️  UPSTREAM DEPENDENCY CHAIN:")
            result.append("-" * 80)
            for level, shapes in sorted(upstream['chain_by_level'].items()):
                result.append(f"\n  Level {level} ({len(shapes)} shape{'s' if len(shapes) != 1 else ''}):")
                for shape_info in shapes:
                    result.append(f"    • Shape {shape_info['shape_id']}: {shape_info['shape_text'] or '(no text)'}")
                    result.append(f"      Type: {shape_info['shape_type']}")
                    result.append(f"      Via Connector: {shape_info['connector_id']}")
            result.append("")
        else:
            result.append("⬆️  UPSTREAM DEPENDENCY CHAIN: None (this is a source node)")
            result.append("")
        
        # Downstream chain
        if downstream['chain_by_level']:
            result.append("⬇️  DOWNSTREAM DEPENDENCY CHAIN:")
            result.append("-" * 80)
            for level, shapes in sorted(downstream['chain_by_level'].items()):
                result.append(f"\n  Level {level} ({len(shapes)} shape{'s' if len(shapes) != 1 else ''}):")
                for shape_info in shapes:
                    result.append(f"    • Shape {shape_info['shape_id']}: {shape_info['shape_text'] or '(no text)'}")
                    result.append(f"      Type: {shape_info['shape_type']}")
                    result.append(f"      Via Connector: {shape_info['connector_id']}")
            result.append("")
        else:
            result.append("⬇️  DOWNSTREAM DEPENDENCY CHAIN: None (this is a sink node)")
            result.append("")
        
        # Cycles
        if cycles:
            result.append("🔄 CYCLES DETECTED:")
            result.append("-" * 80)
            for i, cycle in enumerate(cycles, 1):
                result.append(f"  Cycle {i}: {' → '.join(cycle)} → {cycle[0]}")
            result.append("")
        
        # Bidirectional connections
        if bidirectional:
            result.append("↔️  BIDIRECTIONAL CONNECTIONS:")
            result.append("-" * 80)
            for bidir in bidirectional:
                result.append(f"  • Shape {bidir['other_shape_id']}: {bidir['other_shape_text'] or '(no text)'}")
                result.append(f"    Type: {bidir['other_shape_type']}")
                result.append(f"    Incoming Connectors: {', '.join(bidir['incoming_connectors'])}")
                result.append(f"    Outgoing Connectors: {', '.join(bidir['outgoing_connectors'])}")
            result.append("")
        
        # Impact assessment
        result.append("💥 DELETION IMPACT ASSESSMENT:")
        result.append("-" * 80)
        result.append(f"  Affected Connectors: {impact['affected_connectors_count']}")
        if impact['affected_connector_ids']:
            result.append(f"    IDs: {', '.join(impact['affected_connector_ids'])}")
        
        if impact['potentially_orphaned_shapes']:
            result.append(f"\n  ⚠️  Potentially Orphaned Shapes ({len(impact['potentially_orphaned_shapes'])}):")
            for orphan in impact['potentially_orphaned_shapes'][:5]:  # Show first 5
                result.append(f"    • Shape {orphan['shape_id']}: {orphan['shape_text'] or '(no text)'} [{orphan['shape_type']}]")
            if len(impact['potentially_orphaned_shapes']) > 5:
                result.append(f"    ... and {len(impact['potentially_orphaned_shapes']) - 5} more")
        
        if impact['broken_paths']:
            result.append(f"\n  ⚠️  Broken Paths ({impact['broken_paths_count']}):")
            for path in impact['broken_paths'][:3]:  # Show first 3
                result.append(f"    • {path['from_text']} (ID: {path['from_shape']}) ✗→ {path['to_text']} (ID: {path['to_shape']})")
            if impact['broken_paths_count'] > 3:
                result.append(f"    ... and {impact['broken_paths_count'] - 3} more")
        
        result.append(f"\n  📋 Recommended Strategy: {impact['recommended_reconnection_strategy'].upper()}")
        if impact['recommended_reconnection_strategy'] == 'simple_bypass':
            result.append("     → Single input, single output: can create direct bypass connection")
        elif impact['recommended_reconnection_strategy'] == 'smart_reconnect':
            result.append("     → Multiple connections: requires smart reconnection logic")
        else:
            result.append("     → Default: remove all connected connectors")
        result.append("")
        
        # Connection health
        result.append("🏥 CONNECTION HEALTH:")
        result.append("-" * 80)
        if health['healthy']:
            result.append("  ✓ All connections are healthy")
        else:
            result.append(f"  ⚠️  Health Status: {health['issue_count']} issue(s), {health['warning_count']} warning(s)")
        
        if health['issues']:
            result.append(f"\n  ❌ ISSUES ({len(health['issues'])}):")
            for issue in health['issues']:
                result.append(f"    • {issue['type']}: {issue['message']}")
        
        if health['warnings']:
            result.append(f"\n  ⚠️  WARNINGS ({len(health['warnings'])}):")
            for warning in health['warnings']:
                result.append(f"    • {warning['type']}: {warning['message']}")
        result.append("")
        
        result.append("=" * 80)
        
        # Log operation
        log_operation(
            operation="generate_detailed_layout_report",
            details={
                "shapes": metadata.get('total_shapes', 0),
                "connectors": metadata.get('total_connectors', 0),
                "anomalies": len(anomalies),
                "critical_issues": len(critical_anomalies),
                "format": format,
                "precision": precision_inches,
                "has_baseline": baseline_file is not None,
                "output_file": output_file
            },
            result=f"Generated layout report with {len(anomalies)} anomalies detected",
            success=True
        )
        
        return result
    
    def add_or_update_shape(self, node_key: str, text: str, shape_type: str = "Rectangle",
                           x: float = 4.0, y: float = 4.0,
                           width: float = 1.5, height: float = 0.75) -> str:
        """
        Idempotently add or update a shape by node key.
        通过节点键幂等地添加或更新形状。
        
        This is the RECOMMENDED method for creating diagrams that can be safely re-run.
        Running multiple times with same node_key will update the existing shape
        instead of creating duplicates.
        
        中文指令：添加或更新形状、创建或更新节点、幂等添加
        
        Args:
            node_key: Unique identifier for this logical node (required)
            text: Text to display in the shape
            shape_type: Type of shape (Rectangle, Diamond, Ellipse, etc.)
            x, y: Position coordinates (in inches)
            width, height: Shape dimensions (in inches)
        
        Returns:
            Status message
        
        Example:
            # First run creates the shape
            add_or_update_shape("step1", "Process Data", "Rectangle", 2.0, 5.0)
            
            # Second run updates existing shape instead of creating duplicate
            add_or_update_shape("step1", "Process Data Updated", "Rectangle", 2.0, 5.0)
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            log_operation(
                operation="add_or_update_shape",
                details={"node_key": node_key, "text": text, "error": "no_diagram_loaded"},
                result=err,
                success=False
            )
            return err
        
        shape, action = self.diagram_builder.add_or_update_shape(
            node_key=node_key,
            text=text,
            shape_type=shape_type,
            x=x,
            y=y,
            width=width,
            height=height,
            use_professional_formatting=False  # Preserve template formatting
        )
        
        if shape and action != "error":
            shape_id = getattr(shape, 'ID', 'unknown')
            if action == "added":
                result = f"✓ Added new shape '{text}' at ({x}, {y}). Shape ID: {shape_id}, Key: {node_key}"
            elif action == "updated":
                result = f"✓ Updated shape '{text}'. Shape ID: {shape_id}, Key: {node_key}"
            elif action == "replaced":
                result = f"✓ Replaced shape type to {shape_type} for '{text}'. Shape ID: {shape_id}, Key: {node_key}"
            elif action == "adopted":
                result = f"✓ Adopted existing shape '{text}' with key. Shape ID: {shape_id}, Key: {node_key}"
            else:
                result = f"✓ Shape operation completed. Action: {action}"
            
            log_operation(
                operation="add_or_update_shape",
                details={
                    "node_key": node_key,
                    "text": text,
                    "shape_type": shape_type,
                    "position": {"x": x, "y": y},
                    "size": {"width": width, "height": height},
                    "action": action,
                    "shape_id": str(shape_id)
                },
                result=result,
                success=True
            )
            return result
        else:
            error_msg = f"✗ Failed to add/update shape with key '{node_key}'"
            log_operation(
                operation="add_or_update_shape",
                details={"node_key": node_key, "text": text},
                result=error_msg,
                success=False
            )
            return error_msg
    
    def add_or_update_connector(self, from_node_key: str, to_node_key: str, 
                               label: str = "", routing_style: str = "right_angle",
                               from_glue_point: Optional[str] = None, 
                               to_glue_point: Optional[str] = None) -> str:
        """
        Idempotently add or update a connector between two shapes with optional connection points.
        幂等地添加或更新两个形状之间的连接器，支持可选的连接点。
        
        Uses node keys instead of shape IDs for stable references.
        Running multiple times will update the existing connector instead of creating duplicates.
        
        Args:
            from_node_key: Source shape's node key
            to_node_key: Target shape's node key
            label: Optional text label for the connector
            routing_style: 'straight', 'right_angle', or 'curved'
            from_glue_point: Optional connection point on source shape 
                           (e.g., 'Top', 'Bottom', 'Left', 'Right', 'Center', etc.)
            to_glue_point: Optional connection point on target shape
                         (e.g., 'Top', 'Bottom', 'Left', 'Right', 'Center', etc.)
        
        Returns:
            Status message
        
        Connection Point Behavior:
            - If both are None → Auto-select optimal points based on shape positions
            - If only one specified → Auto-select the other
            - If both specified → Use manual values
        
        Examples:
            # Basic connection (auto-select connection points)
            add_or_update_connector("step1", "step2", "Yes")
            
            # Manual connection points
            add_or_update_connector("step1", "step2", "Yes", "right_angle", "Right", "Left")
            
            # Mixed: specify source only, auto-select target
            add_or_update_connector("step1", "step2", "Yes", "right_angle", "Right", None)
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            log_operation(
                operation="add_or_update_connector",
                details={"from_node_key": from_node_key, "to_node_key": to_node_key, "error": "no_diagram_loaded"},
                result=err,
                success=False
            )
            return err
        
        # Import after error check to avoid import issues
        from ..utils.shape_identity import compute_edge_key
        from ..utils.connection_points import validate_glue_point
        from .connection_tools import get_optimal_connection_points
        
        # Validate glue point parameters
        from_valid, from_error = validate_glue_point(from_glue_point)
        if not from_valid:
            return f"✗ Invalid from_glue_point: {from_error}"
        
        to_valid, to_error = validate_glue_point(to_glue_point)
        if not to_valid:
            return f"✗ Invalid to_glue_point: {to_error}"
        
        # Auto-select connection points if needed
        final_from_glue = from_glue_point
        final_to_glue = to_glue_point
        
        if final_from_glue is None or final_to_glue is None:
            try:
                auto_from, auto_to = get_optimal_connection_points(
                    from_node_key, to_node_key, self.diagram_builder
                )
                
                if final_from_glue is None:
                    final_from_glue = auto_from
                if final_to_glue is None:
                    final_to_glue = auto_to
                    
            except Exception as e:
                # Fallback to center if auto-selection fails
                if final_from_glue is None:
                    final_from_glue = "Center"
                if final_to_glue is None:
                    final_to_glue = "Center"
                print(f"Warning: Auto-selection failed, using Center connections: {e}")
        
        # Compute edge key with connection points
        edge_key = compute_edge_key(from_node_key, to_node_key, label, 
                                  final_from_glue, final_to_glue)
        
        connector, action = self.diagram_builder.add_or_update_connector(
            edge_key=edge_key,
            from_node_key=from_node_key,
            to_node_key=to_node_key,
            label=label,
            routing_style=routing_style,
            from_glue_point=final_from_glue,
            to_glue_point=final_to_glue
        )
        
        if connector and action != "error":
            # Mark as having unsaved changes
            self._has_unsaved_changes = True
            
            connector_id = getattr(connector, 'ID', 'unknown')
            
            # Build descriptive connection info
            connection_info = f"{from_node_key}"
            if final_from_glue:
                connection_info += f"@{final_from_glue}"
            connection_info += f" → {to_node_key}"
            if final_to_glue:
                connection_info += f"@{final_to_glue}"
            
            if action == "added":
                result = f"✓ Added connector {connection_info}. ID: {connector_id}, Key: {edge_key}\n⚠️ Connector created in memory only - call save_diagram() to persist to file"
            else:
                result = f"✓ Updated connector {connection_info}. ID: {connector_id}, Key: {edge_key}\n⚠️ Changes in memory only - call save_diagram() to persist to file"
            
            log_operation(
                operation="add_or_update_connector",
                details={
                    "from_node_key": from_node_key,
                    "to_node_key": to_node_key,
                    "label": label,
                    "from_glue_point": final_from_glue,
                    "to_glue_point": final_to_glue,
                    "action": action,
                    "connector_id": str(connector_id),
                    "edge_key": edge_key
                },
                result=result,
                success=True
            )
            return result
        else:
            # Provide more detailed error information
            error_details = {
                "from_node_key": from_node_key, 
                "to_node_key": to_node_key,
                "label": label,
                "from_glue_point": final_from_glue,
                "to_glue_point": final_to_glue,
                "edge_key": edge_key,
                "error": (
                    getattr(self.diagram_builder, "last_connector_error", None)
                    or "Failed to create connector"
                ),
            }
            
            error_msg = f"✗ Failed to add/update connector between '{from_node_key}' and '{to_node_key}'"
            log_operation(
                operation="add_or_update_connector",
                details=error_details,
                result=error_msg,
                success=False
            )
            return error_msg
    
    def get_shape_connection_points(self, node_key: str) -> str:
        """
        List all available connection points for a shape.
        列出形状的所有可用连接点。
        
        Args:
            node_key: Node key of the shape to analyze
        
        Returns:
            Formatted list of connection points
        
        Example:
            get_shape_connection_points("step1")
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        
        try:
            from ..tools.connection_tools import get_shape_connection_points
            from ..utils.shape_identity import index_shapes_by_key
            
            # Find the shape
            nodes_by_key, _ = index_shapes_by_key(self.diagram_builder.current_page, self.diagram_builder)
            shape = nodes_by_key.get(node_key)
            
            if not shape:
                return f"✗ Shape with key '{node_key}' not found"
            
            connection_points = get_shape_connection_points(shape, self.diagram_builder)
            
            if not connection_points:
                return f"✗ No connection points found for shape '{node_key}'"
            
            result = f"Connection points for '{node_key}':\n"
            for point in connection_points:
                result += f"  - {point['name']} (index: {point['index']})\n"
            
            return result.rstrip()
            
        except Exception as e:
            error_msg = f"✗ Failed to get connection points for '{node_key}': {e}"
            log_operation(
                operation="get_shape_connection_points",
                details={"node_key": node_key, "error": str(e)},
                result=error_msg,
                success=False
            )
            return error_msg
    
    def list_all_connections(self, node_key: str) -> str:
        """
        Show all incoming and outgoing connections for a shape.
        显示形状的所有输入和输出连接。
        
        Args:
            node_key: Node key of the shape to analyze
        
        Returns:
            Formatted connection summary
        
        Example:
            list_all_connections("step1")
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        
        try:
            from ..tools.connection_tools import list_all_connections, format_connection_summary
            
            connections = list_all_connections(node_key, self.diagram_builder)
            result = format_connection_summary(node_key, connections)
            
            log_operation(
                operation="list_all_connections",
                details={
                    "node_key": node_key,
                    "incoming_count": len(connections.get('incoming', [])),
                    "outgoing_count": len(connections.get('outgoing', [])),
                },
                result=f"Listed connections for '{node_key}'",
                success=True
            )
            
            return result
            
        except Exception as e:
            error_msg = f"✗ Failed to list connections for '{node_key}': {e}"
            log_operation(
                operation="list_all_connections",
                details={"node_key": node_key, "error": str(e)},
                result=error_msg,
                success=False
            )
            return error_msg
    
    def get_optimal_connection_points(self, from_node_key: str, to_node_key: str) -> str:
        """
        Auto-calculate best connection points for two nodes.
        自动计算两个节点的最佳连接点。
        
        Args:
            from_node_key: Source node key
            to_node_key: Target node key
        
        Returns:
            Formatted optimal connection points
        
        Example:
            get_optimal_connection_points("step1", "step2")
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded. Use load_diagram first.")
        if err:
            return err
        
        try:
            from ..tools.connection_tools import get_optimal_connection_points
            
            from_glue, to_glue = get_optimal_connection_points(
                from_node_key, to_node_key, self.diagram_builder
            )
            
            result = f"Optimal connection points for {from_node_key} → {to_node_key}:\n"
            result += f"  From '{from_node_key}': {from_glue}\n"
            result += f"  To '{to_node_key}': {to_glue}"
            
            log_operation(
                operation="get_optimal_connection_points",
                details={
                    "from_node_key": from_node_key,
                    "to_node_key": to_node_key,
                    "from_glue": from_glue,
                    "to_glue": to_glue
                },
                result=f"Calculated optimal points: {from_glue} → {to_glue}",
                success=True
            )
            
            return result
            
        except Exception as e:
            error_msg = f"✗ Failed to calculate optimal connection points: {e}"
            log_operation(
                operation="get_optimal_connection_points",
                details={
                    "from_node_key": from_node_key,
                    "to_node_key": to_node_key,
                    "error": str(e)
                },
                result=error_msg,
                success=False
            )
            return error_msg
    
    def ensure_all_shapes_have_keys(self) -> str:
        """
        Ensure all shapes have NodeKey properties assigned.
        确保所有形状都分配了节点键。
        
        This is useful when working with shapes that were created without using
        add_or_update_shape(), ensuring they can be connected with add_or_update_connector().
        
        中文指令：分配节点键、确保形状有键、设置形状键
        
        Returns:
            Status message with number of keys assigned
        
        Example:
            ensure_all_shapes_have_keys()
        """
        err = self._ensure_loaded_or_error("✗ No diagram loaded.")
        if err:
            return err
        
        assignments = self.diagram_builder.ensure_all_shapes_have_keys()
        
        if assignments:
            result = f"✓ Assigned NodeKeys to {len(assignments)} shapes:\n"
            for shape_id, node_key in list(assignments.items())[:10]:  # Show first 10
                result += f"  - Shape ID {shape_id} → Key: {node_key}\n"
            if len(assignments) > 10:
                result += f"  ... and {len(assignments) - 10} more"
        else:
            result = "✓ All shapes already have NodeKeys assigned"
        
        log_operation(
            operation="ensure_all_shapes_have_keys",
            details={"assignments_count": len(assignments)},
            result=result,
            success=True
        )
        
        return result

def get_visio_tools(visio_tools_instance: VisioTools) -> List:
    """
    Get list of Agno-compatible tool functions
    
    Args:
        visio_tools_instance: Instance of VisioTools to bind methods to
    
    Returns:
        List of tool functions
    """
    return [
        # Session management
        visio_tools_instance.set_session,
        visio_tools_instance.reset_session,
        visio_tools_instance.get_session_context,
        # File operations
        visio_tools_instance.load_diagram,
        visio_tools_instance.create_new_diagram,
        visio_tools_instance.get_diagram_info,
        visio_tools_instance.save_diagram,
        # Template library management
        visio_tools_instance.list_library_templates,
        visio_tools_instance.search_library_templates,
        visio_tools_instance.get_template_info,
        visio_tools_instance.create_from_template_and_load,
        # Stencil library management
        visio_tools_instance.list_library_stencils,
        visio_tools_instance.search_library_stencils,
        visio_tools_instance.get_stencil_info,
        visio_tools_instance.list_stencil_masters,
        visio_tools_instance.add_shape_from_stencil,
        # Shape operations
        visio_tools_instance.add_shape,
        visio_tools_instance.clone_shape,
        visio_tools_instance.replace_shape,
        visio_tools_instance.remove_shape,
        visio_tools_instance.remove_connector,
        visio_tools_instance.remove_shape_smart,
        visio_tools_instance.find_shape_by_text,
        visio_tools_instance.list_shapes,
        visio_tools_instance.set_shape_position,
        visio_tools_instance.nudge_shape,
        visio_tools_instance.set_shape_size,
        # Shape styling
        visio_tools_instance.set_line_width,
        visio_tools_instance.set_line_color,
        visio_tools_instance.set_fill_color,
        # Text operations
        visio_tools_instance.update_shape_text,
        visio_tools_instance.update_text_by_match,
        visio_tools_instance.update_text_by_match_all,
        visio_tools_instance.batch_update_text_by_map,
        visio_tools_instance.fill_placeholders,
        # Connection operations
        visio_tools_instance.connect_shapes,
        visio_tools_instance.get_shape_connections,
        visio_tools_instance.query_shape_connections,
        visio_tools_instance.cleanup_diagram_connectors,
        visio_tools_instance.validate_diagram_connectors,
        visio_tools_instance.verify_connector_persisted,
        # Idempotent operations (RECOMMENDED for maintainable diagrams)
        visio_tools_instance.add_or_update_shape,
        visio_tools_instance.add_or_update_connector,
        visio_tools_instance.ensure_all_shapes_have_keys,
        # Page management
        visio_tools_instance.add_page,
        visio_tools_instance.switch_page,
        # Debugging and diagnostics
        visio_tools_instance.get_log_summary,
    ]
