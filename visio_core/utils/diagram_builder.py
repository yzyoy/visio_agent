"""
Low-level Visio diagram manipulation using vsdx library
Enhanced with professional layout and print-ready quality features
Supports idempotent operations with key-based shape identity
"""
import os
from typing import Optional, List, Dict, Any, Tuple, Iterable, Set
import re
from typing import Pattern
from vsdx import VisioFile
from .layout_config import (
    GRID_SPACING_IN, MIN_SHAPE_SPACING_IN, MIN_FONT_SIZE_PT, PREFERRED_FONT_SIZE_PT,
    FONT_FAMILY, LINE_WEIGHT_PT, CONNECTOR_WEIGHT_PT, ROUTING_STYLES, DEFAULT_ROUTING_STYLE,
    COLORS, TEXT_ALIGN_HORIZONTAL, TEXT_ALIGN_VERTICAL, TEXT_MARGIN_IN,
    snap_to_grid, validate_position, get_shape_size, get_fill_color,
    normalize_shape_type, get_default_size, SHAPE_TYPE_ALIASES
)
from .shape_identity import (
    get_shape_prop, set_shape_prop, index_shapes_by_key,
    find_shape_by_fallback, compute_edge_key, extract_edge_key_components
)
from .stencil_importer import StencilImporter
from .edge_manager import EdgeCentricManager, EdgeDirection, EdgeType

# Import patches to fix vsdx library issues
import visio_core.patches


class DiagramBuilder:
    """Handles low-level Visio file operations"""
    
    def __init__(self, visio_file: Optional[VisioFile] = None):
        """
        Initialize DiagramBuilder
        
        Args:
            visio_file: Optional existing VisioFile object
        """
        self.visio_file = visio_file
        self.current_page = None
        if self.visio_file and self.visio_file.pages:
            self.current_page = self.visio_file.pages[0]
        
        # Template catalog cache for performance (Phase 2 optimization)
        self._template_catalog_cache: Optional[Dict[str, List[Any]]] = None
        self._catalog_cache_page_id: Optional[str] = None
        
        # Stencil importer for importing masters from VSSX files
        self._stencil_importer: Optional[StencilImporter] = None
        self._current_vsdx_path: Optional[str] = None
        
        # Edge-centric manager for rigorous edge management
        self.edge_manager = EdgeCentricManager(self)

        # Last connector failure detail (set by connect_shapes) for tool/logging diagnostics
        self.last_connector_error: Optional[str] = None
    
    @classmethod
    def load_from_file(cls, filepath: str) -> 'DiagramBuilder':
        """Load existing Visio file"""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Visio file not found: {filepath}")
        
        visio_file = VisioFile(filepath)
        builder = cls(visio_file)
        builder._current_vsdx_path = os.path.abspath(filepath)
        return builder
    
    @classmethod
    def create_new(cls, page_name: str = "Page-1") -> 'DiagramBuilder':
        """Create new Visio diagram - Note: vsdx library doesn't support creating from scratch easily"""
        raise NotImplementedError(
            "Creating new diagrams from scratch is not well supported by vsdx library. "
            "Please load an existing template file instead."
        )
    
    def add_page(self, page_name: str):
        """Add a new page to the diagram"""
        if self.visio_file:
            page = self.visio_file.add_page(page_name)
            self.current_page = page
            return page
    
    def get_page(self, index: int = 0):
        """Get a specific page by index"""
        if self.visio_file and self.visio_file.pages:
            self.current_page = self.visio_file.pages[index]
            self._invalidate_template_cache()  # Cache invalidation on page change
            return self.current_page
        return None
    
    def _invalidate_template_cache(self):
        """Invalidate the template catalog cache"""
        self._template_catalog_cache = None
        self._catalog_cache_page_id = None
    
    def _get_cached_template_catalog(self) -> Dict[str, List[Any]]:
        """
        Get template catalog with caching for performance.
        
        Returns:
            Dictionary mapping master keys to lists of shapes
        """
        if not self.current_page:
            return {}
        
        # Get page identifier for cache validation
        page_id = id(self.current_page)  # Use object id as identifier
        
        # Check if cache is valid
        if (self._template_catalog_cache is not None and 
            self._catalog_cache_page_id == page_id):
            return self._template_catalog_cache
        
        # Build fresh catalog
        shape_catalog: Dict[str, List[Any]] = {}
        for shape in self._iter_shapes(self.current_page.child_shapes):
            # Skip connectors and guide shapes
            if self._is_connector(shape) or self._is_guide(shape):
                continue
            master_name = self._get_master_key(shape)
            shape_catalog.setdefault(master_name, []).append(shape)
        
        # Cache the result
        self._template_catalog_cache = shape_catalog
        self._catalog_cache_page_id = page_id
        
        return shape_catalog
    
    def list_pages(self) -> List[str]:
        """List all page names"""
        if self.visio_file:
            return self.visio_file.get_page_names()
        return []
    
    def add_shape(self, text: str, shape_type: str, x: float, y: float, 
                  width: float = 1.5, height: float = 0.75, 
                  use_professional_formatting: bool = False) -> Optional[Any]:
        """
        Add a shape to the current page by copying an existing similar shape.
        Enhanced with professional formatting and grid-based positioning.
        
        Args:
            text: Text to display in the shape
            shape_type: Type of shape (used to find a similar shape to copy)
            x, y: Position coordinates (in inches)
            width, height: Shape dimensions (in inches)
            use_professional_formatting: Apply professional typography, colors, and layout.
                Default False preserves template formatting (RECOMMENDED for Chinese text).
                Set True only when creating diagrams from scratch without good templates.
        
        Returns:
            Shape object or None
        """
        if not self.current_page:
            print("Error: No current page set")
            return None
        
        try:
            # Normalize shape type using aliases (Phase 3 enhancement)
            normalized_type = normalize_shape_type(shape_type)
            
            # Use cached template catalog for performance (Phase 2 optimization)
            shape_catalog = self._get_cached_template_catalog()

            # Determine best template list for requested shape_type
            candidate_templates = self._select_shape_templates(normalized_type, shape_catalog)
            template_shape = candidate_templates[0] if candidate_templates else None

            if not template_shape:
                # Better error message with suggestions
                available_types = list(set([
                    getattr(getattr(s, 'master', None), 'name', 'Unknown')
                    for shapes in shape_catalog.values() 
                    for s in shapes
                ]))
                available_types_str = ', '.join(available_types[:5]) if available_types else 'none'
                
                print(f"Warning: No template shape found for type '{shape_type}' (normalized: '{normalized_type}')")
                print(f"  Available shape types on page: {available_types_str}")
                print(f"  Suggestion: Add at least one shape of the desired type manually, or use one of: {', '.join(SHAPE_TYPE_ALIASES.keys())[:100]}")
                print(f"  The page '{self.current_page.name}' needs at least one usable shape to copy.")
                return None

            # Copy the shape while preserving master/style
            new_shape_xml = self.visio_file.copy_shape(template_shape.xml, self.current_page)

            # Find the newly created shape by matching the XML we just created
            new_shape = None
            if self.current_page.child_shapes:
                for shape in reversed(self.current_page.child_shapes):
                    if shape.xml == new_shape_xml:
                        new_shape = shape
                        break
                
                # Fallback: use last shape if XML matching fails
                if not new_shape:
                    print("Warning: Could not match new shape XML, using fallback detection")
                    new_shape = self.current_page.child_shapes[-1]
            
            if not new_shape:
                print("Error: Failed to locate newly created shape")
                return None
            
            # Invalidate cache since we added a shape
            self._invalidate_template_cache()

            # Preserve z-order by inserting near template if possible
            self._align_z_order(new_shape, template_shape)

            # ENHANCED POSITIONING LOGIC
            # 1. Always validate and snap ALL dimensions to grid
            x, y = validate_position(x, y)
            x = snap_to_grid(x)
            y = snap_to_grid(y)
            width = snap_to_grid(width)
            height = snap_to_grid(height)
            
            # 2. Store original requested position for fallback
            original_x, original_y = x, y

            # 3. Find optimal position considering existing shapes and layout
            try:
                free_x, free_y = self._find_free_spot(x, y, width, height)
                x, y = free_x, free_y
                
                # If position moved significantly, log it for debugging
                distance_moved = ((x - original_x)**2 + (y - original_y)**2)**0.5
                if distance_moved > GRID_SPACING_IN * 2:
                    print(f"Info: Shape position adjusted from ({original_x:.2f}, {original_y:.2f}) to ({x:.2f}, {y:.2f})")
                    
            except Exception as e:
                # Fallback: keep requested position but ensure it's snapped
                print(f"Warning: Could not find optimal position: {e}")
                x, y = original_x, original_y

            # 4. Apply geometry with validated dimensions
            # Set position first
            new_shape.set_cell_value('PinX', str(x))
            new_shape.set_cell_value('PinY', str(y))
            
            # Set size if provided (also snapped to grid)
            if width and height:
                new_shape.set_cell_value('Width', str(width))
                new_shape.set_cell_value('Height', str(height))
            
            # 5. Force shape anchor to center for consistent positioning
            try:
                # LocPinX/Y determine the shape's anchor point (0.5 = center)
                new_shape.set_cell_value('LocPinX', str(width / 2.0))
                new_shape.set_cell_value('LocPinY', str(height / 2.0))
            except Exception:
                pass  # Some shapes may not support these cells

            # Only update text if provided
            if text is not None:
                new_shape.text = text
            
            # CRITICAL: Auto-assign NodeKey for new shapes to ensure they can be connected
            # This ensures add_or_update_connector can always find the shape
            try:
                # Generate a node key based on text or shape ID
                if text and text.strip():
                    # Use sanitized text as base for key
                    base_key = text.strip().lower()
                    # Replace spaces and special chars with underscores
                    base_key = ''.join(c if c.isalnum() else '_' for c in base_key)
                    # Remove consecutive underscores
                    base_key = '_'.join(filter(None, base_key.split('_')))
                    # Limit length
                    node_key = base_key[:30] if base_key else f"shape_{new_shape.ID}"
                else:
                    # No text, use shape ID
                    node_key = f"shape_{new_shape.ID}"
                
                # Ensure uniqueness by checking existing keys
                nodes_by_key, _ = index_shapes_by_key(self.current_page, self)
                final_key = node_key
                counter = 1
                while final_key in nodes_by_key:
                    final_key = f"{node_key}_{counter}"
                    counter += 1
                
                # Set the NodeKey
                set_shape_prop(new_shape, 'NodeKey', final_key)
                print(f"Auto-assigned NodeKey '{final_key}' to new shape ID {new_shape.ID}")
            except Exception as key_error:
                print(f"Warning: Could not auto-assign NodeKey: {key_error}")

            # Mirror shape-level formatting hooks
            self._copy_formatting(template_shape, new_shape)
            
            # Apply professional formatting enhancements
            if use_professional_formatting:
                self._apply_professional_formatting(new_shape, normalized_type)

            # After placing a shape, attempt to reroute nearby connectors to avoid crossing
            try:
                self._reroute_connectors_near_shape(new_shape)
            except Exception:
                pass

            return new_shape
            
        except Exception as e:
            print(f"Error adding shape: {e}")
            import traceback
            traceback.print_exc()
        
        return None
    
    def add_shape_between_edge(self, text: str, shape_type: str, edge_id: str,
                               width: Optional[float] = None, height: Optional[float] = None,
                               use_professional_formatting: bool = True) -> Optional[Any]:
        """
        Add a shape by splitting an existing edge.
        
        This method ensures proper edge continuity by:
        1. Creating the new shape at the midpoint of the edge
        2. Splitting the edge into two segments
        3. Preserving all edge metadata and properties
        
        Args:
            text: Shape text/label
            shape_type: Type of shape
            edge_id: ID of the edge to split
            width: Shape width (optional)
            height: Shape height (optional)
            use_professional_formatting: Apply professional formatting
            
        Returns:
            New shape object or None if failed
        """
        try:
            # Get edge metadata
            inventory = self.edge_manager.build_edge_inventory()
            edge_meta = inventory.edges.get(edge_id)
            
            if not edge_meta:
                print(f"Error: Edge '{edge_id}' not found")
                return None
                
            # Get source and target shapes to calculate midpoint
            source_shape = self.get_shape_by_id(edge_meta.source_id)
            target_shape = self.get_shape_by_id(edge_meta.target_id)
            
            if not source_shape or not target_shape:
                print(f"Error: Cannot find edge endpoints")
                return None
                
            # Calculate midpoint position
            source_x = float(source_shape.cell_value('PinX') or source_shape.x or 0)
            source_y = float(source_shape.cell_value('PinY') or source_shape.y or 0)
            target_x = float(target_shape.cell_value('PinX') or target_shape.x or 0)
            target_y = float(target_shape.cell_value('PinY') or target_shape.y or 0)
            
            mid_x = (source_x + target_x) / 2
            mid_y = (source_y + target_y) / 2
            
            # Ensure we have dimensions
            if width is None or height is None:
                default_size = get_default_size(shape_type)
                width = float(width or default_size['width'])
                height = float(height or default_size['height'])
            
            # Create the new shape at midpoint
            new_shape = self.add_shape(
                text=text,
                shape_type=shape_type,
                x=mid_x,
                y=mid_y,
                width=width,
                height=height,
                use_professional_formatting=use_professional_formatting
            )
            
            if new_shape:
                new_shape_id = str(new_shape.ID)
                
                # Use edge manager to handle the edge splitting
                split_results = self.edge_manager.handle_shape_insertion(
                    new_shape_id=new_shape_id,
                    between_edge_id=edge_id
                )
                
                # Log results
                if split_results['edges_split']:
                    print(f"Successfully split edge into {len(split_results['edges_split'][0]['new_edges'])} segments")
                if split_results['errors']:
                    for error in split_results['errors']:
                        print(f"Warning: {error}")
                        
                # Rebuild edge inventory
                self.edge_manager.build_edge_inventory(force_rebuild=True)
                
                return new_shape
                
        except Exception as e:
            print(f"Error adding shape between edge: {e}")
            import traceback
            traceback.print_exc()
            
        return None
    
    def get_shapes(self) -> List[Any]:
        """Get all shapes from current page"""
        if self.current_page:
            return self.current_page.child_shapes
        return []
    
    def find_shape_by_text(self, text: str, mode: str = "contains") -> Optional[Any]:
        """Find a shape by its text content - searches through all shapes
        
        Args:
            text: Text or regex pattern to match
            mode: 'equals' | 'contains' | 'regex' (default: 'contains')
        
        Returns:
            First matching shape or None
        """
        if not self.current_page:
            return None
        
        shapes = list(self._iter_shapes(self.current_page.child_shapes, include_groups=True))
        
        for shape in shapes:
            # Skip connectors for text matching
            if self._is_connector(shape):
                continue
            
            try:
                txt = (getattr(shape, 'text', '') or '').strip()
                if not txt:
                    continue
                
                # Match based on mode
                if mode == 'equals':
                    if txt == text:
                        return shape
                elif mode == 'contains':
                    if text in txt:
                        return shape
                elif mode == 'regex':
                    try:
                        if re.search(text, txt):
                            return shape
                    except re.error:
                        # Invalid regex pattern, skip this shape
                        continue
            except Exception:
                continue
        
        return None
    
    def get_shape_by_id(self, shape_id: str) -> Optional[Any]:
        """Get shape by its ID"""
        if self.current_page:
            # Try native lookup
            found = self.current_page.find_shape_by_id(shape_id)
            if found:
                return found
            # Robust fallback: string/int equality over all child shapes
            sid = str(shape_id)
            for shape in self.current_page.child_shapes:
                try:
                    if str(getattr(shape, 'ID', '')) == sid:
                        return shape
                except Exception:
                    continue
        return None
    
    def _resolve_shape_identifier(self, identifier: Any) -> Optional[Any]:
        """
        Resolve a shape by either numeric ID, shape key (NodeKey), or shape object.
        
        This enables layout and manipulation methods to work with:
        - Shape objects (returned by add_shape, etc.)
        - Numeric shape IDs (e.g., "3", "5", "7") - Visio's internal IDs
        - Shape keys (e.g., "encoder_1", "src_tokens") - NodeKey property for idempotent operations
        
        Args:
            identifier: Shape object, numeric shape ID, or shape key (NodeKey)
        
        Returns:
            Shape object if found, None otherwise
        """
        if not self.current_page:
            return None
        
        # If it's already a shape object, return it
        if hasattr(identifier, 'ID') and hasattr(identifier, 'xml'):
            return identifier
        
        # Convert to string for ID/NodeKey lookup
        identifier = str(identifier)
        
        # Fast path: Try numeric ID lookup first
        shape = self.get_shape_by_id(identifier)
        if shape:
            return shape
        
        # Fallback: Try NodeKey lookup for idempotent operations
        nodes_by_key, _ = index_shapes_by_key(self.current_page, self)
        shape = nodes_by_key.get(identifier)
        
        return shape
    
    def connect_shapes(self, from_shape_id: Any, to_shape_id: Any, 
                      from_glue_point: Optional[str] = None, 
                      to_glue_point: Optional[str] = None) -> Optional[Any]:
        """
        Connect two shapes with a connector, with optional precise connection points.
        
        Args:
            from_shape_id: Source shape (can be shape object, shape ID string, or NodeKey)
            to_shape_id: Target shape (can be shape object, shape ID string, or NodeKey)  
            from_glue_point: Optional connection point on source shape (e.g., 'Right', 'Top')
            to_glue_point: Optional connection point on target shape (e.g., 'Left', 'Bottom')
        
        Returns:
            Connector object if successful, None if failed
        """
        if not self.current_page:
            print("Error: No current page set")
            return None

        self.last_connector_error = None

        try:
            # Convert shape objects to IDs if needed
            if hasattr(from_shape_id, 'ID'):
                # It's a shape object
                from_shape_id = str(from_shape_id.ID)
            else:
                # It's already a string ID or NodeKey
                from_shape_id = str(from_shape_id)
            
            if hasattr(to_shape_id, 'ID'):
                # It's a shape object
                to_shape_id = str(to_shape_id.ID)
            else:
                # It's already a string ID or NodeKey
                to_shape_id = str(to_shape_id)
            
            # DON'T call load_pages() - it reloads from file and loses in-memory changes!
            from_shape = self.get_shape_by_id(from_shape_id) or self._resolve_shape_identifier(from_shape_id)
            to_shape = self.get_shape_by_id(to_shape_id) or self._resolve_shape_identifier(to_shape_id)
            
            if not from_shape:
                print(f"Error: Source shape with ID or key '{from_shape_id}' not found")
                return None
            
            if not to_shape:
                print(f"Error: Target shape with ID or key '{to_shape_id}' not found")
                return None
            
            # Try to find an existing connector template for styling (optional)
            connector_template = None
            template_sources: List[str] = []
            template_style: Dict[str, str] = {}
            
            # Search current page first
            current_page_connectors = [s for s in self.current_page.child_shapes if self._is_connector(s)]
            if current_page_connectors:
                connector_template = current_page_connectors[0]
                template_sources.append(f"current page ({len(current_page_connectors)} connectors)")
            
            # Search all pages if not found
            if not connector_template and hasattr(self.visio_file, 'pages'):
                for page_idx, page in enumerate(self.visio_file.pages):
                    page_connectors = [s for s in getattr(page, 'child_shapes', []) if self._is_connector(s)]
                    if page_connectors:
                        connector_template = page_connectors[0]
                        template_sources.append(f"page {page_idx} ({len(page_connectors)} connectors)")
                        break
            
            if connector_template:
                template_source_msg = template_sources[0] if template_sources else "existing connector"
                print(f"Using connector template from: {template_source_msg} (copy_shape + set_start_and_finish)")
                template_style = self._extract_connector_style(connector_template)
            else:
                print(f"Info: No connector template found. Creating connector programmatically using vsdx library.")
            
            new_connector = None
            if connector_template:
                try:
                    self.visio_file.copy_shape(connector_template.xml, self.current_page)
                    new_connector = self.current_page.child_shapes[-1]
                    sx, sy, tx, ty = self._compute_edge_connection(from_shape, to_shape)
                    if not hasattr(new_connector, 'set_start_and_finish'):
                        raise RuntimeError("Copied connector lacks set_start_and_finish")
                    new_connector.set_start_and_finish((sx, sy), (tx, ty))
                    print(
                        f"[OK] Created connector via copy_shape (ID: {getattr(new_connector, 'ID', 'unknown')})"
                    )
                except Exception as e:
                    import traceback
                    self.last_connector_error = (
                        f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=5)}"
                    )
                    print(f"Error: copy_shape connector path failed: {e}")
                    traceback.print_exc()
                    new_connector = None
            
            if new_connector is None:
                try:
                    from vsdx.connectors import Connect
                    
                    new_connector = Connect.create(
                        page=self.current_page,
                        from_shape=from_shape,
                        to_shape=to_shape
                    )
                    
                    if new_connector:
                        cid = getattr(new_connector, 'ID', 'unknown')
                        print(f"[OK] Created connector via vsdx.Connect.create() (ID: {cid})")
                    else:
                        self.last_connector_error = (
                            self.last_connector_error or "vsdx.Connect.create() returned None"
                        )
                        print(f"Error: vsdx.Connect.create() returned None")
                        return None
                        
                except Exception as e:
                    import traceback
                    tb = traceback.format_exc(limit=8)
                    self.last_connector_error = f"{type(e).__name__}: {e}\n{tb}"
                    print(f"Error: Failed to create connector via vsdx library: {e}")
                    traceback.print_exc()
                    return None
            
            try:
                self._normalize_connector_geometry(new_connector, from_shape, to_shape)
            except Exception as norm_err:
                print(f"Warning: connector geometry normalize failed: {norm_err}")
            
            # Apply styling based on template (if available) or fall back to defaults
            applied_style_cells = set()
            if template_style:
                applied_style_cells = self._apply_connector_style(new_connector, template_style)
                if applied_style_cells:
                    source_desc = template_sources[0] if template_sources else "template"
                    print(f"[OK] Applied connector styling from {source_desc}")
            self._apply_default_connector_style(new_connector, skip_cells=applied_style_cells)
            
            # CRITICAL FIX: Ensure connector has proper Line section in XML
            # vsdx-created connectors usually include these sections, but older masters
            # or previously imported templates sometimes miss key cells
            try:
                import xml.etree.ElementTree as ET
                
                if hasattr(new_connector, 'xml') and new_connector.xml is not None:
                    ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
                    
                    # Check if Line element exists
                    line_elem = new_connector.xml.find('.//v:Line', ns)
                    if line_elem is None:
                        line_elem = new_connector.xml.find('.//Line')
                    
                    if line_elem is None:
                        # Create Line element if it doesn't exist
                        print("Creating Line element for connector visibility")
                        
                        # Create Line section with namespace
                        line_elem = ET.SubElement(new_connector.xml, '{http://schemas.microsoft.com/office/visio/2012/main}Line')
                        
                        # Add essential Line cells for connector visibility
                        line_cells = [
                            ('LineWeight', '0.01388889'),  # Slightly thicker for better visibility (1pt)
                            ('LineColor', '0'),            # Black color
                            ('LinePattern', '1'),          # Solid line (critical for visibility)
                            ('LineCap', '1'),              # Round cap
                            ('BeginArrow', '0'),           # No begin arrow
                            ('EndArrow', '4'),             # Standard arrow
                            ('BeginArrowSize', '2'),       # Medium size
                            ('EndArrowSize', '2'),         # Medium size
                            ('Rounding', '0'),             # No rounding initially
                            ('Transparency', '0'),         # Fully opaque
                            ('LineColorTrans', '0'),       # No transparency on line color
                        ]
                        
                        for cell_name, cell_value in line_cells:
                            cell_elem = ET.SubElement(line_elem, '{http://schemas.microsoft.com/office/visio/2012/main}Cell')
                            cell_elem.set('N', cell_name)
                            cell_elem.set('V', cell_value)
                        
                        print(f"[OK] Created Line element with {len(line_cells)} visibility properties")
                    else:
                        # Line element exists - ensure it has essential cells for visibility
                        essential_cells = [
                            ('LineWeight', '0.01388889'),  # 1pt for visibility
                            ('LineColor', '0'),            # Black
                            ('LinePattern', '1'),          # CRITICAL: Must be 1 for solid line
                            ('Transparency', '0'),         # CRITICAL: Must be 0 for visibility
                            ('LineColorTrans', '0'),       # No transparency
                        ]
                        
                        for cell_name, default_value in essential_cells:
                            cell = line_elem.find(f'.//v:Cell[@N="{cell_name}"]', ns) or line_elem.find(f'.//Cell[@N="{cell_name}"]')
                            if cell is None:
                                # Add missing essential cell
                                cell_elem = ET.SubElement(line_elem, '{http://schemas.microsoft.com/office/visio/2012/main}Cell')
                                cell_elem.set('N', cell_name)
                                cell_elem.set('V', default_value)
                            elif cell_name == 'LinePattern' and cell.get('V', '') == '0':
                                # Fix invisible line pattern
                                cell.set('V', '1')
                                print(f"Fixed invisible LinePattern for connector")
                            elif cell_name == 'Transparency' and float(cell.get('V', '0')) > 0.99:
                                # Fix fully transparent line
                                cell.set('V', '0')
                                print(f"Fixed transparent line for connector")
                    
                    # CRITICAL: Ensure Geom (geometry) section exists for connector path
                    geom_elem = new_connector.xml.find('.//v:Geom', ns)
                    if geom_elem is None:
                        geom_elem = new_connector.xml.find('.//Geom')
                    
                    if geom_elem is None:
                        # Create basic Geom section for line
                        print("Creating missing Geom section for connector path")
                        section_elem = ET.SubElement(new_connector.xml, '{http://schemas.microsoft.com/office/visio/2012/main}Section')
                        section_elem.set('N', 'Geometry')
                        section_elem.set('IX', '0')
                        
                        # Add NoFill cell
                        cell_elem = ET.SubElement(section_elem, '{http://schemas.microsoft.com/office/visio/2012/main}Cell')
                        cell_elem.set('N', 'NoFill')
                        cell_elem.set('V', '1')  # Connectors have no fill
                        
                        # Add MoveTo row
                        row_elem = ET.SubElement(section_elem, '{http://schemas.microsoft.com/office/visio/2012/main}Row')
                        row_elem.set('T', 'MoveTo')
                        row_elem.set('IX', '0')
                        
                        x_cell = ET.SubElement(row_elem, '{http://schemas.microsoft.com/office/visio/2012/main}Cell')
                        x_cell.set('N', 'X')
                        x_cell.set('V', '0')
                        
                        y_cell = ET.SubElement(row_elem, '{http://schemas.microsoft.com/office/visio/2012/main}Cell')
                        y_cell.set('N', 'Y')
                        y_cell.set('V', '0')
                        
                        # Add LineTo row
                        row_elem2 = ET.SubElement(section_elem, '{http://schemas.microsoft.com/office/visio/2012/main}Row')
                        row_elem2.set('T', 'LineTo')
                        row_elem2.set('IX', '1')
                        
                        x_cell2 = ET.SubElement(row_elem2, '{http://schemas.microsoft.com/office/visio/2012/main}Cell')
                        x_cell2.set('N', 'X')
                        x_cell2.set('V', 'Width*1')
                        
                        y_cell2 = ET.SubElement(row_elem2, '{http://schemas.microsoft.com/office/visio/2012/main}Cell')
                        y_cell2.set('N', 'Y')
                        y_cell2.set('V', '0')
                    
                    # CRITICAL: Ensure XForm section exists with proper coordinate formulas
                    xform_elem = new_connector.xml.find('.//v:XForm', ns)
                    if xform_elem is None:
                        xform_elem = new_connector.xml.find('.//XForm')
                    
                    if xform_elem is None:
                        print("Creating XForm section for connector coordinates")
                        xform_elem = ET.SubElement(new_connector.xml, '{http://schemas.microsoft.com/office/visio/2012/main}XForm')
                        
                        # Add XForm cells with formulas that reference XForm1D
                        xform_cells = [
                            ('PinX', '(BeginX+EndX)*0.5', None),
                            ('PinY', '(BeginY+EndY)*0.5', None),
                            ('Width', 'SQRT((EndX-BeginX)^2+(EndY-BeginY)^2)', None),
                            ('Height', '0', None),
                            ('LocPinX', 'Width*0.5', None),
                            ('LocPinY', 'Height*0.5', None),
                            ('Angle', 'ATAN2(EndY-BeginY,EndX-BeginX)', None),
                        ]
                        
                        for cell_name, formula, value in xform_cells:
                            cell_elem = ET.SubElement(xform_elem, '{http://schemas.microsoft.com/office/visio/2012/main}Cell')
                            cell_elem.set('N', cell_name)
                            if formula:
                                cell_elem.set('F', formula)
                            if value is not None:
                                cell_elem.set('V', str(value))
                        
                        print("[OK] Created XForm section with coordinate formulas")
                    
                    # CRITICAL: Ensure XForm1D section exists (makes it a dynamic connector)
                    xform1d_elem = new_connector.xml.find('.//v:XForm1D', ns)
                    if xform1d_elem is None:
                        xform1d_elem = new_connector.xml.find('.//XForm1D')
                    
                    if xform1d_elem is None:
                        print("[WARN]  CRITICAL: Connector missing XForm1D - creating it now")
                        # XForm1D is what makes a shape a dynamic connector in Visio
                        xform1d_elem = ET.SubElement(new_connector.xml, '{http://schemas.microsoft.com/office/visio/2012/main}XForm1D')
                        
                        # Add essential XForm1D cells
                        # Note: Direct values (not formulas) since there's no Master to inherit from
                        xform1d_cells = [
                            ('BeginX', f'{from_shape.x}'),
                            ('BeginY', f'{from_shape.y}'),
                            ('EndX', f'{to_shape.x}'),
                            ('EndY', f'{to_shape.y}'),
                        ]
                        
                        for cell_name, cell_value in xform1d_cells:
                            cell_elem = ET.SubElement(xform1d_elem, '{http://schemas.microsoft.com/office/visio/2012/main}Cell')
                            cell_elem.set('N', cell_name)
                            cell_elem.set('V', str(cell_value))
                        
                        print(f"[OK] Created XForm1D section - connector is now dynamic")
                    
                    # Add UniqueID for shape tracking
                    if new_connector.xml.get('UniqueID') is None:
                        import uuid
                        unique_id = f'{{{str(uuid.uuid4()).upper()}}}'
                        new_connector.xml.set('UniqueID', unique_id)
                        print(f"[OK] Added UniqueID to connector")
                    
                    # CRITICAL: Set explicit style attributes to ensure visibility
                    # Using style ID 3 which typically exists in most templates
                    if new_connector.xml.get('LineStyle') == '0':
                        new_connector.xml.set('LineStyle', '3')
                    if new_connector.xml.get('FillStyle') == '0':
                        new_connector.xml.set('FillStyle', '3')
                    if new_connector.xml.get('TextStyle') == '0':
                        new_connector.xml.set('TextStyle', '3')
                    
                    # Add Layout section for routing behavior
                    layout_section = new_connector.xml.find('.//v:Section[@N="Layout"]', ns)
                    if layout_section is None:
                        layout_section = new_connector.xml.find('.//Section[@N="Layout"]')
                    
                    if layout_section is None:
                        print("Creating Layout section for connector")
                        layout_section = ET.SubElement(new_connector.xml, '{http://schemas.microsoft.com/office/visio/2012/main}Section')
                        layout_section.set('N', 'Layout')
                        
                        # Add essential layout cells
                        layout_cells = [
                            ('ShapePermeableX', 'False'),
                            ('ShapePermeableY', 'False'),
                            ('ShapePermeablePlace', 'False'),
                            ('ShapeRouteStyle', '16'),  # Right-angle routing
                            ('ConFixedCode', '0'),
                        ]
                        
                        for cell_name, cell_value in layout_cells:
                            row_elem = ET.SubElement(layout_section, '{http://schemas.microsoft.com/office/visio/2012/main}Row')
                            row_elem.set('N', cell_name)
                            cell_elem = ET.SubElement(row_elem, '{http://schemas.microsoft.com/office/visio/2012/main}Cell')
                            cell_elem.set('N', 'Value')
                            cell_elem.set('V', cell_value)
                        
                        print(f"[OK] Created Layout section with {len(layout_cells)} cells")
                
            except Exception as line_fix_error:
                print(f"Warning: Failed to ensure Line element: {line_fix_error}")
                import traceback
                traceback.print_exc()
            
            # Set proper glue connections using shape ID references
            # Note: vsdx.Connect.create() already sets up basic connections (with our patch),
            # but we still need to apply custom connection points if specified
            try:
                if from_glue_point is None and to_glue_point is None:
                    # vsdx.Connect.create() already set up default connections to the centers
                    # and the patched version adds Begin/End connection rows automatically
                    print(f"[OK] Using default connections from vsdx.Connect.create()")
                    glue_success = True
                else:
                    # Apply custom connection points when caller specifies glue overrides
                    glue_success = self._set_connector_glue(new_connector, from_shape, to_shape, 
                                                           from_glue_point, to_glue_point)
                    if not glue_success:
                        print(f"Error: Failed to establish glue connection between shapes {from_shape_id} and {to_shape_id}")
                        # Clean up the failed connector
                        try:
                            new_connector.remove()
                        except:
                            pass
                        return None
                
                # Verify glue connection was actually set in XML
                glue_verified = self._verify_connector_glue(new_connector, from_shape, to_shape)
                if not glue_verified:
                    print(f"Warning: Glue connection verification failed - attempting fallback connection method")
                    
                    # Try fallback coordinate-based connection before giving up
                    try:
                        sx, sy, tx, ty = self._compute_edge_connection(from_shape, to_shape)
                        if hasattr(new_connector, 'set_start_and_finish'):
                            new_connector.set_start_and_finish((sx, sy), (tx, ty))
                            print(f"Applied fallback coordinate-based connection: ({sx:.2f},{sy:.2f}) to ({tx:.2f},{ty:.2f})")
                        else:
                            print(f"Error: Connector lacks set_start_and_finish method, cannot apply fallback")
                            # Clean up the failed connector
                            try:
                                new_connector.remove()
                            except:
                                pass
                            return None
                    except Exception as fallback_error:
                        print(f"Error: Fallback connection also failed: {fallback_error}")
                        # Clean up the failed connector
                        try:
                            new_connector.remove()
                        except:
                            pass
                        return None
                
                # Rebuild edge inventory after adding connector
                self.edge_manager.build_edge_inventory(force_rebuild=True)
                
                # Additional check: verify connector is actually committed to the file structure
                try:
                    connector_id = str(getattr(new_connector, 'ID', ''))
                    
                    # Verify connector has proper XML structure
                    if hasattr(new_connector, 'xml') and new_connector.xml is not None:
                        # Ensure connector is in page's shape collection
                        if new_connector not in self.current_page.child_shapes:
                            print(f"Warning: Connector not in page's child_shapes, forcing refresh")
                            # NOTE: _shapes and child_shapes are @property accessors that
                            # always re-read from page XML.  Setting _shapes = None would
                            # shadow the property and break subsequent access.
                            # Instead, verify the connector XML is in the page's Shapes element.
                            try:
                                ns_p = '{http://schemas.microsoft.com/office/visio/2012/main}'
                                shapes_tag = self.current_page.xml.find(f'.//{ns_p}Shapes')
                                if shapes_tag is None:
                                    shapes_tag = self.current_page.xml.find('.//Shapes')
                                if shapes_tag is not None and new_connector.xml not in list(shapes_tag):
                                    shapes_tag.append(new_connector.xml)
                                    print(f"[OK] Appended connector {connector_id} XML to page Shapes")
                                # Check again after fix
                                if new_connector in self.current_page.child_shapes:
                                    print(f"[OK] Connector {connector_id} now in child_shapes after refresh")
                            except Exception as refresh_error:
                                print(f"Warning: Cache refresh failed: {refresh_error}")
                    
                    # Verify the connector can be found (use direct search instead of get_shape_by_id)
                    # get_shape_by_id might use cached index, so check directly in child_shapes
                    found = False
                    for shape in self.current_page.child_shapes:
                        if str(getattr(shape, 'ID', '')) == connector_id:
                            found = True
                            break
                    
                    if not found:
                        print(f"Warning: Connector {connector_id} not in child_shapes, but object exists")
                        # Don't fail - the connector object is valid and will be saved
                    else:
                        print(f"[OK] Connector {connector_id} successfully created and verified")
                    
                except Exception as commit_error:
                    print(f"Warning: Error during connector verification: {commit_error}")
                
                return new_connector  # Return connector object for further processing
                
            except Exception as e:
                print(f"Error setting connector glue: {e}")
                import traceback
                traceback.print_exc()
                # Clean up the failed connector
                try:
                    new_connector.remove()
                except:
                    pass
                return None
            
        except Exception as e:
            print(f"Error connecting shapes: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _extract_connector_style(self, connector: Any) -> Dict[str, str]:
        """
        Capture connector line styling from an existing connector to reapply elsewhere.
        """
        style_cells: Dict[str, str] = {}
        if not connector:
            return style_cells
        
        candidate_cells = [
            'LineWeight', 'LineColor', 'LinePattern', 'LineCap',
            'BeginArrow', 'EndArrow', 'BeginArrowSize', 'EndArrowSize',
            'Rounding', 'Transparency', 'LineColorTrans'
        ]
        
        for cell_name in candidate_cells:
            value = None
            if hasattr(connector, 'cell_value'):
                try:
                    value = connector.cell_value(cell_name)
                except Exception:
                    value = None
            
            if (value is None or value == '') and hasattr(connector, 'get_cell_value'):
                try:
                    value = connector.get_cell_value(cell_name)
                except Exception:
                    value = None
            
            if value is None or value == '':
                continue
            
            style_cells[cell_name] = str(value)
        
        return style_cells
    
    def _apply_connector_style(self, connector: Any, style_cells: Dict[str, str]) -> Set[str]:
        """
        Apply captured connector style cells to a new connector.
        Returns the set of cell names successfully updated.
        """
        applied_cells: Set[str] = set()
        if not connector or not style_cells:
            return applied_cells
        
        setter = getattr(connector, 'set_cell_value', None)
        if not setter:
            return applied_cells
        
        for cell_name, cell_value in style_cells.items():
            if cell_value is None:
                continue
            try:
                setter(cell_name, cell_value)
                applied_cells.add(cell_name)
            except Exception as e:
                print(f"Warning: Failed to apply connector style cell '{cell_name}': {e}")
        
        return applied_cells
    
    def _apply_default_connector_style(self, connector: Any, skip_cells: Optional[Set[str]] = None) -> None:
        """
        Ensure essential connector styling exists when no template style is available.
        """
        if not connector or not hasattr(connector, 'set_cell_value'):
            return
        
        skip = skip_cells or set()
        default_cells = {
            'LineWeight': '0.01',
            'LineColor': '0',
            'LinePattern': '1',
            'LineCap': '1',
            'BeginArrow': '0',
            'EndArrow': '3',
            'BeginArrowSize': '2',
            'EndArrowSize': '2',
            'Rounding': '0',
            'Transparency': '0',
        }
        
        for cell_name, cell_value in default_cells.items():
            if cell_name in skip:
                continue
            try:
                connector.set_cell_value(cell_name, cell_value)
            except Exception:
                # Don't fail if certain cells can't be set (depends on connector type)
                pass
    
    def update_shape_text(self, shape_id: str, new_text: str) -> bool:
        """Update text of a shape"""
        shape = self.get_shape_by_id(shape_id)
        if shape:
            try:
                shape.text = new_text
                return True
            except Exception as e:
                print(f"Error updating shape text: {e}")
        return False
    
    def remove_shape(self, shape_id: str) -> bool:
        """Remove a shape from the diagram with basic connector cleanup"""
        return self.remove_shape_with_connector_management(shape_id, reconnect_mode='remove_connectors')

    def remove_shape_with_connector_management(
        self, shape_id: str, reconnect_mode: str = 'smart_reconnect'
    ):
        """Remove a shape from the diagram with advanced connector management.

        Args:
            shape_id: ID of the shape to remove
            reconnect_mode: How to handle connectors:
                - 'remove_connectors': Remove all connected connectors (simple cleanup)
                - 'smart_reconnect': Try to reconnect through the deleted shape (preserves flow)
                - 'validate_only': Check for issues but don't remove (useful for batch operations)

        Returns:
            ``(True, "")`` on success.
            ``(False, reason_code)`` on failure, where *reason_code* is one of:
            ``"NO_SHAPE"`` – shape not found,
            ``"IS_CONNECTOR"`` – target is a connector (use remove_connector),
            ``"SAVE_REQUIRED"`` – diagram was modified after last save,
            ``"EDGE_ERROR"`` – connector-management step failed,
            ``"EXCEPTION:<msg>"`` – unexpected exception.
        """
        shape = self.get_shape_by_id(shape_id)
        if not shape:
            print(f"Error: Shape '{shape_id}' not found")
            return False, "NO_SHAPE"

        # Skip connectors - they should be removed via connector-specific methods
        if self._is_connector(shape):
            print(f"Error: Cannot remove connector '{shape_id}' via remove_shape. Use remove_connector instead.")
            return False, "IS_CONNECTOR"

        try:
            # Use edge-centric manager for precise edge handling
            edge_results = self.edge_manager.handle_shape_deletion(
                shape_id,
                reconnect_strategy='smart' if reconnect_mode == 'smart_reconnect' else 'remove'
            )

            # Log edge management results
            if edge_results.get('edges_reconnected'):
                print(f"Reconnected {len(edge_results['edges_reconnected'])} edges through deleted shape")
            if edge_results.get('edges_removed'):
                print(f"Removed {len(edge_results['edges_removed'])} edges")
            if edge_results.get('errors'):
                for error in edge_results['errors']:
                    print(f"Warning: {error}")
                # If every individual edge operation failed, surface a summary
                if not edge_results.get('edges_reconnected') and not edge_results.get('edges_removed'):
                    detail = "; ".join(str(e) for e in edge_results['errors'][:3])
                    return False, f"EDGE_ERROR:{detail}"

            # Remove the shape itself
            shape.remove()

            # Template cleanup can leave half-connected or formula-only orphan
            # connectors behind; remove them before rebuilding inventory.
            orphaned_removed = self.cleanup_orphaned_connectors()
            if orphaned_removed:
                print(f"Removed {orphaned_removed} orphaned connectors after shape deletion")

            # Rebuild edge inventory after changes
            self.edge_manager.build_edge_inventory(force_rebuild=True)

            return True, ""

        except Exception as e:
            print(f"Error removing shape: {e}")
            return False, f"EXCEPTION:{e}"
    
    def remove_connector(self, connector_id: str) -> bool:
        """
        Remove a connector from the diagram.
        
        Args:
            connector_id: ID of the connector to remove
        
        Returns:
            True if successful
        """
        connector = self.get_shape_by_id(connector_id)
        if not connector:
            print(f"Error: Connector '{connector_id}' not found")
            return False
        
        if not self._is_connector(connector):
            print(f"Error: Shape '{connector_id}' is not a connector")
            return False
        
        try:
            connector.remove()
            return True
        except Exception as e:
            print(f"Error removing connector: {e}")
            return False
    
    def _remove_connected_connectors(self, connected_connectors: List[Dict[str, Any]]) -> None:
        """
        Remove all connectors connected to a shape.
        
        Args:
            connected_connectors: List of connector info dictionaries
        """
        for conn_info in connected_connectors:
            try:
                connector = conn_info['connector']
                connector.remove()
            except Exception as e:
                print(f"Warning: Could not remove connector {conn_info.get('connector_id', '?')}: {e}")
    
    def _smart_reconnect_through_deleted_shape(self, deleted_shape_id: str, connected_connectors: List[Dict[str, Any]]) -> None:
        """
        Reconnect connectors to bypass a deleted shape, maintaining logical flow.
        
        This method implements smart reconnection logic:
        1. If shape has 1 input and 1 output connector -> connect input source to output target
        2. If shape has multiple inputs/outputs -> create direct connections between all combinations
        3. Handle special cases like decision nodes, loops, etc.
        
        Args:
            deleted_shape_id: ID of the shape being deleted
            connected_connectors: List of connector info dictionaries
        """
        if not connected_connectors:
            return
        
        # Categorize connectors
        input_connectors = []
        output_connectors = []
        
        for conn_info in connected_connectors:
            if conn_info['is_target']:  # Connector ends at this shape
                input_connectors.append(conn_info)
            elif conn_info['is_source']:  # Connector begins at this shape
                output_connectors.append(conn_info)
        
        # Smart reconnection logic
        if len(input_connectors) == 1 and len(output_connectors) == 1:
            # Simple case: one input, one output - create direct connection
            self._create_bypass_connection(input_connectors[0], output_connectors[0])
        elif len(input_connectors) > 0 and len(output_connectors) > 0:
            # Complex case: multiple inputs/outputs - connect all inputs to all outputs
            self._create_multiple_bypass_connections(input_connectors, output_connectors)
        
        # Remove original connectors after creating bypasses
        self._remove_connected_connectors(connected_connectors)
    
    def _create_bypass_connection(self, input_conn: Dict[str, Any], output_conn: Dict[str, Any]) -> bool:
        """
        Create a direct connection bypassing the deleted shape.
        
        Args:
            input_conn: Information about the input connector
            output_conn: Information about the output connector
        
        Returns:
            True if successful
        """
        try:
            # Find the source shape of the input connector
            source_shape_id = input_conn.get('other_shape_id')
            # Find the target shape of the output connector  
            target_shape_id = output_conn.get('other_shape_id')
            
            if source_shape_id and target_shape_id:
                # Create new connection
                return self.connect_shapes(source_shape_id, target_shape_id)
            
        except Exception as e:
            print(f"Warning: Could not create bypass connection: {e}")
        
        return False
    
    def _create_multiple_bypass_connections(self, input_connectors: List[Dict[str, Any]], output_connectors: List[Dict[str, Any]]) -> None:
        """
        Create multiple connections to handle complex routing scenarios.
        
        Args:
            input_connectors: List of input connector info
            output_connectors: List of output connector info
        """
        for input_conn in input_connectors:
            for output_conn in output_connectors:
                self._create_bypass_connection(input_conn, output_conn)

    def _extract_shape_ids_from_formula(self, formula: Any) -> Set[str]:
        """Extract referenced shape IDs from a Visio cell formula."""
        if formula is None:
            return set()
        return set(re.findall(r'Sheet\.?(\d+)!', str(formula), flags=re.IGNORECASE))

    def _iter_connector_cell_formulas(self, connector: Any) -> Iterable[Tuple[str, str]]:
        """Yield connector cell names and formulas from both object and XML views."""
        seen: Set[Tuple[str, str]] = set()

        if hasattr(connector, 'cells'):
            try:
                cells = connector.cells or {}
                if hasattr(cells, 'items'):
                    for cell_name, cell in cells.items():
                        formula = None
                        if isinstance(cell, dict):
                            formula = cell.get('formula') or cell.get('F')
                        else:
                            formula = getattr(cell, 'formula', None) or getattr(cell, 'F', None)
                        if formula:
                            item = (str(cell_name), str(formula))
                            if item not in seen:
                                seen.add(item)
                                yield item
            except Exception:
                pass

        if hasattr(connector, 'xml') and connector.xml is not None:
            try:
                ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
                xml_cells = connector.xml.findall('.//v:Cell', ns)
                if not xml_cells:
                    xml_cells = connector.xml.findall('.//Cell')
                for cell in xml_cells:
                    cell_name = cell.get('N', '')
                    formula = cell.get('F')
                    if formula:
                        item = (str(cell_name), str(formula))
                        if item not in seen:
                            seen.add(item)
                            yield item
            except Exception:
                pass

    def _get_connector_formula_references(self, connector: Any) -> Dict[str, Set[str]]:
        """Collect connector shape references from Begin/End formulas and triggers."""
        references = {'source': set(), 'target': set(), 'all': set()}

        for cell_name, formula in self._iter_connector_cell_formulas(connector):
            shape_ids = self._extract_shape_ids_from_formula(formula)
            if not shape_ids:
                continue

            references['all'].update(shape_ids)
            cell_name = str(cell_name or '')
            if cell_name.startswith(('Beg', 'Begin')):
                references['source'].update(shape_ids)
            elif cell_name.startswith('End'):
                references['target'].update(shape_ids)

        return references

    def get_connector_reference_summary(self, connector: Any) -> Dict[str, Any]:
        """Summarize a connector's endpoint and formula-based shape references."""
        endpoints = self._get_connector_endpoints(connector)
        connect_refs: Set[str] = set()

        try:
            if hasattr(connector, 'connects') and connector.connects:
                for conn in connector.connects:
                    shape_id = getattr(conn, 'shape_id', None) or getattr(conn, 'to_id', None)
                    if shape_id:
                        connect_refs.add(str(shape_id))
        except Exception:
            pass

        formula_refs = self._get_connector_formula_references(connector)
        referenced_shape_ids = set(connect_refs)
        referenced_shape_ids.update(formula_refs['all'])
        if endpoints['source']:
            referenced_shape_ids.add(endpoints['source'])
        if endpoints['target']:
            referenced_shape_ids.add(endpoints['target'])

        existing_shape_ids = set()
        if self.current_page:
            for shape in self.current_page.child_shapes:
                shape_id = getattr(shape, 'ID', None)
                if shape_id is not None:
                    existing_shape_ids.add(str(shape_id))

        missing_shape_ids = {
            shape_id for shape_id in referenced_shape_ids
            if shape_id not in existing_shape_ids
        }

        return {
            'source': endpoints['source'],
            'target': endpoints['target'],
            'connect_shape_ids': connect_refs,
            'formula_shape_ids': formula_refs['all'],
            'referenced_shape_ids': referenced_shape_ids,
            'missing_shape_ids': missing_shape_ids,
        }
    
    def cleanup_orphaned_connectors(self) -> int:
        """
        Find and remove connectors that reference non-existent shapes.
        
        Returns:
            Number of orphaned connectors removed
        """
        if not self.current_page:
            return 0
        
        orphaned_count = 0
        connectors_to_remove = []
        
        for connector in self.current_page.child_shapes:
            if not self._is_connector(connector):
                continue
            
            try:
                reference_summary = self.get_connector_reference_summary(connector)
                has_missing_refs = bool(reference_summary['missing_shape_ids'])
                has_partial_attachment = bool(reference_summary['referenced_shape_ids']) and not (
                    reference_summary['source'] and reference_summary['target']
                )
                is_orphaned = has_missing_refs or has_partial_attachment

                if is_orphaned:
                    connectors_to_remove.append(connector)
                    orphaned_count += 1
            
            except Exception as e:
                print(f"Warning: Error checking connector for orphaned state: {e}")
                continue
        
        # Remove orphaned connectors
        for connector in connectors_to_remove:
            try:
                connector.remove()
            except Exception as e:
                print(f"Warning: Could not remove orphaned connector: {e}")
        
        return orphaned_count
    
    def resolve_connector_ambiguity(self) -> Dict[str, int]:
        """
        Resolve ambiguous connector paths by consolidating multiple begin nodes and ensuring clear paths.
        
        Returns:
            Dictionary with resolution statistics
        """
        if not self.current_page:
            return {'resolved_ambiguities': 0, 'removed_duplicates': 0}
        
        resolved = 0
        duplicates_removed = 0
        
        # Group connectors by their endpoints to find duplicates
        connector_groups = {}
        
        for connector in self.current_page.child_shapes:
            if not self._is_connector(connector):
                continue
            
            try:
                endpoints = self._get_connector_endpoints(connector)
                if endpoints['source'] and endpoints['target']:
                    key = f"{endpoints['source']}->{endpoints['target']}"
                    if key not in connector_groups:
                        connector_groups[key] = []
                    connector_groups[key].append(connector)
            
            except Exception as e:
                print(f"Warning: Error analyzing connector endpoints: {e}")
                continue
        
        # Remove duplicate connectors (keep the first one)
        for key, connectors in connector_groups.items():
            if len(connectors) > 1:
                for duplicate in connectors[1:]:  # Keep the first, remove the rest
                    try:
                        duplicate.remove()
                        duplicates_removed += 1
                    except Exception as e:
                        print(f"Warning: Could not remove duplicate connector: {e}")
        
        return {'resolved_ambiguities': resolved, 'removed_duplicates': duplicates_removed}
    
    def _get_connector_endpoints(self, connector: Any) -> Dict[str, Optional[str]]:
        """
        Get the source and target shape IDs for a connector.
        
        Uses multiple methods to find endpoints:
        1. connector.connects property (vsdx library)
        2. Page's Connects XML element (direct XML parsing)
        3. BegTrigger/EndTrigger cell formulas
        
        Args:
            connector: Connector shape object
        
        Returns:
            Dictionary with 'source' and 'target' shape IDs
        """
        import xml.etree.ElementTree as ET
        
        endpoints = {'source': None, 'target': None}
        connector_id = str(getattr(connector, 'ID', ''))
        
        # Method 1: Try connector.connects property
        try:
            if hasattr(connector, 'connects') and connector.connects:
                for conn in connector.connects:
                    connected_shape_id = getattr(conn, 'shape_id', None)
                    from_rel = getattr(conn, 'from_rel', '')
                    
                    if connected_shape_id:
                        if 'BeginX' in from_rel or 'Begin' in from_rel:
                            endpoints['source'] = str(connected_shape_id)
                        elif 'EndX' in from_rel or 'End' in from_rel:
                            endpoints['target'] = str(connected_shape_id)
        except Exception:
            pass
        
        # Method 2: Parse page's Connects XML element directly
        if (endpoints['source'] is None or endpoints['target'] is None) and self.current_page:
            try:
                ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
                page_xml = getattr(self.current_page, 'xml', None)
                
                if page_xml is not None:
                    # Find all Connect elements
                    connects = page_xml.findall('.//v:Connect', ns)
                    if not connects:
                        connects = page_xml.findall('.//Connect')
                    
                    for connect_elem in connects:
                        from_sheet = connect_elem.get('FromSheet', '')
                        to_sheet = connect_elem.get('ToSheet', '')
                        from_cell = connect_elem.get('FromCell', '')
                        
                        if from_sheet == connector_id:
                            if 'BeginX' in from_cell or 'Begin' in from_cell:
                                if endpoints['source'] is None:
                                    endpoints['source'] = to_sheet
                            elif 'EndX' in from_cell or 'End' in from_cell:
                                if endpoints['target'] is None:
                                    endpoints['target'] = to_sheet
            except Exception:
                pass
        
        # Method 3: Check connector formulas for Sheet.<id> references
        if (endpoints['source'] is None or endpoints['target'] is None):
            try:
                formula_refs = self._get_connector_formula_references(connector)

                if endpoints['source'] is None and formula_refs['source']:
                    endpoints['source'] = sorted(formula_refs['source'], key=int)[0]

                if endpoints['target'] is None and formula_refs['target']:
                    endpoints['target'] = sorted(formula_refs['target'], key=int)[0]
            except Exception:
                pass
        
        return endpoints
    
    def validate_connector_integrity(self) -> Dict[str, Any]:
        """
        Validate the integrity of all connectors in the diagram.
        
        Returns:
            Dictionary with validation results and issues found
        """
        if not self.current_page:
            return {'total_connectors': 0, 'valid_connectors': 0, 'issues': []}
        
        total = 0
        valid = 0
        issues = []
        
        for connector in self.current_page.child_shapes:
            if not self._is_connector(connector):
                continue
            
            total += 1
            connector_id = str(getattr(connector, 'ID', ''))
            
            try:
                endpoints = self._get_connector_endpoints(connector)
                
                # Check if both endpoints exist
                source_exists = endpoints['source'] and self.get_shape_by_id(endpoints['source']) is not None
                target_exists = endpoints['target'] and self.get_shape_by_id(endpoints['target']) is not None
                
                if not source_exists:
                    issues.append({
                        'connector_id': connector_id,
                        'type': 'missing_source',
                        'description': f"Connector {connector_id} has missing or invalid source shape"
                    })
                
                if not target_exists:
                    issues.append({
                        'connector_id': connector_id,
                        'type': 'missing_target', 
                        'description': f"Connector {connector_id} has missing or invalid target shape"
                    })
                
                if source_exists and target_exists:
                    # Check for self-connection
                    if endpoints['source'] == endpoints['target']:
                        issues.append({
                            'connector_id': connector_id,
                            'type': 'self_connection',
                            'description': f"Connector {connector_id} connects shape to itself"
                        })
                    else:
                        valid += 1
            
            except Exception as e:
                issues.append({
                    'connector_id': connector_id,
                    'type': 'validation_error',
                    'description': f"Error validating connector {connector_id}: {e}"
                })
        
        return {
            'total_connectors': total,
            'valid_connectors': valid,
            'issues': issues,
            'integrity_score': valid / total if total > 0 else 1.0
        }

    # -----------------------
    # Geometry & styling ops
    # -----------------------
    def set_shape_position(self, shape_id: str, x: float, y: float) -> bool:
        """Set absolute position (inches) of a shape with grid snapping."""
        shape = self._resolve_shape_identifier(shape_id)
        if not shape:
            return False
        try:
            # Always snap to grid and validate position
            x, y = validate_position(x, y)
            x = snap_to_grid(x)
            y = snap_to_grid(y)
            
            shape.set_cell_value('PinX', str(x))
            shape.set_cell_value('PinY', str(y))
            
            # After moving, reroute nearby connectors
            self._reroute_connectors_near_shape(shape)
            return True
        except Exception:
            return False

    def move_shape_by(self, shape_id: str, dx: float, dy: float) -> bool:
        """Move a shape by delta (inches) with grid snapping."""
        shape = self._resolve_shape_identifier(shape_id)
        if not shape:
            return False
        try:
            old_x = float(shape.cell_value('PinX') or getattr(shape, 'x', 0) or 0)
            old_y = float(shape.cell_value('PinY') or getattr(shape, 'y', 0) or 0)
            
            # Calculate new position and snap to grid
            new_x = old_x + dx
            new_y = old_y + dy
            new_x, new_y = validate_position(new_x, new_y)
            new_x = snap_to_grid(new_x)
            new_y = snap_to_grid(new_y)
            
            shape.set_cell_value('PinX', str(new_x))
            shape.set_cell_value('PinY', str(new_y))
            
            # After moving, reroute nearby connectors
            self._reroute_connectors_near_shape(shape)
            return True
        except Exception:
            return False

    def set_shape_size(self, shape_id: str, width: float, height: float) -> bool:
        """Set size (inches) of a shape with grid snapping."""
        shape = self._resolve_shape_identifier(shape_id)
        if not shape:
            return False
        try:
            # Snap dimensions to grid for consistency
            width = snap_to_grid(width)
            height = snap_to_grid(height)
            
            shape.set_cell_value('Width', str(width))
            shape.set_cell_value('Height', str(height))
            
            # Update anchor point to center
            try:
                shape.set_cell_value('LocPinX', str(width / 2.0))
                shape.set_cell_value('LocPinY', str(height / 2.0))
            except Exception:
                pass
            
            # After resizing, reroute nearby connectors
            self._reroute_connectors_near_shape(shape)
            return True
        except Exception:
            return False

    def set_shape_line_width(self, shape_id: str, weight_pt: float) -> bool:
        """Set line width (points)."""
        shape = self.get_shape_by_id(shape_id)
        if not shape:
            return False
        try:
            shape.set_cell_value('LineWeight', f'{float(weight_pt)}pt')
            return True
        except Exception:
            return False

    def set_shape_line_color(self, shape_id: str, color: str) -> bool:
        """Set line color (hex like #RRGGBB)."""
        shape = self.get_shape_by_id(shape_id)
        if not shape:
            return False
        try:
            shape.set_cell_value('LineColor', color)
            return True
        except Exception:
            return False

    def set_shape_fill_color(self, shape_id: str, color: str) -> bool:
        """Set fill color (hex like #RRGGBB)."""
        shape = self.get_shape_by_id(shape_id)
        if not shape:
            return False
        try:
            shape.set_cell_value('FillForegnd', color)
            shape.set_cell_value('FillPattern', '1')  # Solid
            # Set background to same for solid appearance
            try:
                shape.set_cell_value('FillBkgnd', color)
            except Exception:
                pass
            return True
        except Exception:
            return False

    # -----------------------
    # Stencil-based helpers
    # -----------------------
    def _get_master_name(self, shape: Any) -> str:
        master = getattr(shape, 'master', None)
        return (getattr(master, 'name', '') or '').strip()

    def find_template_by_master_name(self, master_name: str, allow_partial: bool = False) -> Optional[Any]:
        """Find a template shape whose master name matches.
        By default requires exact (case-insensitive) match. Set allow_partial=True to enable substring matching.
        """
        if not self.visio_file:
            return None
        try:
            m = (master_name or '').strip().lower()
            for page in getattr(self.visio_file, 'pages', []) or []:
                for shape in getattr(page, 'child_shapes', []) or []:
                    if self._is_connector(shape) or self._is_guide(shape):
                        continue
                    mn = self._get_master_name(shape).lower()
                    if not mn:
                        continue
                    if (not allow_partial and mn == m) or (allow_partial and (m in mn or mn in m)):
                        return shape
        except Exception:
            return None
        return None

    def add_shape_from_master_name(self, master_name: str, x: float, y: float, text: Optional[str] = None, allow_partial: bool = False) -> Optional[Any]:
        """Add a shape by copying a template whose master name matches.
        Uses exact matching by default; set allow_partial=True to enable substring matching.
        """
        if not self.current_page:
            return None
        template_shape = self.find_template_by_master_name(master_name, allow_partial=allow_partial)
        if not template_shape:
            return None
        try:
            new_shape_xml = self.visio_file.copy_shape(template_shape.xml, self.current_page)
            
            # Find the newly created shape by matching XML
            new_shape = None
            if self.current_page.child_shapes:
                for shape in reversed(self.current_page.child_shapes):
                    if shape.xml == new_shape_xml:
                        new_shape = shape
                        break
                
                # Fallback: use last shape if XML matching fails
                if not new_shape:
                    new_shape = self.current_page.child_shapes[-1]
            
            if new_shape:
                x, y = validate_position(x, y)
                new_shape.set_cell_value('PinX', str(x))
                new_shape.set_cell_value('PinY', str(y))
                if text is not None:
                    new_shape.text = text
                return new_shape
        except Exception:
            return None
        return None
    
    def add_shape_from_vssx_stencil(self, vssx_path: str, master_name: str, x: float, y: float, 
                                     text: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Add a shape from a VSSX stencil file by importing the master and creating an instance.
        
        This method properly imports master shapes from external VSSX stencil files into
        the current VSDX diagram, then creates a shape instance at the specified position.
        
        Args:
            vssx_path: Path to the VSSX stencil file
            master_name: Name of the master shape to import and use
            x: X coordinate for the new shape
            y: Y coordinate for the new shape
            text: Optional text content for the shape
            
        Returns:
            Dictionary with result information:
            {
                'success': bool,
                'shape': shape object or None,
                'message': str
            }
        """
        if not self.current_page:
            return {
                'success': False,
                'shape': None,
                'message': 'No current page set'
            }
        
        if not self._current_vsdx_path:
            return {
                'success': False,
                'shape': None,
                'message': 'VSDX file path not available. File must be saved first.'
            }
        
        # Initialize stencil importer if needed
        if not self._stencil_importer:
            self._stencil_importer = StencilImporter(self._current_vsdx_path)
        
        # Import the master from VSSX into VSDX
        import_result = self._stencil_importer.import_master_from_vssx(vssx_path, master_name)
        
        if not import_result['success']:
            return {
                'success': False,
                'shape': None,
                'message': import_result['message']
            }
        
        # After importing, we need to reload the VSDX file to access the new master
        try:
            # Save current state first to ensure file is written
            if hasattr(self.visio_file, 'save_vsdx') and self._current_vsdx_path:
                self.visio_file.save_vsdx(self._current_vsdx_path)
            
            # Remember the current page index/name for restoration
            old_page_index = 0
            old_page_name = None
            if self.current_page and self.visio_file and self.visio_file.pages:
                try:
                    old_page_index = self.visio_file.pages.index(self.current_page)
                except (ValueError, AttributeError):
                    pass
                try:
                    old_page_name = self.current_page.name if hasattr(self.current_page, 'name') else None
                except AttributeError:
                    pass
            
            # Reload the file to pick up the imported master
            self.visio_file = VisioFile(self._current_vsdx_path)
            
            # Restore current page reference
            if self.visio_file and self.visio_file.pages:
                # Try to find by name first
                if old_page_name:
                    for page in self.visio_file.pages:
                        try:
                            if hasattr(page, 'name') and page.name == old_page_name:
                                self.current_page = page
                                break
                        except AttributeError:
                            continue
                    else:
                        # Try by index
                        if old_page_index < len(self.visio_file.pages):
                            self.current_page = self.visio_file.pages[old_page_index]
                        else:
                            self.current_page = self.visio_file.pages[0]
                else:
                    # Use index
                    if old_page_index < len(self.visio_file.pages):
                        self.current_page = self.visio_file.pages[old_page_index]
                    else:
                        self.current_page = self.visio_file.pages[0]
            
            # Invalidate template cache after reload
            self._invalidate_template_cache()
            
            # Now try to add shape using the imported master
            new_shape = self.add_shape_from_master_name(master_name, x, y, text, allow_partial=False)
            
            # If no existing template instance is available, create a new instance referencing the master
            if not new_shape:
                new_shape = self.create_shape_from_master(master_name, x, y, text)
            
            if new_shape:
                return {
                    'success': True,
                    'shape': new_shape,
                    'message': f"Successfully added shape from master '{master_name}'"
                }
            else:
                return {
                    'success': False,
                    'shape': None,
                    'message': f"Master '{master_name}' imported but failed to create shape instance"
                }
                
        except Exception as e:
            import traceback
            return {
                'success': False,
                'shape': None,
                'message': f"Error after master import: {str(e)}\n{traceback.format_exc()}"
            }

    def create_shape_from_master(self, master_name: str, x: float, y: float, text: Optional[str] = None) -> Optional[Any]:
        """Create a new shape instance on the current page referencing an imported master.
        Best-effort XML injection when no template instance exists to copy.
        """
        if not self.current_page or not self._current_vsdx_path:
            return None
        try:
            # Determine current page index
            page_index = 0
            try:
                page_index = self.visio_file.pages.index(self.current_page)
            except Exception:
                page_index = 0
            page_num = page_index + 1
            
            # Resolve master id by reading visio/masters/masters.xml
            import zipfile
            import xml.etree.ElementTree as ET
            ns = {
                'v': 'http://schemas.microsoft.com/office/visio/2012/main',
                'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
            }
            master_id = None
            with zipfile.ZipFile(self._current_vsdx_path, 'r') as zf:
                with zf.open('visio/masters/masters.xml') as f:
                    m_tree = ET.parse(f)
                    m_root = m_tree.getroot()
                    target = (master_name or '').strip()
                    for m in m_root.findall('.//v:Master', ns):
                        name = m.get('Name', '')
                        name_u = m.get('NameU', '')
                        if name == target or name_u == target:
                            master_id = m.get('ID')
                            break
            if not master_id:
                return None
            
            # Unzip, edit page xml, zip back
            import tempfile, os, shutil
            temp_dir = tempfile.mkdtemp(prefix='vsdx_page_edit_')
            try:
                with zipfile.ZipFile(self._current_vsdx_path, 'r') as zread:
                    zread.extractall(temp_dir)
                page_xml_path = os.path.join(temp_dir, 'visio', 'pages', f'page{page_num}.xml')
                tree = ET.parse(page_xml_path)
                root = tree.getroot()
                # Find or create Shapes container
                shapes = root.find('v:Shapes', ns)
                if shapes is None:
                    shapes = ET.SubElement(root, '{http://schemas.microsoft.com/office/visio/2012/main}Shapes')
                # Compute next shape ID
                max_id = 0
                for s in shapes.findall('v:Shape', ns):
                    try:
                        max_id = max(max_id, int(s.get('ID', '0')))
                    except Exception:
                        continue
                new_id = str(max_id + 1 if max_id else 1)
                # Create minimal shape referencing master
                shape_el = ET.SubElement(shapes, '{http://schemas.microsoft.com/office/visio/2012/main}Shape')
                shape_el.set('ID', new_id)
                shape_el.set('Master', str(master_id))
                # Optionally set initial text (page reload will allow proper text setting too)
                if text:
                    text_el = ET.SubElement(shape_el, '{http://schemas.microsoft.com/office/visio/2012/main}Text')
                    text_el.text = text
                # Write back page xml
                tree.write(page_xml_path, encoding='utf-8', xml_declaration=True)
                # Rebuild vsdx
                with zipfile.ZipFile(self._current_vsdx_path, 'w', zipfile.ZIP_DEFLATED) as zwrite:
                    for root_dir, dirs, files in os.walk(temp_dir):
                        for file in files:
                            file_path = os.path.join(root_dir, file)
                            arcname = os.path.relpath(file_path, temp_dir)
                            zwrite.write(file_path, arcname)
            finally:
                try:
                    shutil.rmtree(temp_dir)
                except Exception:
                    pass
            
            # Reload and return the new shape (likely last shape on page)
            self.visio_file = VisioFile(self._current_vsdx_path)
            if self.visio_file and self.visio_file.pages:
                self.current_page = self.visio_file.pages[page_index if page_index < len(self.visio_file.pages) else 0]
                if self.current_page.child_shapes:
                    new_shape = self.current_page.child_shapes[-1]
                    # Set position and text after creation using library APIs
                    try:
                        x, y = validate_position(x, y)
                        new_shape.set_cell_value('PinX', str(x))
                        new_shape.set_cell_value('PinY', str(y))
                        if text is not None:
                            new_shape.text = text
                    except Exception:
                        pass
                    return new_shape
            return None
        except Exception:
            return None
    
    def clone_shape(self, shape_id: str, x: Optional[float] = None, y: Optional[float] = None, 
                    text: Optional[str] = None) -> Optional[Any]:
        """
        Create a high-fidelity clone of an existing shape
        
        This method creates an exact copy of a shape, preserving all formatting,
        and optionally updates its position and text.
        
        Args:
            shape_id: ID of the shape to clone
            x: Optional new X position (uses offset from original if None)
            y: Optional new Y position (uses offset from original if None)
            text: Optional new text content (preserves original if None)
        
        Returns:
            Cloned shape object or None if failed
        """
        if not self.current_page:
            print("Error: No current page set")
            return None
            
        source_shape = self.get_shape_by_id(shape_id)
        if not source_shape:
            print(f"Error: Shape with ID '{shape_id}' not found")
            return None
        
        try:
            # Copy the shape preserving all properties
            new_shape_xml = self.visio_file.copy_shape(source_shape.xml, self.current_page)
            
            # Find the newly created shape by matching XML
            new_shape = None
            if self.current_page.child_shapes:
                for shape in reversed(self.current_page.child_shapes):
                    if shape.xml == new_shape_xml:
                        new_shape = shape
                        break
                
                # Fallback: use last shape if XML matching fails
                if not new_shape:
                    new_shape = self.current_page.child_shapes[-1]
            
            if new_shape:
                
                # Update position if provided (with grid snapping)
                if x is not None:
                    new_x = snap_to_grid(x)
                    new_x, _ = validate_position(new_x, 0)
                    new_shape.set_cell_value('PinX', str(new_x))
                else:
                    # Default offset: move right by 1 inch (snap to grid)
                    original_x = float(source_shape.cell_value('PinX') or source_shape.x or 0)
                    new_x = snap_to_grid(original_x + 1.0)
                    new_shape.set_cell_value('PinX', str(new_x))
                
                if y is not None:
                    new_y = snap_to_grid(y)
                    _, new_y = validate_position(0, new_y)
                    new_shape.set_cell_value('PinY', str(new_y))
                else:
                    # Default offset: move down by 1 inch (snap to grid)
                    original_y = float(source_shape.cell_value('PinY') or source_shape.y or 0)
                    new_y = snap_to_grid(original_y - 1.0)  # Down is negative in Visio
                    new_shape.set_cell_value('PinY', str(new_y))
                
                # Update text if provided
                if text is not None:
                    new_shape.text = text
                
                return new_shape
                
        except Exception as e:
            print(f"Error cloning shape: {e}")
            import traceback
            traceback.print_exc()
        
        return None
    
    def get_diagram_info(self) -> Dict[str, Any]:
        """Get information about the current diagram"""
        info = {
            "pages": self.list_pages(),
            "current_page": self.current_page.name if self.current_page else None,
            "shapes_count": len(self.get_shapes()) if self.current_page else 0,
            "connector_count": 0,
            "shapes": [],
            "connectors": []
        }
        
        if self.current_page:
            for shape in self.get_shapes():
                # Check if this is a connector
                if self._is_connector(shape):
                    info["connector_count"] += 1
                    connector_info = {
                        "id": shape.ID,
                        "text": shape.text.strip() if shape.text else '',
                        "type": "Connector",
                        "edge_key": get_shape_prop(shape, 'EdgeKey') or '',
                        "from": "Unknown",  # Would need to parse connection info
                        "to": "Unknown"     # Would need to parse connection info
                    }
                    info["connectors"].append(connector_info)
                else:
                    shape_info = {
                        "id": shape.ID,
                        "text": shape.text.strip() if shape.text else '',
                        "type": shape.shape_type,
                        "position": {
                            "x": shape.x,
                            "y": shape.y,
                            "width": shape.width,
                            "height": shape.height
                        }
                    }
                    info["shapes"].append(shape_info)
        
        return info
    
    def ensure_all_shapes_have_keys(self) -> Dict[str, str]:
        """
        Ensure all shapes have NodeKey properties assigned.
        For shapes without keys, generate keys based on their text or ID.
        
        Returns:
            Dict mapping shape IDs to their assigned NodeKeys
        """
        if not self.current_page:
            return {}
        
        assignments = {}
        used_keys = set()
        
        # First pass: collect existing keys
        for shape in self.current_page.child_shapes:
            if not self._is_connector(shape):
                node_key = get_shape_prop(shape, 'NodeKey')
                if node_key:
                    used_keys.add(node_key)
        
        # Second pass: assign keys to shapes without them
        for shape in self.current_page.child_shapes:
            if not self._is_connector(shape):
                shape_id = str(getattr(shape, 'ID', ''))
                existing_key = get_shape_prop(shape, 'NodeKey')
                
                if not existing_key:
                    # Generate a key based on text content or shape ID
                    shape_text = getattr(shape, 'text', '').strip()
                    
                    if shape_text:
                        # Use sanitized text as base for key
                        base_key = shape_text.lower()
                        # Replace spaces and special chars with underscores
                        base_key = ''.join(c if c.isalnum() else '_' for c in base_key)
                        # Remove consecutive underscores
                        base_key = '_'.join(filter(None, base_key.split('_')))
                        # Limit length
                        base_key = base_key[:30] if base_key else f"shape_{shape_id}"
                    else:
                        # No text, use shape ID
                        base_key = f"shape_{shape_id}"
                    
                    # Ensure uniqueness
                    final_key = base_key
                    counter = 1
                    while final_key in used_keys:
                        final_key = f"{base_key}_{counter}"
                        counter += 1
                    
                    # Assign the key
                    set_shape_prop(shape, 'NodeKey', final_key)
                    used_keys.add(final_key)
                    assignments[shape_id] = final_key
                    print(f"Assigned NodeKey '{final_key}' to shape ID {shape_id} (text: '{shape_text[:20]}...')")
        
        return assignments
    
    def validate_edge_integrity(self) -> Tuple[bool, List[str]]:
        """
        Validate edge integrity across the diagram.
        
        Returns:
            Tuple of (is_valid, error_messages)
        """
        return self.edge_manager.validate_edge_integrity()
    
    def optimize_edge_routing(self, avoid_crossings: bool = True) -> Dict[str, int]:
        """
        Optimize edge routing to improve visual clarity.
        
        Args:
            avoid_crossings: Whether to try to minimize edge crossings
            
        Returns:
            Dictionary with optimization statistics
        """
        return self.edge_manager.optimize_edge_routing(avoid_crossings)
    
    def cleanup_edges(self) -> Dict[str, int]:
        """
        Clean up edge issues including orphaned connectors and duplicates.
        
        Returns:
            Dictionary with cleanup statistics
        """
        stats = {
            'orphaned_removed': 0,
            'duplicates_removed': 0,
            'total_cleaned': 0
        }
        
        # First use built-in cleanup
        stats['orphaned_removed'] = self.cleanup_orphaned_connectors()
        
        # Then use edge manager for duplicate resolution
        resolution_stats = self.resolve_connector_ambiguity()
        stats['duplicates_removed'] = resolution_stats.get('removed_duplicates', 0)
        
        stats['total_cleaned'] = stats['orphaned_removed'] + stats['duplicates_removed']
        
        # Rebuild edge inventory after cleanup
        self.edge_manager.build_edge_inventory(force_rebuild=True)
        
        return stats
    
    def get_edge_report(self) -> Dict[str, Any]:
        """
        Generate comprehensive edge analysis report.
        
        Returns:
            Dictionary containing edge statistics and issues
        """
        return self.edge_manager.generate_edge_report()
    
    def save(self, filepath: str, auto_fit: bool = False, validate_compatibility: bool = True):
        """
        Save the Visio file with optional validation and auto-fix for web viewer compatibility
        
        Args:
            filepath: Path to save the file
            auto_fit: If True, automatically adjust page size to fit content before saving (default: False)
            validate_compatibility: If True, validate and fix VSDX structure for web viewer compatibility
        """
        # Validate edges before saving
        is_valid, errors = self.validate_edge_integrity()
        if not is_valid:
            print(f"Warning: {len(errors)} edge integrity issues detected:")
            for error in errors[:5]:  # Show first 5 errors
                print(f"  - {error}")
            if len(errors) > 5:
                print(f"  ... and {len(errors) - 5} more issues")
        if self.visio_file:
            # Auto-fit page to content if enabled
            if auto_fit:
                try:
                    self.auto_fit_page_to_content()
                except Exception as e:
                    print(f"Warning: Auto-fit failed: {e}. Continuing with save...")
            
            # Guard: enforce .vsdx extension
            if not filepath.lower().endswith('.vsdx'):
                raise ValueError("Filepath must end with .vsdx")
            
            # Ensure output directory exists
            output_dir = os.path.dirname(filepath)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
            
            # Save the file - vsdx library handles its own temporary directory
            # CRITICAL: Force save to ensure connectors are persisted
            try:
                # Force refresh all pages to ensure shapes are indexed
                if hasattr(self.visio_file, 'pages'):
                    for page in self.visio_file.pages:
                        try:
                            # Access child_shapes to force rebuild of shape index
                            _ = len(page.child_shapes)
                        except:
                            pass
            except Exception as refresh_error:
                print(f"Warning: Could not refresh pages: {refresh_error}")
            
            self.visio_file.save_vsdx(filepath)
            print(f"Diagram saved to: {filepath}")
            
            # Reload the file to ensure all changes are visible
            try:
                # Reload the file to verify changes
                from vsdx import VisioFile as VerifyVisioFile
                test_load = VerifyVisioFile(filepath)
                test_page = test_load.pages[0] if test_load.pages else None
                if test_page:
                    connector_count = sum(1 for s in test_page.child_shapes if self._is_connector(s))
                    shape_count = sum(1 for s in test_page.child_shapes if not self._is_connector(s))
                    print(f"Verified saved file: {shape_count} shapes, {connector_count} connectors")
                test_load.close_vsdx()
            except Exception as verify_error:
                print(f"Warning: Could not verify saved file: {verify_error}")
            
            # Update current path tracking for stencil importer
            self._current_vsdx_path = os.path.abspath(filepath)
            if self._stencil_importer:
                # Update importer with new path
                self._stencil_importer = StencilImporter(self._current_vsdx_path)
            
            # Validate and fix for web viewer compatibility
            if validate_compatibility:
                self._validate_and_fix_compatibility(filepath)
        else:
            raise ValueError("No Visio file to save")
    
    def _validate_and_fix_compatibility(self, filepath: str):
        """
        Validate VSDX file structure and attempt auto-fix if issues found
        
        Args:
            filepath: Path to saved VSDX file
        """
        try:
            from .vsdx_validator import validate_vsdx_structure, fix_vsdx_with_aspose
            
            # Validate structure
            issues = validate_vsdx_structure(filepath, verbose=False)
            
            # Check for errors
            errors = [issue for issue in issues if issue.severity == "error"]
            warnings = [issue for issue in issues if issue.severity == "warning"]
            
            if errors or warnings:
                print(f"\n[WARN]  VSDX Compatibility Check:")
                
                if errors:
                    print(f"   [ERR] {len(errors)} error(s) detected:")
                    for err in errors[:3]:  # Show first 3 errors
                        print(f"      * {err.message}")
                    if len(errors) > 3:
                        print(f"      ... and {len(errors) - 3} more")
                
                if warnings:
                    print(f"   [WARN]  {len(warnings)} warning(s) detected")
                
                # Attempt auto-fix for errors
                if errors:
                    print(f"   [FIX] Attempting auto-fix with Aspose.Diagram...")
                    if fix_vsdx_with_aspose(filepath):
                        # Re-validate after fix
                        issues_after = validate_vsdx_structure(filepath, verbose=False)
                        errors_after = [issue for issue in issues_after if issue.severity == "error"]
                        
                        if not errors_after:
                            print(f"   [OK] File fixed successfully! Compatible with web viewers.")
                        else:
                            print(f"   [WARN]  Some issues remain. Desktop Visio should work, but web preview may fail.")
                    else:
                        print(f"   [WARN]  Auto-fix unavailable. File may not work in web viewers.")
                        print(f"   [TIP] Tip: Install Aspose.Diagram for auto-fix: pip install aspose-diagram-python")
            else:
                print(f"[OK] VSDX file structure validated - compatible with web viewers")
                
        except ImportError as e:
            # vsdx_validator not available - silently skip validation
            print(f"Note: VSDX validation skipped (vsdx_validator module not found)")
        except Exception as e:
            # Don't fail the save if validation fails
            print(f"Warning: VSDX validation failed: {e}")
    
    def close(self):
        """Close the Visio file"""
        if self.visio_file:
            self.visio_file.close_vsdx()

    def _is_connector(self, shape: Any) -> bool:
        """
        Determine if shape behaves like a connector/line with robust heuristics.
        
        CRITICAL: The order of checks matters! Most reliable indicators first.
        
        Enhanced to also check page XML for Connect entries (for newly created connectors)
        and XForm1D section (connector-specific transform section).
        """
        import xml.etree.ElementTree as ET
        
        # 1. MOST RELIABLE: Negative dimension (primary indicator in vsdx for connectors)
        # This is the KEY indicator - connectors typically have negative width or height
        height = getattr(shape, 'height', None)
        width = getattr(shape, 'width', None)
        
        if height is not None and height < 0:
            return True
        if width is not None and width < 0:
            return True
        
        # 1b. If the shape has a NodeKey property, it's definitely NOT a connector
        from visio_core.utils.shape_identity import get_shape_prop
        if get_shape_prop(shape, 'NodeKey') is not None:
            return False
        
        # 2. NameU attribute -- manually created connectors have NameU="Dynamic connector"
        if hasattr(shape, 'xml') and shape.xml is not None:
            name_u = shape.xml.get('NameU', '')
            if name_u and 'dynamic connector' in name_u.lower():
                return True
        
        # 3. Master name explicitly indicates connector
        master = getattr(shape, 'master', None)
        if master:
            mname = (getattr(master, 'name', '') or '').lower()
            if mname.startswith('动态连接线') or 'dynamic connector' in mname or 'connector' in mname:
                return True
        
        # 4. Shape type contains connector/line keywords
        if hasattr(shape, 'shape_type') and shape.shape_type:
            st = shape.shape_type.lower()
            if 'connector' in st or 'line' in st:
                return True
        
        # 5. CRITICAL FIX: Check for XForm1D section in shape XML (connector-specific)
        # Connectors have XForm1D section with BeginX, BeginY, EndX, EndY
        if hasattr(shape, 'xml') and shape.xml is not None:
            ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
            xform1d = shape.xml.find('.//v:XForm1D', ns)
            if xform1d is None:
                xform1d = shape.xml.find('.//XForm1D')
            if xform1d is not None:
                return True
        
        # 6. CRITICAL FIX: Check page XML Connects element for this shape as FromSheet
        # This catches newly created connectors that haven't been saved/reloaded
        shape_id = str(getattr(shape, 'ID', ''))
        if shape_id and self.current_page:
            try:
                page_xml = getattr(self.current_page, 'xml', None)
                if page_xml is not None:
                    ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
                    connects = page_xml.findall('.//v:Connect', ns)
                    if not connects:
                        connects = page_xml.findall('.//Connect')
                    
                    # If this shape appears as FromSheet with BeginX/EndX, it's a connector
                    for conn in connects:
                        from_sheet = conn.get('FromSheet', '')
                        from_cell = conn.get('FromCell', '')
                        if from_sheet == shape_id:
                            if 'BeginX' in from_cell or 'EndX' in from_cell:
                                return True
            except Exception:
                pass
        
        # 7. Shapes with connects but no master and no/minimal dimensions
        # This catches programmatically created connectors from vsdx.Connect.create()
        if hasattr(shape, 'connects') and shape.connects and len(shape.connects) > 0:
            # Check if it has no master (programmatically created)
            if master is None:
                # Additional validation: should have minimal or no text AND thin (1D) shape
                txt = (getattr(shape, 'text', '') or '').strip()
                if len(txt) <= 3:
                    # Connectors are 1D (height ~ 0); shapes with normal dimensions are NOT connectors
                    if height is not None and height <= 0.05:
                        return True
        
        # 7. Very thin, textless shapes (secondary indicator)
        # Only check this if we haven't already determined it's NOT a connector
        txt = (getattr(shape, 'text', '') or '').strip()
        if txt == '' and width is not None and height is not None:
            thin_threshold = 0.15  # inches
            if (width >= 0 and height >= 0) and (width <= thin_threshold or height <= thin_threshold):
                return True
        
        # 8. LAST RESORT: Check connects property with additional validation
        # NOTE: We check this LAST because normal shapes can also have connection points!
        # Only consider it a connector if it has connects AND no text AND reasonable size
        if hasattr(shape, 'connects') and shape.connects:
            # Additional validation: if it has substantial text or normal dimensions, it's NOT a connector
            if txt:  # Has text - probably not a pure connector
                # Exception: very short text like "是", "否" might be connector labels
                if len(txt) <= 3 and (width is not None and width < 0.5):
                    return True
                return False
            # If it has normal positive dimensions, it's probably a shape, not a connector
            if width is not None and height is not None:
                if width > 0.3 and height > 0.3:  # Normal-sized shape
                    return False
            # If we reach here, it might be a connector
            # But be conservative - return False unless other evidence
            return False
        
        return False

    def _compute_edge_connection(self, from_shape: Any, to_shape: Any) -> Tuple[float, float, float, float]:
        """Compute edge-to-edge connection points between two shapes.
        Falls back to centers if dimensions are unavailable.
        """
        fx = getattr(from_shape, 'x', None)
        fy = getattr(from_shape, 'y', None)
        fw = getattr(from_shape, 'width', None)
        fh = getattr(from_shape, 'height', None)
        tx = getattr(to_shape, 'x', None)
        ty = getattr(to_shape, 'y', None)
        tw = getattr(to_shape, 'width', None)
        th = getattr(to_shape, 'height', None)

        # Fallback to centers
        if None in (fx, fy, fw, fh, tx, ty, tw, th):
            return (
                from_shape.center_x_y[0], from_shape.center_x_y[1],
                to_shape.center_x_y[0], to_shape.center_x_y[1]
            )

        # Determine horizontal vs vertical routing preference
        horizontal = abs((fx or 0) - (tx or 0)) >= abs((fy or 0) - (ty or 0))

        # From edge
        if horizontal:
            start_x = (fx + fw/2) if fx <= tx else (fx - fw/2)
            start_y = fy
            end_x = (tx - tw/2) if fx <= tx else (tx + tw/2)
            end_y = ty
        else:
            start_x = fx
            start_y = (fy - fh/2) if fy >= ty else (fy + fh/2)
            end_x = tx
            end_y = (ty + th/2) if fy >= ty else (ty - th/2)

        return (float(start_x), float(start_y), float(end_x), float(end_y))

    def _normalize_connector_geometry(self, connector: Any, _from_shape: Any, _to_shape: Any) -> None:
        """Force 1-D dynamic connector geometry and valid Sheet.{id}! formulas.

        Master-copied connectors often inherit bad Geometry rows (literal LineTo Y,
        Del=\"1\" rows) and malformed _XFTRIGGER(Sheet49!...) references — those break
        Visio/LibreOffice render and preview.
        """
        if connector is None or not hasattr(connector, 'xml') or connector.xml is None:
            return
        import xml.etree.ElementTree as ET

        P = '{http://schemas.microsoft.com/office/visio/2012/main}'
        root = connector.xml

        for elem in root.iter():
            f = elem.get('F')
            if f and re.search(r'Sheet\d+!', f):
                elem.set('F', re.sub(r'Sheet(\d+)!', r'Sheet.\1!', f))

        for child in list(root):
            tag_local = child.tag.split('}')[-1]
            if tag_local == 'Section' and child.get('N') == 'Geometry':
                root.remove(child)

        for child in list(root):
            tag_local = child.tag.split('}')[-1]
            if tag_local == 'Geom':
                root.remove(child)

        geom = ET.SubElement(root, f'{P}Section', {'N': 'Geometry', 'IX': '0'})
        ET.SubElement(geom, f'{P}Cell', {'N': 'NoFill', 'V': '1'})
        move = ET.SubElement(geom, f'{P}Row', {'T': 'MoveTo', 'IX': '1'})
        ET.SubElement(move, f'{P}Cell', {'N': 'X', 'V': '0', 'F': 'Width*0'})
        ET.SubElement(move, f'{P}Cell', {'N': 'Y', 'V': '0', 'F': 'Height*0.5'})
        line = ET.SubElement(geom, f'{P}Row', {'T': 'LineTo', 'IX': '2'})
        ET.SubElement(line, f'{P}Cell', {'N': 'X', 'V': '0', 'F': 'Width*1'})
        ET.SubElement(line, f'{P}Cell', {'N': 'Y', 'V': '0', 'F': 'Height*0.5'})

        xform_cells = (
            ('PinX', '(BeginX+EndX)*0.5'),
            ('PinY', '(BeginY+EndY)*0.5'),
            ('Width', 'GUARD(SQRT((EndX-BeginX)^2+(EndY-BeginY)^2))'),
            ('Height', 'GUARD(0)'),
            ('LocPinX', 'Width*0.5'),
            ('LocPinY', 'Height*0.5'),
            ('Angle', 'ATAN2(EndY-BeginY,EndX-BeginX)'),
        )
        for cell_name, formula in xform_cells:
            for elem in list(root):
                if elem.tag == f'{P}Cell' and elem.get('N') == cell_name:
                    elem.set('F', formula)
                    break

    def _get_connection_point(self, shape: Any, from_position: Optional[Tuple[float, float]] = None) -> int:
        """
        Get the best connection point index for a shape based on relative position.
        
        Args:
            shape: Shape object to find connection point on
            from_position: Optional (x, y) tuple of the connecting shape's position
        
        Returns:
            Connection point index (0 for center/auto, or specific point index)
        """
        # Connection point index 0 typically represents dynamic/center connection
        # which allows Visio to auto-select the best edge based on routing
        # For now, we'll use 0 (center/auto) which works well with auto-routing
        return 0

    def _get_shape_bbox(self, shape: Any) -> Optional[Tuple[float, float, float, float]]:
        """Return bounding box (left, right, top, bottom) in inches for a shape based on PinX/PinY and Width/Height."""
        try:
            # Try cell values first (PinX/PinY refer to center)
            cx = None
            cy = None
            if hasattr(shape, 'cell_value'):
                try:
                    cx = float(shape.cell_value('PinX') or getattr(shape, 'x', None) or 0)
                except Exception:
                    cx = getattr(shape, 'x', None)
                try:
                    cy = float(shape.cell_value('PinY') or getattr(shape, 'y', None) or 0)
                except Exception:
                    cy = getattr(shape, 'y', None)
            else:
                cx = getattr(shape, 'x', None)
                cy = getattr(shape, 'y', None)

            w = None
            h = None
            try:
                w = float(shape.cell_value('Width') or getattr(shape, 'width', None) or 0)
            except Exception:
                w = getattr(shape, 'width', None) or 0
            try:
                h = float(shape.cell_value('Height') or getattr(shape, 'height', None) or 0)
            except Exception:
                h = getattr(shape, 'height', None) or 0

            if cx is None or cy is None:
                return None

            left = cx - (w / 2)
            right = cx + (w / 2)
            # For consistency use top as larger Y and bottom as smaller Y
            top = cy + (h / 2)
            bottom = cy - (h / 2)

            return (left, right, top, bottom)
        except Exception:
            return None

    def _rects_overlap(self, bbox1: Tuple[float, float, float, float], bbox2: Tuple[float, float, float, float], min_spacing: float = MIN_SHAPE_SPACING_IN) -> bool:
        """Return True if two bboxes overlap or are closer than min_spacing."""
        l1, r1, t1, b1 = bbox1
        l2, r2, t2, b2 = bbox2

        # Expand boxes by min_spacing/2 on all sides
        pad = min_spacing / 2.0
        l1p, r1p, t1p, b1p = l1 - pad, r1 + pad, t1 + pad, b1 - pad
        l2p, r2p, t2p, b2p = l2 - pad, r2 + pad, t2 + pad, b2 - pad

        horiz_overlap = not (r1p <= l2p or r2p <= l1p)
        vert_overlap = not (b1p >= t2p or b2p >= t1p)

        return horiz_overlap and vert_overlap

    def _find_free_spot(self, x: float, y: float, width: float, height: float, max_radius: float = 6.0) -> Tuple[float, float]:
        """Find nearby grid-aligned free spot that doesn't overlap existing shapes.

        Enhanced algorithm with smarter positioning:
        1. First tries the exact requested position
        2. Then tries positions along horizontal/vertical axes (better for flowcharts)
        3. Finally falls back to spiral search if needed
        4. Considers connector paths to avoid crossings
        """
        grid = GRID_SPACING_IN
        # Candidate origin is center coordinates
        base_x = snap_to_grid(x, grid)
        base_y = snap_to_grid(y, grid)
        
        # Ensure we use proper spacing
        min_spacing = max(MIN_SHAPE_SPACING_IN, grid * 2)  # At least 2 grid units

        # Build bbox for candidate with proper margins
        def candidate_bbox(cx, cy):
            # Snap dimensions to grid as well for consistency
            snapped_width = snap_to_grid(width, grid)
            snapped_height = snap_to_grid(height, grid)
            left = cx - snapped_width / 2.0
            right = cx + snapped_width / 2.0
            top = cy + snapped_height / 2.0
            bottom = cy - snapped_height / 2.0
            return (left, right, top, bottom)

        # Precompute existing shape bboxes and connector paths
        existing_bboxes = []
        connector_paths = []
        
        for s in self._iter_shapes(self.current_page.child_shapes):
            try:
                if self._is_connector(s):
                    # Store connector path for crossing detection
                    conn_bbox = self._get_shape_bbox(s)
                    if conn_bbox:
                        connector_paths.append(conn_bbox)
                else:
                    # Store shape bbox
                    b = self._get_shape_bbox(s)
                    if b:
                        existing_bboxes.append(b)
            except Exception:
                continue
        
        # Helper to check if position is valid
        def is_position_valid(cx, cy, check_connectors=True):
            cb = candidate_bbox(cx, cy)
            # Check shape overlaps with proper spacing
            for eb in existing_bboxes:
                if self._rects_overlap(cb, eb, min_spacing=min_spacing):
                    return False
            # Check connector crossings if enabled
            if check_connectors:
                for conn_bbox in connector_paths:
                    # Check if new shape would overlap with connector path
                    if self._rects_overlap(cb, conn_bbox, min_spacing=grid):
                        return False
            return True
        
        # 1. First try the exact requested position
        if is_position_valid(base_x, base_y):
            return (base_x, base_y)
        
        # 2. Try positions along axes (better for maintaining alignment)
        axis_offsets = []
        for i in range(1, int(max_radius / grid) + 1):
            offset = i * grid
            # Try horizontal positions first (left/right)
            axis_offsets.extend([
                (offset, 0),   # Right
                (-offset, 0),  # Left
                (0, offset),   # Up
                (0, -offset)   # Down
            ])
        
        for dx_grid, dy_grid in axis_offsets:
            cx = base_x + dx_grid
            cy = base_y + dy_grid
            cx, cy = validate_position(cx, cy)
            if is_position_valid(cx, cy):
                return (cx, cy)
        
        # 3. Try diagonal positions (for better space utilization)
        diagonal_offsets = []
        for i in range(1, int(max_radius / grid) + 1):
            offset = i * grid
            diagonal_offsets.extend([
                (offset, offset),    # Top-right
                (-offset, offset),   # Top-left
                (offset, -offset),   # Bottom-right
                (-offset, -offset)   # Bottom-left
            ])
        
        for dx_grid, dy_grid in diagonal_offsets:
            cx = base_x + dx_grid
            cy = base_y + dy_grid
            cx, cy = validate_position(cx, cy)
            if is_position_valid(cx, cy):
                return (cx, cy)

        # 4. Full spiral search as last resort
        max_steps = int(max_radius / grid)
        for ring in range(1, max_steps + 1):
            step = ring
            for dx in range(-step, step + 1):
                for dy in range(-step, step + 1):
                    # only perimeter points
                    if not (abs(dx) == step or abs(dy) == step):
                        continue
                    cx = base_x + dx * grid
                    cy = base_y + dy * grid
                    cx, cy = validate_position(cx, cy)
                    # Try with relaxed connector checking
                    if is_position_valid(cx, cy, check_connectors=False):
                        return (cx, cy)

        # If nothing found, return original (snapped) - but warn
        print(f"Warning: No free spot found near ({x:.2f}, {y:.2f}), using original position")
        return (base_x, base_y)

    def _reroute_connectors_near_shape(self, shape: Any, expand: float = MIN_SHAPE_SPACING_IN) -> None:
        """Reroute connectors whose geometry intersects an expanded bbox around shape.
        
        Enhanced to:
        1. Better detect connector-shape intersections
        2. Apply appropriate routing styles based on connector direction
        3. Handle multiple connectors more intelligently
        """
        try:
            sb = self._get_shape_bbox(shape)
            if not sb:
                return
            
            # Expand bbox with proper spacing
            left, right, top, bottom = sb
            # Use a more conservative expansion to avoid over-aggressive rerouting
            safe_expand = min(expand, GRID_SPACING_IN * 2)
            left -= safe_expand
            right += safe_expand
            top += safe_expand
            bottom -= safe_expand
            expanded_bbox = (left, right, top, bottom)

            # Collect connectors that need rerouting
            connectors_to_reroute = []
            
            for s in self._iter_shapes(self.current_page.child_shapes):
                try:
                    if not self._is_connector(s):
                        continue
                    
                    # Get connector endpoints if available
                    conn_id = str(getattr(s, 'ID', None))
                    if not conn_id:
                        continue
                        
                    # Check if connector path intersects with shape
                    cb = self._get_shape_bbox(s)
                    if not cb:
                        continue
                    
                    # Check for intersection with expanded shape bbox
                    if self._rects_overlap(expanded_bbox, cb, min_spacing=0.0):
                        # Determine connector orientation for better routing
                        cl, cr, ct, cb_bottom = cb
                        is_horizontal = (cr - cl) > (ct - cb_bottom)
                        
                        connectors_to_reroute.append({
                            'id': conn_id,
                            'shape': s,
                            'is_horizontal': is_horizontal,
                            'bbox': cb
                        })
                except Exception:
                    continue
            
            # Apply routing to affected connectors
            for conn_info in connectors_to_reroute:
                try:
                    # Use orthogonal routing for professional appearance
                    self.apply_orthogonal_routing(conn_info['id'])
                    
                    # For very short connectors, try straight routing instead
                    conn_bbox = conn_info['bbox']
                    conn_length = max(
                        abs(conn_bbox[1] - conn_bbox[0]),  # width
                        abs(conn_bbox[2] - conn_bbox[3])   # height
                    )
                    
                    if conn_length < GRID_SPACING_IN * 2:
                        # Short connectors often look better as straight lines
                        self.auto_route_connector(conn_info['id'], 'straight')
                        
                except Exception:
                    # Best-effort: ignore routing failures
                    continue
                    
        except Exception:
            # Fail silently to not interrupt shape addition
            return
    
    def _verify_connector_glue(self, connector: Any, from_shape: Any, to_shape: Any) -> bool:
        """
        Verify that glue connections are actually established in the connector XML.
        
        Args:
            connector: Connector shape object
            from_shape: Source shape object  
            to_shape: Target shape object
        
        Returns:
            True if glue formulas are present and valid
        """
        try:
            if not hasattr(connector, 'xml') or connector.xml is None:
                return False
            
            import xml.etree.ElementTree as ET
            ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
            
            from_id = str(getattr(from_shape, 'ID', None))
            to_id = str(getattr(to_shape, 'ID', None))
            
            if not from_id or not to_id:
                return False
            
            # Check BeginX has glue formula pointing to from_shape
            begin_x_cell = connector.xml.find('.//v:Cell[@N="BeginX"]', ns)
            if begin_x_cell is None:
                begin_x_cell = connector.xml.find('.//Cell[@N="BeginX"]')
            
            if begin_x_cell is None or not begin_x_cell.get('F'):
                # Check if it has a fixed coordinate value instead (fallback connection)
                if begin_x_cell and begin_x_cell.get('V'):
                    print(f"Info: BeginX uses coordinate-based connection instead of glue formula")
                else:
                    print(f"Verification failed: BeginX cell missing or has no formula/value")
                    return False
            
            begin_formula = begin_x_cell.get('F', '')
            # vsdx uses Sheet{id}! format (no dot), but some masters use Sheet.{id}!
            if begin_formula and f'Sheet{from_id}!' not in begin_formula and f'Sheet.{from_id}!' not in begin_formula:
                # Check if it has a fixed coordinate value instead (fallback connection)
                begin_value = begin_x_cell.get('V')
                if begin_value:
                    print(f"Info: BeginX uses coordinate-based connection (V='{begin_value}') instead of glue formula")
                else:
                    print(f"Verification failed: BeginX formula '{begin_formula}' doesn't reference from_shape {from_id}")
                    return False
            
            # Check EndX has glue formula pointing to to_shape
            end_x_cell = connector.xml.find('.//v:Cell[@N="EndX"]', ns)
            if end_x_cell is None:
                end_x_cell = connector.xml.find('.//Cell[@N="EndX"]')
            
            if end_x_cell is None or not end_x_cell.get('F'):
                # Check for coordinate-based connection
                if end_x_cell and end_x_cell.get('V'):
                    print(f"Info: EndX uses coordinate-based connection instead of glue formula")
                    return True  # Accept coordinate-based connections as valid
                else:
                    print(f"Verification failed: EndX cell missing or has no formula/value")
                    return False
            
            end_formula = end_x_cell.get('F', '')
            # vsdx uses Sheet{id}! format (no dot), but some masters use Sheet.{id}!
            if end_formula and f'Sheet{to_id}!' not in end_formula and f'Sheet.{to_id}!' not in end_formula:
                # Check if it has a fixed coordinate value instead (fallback connection)
                end_value = end_x_cell.get('V')
                if end_value:
                    print(f"Info: EndX uses coordinate-based connection (V='{end_value}') instead of glue formula")
                    return True  # Accept coordinate-based connections as valid
                else:
                    print(f"Verification failed: EndX formula '{end_formula}' doesn't reference to_shape {to_id}")
                    return False
            
            return True
            
        except Exception as e:
            print(f"Error verifying connector glue: {e}")
            return False

    def verify_connector_visibility(self, connector: Any) -> Dict[str, Any]:
        """
        Comprehensive check for connector visibility issues.
        
        This method checks all aspects that affect whether a connector will be
        visible when the diagram is opened in Visio:
        1. Line properties (weight, color, pattern)
        2. Geometry section (NoLine, NoShow flags)
        3. Endpoint coordinates (BeginX/Y, EndX/Y)
        4. Connects table entries
        
        Args:
            connector: Connector shape object
        
        Returns:
            Dictionary with visibility status and any issues found
        """
        result = {
            'visible': True,
            'issues': [],
            'warnings': [],
            'details': {}
        }
        
        try:
            if not hasattr(connector, 'xml') or connector.xml is None:
                result['visible'] = False
                result['issues'].append("Connector has no XML element")
                return result
            
            import xml.etree.ElementTree as ET
            ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
            
            def get_cell_value(cell_name: str) -> Optional[str]:
                cell = connector.xml.find(f'.//v:Cell[@N="{cell_name}"]', ns)
                if cell is None:
                    cell = connector.xml.find(f'.//Cell[@N="{cell_name}"]')
                return cell.get('V') if cell is not None else None
            
            # Check line properties
            line_weight = get_cell_value('LineWeight')
            line_color = get_cell_value('LineColor')
            line_pattern = get_cell_value('LinePattern')
            transparency = get_cell_value('Transparency') or get_cell_value('LineColorTrans')
            
            result['details']['line_weight'] = line_weight
            result['details']['line_color'] = line_color
            result['details']['line_pattern'] = line_pattern
            result['details']['transparency'] = transparency
            
            if line_pattern == '0':
                result['visible'] = False
                result['issues'].append("LinePattern is 0 (no line)")
            
            if transparency and float(transparency) >= 1.0:
                result['visible'] = False
                result['issues'].append("Connector is fully transparent")
            
            if not line_weight or float(line_weight or 0) <= 0:
                result['warnings'].append("LineWeight is zero or missing")
            
            # Check geometry section
            geom_section = connector.xml.find('.//v:Section[@N="Geometry"]', ns)
            if geom_section is None:
                geom_section = connector.xml.find('.//Section[@N="Geometry"]')
            
            if geom_section is not None:
                no_line = geom_section.find('.//v:Cell[@N="NoLine"]', ns)
                if no_line is None:
                    no_line = geom_section.find('.//Cell[@N="NoLine"]')
                
                no_show = geom_section.find('.//v:Cell[@N="NoShow"]', ns)
                if no_show is None:
                    no_show = geom_section.find('.//Cell[@N="NoShow"]')
                
                if no_line is not None and no_line.get('V') == '1':
                    result['visible'] = False
                    result['issues'].append("Geometry NoLine flag is set")
                
                if no_show is not None and no_show.get('V') == '1':
                    result['visible'] = False
                    result['issues'].append("Geometry NoShow flag is set")
            else:
                result['warnings'].append("No Geometry section found")
            
            # Check endpoint coordinates
            begin_x = get_cell_value('BeginX')
            begin_y = get_cell_value('BeginY')
            end_x = get_cell_value('EndX')
            end_y = get_cell_value('EndY')
            
            result['details']['begin'] = (begin_x, begin_y)
            result['details']['end'] = (end_x, end_y)
            
            if begin_x and end_x and begin_y and end_y:
                try:
                    dx = float(end_x) - float(begin_x)
                    dy = float(end_y) - float(begin_y)
                    length = (dx**2 + dy**2)**0.5
                    result['details']['length'] = length
                    
                    if length < 0.01:
                        result['warnings'].append(f"Connector length is very small ({length:.4f})")
                except ValueError:
                    result['warnings'].append("Could not calculate connector length")
            else:
                result['warnings'].append("Missing endpoint coordinates")
            
            # Check for Connects table entries
            connector_id = str(getattr(connector, 'ID', ''))
            if self.current_page and connector_id:
                page_root = self.current_page.xml if hasattr(self.current_page.xml, 'tag') else self.current_page.xml.getroot()
                connects_elem = page_root.find(f'{{{ns["v"]}}}Connects')
                if connects_elem is None:
                    connects_elem = page_root.find('Connects')
                
                if connects_elem is not None:
                    connect_count = 0
                    for connect in connects_elem:
                        if connect.get('FromSheet') == connector_id:
                            connect_count += 1
                    
                    result['details']['connect_entries'] = connect_count
                    
                    if connect_count < 4:
                        result['warnings'].append(f"Only {connect_count} Connect entries (expected 4)")
                else:
                    result['warnings'].append("No Connects element in page")
            
            # Summary
            if result['visible']:
                if result['warnings']:
                    print(f"[WARN]  Connector {connector_id} is visible but has warnings: {result['warnings']}")
                else:
                    print(f"[OK] Connector {connector_id} visibility check passed")
            else:
                print(f"[ERR] Connector {connector_id} visibility issues: {result['issues']}")
            
        except Exception as e:
            result['visible'] = False
            result['issues'].append(f"Error during visibility check: {e}")
        
        return result
    
    def _set_connector_glue(self, connector: Any, from_shape: Any, to_shape: Any, 
                           from_glue_point: Optional[str] = None, 
                           to_glue_point: Optional[str] = None) -> bool:
        """
        Set proper Visio glue connection formulas for a connector using shape ID references
        with optional precise connection points.
        
        This creates proper glued connections that stay attached when shapes are moved.
        
        VISIBILITY FIX: Now uses edge-based formulas instead of just PinX/PinY.
        This ensures connectors visually connect to shape edges, not centers.
        
        Args:
            connector: Connector shape object
            from_shape: Source shape object
            to_shape: Target shape object
            from_glue_point: Optional connection point on source shape (e.g., 'Right', 'Top', 'Bottom')
            to_glue_point: Optional connection point on target shape (e.g., 'Left', 'Bottom', 'Top')
        
        Returns:
            True if successful
        """
        try:
            # Get shape IDs
            from_id = getattr(from_shape, 'ID', None)
            to_id = getattr(to_shape, 'ID', None)
            
            if from_id is None or to_id is None:
                print(f"Error: Cannot get shape IDs for glue connection")
                return False
            
            # Import connection point utilities for edge coordinate calculation
            from .connection_points import (
                get_connection_formula, 
                GluePointPosition,
                calculate_edge_coordinates_from_string
            )
            
            # Get glue formulas based on edge positions
            # This is the KEY fix for visibility - use edge formulas, not just PinX/PinY
            if from_glue_point:
                from_pos = GluePointPosition.from_string(from_glue_point)
                begin_x_formula, begin_y_formula = get_connection_formula(str(from_id), from_pos)
                print(f"Using edge connection: from={from_glue_point} -> formulas: X={begin_x_formula}, Y={begin_y_formula}")
            else:
                begin_x_formula = f"Sheet.{from_id}!PinX"
                begin_y_formula = f"Sheet.{from_id}!PinY"
                print(f"Using center connection for source shape")
            
            if to_glue_point:
                to_pos = GluePointPosition.from_string(to_glue_point)
                end_x_formula, end_y_formula = get_connection_formula(str(to_id), to_pos)
                print(f"Using edge connection: to={to_glue_point} -> formulas: X={end_x_formula}, Y={end_y_formula}")
            else:
                end_x_formula = f"Sheet.{to_id}!PinX"
                end_y_formula = f"Sheet.{to_id}!PinY"
                print(f"Using center connection for target shape")
            
            # Calculate actual edge coordinates for the V (value) attributes
            from_x, from_y = calculate_edge_coordinates_from_string(from_shape, from_glue_point)
            to_x, to_y = calculate_edge_coordinates_from_string(to_shape, to_glue_point)
            
            # For connection point tracking (used in Connects table)
            # Convert string glue point names to Visio connection point indices
            # Top->0, Bottom->1, Left->2, Right->3. _update_connector_connects expects Optional[int].
            _glue_to_cp_index = {'top': 0, 'bottom': 1, 'left': 2, 'right': 3}
            from_cp_normalized = _glue_to_cp_index.get(from_glue_point.lower()) if isinstance(from_glue_point, str) else from_glue_point
            to_cp_normalized = _glue_to_cp_index.get(to_glue_point.lower()) if isinstance(to_glue_point, str) else to_glue_point
            
            # Use direct XML manipulation to set formulas (not values)
            # Note: set_cell_value sets values (V attribute), not formulas (F attribute)
            if hasattr(connector, 'xml') and connector.xml is not None:
                import xml.etree.ElementTree as ET
                
                # Find the Cell elements and update their formulas
                ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
                
                # Helper function to find and update cell
                # CRITICAL: Visio requires BOTH V (value) AND F (formula) attributes
                # The V attribute provides the current calculated value
                # The F attribute tells Visio how to recalculate when shapes move
                def update_cell(cell_name: str, formula: str, value: str):
                    # Try with namespace
                    cell = connector.xml.find(f'.//v:Cell[@N="{cell_name}"]', ns)
                    if cell is None:
                        # Try without namespace
                        cell = connector.xml.find(f'.//Cell[@N="{cell_name}"]')
                    
                    if cell is not None:
                        # Set formula attribute
                        cell.set('F', formula)
                        # CRITICAL FIX: Always set the V attribute - Visio needs both!
                        # Use the actual edge coordinate value for proper initial rendering
                        cell.set('V', value)
                        return True
                    else:
                        # Create the cell if it doesn't exist
                        cell_elem = ET.SubElement(connector.xml, '{http://schemas.microsoft.com/office/visio/2012/main}Cell')
                        cell_elem.set('N', cell_name)
                        cell_elem.set('V', value)  # Set value first
                        cell_elem.set('F', formula)  # Then formula
                        return True
                    return False
                
                # CRITICAL FIX: Use actual edge coordinates, not just PinX/PinY
                # This is essential for connector visibility - connectors must start/end
                # at the actual edge positions, not shape centers
                from_edge_x, from_edge_y = calculate_edge_coordinates_from_string(from_shape, from_glue_point)
                to_edge_x, to_edge_y = calculate_edge_coordinates_from_string(to_shape, to_glue_point)
                
                # Convert to strings for XML
                from_x_str = str(from_edge_x)
                from_y_str = str(from_edge_y)
                to_x_str = str(to_edge_x)
                to_y_str = str(to_edge_y)
                
                print(f"Setting connector endpoints: ({from_edge_x:.3f},{from_edge_y:.3f}) -> ({to_edge_x:.3f},{to_edge_y:.3f})")
                
                success = True
                success &= update_cell('BeginX', begin_x_formula, from_x_str)
                success &= update_cell('BeginY', begin_y_formula, from_y_str)
                success &= update_cell('EndX', end_x_formula, to_x_str)
                success &= update_cell('EndY', end_y_formula, to_y_str)
                
                if success:
                    # Update connector geometry to match new endpoints
                    try:
                        self._update_connector_geometry(connector, from_edge_x, from_edge_y, to_edge_x, to_edge_y)
                    except Exception as geom_error:
                        print(f"Warning: Failed to update connector geometry: {geom_error}")
                    
                    # Synchronize Connects table so the connector appears in Visio UI
                    try:
                        self._update_connector_connects(
                            connector,
                            from_shape,
                            to_shape,
                            from_cp_normalized,
                            to_cp_normalized
                        )
                    except Exception as sync_error:
                        print(f"Warning: Failed to update connector Connects entries: {sync_error}")
                    return True
                else:
                    print(f"Warning: Could not find all connector endpoint cells in XML")
                    # Fallback - try using set_start_and_finish as last resort
                    print(f"Warning: Falling back to coordinate-based connection")
                    sx, sy, tx, ty = self._compute_edge_connection(from_shape, to_shape)
                    if hasattr(connector, 'set_start_and_finish'):
                        connector.set_start_and_finish((sx, sy), (tx, ty))
                        try:
                            self._update_connector_connects(connector, from_shape, to_shape, None, None)
                        except Exception as sync_error:
                            print(f"Warning: Failed to sync Connects for fallback connection: {sync_error}")
                        return True
                
        except Exception as e:
            print(f"Error setting connector glue: {e}")
            import traceback
            traceback.print_exc()
        
        return False

    def _update_connector_geometry(self, connector: Any, from_x: float, from_y: float, 
                                   to_x: float, to_y: float) -> bool:
        """
        Update connector geometry cells to match the endpoint coordinates.
        
        This ensures the connector's visual geometry (PinX, PinY, Width, Angle, etc.)
        matches its endpoint positions for proper rendering.
        
        Args:
            connector: Connector shape object
            from_x, from_y: Start point coordinates
            to_x, to_y: End point coordinates
        
        Returns:
            True if successful
        """
        try:
            import math
            import xml.etree.ElementTree as ET
            
            # Calculate geometry values
            dx = to_x - from_x
            dy = to_y - from_y
            length = math.sqrt(dx**2 + dy**2)
            pin_x = (from_x + to_x) / 2
            pin_y = (from_y + to_y) / 2
            angle = math.atan2(dy, dx)
            
            # Ensure minimum length
            if length < 0.01:
                length = 0.01
            
            if hasattr(connector, 'xml') and connector.xml is not None:
                ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
                
                def update_cell_value(cell_name: str, value: str, formula: str = None):
                    cell = connector.xml.find(f'.//v:Cell[@N="{cell_name}"]', ns)
                    if cell is None:
                        cell = connector.xml.find(f'.//Cell[@N="{cell_name}"]')
                    if cell is not None:
                        cell.set('V', value)
                        if formula:
                            cell.set('F', formula)
                        return True
                    return False
                
                # Update geometry cells
                update_cell_value('PinX', str(pin_x), '(BeginX+EndX)/2')
                update_cell_value('PinY', str(pin_y), '(BeginY+EndY)/2')
                update_cell_value('Width', str(length), 'GUARD(SQRT((EndX-BeginX)^2+(EndY-BeginY)^2))')
                update_cell_value('Height', '0', 'GUARD(0)')
                update_cell_value('LocPinX', str(length/2), 'Width*0.5')
                update_cell_value('LocPinY', '0', 'Height*0.5')
                update_cell_value('Angle', str(angle), 'ATAN2(EndY-BeginY,EndX-BeginX)')
                
                # Update geometry section if present
                geom_section = connector.xml.find('.//v:Section[@N="Geometry"]', ns)
                if geom_section is None:
                    geom_section = connector.xml.find('.//Section[@N="Geometry"]')
                
                if geom_section is not None:
                    # Update LineTo row X value
                    for row in geom_section.findall('.//v:Row[@T="LineTo"]', ns) or geom_section.findall('.//Row[@T="LineTo"]'):
                        x_cell = row.find('.//v:Cell[@N="X"]', ns)
                        if x_cell is None:
                            x_cell = row.find('.//Cell[@N="X"]')
                        if x_cell is not None:
                            x_cell.set('V', str(length))
                            x_cell.set('F', 'Width*1')
                
                print(f"  Updated connector geometry: length={length:.3f}, angle={math.degrees(angle):.1f}deg")
                return True
                
        except Exception as e:
            print(f"Warning: Failed to update connector geometry: {e}")
        
        return False

    def _update_connector_connects(self, connector: Any, from_shape: Any, to_shape: Any,
                                   from_cp: Optional[int], to_cp: Optional[int]) -> None:
        """
        Ensure the page-level Connects table reflects the connector's current endpoints.
        
        Without proper Connect records, Visio may omit connectors when rendering the UI even
        though the shape XML exists. This method removes stale entries for the connector and
        writes fresh ones that point to the correct source/target shapes.
        """
        if not self.current_page:
            return
        
        connector_id = str(getattr(connector, 'ID', ''))
        from_id = str(getattr(from_shape, 'ID', ''))
        to_id = str(getattr(to_shape, 'ID', ''))
        
        if not connector_id or not from_id or not to_id:
            return
        
        try:
            import xml.etree.ElementTree as ET
            
            ns_uri = 'http://schemas.microsoft.com/office/visio/2012/main'
            ns = f'{{{ns_uri}}}'
            
            # Find Connects element - check both at root and in page
            page_root = self.current_page.xml if hasattr(self.current_page.xml, 'tag') else self.current_page.xml.getroot()
            connects_elem = page_root.find(f'{ns}Connects')
            if connects_elem is None:
                # Try without namespace
                connects_elem = page_root.find('Connects')
            if connects_elem is None:
                # Create new Connects element with proper namespace
                connects_elem = ET.SubElement(page_root, f'{ns}Connects')
            
            # Remove existing connections for this connector to avoid duplicates/stale references
            # Check both with and without namespace
            for connect_elem in list(connects_elem.findall(f'{ns}Connect')):
                if connect_elem.attrib.get('FromSheet') == connector_id:
                    connects_elem.remove(connect_elem)
            for connect_elem in list(connects_elem.findall('Connect')):
                if connect_elem.attrib.get('FromSheet') == connector_id:
                    connects_elem.remove(connect_elem)
            
            print(f"Adding Connects entries for connector {connector_id}: Begin to shape {from_id}, End to shape {to_id}")
            
            # Normalize connection indices: 0/None mean auto pin reference
            from_cp_normalized = from_cp if from_cp not in (None, 0) else None
            to_cp_normalized = to_cp if to_cp not in (None, 0) else None
            
            def _connection_cell(cp_index: Optional[int]) -> str:
                if cp_index is None:
                    return 'PinX'
                return f'Connections.X{cp_index}'
            
            def _to_part(cp_index: Optional[int]) -> str:
                # 3 represents the entire shape (default). Use 0 when referencing a specific connection row.
                return '0' if cp_index is not None else '3'
            
            # Create Begin (source) connection entries - both X and Y coordinates
            # BeginX connection
            begin_x_elem = ET.SubElement(connects_elem, f'{ns}Connect')
            begin_x_elem.set('FromSheet', connector_id)
            begin_x_elem.set('FromCell', 'BeginX')
            begin_x_elem.set('FromPart', '9')   # 9 == Begin handle
            begin_x_elem.set('ToSheet', from_id)
            begin_x_elem.set('ToCell', _connection_cell(from_cp_normalized))
            begin_x_elem.set('ToPart', _to_part(from_cp_normalized))
            
            # BeginY connection
            begin_y_elem = ET.SubElement(connects_elem, f'{ns}Connect')
            begin_y_elem.set('FromSheet', connector_id)
            begin_y_elem.set('FromCell', 'BeginY')
            begin_y_elem.set('FromPart', '9')   # 9 == Begin handle
            begin_y_elem.set('ToSheet', from_id)
            # Convert X cell to Y cell for proper coordinate reference
            to_cell_y = _connection_cell(from_cp_normalized).replace('.X', '.Y') if from_cp_normalized is not None else 'PinY'
            begin_y_elem.set('ToCell', to_cell_y)
            begin_y_elem.set('ToPart', _to_part(from_cp_normalized))
            
            # Create End (target) connection entries - both X and Y coordinates
            # EndX connection
            end_x_elem = ET.SubElement(connects_elem, f'{ns}Connect')
            end_x_elem.set('FromSheet', connector_id)
            end_x_elem.set('FromCell', 'EndX')
            end_x_elem.set('FromPart', '12')   # 12 == End handle
            end_x_elem.set('ToSheet', to_id)
            end_x_elem.set('ToCell', _connection_cell(to_cp_normalized))
            end_x_elem.set('ToPart', _to_part(to_cp_normalized))
            
            # EndY connection
            end_y_elem = ET.SubElement(connects_elem, f'{ns}Connect')
            end_y_elem.set('FromSheet', connector_id)
            end_y_elem.set('FromCell', 'EndY')
            end_y_elem.set('FromPart', '12')   # 12 == End handle
            end_y_elem.set('ToSheet', to_id)
            # Convert X cell to Y cell for proper coordinate reference
            to_cell_y = _connection_cell(to_cp_normalized).replace('.X', '.Y') if to_cp_normalized is not None else 'PinY'
            end_y_elem.set('ToCell', to_cell_y)
            end_y_elem.set('ToPart', _to_part(to_cp_normalized))
        
        except Exception as e:
            print(f"Warning: Could not update Connects for connector {connector_id}: {e}")

    def _is_guide(self, shape: Any) -> bool:
        """Identify guide/helper shapes that shouldn't be cloned."""
        if hasattr(shape, 'shape_type') and shape.shape_type:
            st = shape.shape_type.lower()
            if 'guide' in st or 'callout' in st:
                return True
        return False

    def _get_master_key(self, shape: Any) -> str:
        """Create a key representing a shape's master/style for matching."""
        master = getattr(shape, 'master', None)
        if master and getattr(master, 'name', None):
            return master.name
        shape_type = getattr(shape, 'shape_type', '') or 'unknown'
        fill = getattr(shape, 'fill_color', '') or ''
        line = getattr(shape, 'line_color', '') or ''
        return f"{shape_type}|{fill}|{line}"

    def _select_shape_templates(self, requested_type: str, catalog: Dict[str, List[Any]]) -> List[Any]:
        """
        Return ranked list of candidate shapes to copy for requested_type.
        
        Enhanced algorithm that uses multiple signals when master/type info is missing:
        1. Master name & shape type (most reliable when present)
        2. Geometry analysis (width/height ratio, dimensions)
        3. Text content hints (secondary, helps identify purpose)
        4. Visual characteristics
        
        This handles templates where shapes lack proper master information.
        """
        if not catalog:
            return []

        # Normalize the requested type for better matching
        normalized_type = normalize_shape_type(requested_type)
        type_lower = normalized_type.lower()
        ranked: List[Tuple[int, Any]] = []

        # Collect all shapes from catalog
        for shapes in catalog.values():
            for shape in shapes:
                score = 0
                
                # Get shape properties
                master = getattr(shape, 'master', None)
                master_name = (getattr(master, 'name', '') or '').lower() if master else ''
                shape_type = (getattr(shape, 'shape_type', '') or '').lower()
                text = (getattr(shape, 'text', '') or '').strip()
                width = float(getattr(shape, 'width', 0) or 0)
                height = float(getattr(shape, 'height', 0) or 0)
                
                # Priority 1: Master name matching (most reliable when available)
                if master_name and master_name != 'no master':
                    if master_name == type_lower:
                        score += 100  # Perfect master match
                    elif type_lower in master_name:
                        score += 50   # Partial master match
                    elif master_name in type_lower:
                        score += 40   # Reverse partial match
                
                # Priority 2: Shape type matching
                if shape_type and shape_type != 'shape':
                    if shape_type == type_lower:
                        score += 30   # Exact type match
                    elif type_lower in shape_type:
                        score += 15   # Partial type match
                
                # Priority 3: Geometry-based matching (critical for templates without master info)
                if width > 0 and height > 0:
                    ratio = width / height
                    
                    if 'diamond' in type_lower or 'decision' in type_lower or '菱形' in type_lower or '决策' in type_lower:
                        # Diamond: square-ish ratio, text often contains '?' or decision keywords
                        if 0.8 <= ratio <= 1.2:
                            score += 20
                        if '?' in text or '条件' in text or '判断' in text or '决策' in text:
                            score += 15
                    
                    elif 'rectangle' in type_lower or 'process' in type_lower or '矩形' in type_lower or '流程' in type_lower:
                        # Rectangle: wider than tall, text should NOT be decision-related
                        if ratio > 1.3:  # Wider than tall
                            score += 20
                        # Boost if text suggests process, penalize if suggests decision
                        if text and not any(k in text for k in ['?', '条件', '判断', '决策', '开始', '结束']):
                            score += 10
                        if '流程' in text or '子流程' in text or 'process' in text.lower():
                            score += 15
                    
                    elif 'rounded' in type_lower or 'terminator' in type_lower or '圆角' in type_lower:
                        # RoundedRectangle: wider than tall, text often start/end
                        if ratio > 1.5:
                            score += 20
                        if '开始' in text or '结束' in text or 'start' in text.lower() or 'end' in text.lower():
                            score += 20
                    
                    elif 'ellipse' in type_lower or 'circle' in type_lower or '椭圆' in type_lower or '圆' in type_lower:
                        # Ellipse/Circle: nearly equal dimensions
                        if 0.9 <= ratio <= 1.1:
                            score += 20
                    
                    elif 'parallelogram' in type_lower or 'data' in type_lower or '平行' in type_lower or '数据' in type_lower:
                        # Parallelogram: similar to rectangle but text contains data keywords
                        if ratio > 1.3:
                            score += 15
                        if '数据' in text or 'data' in text.lower() or '输入' in text or '输出' in text:
                            score += 20
                
                # Priority 4: Text content hints (use cautiously)
                if text:
                    text_lower = text.lower()
                    
                    # Only use as tiebreaker, not primary signal
                    if 'diamond' in type_lower or 'decision' in type_lower:
                        if '?' in text or '条件' in text or '判断' in text:
                            score += 5
                    
                    if 'rectangle' in type_lower or 'process' in type_lower:
                        if '流程' in text or '子流程' in text or 'process' in text_lower:
                            score += 5
                
                # Minimum score: any shape gets at least 1 point (fallback)
                if score == 0:
                    score = 1
                
                ranked.append((score, shape))

        # Sort by score (highest first)
        ranked.sort(key=lambda item: item[0], reverse=True)
        
        # Return all shapes ranked by score
        return [shape for score, shape in ranked]

    def debug_template_selection_simple(self, shape_type: str) -> str:
        """
        Simple debug output showing ALL available shapes and which would be selected.
        
        This is a simplified debugging tool that shows:
        - All non-connector shapes on the current page
        - Their master names, shape types, text, and geometry
        - Score for each shape (why it was/wasn't selected)
        - Which one would be selected for the requested shape type and why
        
        Args:
            shape_type: Shape type to test selection for
        
        Returns:
            Formatted debug information string with scores
        """
        if not self.current_page:
            return "Error: No current page set"
        
        normalized_type = normalize_shape_type(shape_type)
        type_lower = normalized_type.lower()
        catalog = self._get_cached_template_catalog()
        
        if not catalog:
            return f"[ERR] No template shapes available on page '{self.current_page.name}'\n" + \
                   "   Add at least one shape manually to use as a template."
        
        # Get all shapes with detailed info and scores
        all_shapes = []
        for shapes in catalog.values():
            for shape in shapes:
                shape_id = getattr(shape, 'ID', 'unknown')
                text = (getattr(shape, 'text', '') or '').strip()
                master = getattr(shape, 'master', None)
                master_name = getattr(master, 'name', 'No master') if master else 'No master'
                shape_type_attr = getattr(shape, 'shape_type', 'unknown')
                width = float(getattr(shape, 'width', 0) or 0)
                height = float(getattr(shape, 'height', 0) or 0)
                ratio = width / height if height > 0 else 0
                
                all_shapes.append({
                    'id': shape_id,
                    'text': text[:30],
                    'master': master_name,
                    'type': shape_type_attr,
                    'width': width,
                    'height': height,
                    'ratio': ratio,
                    'shape': shape
                })
        
        # Get selection result with scores
        candidates = self._select_shape_templates(normalized_type, catalog)
        
        # Re-score each shape for display
        scored_shapes = []
        for s in all_shapes:
            shape = s['shape']
            score = 0
            reasons = []
            
            # Replicate scoring logic to show reasons
            master_name_lower = s['master'].lower()
            shape_type_lower = s['type'].lower()
            text = s['text']
            ratio = s['ratio']
            
            # Master matching
            if master_name_lower and master_name_lower != 'no master':
                if master_name_lower == type_lower:
                    score += 100
                    reasons.append("exact_master")
                elif type_lower in master_name_lower:
                    score += 50
                    reasons.append("master_contains")
            
            # Type matching
            if shape_type_lower and shape_type_lower != 'shape':
                if shape_type_lower == type_lower:
                    score += 30
                    reasons.append("exact_type")
                elif type_lower in shape_type_lower:
                    score += 15
                    reasons.append("type_contains")
            
            # Geometry matching
            if ratio > 0:
                if 'diamond' in type_lower or 'decision' in type_lower or '菱形' in type_lower:
                    if 0.8 <= ratio <= 1.2:
                        score += 20
                        reasons.append("diamond_ratio")
                    if '?' in text or '条件' in text or '判断' in text:
                        score += 15
                        reasons.append("decision_text")
                
                elif 'rectangle' in type_lower or 'process' in type_lower or '矩形' in type_lower:
                    if ratio > 1.3:
                        score += 20
                        reasons.append("rect_ratio")
                    if text and not any(k in text for k in ['?', '条件', '判断', '开始', '结束']):
                        score += 10
                        reasons.append("process_text")
                    if '流程' in text or '子流程' in text:
                        score += 15
                        reasons.append("process_keyword")
                
                elif 'rounded' in type_lower or 'terminator' in type_lower or '圆角' in type_lower:
                    if ratio > 1.5:
                        score += 20
                        reasons.append("rounded_ratio")
                    if '开始' in text or '结束' in text or 'start' in text.lower() or 'end' in text.lower():
                        score += 20
                        reasons.append("terminator_text")
            
            if score == 0:
                score = 1
                reasons.append("fallback")
            
            scored_shapes.append({
                **s,
                'score': score,
                'reasons': reasons
            })
        
        # Sort by score
        scored_shapes.sort(key=lambda x: x['score'], reverse=True)
        selected = scored_shapes[0] if scored_shapes else None
        
        result = f"🔍 Template Selection Debug for '{shape_type}' (normalized: '{normalized_type}'):\n\n"
        result += f"📋 Available shapes ({len(scored_shapes)} total, sorted by score):\n\n"
        
        for i, s in enumerate(scored_shapes, 1):
            marker = "👉" if i == 1 else "  "
            reason_str = ",".join(s['reasons'][:3])  # Show top 3 reasons
            result += f"{marker} {i}. [Score:{s['score']:3d}] ID={s['id']}, W/H={s['ratio']:.2f}, Text='{s['text']}'\n"
            result += f"      Master='{s['master']}', Type='{s['type']}', Why: {reason_str}\n"
        
        if selected:
            result += f"\n[OK] WILL USE: ID={selected['id']} (Score: {selected['score']}, Reasons: {','.join(selected['reasons'])})\n"
        else:
            result += f"\n[ERR] NO SUITABLE TEMPLATE FOUND\n"
        
        return result
    
    def explain_template_selection(self, shape_type: str, max_candidates: int = 5) -> str:
        """
        Explain which templates would be selected for a given shape type.
        
        Provides visibility into the template selection process for debugging.
        
        Args:
            shape_type: Shape type to analyze
            max_candidates: Maximum number of candidates to show
        
        Returns:
            Formatted explanation string
        """
        if not self.current_page:
            return "Error: No current page set"
        
        normalized_type = normalize_shape_type(shape_type)
        catalog = self._get_cached_template_catalog()
        
        if not catalog:
            return f"No templates available on page '{self.current_page.name}'"
        
        candidates = self._select_shape_templates(normalized_type, catalog)
        
        result = f"📋 Template Selection for '{shape_type}' (normalized: '{normalized_type}'):\n\n"
        
        if not candidates:
            result += "  [ERR] No matching templates found\n"
            result += f"  [TIP] Suggestion: Add a shape of type '{normalized_type}' manually to the page\n"
            return result
        
        result += f"  [OK] Found {len(candidates)} candidate(s)\n\n"
        result += "  Top candidates:\n"
        
        for i, shape in enumerate(candidates[:max_candidates], 1):
            shape_id = getattr(shape, 'ID', 'unknown')
            text = (getattr(shape, 'text', '') or '').strip()
            shape_type_attr = getattr(shape, 'shape_type', 'unknown')
            master = getattr(shape, 'master', None)
            master_name = getattr(master, 'name', 'No master') if master else 'No master'
            
            result += f"  {i}. Shape ID={shape_id}\n"
            result += f"     Text: '{text[:30]}'\n"
            result += f"     Type: {shape_type_attr}\n"
            result += f"     Master: {master_name}\n"
            if i < len(candidates[:max_candidates]):
                result += "\n"
        
        return result
    
    def _align_z_order(self, new_shape: Any, template_shape: Any):
        """Try to place new shape in similar z-order as template."""
        try:
            siblings = list(self._iter_shapes(self.current_page.child_shapes, include_groups=True))
            if template_shape in siblings and new_shape in siblings:
                template_index = siblings.index(template_shape)
                new_index = siblings.index(new_shape)
                if new_index < template_index:
                    siblings.pop(new_index)
                    siblings.insert(template_index + 1, new_shape)
                    self._reassign_children(self.current_page, siblings)
        except Exception:
            pass

    def _copy_geometry(self, source_shape: Any, target_shape: Any, preserve_size: bool = True):
        """Copy geometric properties from source to target shape."""
        geometry_cells = [
            'Angle',  # Rotation angle
            'FlipX', 'FlipY',  # Flip properties
            'LocPinX', 'LocPinY',  # Local pin position
        ]
        
        if preserve_size:
            # Also preserve exact proportions if requested
            geometry_cells.extend(['Width', 'Height'])
        
        for cell_name in geometry_cells:
            try:
                source_value = source_shape.cell_value(cell_name)
                if source_value is not None:
                    target_shape.set_cell_value(cell_name, source_value)
            except Exception:
                continue

    def _copy_formatting(self, source_shape: Any, target_shape: Any):
        """Enhanced copy of formatting attributes from source to target."""
        # Basic visual attributes
        basic_attrs = [
            'line_color', 'line_pattern', 'line_weight', 
            'fill_color', 'fill_pattern', 'fill_foreground',
            'font_size', 'font', 'font_style', 'font_color',
            'char_color', 'char_size', 'char_style',
            'shadow_foreground', 'shadow_pattern', 'shadow_offset_x', 'shadow_offset_y'
        ]
        
        for attr in basic_attrs:
            value = getattr(source_shape, attr, None)
            if value is not None:
                try:
                    setattr(target_shape, attr, value)
                except Exception:
                    continue
        
        # Copy cell values for more precise formatting
        cell_names = [
            # Line formatting
            'LineColor', 'LineWeight', 'LinePattern', 'Rounding',
            # Fill formatting  
            'FillForegnd', 'FillBkgnd', 'FillPattern',
            # Shadow
            'ShapeShdwShow', 'ShapeShdwType', 'ShdwForegnd', 'ShdwPattern',
            # Text formatting
            'VerticalAlign', 'TxtAngle', 'TxtWidth', 'TxtHeight',
            'LeftMargin', 'RightMargin', 'TopMargin', 'BottomMargin',
            # Character formatting
            'CharCase', 'CharColor', 'CharSize', 'CharStyle', 'CharFont',
            # Paragraph formatting
            'HAlign', 'Bullet', 'BulletFont', 'BulletSize', 'TextPosAfterBullet',
            'IndFirst', 'IndLeft', 'IndRight', 'SpLine', 'SpBefore', 'SpAfter'
        ]
        
        for cell_name in cell_names:
            try:
                source_value = source_shape.cell_value(cell_name)
                if source_value is not None:
                    target_shape.set_cell_value(cell_name, source_value)
            except Exception:
                continue

    def _iter_shapes(self, shapes: Iterable[Any], include_groups: bool = False) -> List[Any]:
        """Flatten nested shape collections while optionally keeping groups."""
        flattened: List[Any] = []
        for shape in shapes:
            if getattr(shape, 'shape_type', '').lower() == 'group' and hasattr(shape, 'child_shapes'):
                if include_groups:
                    flattened.append(shape)
                flattened.extend(self._iter_shapes(shape.child_shapes, include_groups=include_groups))
            else:
                flattened.append(shape)
        return flattened

    def _reassign_children(self, page: Any, shapes: List[Any]):
        """Reassign child shapes preserving group membership."""
        try:
            # This operation isn't directly supported; fallback to no-op if attribute is read-only
            page.child_shapes[:] = shapes  # type: ignore[index]
        except Exception:
            pass

    # -----------------------
    # Template discovery (RO)
    # -----------------------
    def get_candidate_templates(self, shape_type: str, max_candidates: int = 5) -> List[Dict[str, Any]]:
        """Return candidate template shapes across the current file for a requested type.

        This method does not mutate the diagram. It searches all pages for
        non-connector, non-guide shapes, ranks them using the internal
        selection algorithm, and returns concise descriptors for UI/agents.
        """
        if not self.visio_file:
            return []

        try:
            # Build a catalog across all pages
            shape_catalog: Dict[str, List[Any]] = {}
            pages = getattr(self.visio_file, 'pages', []) or []
            for page in pages:
                for shape in getattr(page, 'child_shapes', []) or []:
                    if self._is_connector(shape) or self._is_guide(shape):
                        continue
                    master_name = self._get_master_key(shape)
                    shape_catalog.setdefault(master_name, []).append(shape)

            candidates = self._select_shape_templates(shape_type, shape_catalog)
            result: List[Dict[str, Any]] = []
            for shape in candidates[: max_candidates]:
                master = getattr(shape, 'master', None)
                result.append({
                    "id": str(getattr(shape, 'ID', '')),
                    "type": str(getattr(shape, 'shape_type', '') or ''),
                    "master": str(getattr(master, 'name', '')) if master else '',
                    "text": (getattr(shape, 'text', '') or '').strip(),
                })
            return result
        except Exception:
            return []

    def has_connector_template_across_pages(self) -> bool:
        """Return True if any connector exists anywhere in the document."""
        if not self.visio_file:
            return False
        try:
            for page in getattr(self.visio_file, 'pages', []) or []:
                for shape in getattr(page, 'child_shapes', []) or []:
                    if self._is_connector(shape):
                        return True
            return False
        except Exception:
            return False

    # -----------------------
    # Template-based updating
    # -----------------------
    def update_shape_text_by_match(self, match_text: str, new_text: str, mode: str = "contains") -> bool:
        """Update the first shape whose text matches the rule.

        Args:
            match_text: Text or regex pattern to match.
            new_text: Replacement text.
            mode: 'equals' | 'contains' | 'regex'
        """
        if not self.current_page:
            return False
        shapes = list(self._iter_shapes(self.current_page.child_shapes, include_groups=True))
        for shape in shapes:
            txt = (getattr(shape, 'text', '') or '').strip()
            try:
                if (mode == 'equals' and txt == match_text) or \
                   (mode == 'contains' and match_text in txt) or \
                   (mode == 'regex' and re.search(match_text, txt)):
                    shape.text = new_text
                    return True
            except Exception:
                continue
        return False

    def update_shape_text_by_match_all(self, match_text: str, new_text: str, 
                                       mode: str = "contains", case_sensitive: bool = False) -> int:
        """Update ALL shapes whose text matches the rule.

        Args:
            match_text: Text or regex pattern to match.
            new_text: Replacement text.
            mode: 'equals' | 'contains' | 'regex'
            case_sensitive: Whether matching is case-sensitive.

        Returns:
            Number of shapes updated.
        """
        if not self.current_page:
            return 0
        flags = 0 if case_sensitive else re.IGNORECASE
        updated = 0
        shapes = list(self._iter_shapes(self.current_page.child_shapes, include_groups=True))
        for shape in shapes:
            # Skip connectors
            if self._is_connector(shape):
                continue
            txt = (getattr(shape, 'text', '') or '')
            try:
                if mode == 'equals':
                    a = txt if case_sensitive else txt.lower()
                    b = match_text if case_sensitive else match_text.lower()
                    if a == b:
                        shape.text = new_text
                        updated += 1
                elif mode == 'contains':
                    pattern = re.compile(re.escape(match_text), flags)
                    replaced = pattern.sub(new_text, txt)
                    if replaced != txt:
                        shape.text = replaced
                        updated += 1
                elif mode == 'regex':
                    pattern = re.compile(match_text, flags)
                    replaced = pattern.sub(new_text, txt)
                    if replaced != txt:
                        shape.text = replaced
                        updated += 1
            except Exception:
                continue
        return updated

    def batch_update_text_by_map(self, mapping: Dict[str, str], mode: str = "equals", 
                                 case_sensitive: bool = False) -> int:
        """Apply multiple text replacements across ALL shapes in-place.

        Args:
            mapping: Dict of pattern -> replacement.
            mode: 'equals' | 'contains' | 'regex'.
            case_sensitive: Whether matching is case-sensitive.

        Returns:
            Number of shapes updated (at least one replacement applied).
        """
        if not self.current_page or not mapping:
            return 0
        flags = 0 if case_sensitive else re.IGNORECASE
        updated_shapes = 0
        shapes = list(self._iter_shapes(self.current_page.child_shapes, include_groups=True))
        for shape in shapes:
            # Skip connectors
            if self._is_connector(shape):
                continue
            original = (getattr(shape, 'text', '') or '')
            txt = original
            try:
                if mode == 'equals':
                    for pattern_str, replacement in mapping.items():
                        a = txt if case_sensitive else txt.lower()
                        b = pattern_str if case_sensitive else pattern_str.lower()
                        if a == b:
                            txt = replacement
                            # For equals mode, a single match replaces the entire text; continue to allow subsequent exact replacements if desired
                elif mode == 'contains':
                    for pattern_str, replacement in mapping.items():
                        pattern = re.compile(re.escape(pattern_str), flags)
                        txt = pattern.sub(replacement, txt)
                elif mode == 'regex':
                    for pattern_str, replacement in mapping.items():
                        pattern = re.compile(pattern_str, flags)
                        txt = pattern.sub(replacement, txt)
            except Exception:
                # Ignore errors for a shape; move on to next
                pass
            if txt != original:
                try:
                    shape.text = txt
                    updated_shapes += 1
                except Exception:
                    # Ignore set failures on this shape
                    pass
        return updated_shapes

    def fill_placeholders(self, values: Dict[str, str], pattern: str = r"\{\{(\w+)\}\}") -> int:
        """Replace placeholder tokens like {{Title}} with provided values.

        Args:
            values: Mapping from placeholder key to replacement text.
            pattern: Regex with a single capture group for the key.
        Returns:
            Number of shapes updated.
        """
        if not self.current_page or not values:
            return 0
        regex: Pattern[str] = re.compile(pattern)
        updated = 0
        shapes = list(self._iter_shapes(self.current_page.child_shapes, include_groups=True))
        for shape in shapes:
            original = getattr(shape, 'text', '') or ''
            if not original:
                continue
            def _repl(m: re.Match[str]) -> str:
                key = m.group(1)
                return values.get(key, m.group(0))
            replaced = regex.sub(_repl, original)
            if replaced != original:
                try:
                    shape.text = replaced
                    updated += 1
                except Exception:
                    pass
        return updated

    def replace_shape(self, shape_id: str, template_shape_id: str, 
                     preserve_text: bool = True, preserve_connections: bool = True) -> Optional[Any]:
        """
        Replace an existing shape with a copy of a template shape, preserving connections and optionally text.
        
        This is superior to removing and adding a new shape because it maintains
        all connections to/from the original shape.
        
        Args:
            shape_id: ID of the shape to replace
            template_shape_id: ID of the template shape to copy style from
            preserve_text: If True, keeps the original shape's text
            preserve_connections: If True, transfers all connections to the new shape
        
        Returns:
            New shape object or None if failed
        """
        if not self.current_page:
            print("Error: No current page set")
            return None
        
        original_shape = self.get_shape_by_id(shape_id)
        template_shape = self.get_shape_by_id(template_shape_id)
        
        if not original_shape:
            print(f"Error: Original shape '{shape_id}' not found")
            return None
        if not template_shape:
            print(f"Error: Template shape '{template_shape_id}' not found")
            return None
        
        try:
            # Store original properties
            original_text = original_shape.text if preserve_text else None
            original_x = float(original_shape.cell_value('PinX') or original_shape.x or 0)
            original_y = float(original_shape.cell_value('PinY') or original_shape.y or 0)
            
            # Find all connectors connected to the original shape
            connected_connectors = []
            if preserve_connections:
                connected_connectors = self._find_connected_connectors(original_shape)
            
            # Create new shape from template
            new_shape_xml = self.visio_file.copy_shape(template_shape.xml, self.current_page)
            
            # Find the newly created shape by matching XML
            new_shape = None
            if self.current_page.child_shapes:
                for shape in reversed(self.current_page.child_shapes):
                    if shape.xml == new_shape_xml:
                        new_shape = shape
                        break
                
                # Fallback: use last shape if XML matching fails
                if not new_shape:
                    new_shape = self.current_page.child_shapes[-1]
            
            if new_shape:
                
                # Apply original position
                new_shape.set_cell_value('PinX', str(original_x))
                new_shape.set_cell_value('PinY', str(original_y))
                
                # Preserve original dimensions
                original_width = original_shape.cell_value('Width') or original_shape.width
                original_height = original_shape.cell_value('Height') or original_shape.height
                if original_width:
                    new_shape.set_cell_value('Width', str(original_width))
                if original_height:
                    new_shape.set_cell_value('Height', str(original_height))
                
                # Apply text if preserving
                if original_text is not None:
                    new_shape.text = original_text
                
                # Reconnect all connectors
                if preserve_connections and connected_connectors:
                    self._reconnect_shape(original_shape, new_shape, connected_connectors)
                
                # Remove the original shape
                original_shape.remove()
                
                return new_shape
                
        except Exception as e:
            print(f"Error replacing shape: {e}")
            import traceback
            traceback.print_exc()
        
        return None
    
    def get_shape_connections(self, shape_id: str) -> Dict[str, List[str]]:
        """
        Get all connections to/from a shape.
        
        Enhanced to check both vsdx library's connects property AND
        page XML Connects element directly (for newly created connectors).
        
        Args:
            shape_id: ID of the shape to check
        
        Returns:
            Dictionary with 'incoming' and 'outgoing' connector IDs
        """
        import xml.etree.ElementTree as ET
        
        shape = self.get_shape_by_id(shape_id)
        if not shape:
            return {'incoming': [], 'outgoing': []}
        
        incoming = []
        outgoing = []
        
        if not self.current_page:
            return {'incoming': incoming, 'outgoing': outgoing}
        
        # Build set of all connector IDs for quick lookup
        connector_ids = set()
        for s in self.current_page.child_shapes:
            if self._is_connector(s):
                connector_ids.add(str(s.ID))
        
        # Method 1: Check via vsdx Connect objects (works for loaded connectors)
        for connector in self.current_page.child_shapes:
            if not self._is_connector(connector):
                continue
            
            try:
                connector_id = str(connector.ID)
                
                if hasattr(connector, 'connects') and connector.connects:
                    begins_at_shape = False
                    ends_at_shape = False
                    
                    for conn in connector.connects:
                        target_shape_id = str(getattr(conn, 'to_id', '') or getattr(conn, 'shape_id', ''))
                        from_rel = getattr(conn, 'from_rel', '')
                        
                        if target_shape_id == shape_id:
                            if from_rel.startswith('Begin'):
                                begins_at_shape = True
                            elif from_rel.startswith('End'):
                                ends_at_shape = True
                    
                    if begins_at_shape and connector_id not in outgoing:
                        outgoing.append(connector_id)
                    if ends_at_shape and connector_id not in incoming:
                        incoming.append(connector_id)
                
            except Exception as e:
                # Log but continue checking other connectors
                print(f"Debug: Error checking connector {connector_id}: {e}")
                continue
        
        # Method 2: Check page XML Connects element directly (catches newly created connectors)
        # This is critical for connectors created via add_or_update_connector that haven't been reloaded
        try:
            ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
            page_xml = getattr(self.current_page, 'xml', None)
            
            if page_xml is not None:
                # Find all Connect elements
                connects = page_xml.findall('.//v:Connect', ns)
                if not connects:
                    connects = page_xml.findall('.//Connect')
                
                for connect_elem in connects:
                    from_sheet = connect_elem.get('FromSheet', '')
                    to_sheet = connect_elem.get('ToSheet', '')
                    from_cell = connect_elem.get('FromCell', '')
                    
                    # Only process if from_sheet is a connector
                    if from_sheet not in connector_ids:
                        continue
                    
                    # Check if this Connect references our target shape
                    if to_sheet == shape_id:
                        if 'BeginX' in from_cell or 'BeginY' in from_cell:
                            # This connector starts at our shape (outgoing)
                            if from_sheet not in outgoing:
                                outgoing.append(from_sheet)
                        elif 'EndX' in from_cell or 'EndY' in from_cell:
                            # This connector ends at our shape (incoming)
                            if from_sheet not in incoming:
                                incoming.append(from_sheet)
        except Exception as e:
            # Don't fail if XML parsing fails, we already have Method 1 results
            pass
        
        return {'incoming': incoming, 'outgoing': outgoing}
    
    def query_shape_connections(self, shape_id: str, depth: int = 2) -> Dict[str, Any]:
        """
        Surgical-level query for shape connectivity with impact analysis.
        
        This method provides comprehensive visibility into:
        - Direct incoming/outgoing connections with full shape details
        - Upstream and downstream dependency chains (multi-hop)
        - Connection point details and routing information
        - Impact assessment for deletion scenarios
        - Multi-node dependency detection
        - Bidirectional and cyclic connection detection
        
        Args:
            shape_id: ID of the shape to analyze
            depth: How many hops to trace (default 2, max 5 for performance)
        
        Returns:
            Comprehensive dictionary with:
            - 'shape': Target shape details
            - 'direct_connections': Immediate connections with full details
            - 'upstream_chain': Multi-hop upstream dependencies
            - 'downstream_chain': Multi-hop downstream dependencies
            - 'dependency_stats': Counts and metrics
            - 'impact_assessment': What would break if shape is deleted/modified
            - 'connection_health': Issues and warnings
        """
        # Validate inputs
        if not self.current_page:
            return {'error': 'No current page set'}
        
        depth = max(1, min(depth, 5))  # Clamp between 1-5
        
        shape = self.get_shape_by_id(shape_id)
        if not shape:
            return {'error': f'Shape {shape_id} not found'}
        
        # Build shape info cache for efficient lookups
        shape_cache = self._build_shape_info_cache()
        
        if shape_id not in shape_cache:
            return {'error': f'Shape {shape_id} not in cache'}
        
        target_info = shape_cache[shape_id]
        
        # Get direct connections with full details
        direct_incoming = self._get_detailed_connections(shape_id, 'incoming', shape_cache)
        direct_outgoing = self._get_detailed_connections(shape_id, 'outgoing', shape_cache)
        
        # Trace upstream chain (sources feeding into this shape)
        upstream_chain = self._trace_connection_chain(shape_id, 'upstream', depth, shape_cache)
        
        # Trace downstream chain (targets this shape feeds into)
        downstream_chain = self._trace_connection_chain(shape_id, 'downstream', depth, shape_cache)
        
        # Detect cycles and bidirectional connections
        cycles = self._detect_cycles_from_shape(shape_id, shape_cache)
        bidirectional = self._find_bidirectional_connections(shape_id, shape_cache)
        
        # Calculate dependency statistics
        dependency_stats = {
            'direct_incoming_count': len(direct_incoming),
            'direct_outgoing_count': len(direct_outgoing),
            'total_upstream_shapes': len(set(upstream_chain.get('all_shapes', []))),
            'total_downstream_shapes': len(set(downstream_chain.get('all_shapes', []))),
            'upstream_depth': upstream_chain.get('max_depth', 0),
            'downstream_depth': downstream_chain.get('max_depth', 0),
            'has_cycles': len(cycles) > 0,
            'bidirectional_count': len(bidirectional)
        }
        
        # Impact assessment for deletion
        impact = self._assess_deletion_impact(shape_id, direct_incoming, direct_outgoing, 
                                              upstream_chain, downstream_chain, shape_cache)
        
        # Connection health check
        health = self._check_connection_health(shape_id, direct_incoming, direct_outgoing, shape_cache)
        
        return {
            'shape': {
                'id': shape_id,
                'text': target_info['text'],
                'type': target_info['type'],
                'position': {'x': target_info['x'], 'y': target_info['y']},
                'size': {'width': target_info['width'], 'height': target_info['height']},
                'node_key': get_shape_prop(shape, 'NodeKey')
            },
            'direct_connections': {
                'incoming': direct_incoming,
                'outgoing': direct_outgoing
            },
            'upstream_chain': upstream_chain,
            'downstream_chain': downstream_chain,
            'cycles': cycles,
            'bidirectional_connections': bidirectional,
            'dependency_stats': dependency_stats,
            'impact_assessment': impact,
            'connection_health': health
        }
    
    def _build_shape_info_cache(self) -> Dict[str, Dict[str, Any]]:
        """Build a cache of all shapes with their connection info."""
        cache = {}
        if not self.current_page:
            return cache
        
        for shape in self.current_page.child_shapes:
            try:
                shape_id = str(getattr(shape, 'ID', ''))
                is_connector = self._is_connector(shape)
                
                # Get shape text safely
                try:
                    text = (getattr(shape, 'text', '') or '').strip()
                except Exception:
                    text = ''
                
                # Get position and size
                try:
                    x = float(shape.cell_value('PinX') or 0)
                    y = float(shape.cell_value('PinY') or 0)
                    width = float(shape.cell_value('Width') or 0)
                    height = float(shape.cell_value('Height') or 0)
                except Exception:
                    x = y = width = height = 0
                
                # Get shape type
                shape_type = 'Connector' if is_connector else 'Shape'
                if hasattr(shape, 'master_shape') and shape.master_shape:
                    shape_type = str(getattr(shape.master_shape, 'name', shape_type))
                
                cache[shape_id] = {
                    'id': shape_id,
                    'text': text,
                    'type': shape_type,
                    'is_connector': is_connector,
                    'x': x,
                    'y': y,
                    'width': width,
                    'height': height,
                    'shape_obj': shape
                }
            except Exception:
                continue
        
        return cache
    
    def _get_detailed_connections(self, shape_id: str, direction: str, 
                                 shape_cache: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Get detailed connection information for a shape in specified direction."""
        connections = []
        
        if not self.current_page:
            return connections
        
        for connector in self.current_page.child_shapes:
            if not self._is_connector(connector):
                continue
            
            try:
                connector_id = str(connector.ID)
                connector_text = shape_cache.get(connector_id, {}).get('text', '')
                
                from_shape_id = None
                to_shape_id = None
                
                # Parse connector endpoints
                if hasattr(connector, 'connects') and connector.connects:
                    for conn in connector.connects:
                        connected_id = getattr(conn, 'shape_id', None)
                        from_rel = getattr(conn, 'from_rel', '')
                        
                        if not connected_id:
                            continue
                        
                        connected_id = str(connected_id)
                        
                        if 'BeginX' in from_rel or 'Begin' in from_rel:
                            from_shape_id = connected_id
                        elif 'EndX' in from_rel or 'End' in from_rel:
                            to_shape_id = connected_id
                
                # Check if this connection involves our shape in the right direction
                relevant = False
                other_shape_id = None
                
                if direction == 'incoming' and to_shape_id == shape_id:
                    relevant = True
                    other_shape_id = from_shape_id
                elif direction == 'outgoing' and from_shape_id == shape_id:
                    relevant = True
                    other_shape_id = to_shape_id
                
                if relevant and other_shape_id and other_shape_id in shape_cache:
                    other_info = shape_cache[other_shape_id]
                    connections.append({
                        'connector_id': connector_id,
                        'connector_text': connector_text,
                        'other_shape_id': other_shape_id,
                        'other_shape_text': other_info['text'],
                        'other_shape_type': other_info['type'],
                        'other_shape_position': {'x': other_info['x'], 'y': other_info['y']},
                        'from_shape_id': from_shape_id,
                        'to_shape_id': to_shape_id
                    })
            except Exception:
                continue
        
        return connections
    
    def _trace_connection_chain(self, start_shape_id: str, direction: str, 
                               max_depth: int, shape_cache: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Trace connection chain in specified direction up to max_depth."""
        visited = set()
        chain_by_level = {}  # level -> [shape_ids]
        all_shapes = set()
        
        current_level = {start_shape_id}
        visited.add(start_shape_id)
        
        for depth in range(1, max_depth + 1):
            next_level = set()
            level_details = []
            
            for shape_id in current_level:
                # Get connections in the specified direction
                conn_dir = 'incoming' if direction == 'upstream' else 'outgoing'
                connections = self._get_detailed_connections(shape_id, conn_dir, shape_cache)
                
                for conn in connections:
                    other_id = conn['other_shape_id']
                    if other_id not in visited:
                        visited.add(other_id)
                        next_level.add(other_id)
                        all_shapes.add(other_id)
                        level_details.append({
                            'shape_id': other_id,
                            'shape_text': conn['other_shape_text'],
                            'shape_type': conn['other_shape_type'],
                            'connector_id': conn['connector_id'],
                            'connector_text': conn['connector_text'],
                            'from_shape_id': shape_id
                        })
            
            if level_details:
                chain_by_level[depth] = level_details
            
            if not next_level:
                break
            
            current_level = next_level
        
        return {
            'chain_by_level': chain_by_level,
            'all_shapes': list(all_shapes),
            'max_depth': len(chain_by_level)
        }
    
    def _detect_cycles_from_shape(self, shape_id: str, 
                                  shape_cache: Dict[str, Dict[str, Any]]) -> List[List[str]]:
        """Detect cycles involving this shape."""
        cycles = []
        
        def dfs_cycle_detect(current_id, path, visited_in_path):
            if current_id in visited_in_path:
                # Found a cycle
                cycle_start = path.index(current_id)
                cycle = path[cycle_start:]
                if shape_id in cycle and cycle not in cycles:
                    cycles.append(cycle)
                return
            
            if len(path) > 10:  # Prevent infinite loops
                return
            
            visited_in_path.add(current_id)
            path.append(current_id)
            
            # Follow outgoing connections
            outgoing = self._get_detailed_connections(current_id, 'outgoing', shape_cache)
            for conn in outgoing:
                other_id = conn['other_shape_id']
                dfs_cycle_detect(other_id, path.copy(), visited_in_path.copy())
        
        dfs_cycle_detect(shape_id, [], set())
        return cycles
    
    def _find_bidirectional_connections(self, shape_id: str, 
                                       shape_cache: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Find shapes with bidirectional connections to this shape."""
        bidirectional = []
        
        incoming = self._get_detailed_connections(shape_id, 'incoming', shape_cache)
        outgoing = self._get_detailed_connections(shape_id, 'outgoing', shape_cache)
        
        incoming_shapes = {conn['other_shape_id'] for conn in incoming}
        outgoing_shapes = {conn['other_shape_id'] for conn in outgoing}
        
        bidirectional_shapes = incoming_shapes & outgoing_shapes
        
        for other_id in bidirectional_shapes:
            other_info = shape_cache.get(other_id, {})
            # Find the specific connectors
            in_conns = [c for c in incoming if c['other_shape_id'] == other_id]
            out_conns = [c for c in outgoing if c['other_shape_id'] == other_id]
            
            bidirectional.append({
                'other_shape_id': other_id,
                'other_shape_text': other_info.get('text', ''),
                'other_shape_type': other_info.get('type', ''),
                'incoming_connectors': [c['connector_id'] for c in in_conns],
                'outgoing_connectors': [c['connector_id'] for c in out_conns]
            })
        
        return bidirectional
    
    def _assess_deletion_impact(self, shape_id: str, direct_incoming: List[Dict[str, Any]], 
                               direct_outgoing: List[Dict[str, Any]], upstream_chain: Dict[str, Any],
                               downstream_chain: Dict[str, Any], shape_cache: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Assess the impact of deleting this shape."""
        # Count affected connectors
        affected_connectors = set()
        for conn in direct_incoming:
            affected_connectors.add(conn['connector_id'])
        for conn in direct_outgoing:
            affected_connectors.add(conn['connector_id'])
        
        # Identify orphaned shapes (would become disconnected)
        potentially_orphaned = set()
        for conn in direct_incoming:
            other_id = conn['other_shape_id']
            other_outgoing = self._get_detailed_connections(other_id, 'outgoing', shape_cache)
            if len(other_outgoing) == 1:  # Only connection is to this shape
                potentially_orphaned.add(other_id)
        
        for conn in direct_outgoing:
            other_id = conn['other_shape_id']
            other_incoming = self._get_detailed_connections(other_id, 'incoming', shape_cache)
            if len(other_incoming) == 1:  # Only connection is from this shape
                potentially_orphaned.add(other_id)
        
        # Identify broken paths
        broken_paths = []
        if direct_incoming and direct_outgoing:
            for in_conn in direct_incoming:
                for out_conn in direct_outgoing:
                    broken_paths.append({
                        'from_shape': in_conn['other_shape_id'],
                        'from_text': in_conn['other_shape_text'],
                        'to_shape': out_conn['other_shape_id'],
                        'to_text': out_conn['other_shape_text']
                    })
        
        # Determine reconnection strategy
        reconnection_strategy = 'remove_connectors'  # Default
        if len(direct_incoming) == 1 and len(direct_outgoing) == 1:
            reconnection_strategy = 'simple_bypass'
        elif direct_incoming and direct_outgoing:
            reconnection_strategy = 'smart_reconnect'
        
        return {
            'affected_connectors_count': len(affected_connectors),
            'affected_connector_ids': list(affected_connectors),
            'potentially_orphaned_shapes': [
                {
                    'shape_id': sid,
                    'shape_text': shape_cache.get(sid, {}).get('text', ''),
                    'shape_type': shape_cache.get(sid, {}).get('type', '')
                }
                for sid in potentially_orphaned
            ],
            'broken_paths_count': len(broken_paths),
            'broken_paths': broken_paths[:10],  # Limit to first 10
            'recommended_reconnection_strategy': reconnection_strategy,
            'upstream_affected_count': upstream_chain.get('max_depth', 0),
            'downstream_affected_count': downstream_chain.get('max_depth', 0)
        }
    
    def _check_connection_health(self, shape_id: str, direct_incoming: List[Dict[str, Any]], 
                                 direct_outgoing: List[Dict[str, Any]], 
                                 shape_cache: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Check for connection health issues."""
        issues = []
        warnings = []
        
        # Check for orphaned connectors (connected on only one end)
        for conn in direct_incoming + direct_outgoing:
            if not conn.get('from_shape_id') or not conn.get('to_shape_id'):
                issues.append({
                    'type': 'orphaned_connector',
                    'connector_id': conn['connector_id'],
                    'message': f"Connector {conn['connector_id']} has incomplete connections"
                })
        
        # Check for duplicate connections
        connection_pairs = set()
        for conn in direct_incoming:
            pair = (conn['other_shape_id'], shape_id)
            if pair in connection_pairs:
                warnings.append({
                    'type': 'duplicate_connection',
                    'message': f"Multiple connectors from {conn['other_shape_text']} to this shape"
                })
            connection_pairs.add(pair)
        
        for conn in direct_outgoing:
            pair = (shape_id, conn['other_shape_id'])
            if pair in connection_pairs:
                warnings.append({
                    'type': 'duplicate_connection',
                    'message': f"Multiple connectors to {conn['other_shape_text']}"
                })
            connection_pairs.add(pair)
        
        # Check for self-loops
        for conn in direct_outgoing:
            if conn['other_shape_id'] == shape_id:
                warnings.append({
                    'type': 'self_loop',
                    'connector_id': conn['connector_id'],
                    'message': 'Shape has a connector to itself'
                })
        
        return {
            'healthy': len(issues) == 0,
            'issues': issues,
            'warnings': warnings,
            'issue_count': len(issues),
            'warning_count': len(warnings)
        }
    
    def reconnect_shapes(self, connector_id: str, from_shape_id: Optional[str] = None, 
                        to_shape_id: Optional[str] = None,
                        from_glue_point: Optional[str] = None,
                        to_glue_point: Optional[str] = None) -> bool:
        """
        Update an existing connector's connections.
        
        Args:
            connector_id: ID of the connector to update
            from_shape_id: New source shape ID (None to keep current)
            to_shape_id: New target shape ID (None to keep current)
            from_glue_point: Optional connection point on source shape (e.g., 'Right', 'Top')
            to_glue_point: Optional connection point on target shape (e.g., 'Left', 'Bottom')
        
        Returns:
            True if successful
        """
        if not self.current_page:
            print("Error: No current page set")
            return False
        
        connector = self.get_shape_by_id(connector_id)
        if not connector or not self._is_connector(connector):
            print(f"Error: Connector '{connector_id}' not found or not a connector")
            return False
        
        try:
            from_shape = self.get_shape_by_id(from_shape_id) if from_shape_id else None
            to_shape = self.get_shape_by_id(to_shape_id) if to_shape_id else None
            
            if from_shape_id and not from_shape:
                print(f"Error: From shape '{from_shape_id}' not found")
                return False
            if to_shape_id and not to_shape:
                print(f"Error: To shape '{to_shape_id}' not found")
                return False
            
            # Get current connection if not replacing
            if not from_shape and hasattr(connector, 'connects') and connector.connects:
                for conn in connector.connects:
                    # Use vsdx Connect structure: check from_rel for BeginX
                    from_rel = getattr(conn, 'from_rel', '')
                    if 'BeginX' in from_rel or 'Begin' in from_rel:
                        # Get the shape at the beginning of the connector
                        shape_id = getattr(conn, 'shape_id', None)
                        if shape_id:
                            from_shape = self.get_shape_by_id(str(shape_id))
                            if from_shape:
                                break
            
            if not to_shape and hasattr(connector, 'connects') and connector.connects:
                for conn in connector.connects:
                    # Use vsdx Connect structure: check from_rel for EndX
                    from_rel = getattr(conn, 'from_rel', '')
                    if 'EndX' in from_rel or 'End' in from_rel:
                        # Get the shape at the end of the connector
                        shape_id = getattr(conn, 'shape_id', None)
                        if shape_id:
                            to_shape = self.get_shape_by_id(str(shape_id))
                            if to_shape:
                                break
            
            if from_shape and to_shape:
                # Use glue-based connection instead of coordinates
                # Pass glue points if specified, otherwise use auto-selection
                return self._set_connector_glue(connector, from_shape, to_shape, 
                                               from_glue_point, to_glue_point)
            
        except Exception as e:
            print(f"Error reconnecting shapes: {e}")
            import traceback
            traceback.print_exc()
        
        return False
    
    def auto_route_connector(self, connector_id: str, routing_style: str = "straight") -> bool:
        """
        Apply routing style to a connector.
        
        Enhanced with validation to prevent breaking glued connections.
        
        Args:
            connector_id: ID of the connector
            routing_style: 'straight', 'right_angle', or 'curved'
        
        Returns:
            True if successful
        """
        connector = self.get_shape_by_id(connector_id)
        if not connector or not self._is_connector(connector):
            print(f"Error: Connector '{connector_id}' not found")
            return False
        
        try:
            # Visio routing style values
            routing_map = {
                'straight': '1',      # Direct line
                'right_angle': '16',  # Right-angle routing
                'curved': '2',        # Curved routing
            }
            
            route_value = routing_map.get(routing_style.lower(), '1')
            
            # Check if connector has glue connections
            has_glue = False
            try:
                if hasattr(connector, 'xml') and connector.xml is not None:
                    import xml.etree.ElementTree as ET
                    ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
                    
                    for cell_name in ['BeginX', 'EndX']:
                        cell = connector.xml.find(f'.//v:Cell[@N="{cell_name}"]', ns)
                        if cell is None:
                            cell = connector.xml.find(f'.//Cell[@N="{cell_name}"]')
                        
                        if cell is not None and cell.get('F'):
                            has_glue = True
                            break
            except Exception:
                pass
            
            # Apply routing style
            connector.set_cell_value('ShapeRouteStyle', route_value)
            
            # Enable connector rerouting (safe for glued connectors)
            connector.set_cell_value('ConLineRouteExt', '0')  # Default routing
            
            # For glued connectors, also set ConFixedCode to allow flexible routing
            if has_glue:
                try:
                    # ConFixedCode=0 means fully flexible routing
                    connector.set_cell_value('ConFixedCode', '0')
                except Exception:
                    pass  # Some connectors may not support this
            
            return True
        except Exception as e:
            print(f"Error setting routing style: {e}")
            return False
    
    def batch_replace_shapes(self, match_criteria: Dict[str, Any], template_shape_id: str,
                            preserve_text: bool = True, preserve_connections: bool = True) -> int:
        """
        Replace multiple shapes matching criteria with copies of a template shape.
        
        Args:
            match_criteria: Dictionary with 'text' (str), 'shape_type' (str), or 'master' (str)
            template_shape_id: ID of template shape to copy style from
            preserve_text: If True, keeps original shapes' text
            preserve_connections: If True, preserves all connections
        
        Returns:
            Number of shapes replaced
        """
        if not self.current_page:
            return 0
        
        template_shape = self.get_shape_by_id(template_shape_id)
        if not template_shape:
            print(f"Error: Template shape '{template_shape_id}' not found")
            return 0
        
        shapes_to_replace = []
        
        # Find matching shapes
        for shape in list(self._iter_shapes(self.current_page.child_shapes)):
            if self._is_connector(shape):
                continue
            
            match = False
            
            if 'text' in match_criteria:
                shape_text = (getattr(shape, 'text', '') or '').strip()
                if match_criteria['text'].lower() in shape_text.lower():
                    match = True
            
            if 'shape_type' in match_criteria:
                shape_type = getattr(shape, 'shape_type', '')
                if match_criteria['shape_type'].lower() in shape_type.lower():
                    match = True
            
            if 'master' in match_criteria:
                master = getattr(shape, 'master', None)
                if master:
                    master_name = getattr(master, 'name', '')
                    if match_criteria['master'].lower() in master_name.lower():
                        match = True
            
            if match:
                shapes_to_replace.append(str(getattr(shape, 'ID', '')))
        
        # Replace each matching shape
        replaced_count = 0
        for shape_id in shapes_to_replace:
            new_shape = self.replace_shape(shape_id, template_shape_id, preserve_text, preserve_connections)
            if new_shape:
                replaced_count += 1
        
        return replaced_count
    
    def _find_connected_connectors(self, shape: Any) -> List[Dict[str, Any]]:
        """Find all connectors connected to a shape with their connection details."""
        connected = []
        
        if not self.current_page:
            return connected
        
        shape_id = str(getattr(shape, 'ID', ''))
        
        for connector in self.current_page.child_shapes:
            if not self._is_connector(connector):
                continue
            
            try:
                if hasattr(connector, 'connects') and connector.connects:
                    for conn in connector.connects:
                        connected_shape_id = getattr(conn, 'shape_id', None)
                        from_rel = getattr(conn, 'from_rel', '')
                        
                        if not connected_shape_id:
                            continue
                        
                        connected_shape_id = str(connected_shape_id)
                        
                        # Check if this connection involves our target shape
                        if connected_shape_id == shape_id:
                            connection_info = {
                                'connector': connector,
                                'connector_id': str(connector.ID),
                                'is_source': False,
                                'is_target': False,
                                'other_shape_id': None
                            }
                            
                            # Determine if this is source or target based on from_rel
                            if 'BeginX' in from_rel or 'Begin' in from_rel:
                                # Connector begins at this shape (it's the source)
                                connection_info['is_source'] = True
                                # Find the other end
                                for other_conn in connector.connects:
                                    other_shape_id = getattr(other_conn, 'shape_id', None)
                                    other_rel = getattr(other_conn, 'from_rel', '')
                                    if other_shape_id and ('EndX' in other_rel or 'End' in other_rel):
                                        connection_info['other_shape_id'] = str(other_shape_id)
                                        break
                            elif 'EndX' in from_rel or 'End' in from_rel:
                                # Connector ends at this shape (it's the target)
                                connection_info['is_target'] = True
                                # Find the other end
                                for other_conn in connector.connects:
                                    other_shape_id = getattr(other_conn, 'shape_id', None)
                                    other_rel = getattr(other_conn, 'from_rel', '')
                                    if other_shape_id and ('BeginX' in other_rel or 'Begin' in other_rel):
                                        connection_info['other_shape_id'] = str(other_shape_id)
                                        break
                            
                            connected.append(connection_info)
            except Exception:
                continue
        
        return connected
    
    def analyze_diagram_connections(self, page_index: Optional[int] = None, include_connectors: bool = True) -> Dict[str, Any]:
        """
        Analyze all connections in a diagram page with detailed information.
        
        This method provides comprehensive connection analysis including:
        - Shape IDs and text
        - Connection directions (incoming/outgoing)
        - Connector IDs and text
        - Connection graph structure
        
        Args:
            page_index: Page index to analyze (None for current page)
            include_connectors: Whether to include connector shape details
        
        Returns:
            Dictionary containing:
            - 'page_name': Name of the analyzed page
            - 'shapes': List of shape connection details
            - 'connectors': List of connector details (if include_connectors=True)
            - 'connection_graph': Graph representation of connections
            - 'statistics': Connection statistics
        """
        target_page = self.current_page
        if page_index is not None:
            target_page = self.get_page(page_index)
        
        if not target_page:
            return {
                'error': 'No page available for analysis',
                'page_name': None,
                'shapes': [],
                'connectors': [],
                'connection_graph': {},
                'statistics': {}
            }
        
        page_name = getattr(target_page, 'name', f'Page {page_index or 0}')
        shapes_list = getattr(target_page, 'child_shapes', [])
        
        # Build shape info cache
        shape_info_cache = {}
        connector_list = []
        
        for shape in shapes_list:
            try:
                shape_id = str(getattr(shape, 'ID', ''))
                if not shape_id:
                    continue
                
                # Get shape text safely
                try:
                    shape_text = (getattr(shape, 'text', '') or '').strip()
                except Exception:
                    shape_text = ''
                
                # Get shape type
                try:
                    shape_type = getattr(shape, 'shape_type', 'Unknown')
                    if not shape_type or shape_type == 'Unknown':
                        # Try to infer from master
                        master = getattr(shape, 'master', None)
                        if master:
                            master_name = getattr(master, 'name', '') or ''
                            shape_type = master_name if master_name else 'Unknown'
                except Exception:
                    shape_type = 'Unknown'
                
                is_connector = self._is_connector(shape)
                
                shape_info = {
                    'id': shape_id,
                    'text': shape_text,
                    'type': shape_type,
                    'is_connector': is_connector,
                    'incoming': [],
                    'outgoing': [],
                    'x': None,
                    'y': None
                }
                
                # Get position if available
                try:
                    shape_info['x'] = float(shape.cell_value('PinX') or shape.x or 0)
                    shape_info['y'] = float(shape.cell_value('PinY') or shape.y or 0)
                except Exception:
                    pass
                
                shape_info_cache[shape_id] = shape_info
                
                if is_connector:
                    connector_list.append(shape)
            except Exception:
                continue
        
        # Analyze connections
        connection_graph = {}
        total_connections = 0
        
        for connector in connector_list:
            try:
                connector_id = str(getattr(connector, 'ID', ''))
                # Get connector text safely
                try:
                    connector_text = (getattr(connector, 'text', '') or '').strip()
                except Exception:
                    connector_text = ''
                
                if not hasattr(connector, 'connects') or not connector.connects:
                    continue
                
                from_shape_id = None
                to_shape_id = None
                
                # Use vsdx library's Connect structure properly
                # Each Connect has: shape (connected shape), from_rel (BeginX/EndX), shape_id, connector_shape_id
                for conn in connector.connects:
                    try:
                        # Get the connected shape ID and the connector end
                        connected_shape_id = getattr(conn, 'shape_id', None) or getattr(conn, 'to_id', None)
                        from_rel = getattr(conn, 'from_rel', '')
                        
                        if not connected_shape_id or not from_rel:
                            continue
                        
                        connected_shape_id = str(connected_shape_id)
                        
                        # Skip if not a regular shape
                        if connected_shape_id not in shape_info_cache:
                            continue
                        
                        # from_rel tells us which end of the connector:
                        # BeginX = start of connector (arrow begins here)
                        # EndX = end of connector (arrow ends here)
                        if 'BeginX' in from_rel or 'Begin' in from_rel:
                            from_shape_id = connected_shape_id
                        elif 'EndX' in from_rel or 'End' in from_rel:
                            to_shape_id = connected_shape_id
                    except Exception:
                        continue
                
                if from_shape_id and to_shape_id:
                    # Update shape connection info
                    if from_shape_id in shape_info_cache:
                        conn_detail = {
                            'connector_id': connector_id,
                            'connector_text': connector_text,
                            'target_shape_id': to_shape_id,
                            'target_shape_text': shape_info_cache.get(to_shape_id, {}).get('text', ''),
                            'target_shape_type': shape_info_cache.get(to_shape_id, {}).get('type', 'Unknown')
                        }
                        shape_info_cache[from_shape_id]['outgoing'].append(conn_detail)
                    
                    if to_shape_id in shape_info_cache:
                        conn_detail = {
                            'connector_id': connector_id,
                            'connector_text': connector_text,
                            'source_shape_id': from_shape_id,
                            'source_shape_text': shape_info_cache.get(from_shape_id, {}).get('text', ''),
                            'source_shape_type': shape_info_cache.get(from_shape_id, {}).get('type', 'Unknown')
                        }
                        shape_info_cache[to_shape_id]['incoming'].append(conn_detail)
                    
                    # Build connection graph
                    if from_shape_id not in connection_graph:
                        connection_graph[from_shape_id] = []
                    connection_graph[from_shape_id].append({
                        'to': to_shape_id,
                        'connector_id': connector_id,
                        'connector_text': connector_text
                    })
                    
                    total_connections += 1
                    
            except Exception:
                continue
        
        # Prepare connector details
        connector_details = []
        if include_connectors:
            for connector in connector_list:
                try:
                    connector_id = str(getattr(connector, 'ID', ''))
                    # Get connector text safely
                    try:
                        connector_text = (getattr(connector, 'text', '') or '').strip()
                    except Exception:
                        connector_text = ''
                    
                    from_shape_id = None
                    to_shape_id = None
                    
                    if hasattr(connector, 'connects') and connector.connects:
                        for conn in connector.connects:
                            try:
                                connected_shape_id = getattr(conn, 'shape_id', None) or getattr(conn, 'to_id', None)
                                from_rel = getattr(conn, 'from_rel', '')
                                
                                if not connected_shape_id or not from_rel:
                                    continue
                                
                                connected_shape_id = str(connected_shape_id)
                                
                                if connected_shape_id not in shape_info_cache:
                                    continue
                                
                                if 'BeginX' in from_rel or 'Begin' in from_rel:
                                    from_shape_id = connected_shape_id
                                elif 'EndX' in from_rel or 'End' in from_rel:
                                    to_shape_id = connected_shape_id
                            except Exception:
                                continue
                    
                    connector_details.append({
                        'connector_id': connector_id,
                        'connector_text': connector_text,
                        'from_shape_id': from_shape_id,
                        'from_shape_text': shape_info_cache.get(from_shape_id, {}).get('text', '') if from_shape_id else '',
                        'to_shape_id': to_shape_id,
                        'to_shape_text': shape_info_cache.get(to_shape_id, {}).get('text', '') if to_shape_id else ''
                    })
                except Exception:
                    continue
        
        # Calculate statistics
        shapes_with_incoming = sum(1 for s in shape_info_cache.values() if s['incoming'])
        shapes_with_outgoing = sum(1 for s in shape_info_cache.values() if s['outgoing'])
        shapes_with_both = sum(1 for s in shape_info_cache.values() if s['incoming'] and s['outgoing'])
        isolated_shapes = sum(1 for s in shape_info_cache.values() if not s['incoming'] and not s['outgoing'] and not s['is_connector'])
        
        statistics = {
            'total_shapes': len([s for s in shape_info_cache.values() if not s['is_connector']]),
            'total_connectors': len(connector_list),
            'total_connections': total_connections,
            'shapes_with_incoming': shapes_with_incoming,
            'shapes_with_outgoing': shapes_with_outgoing,
            'shapes_with_both': shapes_with_both,
            'isolated_shapes': isolated_shapes
        }
        
        # Convert shape_info_cache to list (exclude connectors if not requested)
        shapes_detail = []
        for shape_id, info in shape_info_cache.items():
            if not info['is_connector']:
                shapes_detail.append(info)
            elif include_connectors:
                shapes_detail.append(info)
        
        return {
            'page_name': page_name,
            'shapes': shapes_detail,
            'connectors': connector_details,
            'connection_graph': connection_graph,
            'statistics': statistics
        }
    
    def _reconnect_shape(self, old_shape: Any, new_shape: Any, connectors: List[Dict[str, Any]]):
        """Reconnect connectors from old shape to new shape."""
        old_id = str(getattr(old_shape, 'ID', ''))
        new_id = str(getattr(new_shape, 'ID', ''))
        
        for conn_info in connectors:
            try:
                connector = conn_info['connector']
                other_id = conn_info['other_shape_id']
                
                if conn_info['is_source'] and other_id:
                    # Old shape was source, reconnect from new shape to target
                    self.reconnect_shapes(conn_info['connector_id'], new_id, other_id)
                elif conn_info['is_target'] and other_id:
                    # Old shape was target, reconnect from source to new shape
                    self.reconnect_shapes(conn_info['connector_id'], other_id, new_id)
            except Exception as e:
                print(f"Warning: Could not reconnect connector {conn_info.get('connector_id')}: {e}")
                continue
    
    # ===========================
    # PROFESSIONAL FORMATTING
    # ===========================
    
    def _apply_professional_formatting(self, shape: Any, shape_type: str):
        """
        Apply professional formatting to a shape for print-ready quality.
        Implements rules from professional flowchart standards:
        - Minimum 14-16pt font for readability
        - High-contrast colors (dark text on white/light background)
        - Consistent line weights
        - Proper text alignment and margins
        
        NOTE: Only applies font if shape doesn't already have proper CJK font.
        
        Args:
            shape: Shape object to format
            shape_type: Type of shape for context-aware styling
        """
        try:
            # Typography: Only set font if not already set to a CJK-compatible font
            existing_font = shape.cell_value('Char.Font') if hasattr(shape, 'cell_value') else None
            if not existing_font or existing_font.lower() == 'calibri':
                # Apply CJK-compatible font
                shape.set_cell_value('Char.Font', FONT_FAMILY)
            
            # Set font size if not already appropriate
            existing_size = shape.cell_value('Char.Size') if hasattr(shape, 'cell_value') else None
            if not existing_size or 'pt' not in str(existing_size):
                shape.set_cell_value('Char.Size', f'{PREFERRED_FONT_SIZE_PT}pt')
            
            # Text color
            shape.set_cell_value('Char.Color', COLORS['text_color'])
            
            # Text alignment: Center both horizontally and vertically
            shape.set_cell_value('Para.HorzAlign', str(TEXT_ALIGN_HORIZONTAL))
            shape.set_cell_value('VerticalAlign', str(TEXT_ALIGN_VERTICAL))
            
            # Text margins: Small, consistent margins inside shapes
            shape.set_cell_value('LeftMargin', f'{TEXT_MARGIN_IN}in')
            shape.set_cell_value('RightMargin', f'{TEXT_MARGIN_IN}in')
            shape.set_cell_value('TopMargin', f'{TEXT_MARGIN_IN}in')
            shape.set_cell_value('BottomMargin', f'{TEXT_MARGIN_IN}in')
            
            # Line formatting: High-contrast dark lines with consistent weight
            shape.set_cell_value('LineWeight', f'{LINE_WEIGHT_PT}pt')
            shape.set_cell_value('LineColor', COLORS['line_color'])
            shape.set_cell_value('LinePattern', '1')  # Solid line
            
            # Fill color: Context-aware muted colors based on shape type
            fill_color = get_fill_color(shape_type)
            shape.set_cell_value('FillForegnd', fill_color)
            shape.set_cell_value('FillPattern', '1')  # Solid fill
            
            # Remove gradients for print clarity
            shape.set_cell_value('FillBkgnd', fill_color)
            
            # Ensure text is fully visible (auto-size if needed)
            shape.set_cell_value('TxtWidth', 'Width*1')
            shape.set_cell_value('TxtHeight', 'Height*1')
            
        except Exception as e:
            # Non-critical: log but don't fail shape creation
            print(f"Note: Could not apply all professional formatting: {e}")
    
    def apply_orthogonal_routing(self, connector_id: str) -> bool:
        """
        Apply orthogonal (right-angle) routing to a connector for professional flowcharts.
        This is the BEST routing style for flowcharts as it creates clean 90-degree angles.
        
        Enhanced with validation to prevent breaking glued connections.
        
        Args:
            connector_id: ID of the connector to route
        
        Returns:
            True if successful, False if routing would break connections
        """
        connector = self.get_shape_by_id(connector_id)
        if not connector or not self._is_connector(connector):
            return False
        
        # Check if connector has glue formulas - if so, be very careful
        has_glue = False
        try:
            if hasattr(connector, 'xml') and connector.xml is not None:
                import xml.etree.ElementTree as ET
                ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
                
                # Check for glue formulas in BeginX/EndX cells
                for cell_name in ['BeginX', 'EndX', 'BeginY', 'EndY']:
                    cell = connector.xml.find(f'.//v:Cell[@N="{cell_name}"]', ns)
                    if cell is None:
                        cell = connector.xml.find(f'.//Cell[@N="{cell_name}"]')
                    
                    if cell is not None and cell.get('F'):
                        # Has formula - this is a glued connection
                        has_glue = True
                        break
        except Exception:
            pass
        
        # Only apply routing if safe to do so
        # Glued connectors should route automatically when shapes move
        if has_glue:
            # For glued connectors, we can safely set the routing style
            # without modifying endpoints
            try:
                connector.set_cell_value('ShapeRouteStyle', '16')  # Orthogonal
                connector.set_cell_value('ConLineRouteExt', '0')  # Default routing
                return True
            except Exception:
                return False
        else:
            # For non-glued connectors, use the standard routing
            return self.auto_route_connector(connector_id, DEFAULT_ROUTING_STYLE)
    
    def align_shapes_horizontal(self, shape_ids: List[str], alignment: str = 'center') -> bool:
        """
        Align multiple shapes horizontally (same Y coordinate).
        
        Args:
            shape_ids: List of shape IDs or keys to align
            alignment: 'top', 'center', or 'bottom'
        
        Returns:
            True if successful
        """
        if not self.current_page:
            print("Error: No current page set")
            return False
        
        if len(shape_ids) < 2:
            print(f"Error: Need at least 2 shape IDs, got {len(shape_ids)}")
            return False
        
        # Get all shapes, filtering out connectors
        shapes = []
        for sid in shape_ids:
            shape = self._resolve_shape_identifier(sid)
            if shape and not self._is_connector(shape):
                shapes.append(shape)
            elif shape is None:
                print(f"Warning: Shape ID or key '{sid}' not found")
            elif self._is_connector(shape):
                print(f"Warning: Shape ID or key '{sid}' is a connector, skipping")
        
        if len(shapes) < 2:
            print(f"Error: Found only {len(shapes)} valid non-connector shapes out of {len(shape_ids)} IDs")
            return False
        
        try:
            # Calculate reference Y position
            if alignment == 'top':
                # Align to highest shape (largest Y + height/2)
                ref_y = max(float(s.y or 0) + float(s.height or 0) / 2 for s in shapes)
            elif alignment == 'bottom':
                # Align to lowest shape (smallest Y - height/2)
                ref_y = min(float(s.y or 0) - float(s.height or 0) / 2 for s in shapes)
            else:  # center
                # Align to average center Y
                ref_y = sum(float(s.y or 0) for s in shapes) / len(shapes)
            
            # Snap to grid
            ref_y = snap_to_grid(ref_y)
            
            # Apply alignment
            for shape in shapes:
                shape.y = ref_y
            
            return True
            
        except Exception as e:
            print(f"Error aligning shapes horizontally: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def align_shapes_vertical(self, shape_ids: List[str], alignment: str = 'center') -> bool:
        """
        Align multiple shapes vertically (same X coordinate).
        
        Args:
            shape_ids: List of shape IDs or keys to align
            alignment: 'left', 'center', or 'right'
        
        Returns:
            True if successful
        """
        if not self.current_page:
            print("Error: No current page set")
            return False
        
        if len(shape_ids) < 2:
            print(f"Error: Need at least 2 shape IDs, got {len(shape_ids)}")
            return False
        
        # Get all shapes, filtering out connectors
        shapes = []
        for sid in shape_ids:
            shape = self._resolve_shape_identifier(sid)
            if shape and not self._is_connector(shape):
                shapes.append(shape)
            elif shape is None:
                print(f"Warning: Shape ID or key '{sid}' not found")
            elif self._is_connector(shape):
                print(f"Warning: Shape ID or key '{sid}' is a connector, skipping")
        
        if len(shapes) < 2:
            print(f"Error: Found only {len(shapes)} valid non-connector shapes out of {len(shape_ids)} IDs")
            return False
        
        try:
            # Calculate reference X position
            if alignment == 'left':
                # Align to leftmost shape (smallest X - width/2)
                ref_x = min(float(s.x or 0) - float(s.width or 0) / 2 for s in shapes)
            elif alignment == 'right':
                # Align to rightmost shape (largest X + width/2)
                ref_x = max(float(s.x or 0) + float(s.width or 0) / 2 for s in shapes)
            else:  # center
                # Align to average center X
                ref_x = sum(float(s.x or 0) for s in shapes) / len(shapes)
            
            # Snap to grid
            ref_x = snap_to_grid(ref_x)
            
            # Apply alignment
            for shape in shapes:
                shape.x = ref_x
            
            return True
            
        except Exception as e:
            print(f"Error aligning shapes vertically: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def distribute_shapes_horizontal(self, shape_ids: List[str], spacing: float = MIN_SHAPE_SPACING_IN) -> bool:
        """
        Distribute shapes evenly with consistent horizontal spacing.
        
        Args:
            shape_ids: List of shape IDs or keys to distribute (left to right)
            spacing: Spacing between shapes in inches
        
        Returns:
            True if successful
        """
        if not self.current_page:
            print("Error: No current page set")
            return False
        
        if len(shape_ids) < 2:
            print(f"Error: Need at least 2 shape IDs, got {len(shape_ids)}")
            return False
        
        # Get all shapes, filtering out connectors
        shapes = []
        for sid in shape_ids:
            shape = self._resolve_shape_identifier(sid)
            if shape and not self._is_connector(shape):
                shapes.append(shape)
            elif shape is None:
                print(f"Warning: Shape ID or key '{sid}' not found")
            elif self._is_connector(shape):
                print(f"Warning: Shape ID or key '{sid}' is a connector, skipping")
        
        if len(shapes) < 2:
            print(f"Error: Found only {len(shapes)} valid non-connector shapes out of {len(shape_ids)} IDs")
            return False
        
        try:
            # Sort shapes by current X position
            shapes.sort(key=lambda s: float(s.x or 0))
            
            # Calculate starting X from first shape
            current_x = float(shapes[0].x or 0)
            
            # Distribute with consistent spacing
            for i, shape in enumerate(shapes):
                if i == 0:
                    continue  # Keep first shape in place
                
                # Calculate new position with spacing
                prev_shape = shapes[i-1]
                prev_width = float(prev_shape.width or 1.5)
                curr_width = float(shape.width or 1.5)
                
                current_x = current_x + prev_width/2 + spacing + curr_width/2
                current_x = snap_to_grid(current_x)
                
                shape.x = current_x
            
            return True
            
        except Exception as e:
            print(f"Error distributing shapes horizontally: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def distribute_shapes_vertical(self, shape_ids: List[str], spacing: float = MIN_SHAPE_SPACING_IN) -> bool:
        """
        Distribute shapes evenly with consistent vertical spacing.
        
        Args:
            shape_ids: List of shape IDs or keys to distribute (top to bottom)
            spacing: Spacing between shapes in inches
        
        Returns:
            True if successful
        """
        if not self.current_page:
            print("Error: No current page set")
            return False
        
        if len(shape_ids) < 2:
            print(f"Error: Need at least 2 shape IDs, got {len(shape_ids)}")
            return False
        
        # Get all shapes, filtering out connectors
        shapes = []
        for sid in shape_ids:
            shape = self._resolve_shape_identifier(sid)
            if shape and not self._is_connector(shape):
                shapes.append(shape)
            elif shape is None:
                print(f"Warning: Shape ID or key '{sid}' not found")
            elif self._is_connector(shape):
                print(f"Warning: Shape ID or key '{sid}' is a connector, skipping")
        
        if len(shapes) < 2:
            print(f"Error: Found only {len(shapes)} valid non-connector shapes out of {len(shape_ids)} IDs")
            return False
        
        try:
            # Sort shapes by current Y position (top to bottom = high to low Y)
            shapes.sort(key=lambda s: float(s.y or 0), reverse=True)
            
            # Calculate starting Y from first shape
            current_y = float(shapes[0].y or 0)
            
            # Distribute with consistent spacing
            for i, shape in enumerate(shapes):
                if i == 0:
                    continue  # Keep first shape in place
                
                # Calculate new position with spacing
                prev_shape = shapes[i-1]
                prev_height = float(prev_shape.height or 0.75)
                curr_height = float(shape.height or 0.75)
                
                current_y = current_y - prev_height/2 - spacing - curr_height/2
                current_y = snap_to_grid(current_y)
                
                shape.y = current_y
            
            return True
            
        except Exception as e:
            print(f"Error distributing shapes vertically: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def center_drawing_on_page(self) -> bool:
        """
        Center all shapes on the page for professional presentation.
        
        IMPORTANT: This function preserves connector glue relationships to avoid breaking connections.
        Only coordinate-based (non-glued) connectors are offset along with shapes.
        
        Returns:
            True if successful
        """
        if not self.current_page:
            print("Error: No current page set")
            return False
        
        try:
            from .layout_config import PAGE_WIDTH_IN, PAGE_HEIGHT_IN
            
            # Get all non-connector shapes
            all_shapes = list(self.current_page.child_shapes)
            shapes = []
            for shape in all_shapes:
                if not self._is_connector(shape):
                    shapes.append(shape)
            
            if not shapes:
                print(f"Error: No non-connector shapes found (total shapes: {len(all_shapes)})")
                # Debug: print what types of shapes we have
                for s in all_shapes[:5]:  # Show first 5 as sample
                    try:
                        shape_text = getattr(s, 'text', '')
                        print(f"  Shape ID {getattr(s, 'ID', '?')}: type={getattr(s, 'shape_type', '?')}, "
                              f"width={getattr(s, 'width', '?')}, height={getattr(s, 'height', '?')}, "
                              f"text='{shape_text}'")
                    except:
                        pass
                return False
            
            # Calculate bounding box
            min_x = min(float(s.x or 0) - float(s.width or 0)/2 for s in shapes)
            max_x = max(float(s.x or 0) + float(s.width or 0)/2 for s in shapes)
            min_y = min(float(s.y or 0) - float(s.height or 0)/2 for s in shapes)
            max_y = max(float(s.y or 0) + float(s.height or 0)/2 for s in shapes)
            
            # Calculate offset to center
            drawing_width = max_x - min_x
            drawing_height = max_y - min_y
            
            offset_x = (PAGE_WIDTH_IN - drawing_width) / 2 - min_x
            offset_y = (PAGE_HEIGHT_IN - drawing_height) / 2 - min_y
            
            # Apply offset to all shapes first
            for shape in shapes:
                current_x = float(shape.x or 0)
                current_y = float(shape.y or 0)
                
                shape.x = current_x + offset_x
                shape.y = current_y + offset_y
            
            # Handle connectors: only offset those without glue formulas
            # Connectors with glue formulas will automatically follow their connected shapes
            for shape in all_shapes:
                if not self._is_connector(shape):
                    continue
                
                # Check if connector has glue formulas (indicated by formula attribute 'F')
                has_glue = False
                try:
                    if hasattr(shape, 'xml') and shape.xml is not None:
                        import xml.etree.ElementTree as ET
                        ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
                        
                        # Check for glue formulas in BeginX/EndX cells
                        for cell_name in ['BeginX', 'EndX']:
                            cell = shape.xml.find(f'.//v:Cell[@N="{cell_name}"]', ns)
                            if cell is None:
                                cell = shape.xml.find(f'.//Cell[@N="{cell_name}"]')
                            
                            if cell is not None and cell.get('F'):
                                # Has formula - this is a glued connection
                                has_glue = True
                                break
                except Exception:
                    # If we can't determine, assume it has glue to be safe
                    has_glue = True
                
                # Only offset coordinate-based (non-glued) connectors
                if not has_glue:
                    try:
                        current_x = float(shape.x or 0)
                        current_y = float(shape.y or 0)
                        
                        shape.x = current_x + offset_x
                        shape.y = current_y + offset_y
                    except Exception:
                        # Skip connectors that can't be offset
                        pass
            
            return True
            
        except Exception as e:
            print(f"Error centering drawing: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def check_content_bounds(self) -> Dict[str, Any]:
        """
        Check if content fits within current page boundaries and return boundary info.
        
        Returns:
            Dictionary with:
            - 'fits': bool - whether content fits within page
            - 'content_width': float - actual content width in inches
            - 'content_height': float - actual content height in inches
            - 'page_width': float - current page width
            - 'page_height': float - current page height
            - 'overflow_x': float - horizontal overflow (0 if fits)
            - 'overflow_y': float - vertical overflow (0 if fits)
            - 'min_x', 'max_x', 'min_y', 'max_y': content boundaries
        """
        if not self.current_page:
            return {'fits': False, 'error': 'No current page set'}
        
        try:
            # Get current page dimensions
            page_width = float(self.current_page.width)
            page_height = float(self.current_page.height)
            
            # Get all non-connector shapes
            all_shapes = list(self.current_page.child_shapes)
            shapes = [s for s in all_shapes if not self._is_connector(s)]
            
            if not shapes:
                return {
                    'fits': True,
                    'content_width': 0,
                    'content_height': 0,
                    'page_width': page_width,
                    'page_height': page_height,
                    'overflow_x': 0,
                    'overflow_y': 0,
                    'error': 'No shapes to measure'
                }
            
            # Calculate content bounding box
            min_x = min(float(s.x or 0) - float(s.width or 0)/2 for s in shapes)
            max_x = max(float(s.x or 0) + float(s.width or 0)/2 for s in shapes)
            min_y = min(float(s.y or 0) - float(s.height or 0)/2 for s in shapes)
            max_y = max(float(s.y or 0) + float(s.height or 0)/2 for s in shapes)
            
            content_width = max_x - min_x
            content_height = max_y - min_y
            
            # Check if content exceeds page boundaries
            overflow_x = max(0, max_x - page_width, -min_x)
            overflow_y = max(0, max_y - page_height, -min_y)
            
            return {
                'fits': overflow_x == 0 and overflow_y == 0,
                'content_width': content_width,
                'content_height': content_height,
                'page_width': page_width,
                'page_height': page_height,
                'overflow_x': overflow_x,
                'overflow_y': overflow_y,
                'min_x': min_x,
                'max_x': max_x,
                'min_y': min_y,
                'max_y': max_y,
            }
            
        except Exception as e:
            return {'fits': False, 'error': str(e)}
    
    def auto_fit_page_to_content(self) -> bool:
        """
        Automatically adjust page size to fit all content (like Visio's "Fit to Drawing" feature).
        Adds margins around content and respects min/max page size constraints.
        
        Returns:
            True if successful, False otherwise
        """
        if not self.current_page:
            print("Error: No current page set")
            return False
        
        try:
            from .layout_config import AUTO_FIT_MARGIN_IN, MIN_PAGE_SIZE_IN, MAX_PAGE_SIZE_IN
            
            # Get all non-connector shapes
            all_shapes = list(self.current_page.child_shapes)
            shapes = [s for s in all_shapes if not self._is_connector(s)]
            
            if not shapes:
                print("Warning: No shapes to fit - keeping default page size")
                return False
            
            # Calculate content bounding box
            min_x = min(float(s.x or 0) - float(s.width or 0)/2 for s in shapes)
            max_x = max(float(s.x or 0) + float(s.width or 0)/2 for s in shapes)
            min_y = min(float(s.y or 0) - float(s.height or 0)/2 for s in shapes)
            max_y = max(float(s.y or 0) + float(s.height or 0)/2 for s in shapes)
            
            # Calculate required page size with margins
            content_width = max_x - min_x
            content_height = max_y - min_y
            
            new_width = content_width + 2 * AUTO_FIT_MARGIN_IN
            new_height = content_height + 2 * AUTO_FIT_MARGIN_IN
            
            # Apply constraints
            new_width = max(MIN_PAGE_SIZE_IN, min(MAX_PAGE_SIZE_IN, new_width))
            new_height = max(MIN_PAGE_SIZE_IN, min(MAX_PAGE_SIZE_IN, new_height))
            
            # Set page dimensions using vsdx library's width and height properties
            # The vsdx library provides direct access to page dimensions as float attributes
            self.current_page.width = new_width
            self.current_page.height = new_height
            
            print(f"[OK] Page auto-fitted to {new_width:.2f} x {new_height:.2f} inches")
            print(f"  Content: {content_width:.2f} x {content_height:.2f} inches")
            print(f"  Margin: {AUTO_FIT_MARGIN_IN} inches")
            return True
                
        except Exception as e:
            print(f"Error auto-fitting page: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    # ===========================
    # IDEMPOTENT OPERATIONS
    # ===========================
    
    def add_or_update_shape(self, node_key: str, text: str, shape_type: str,
                           x: float, y: float, width: float = 1.5, height: float = 0.75,
                           use_professional_formatting: bool = False) -> Tuple[Optional[Any], str]:
        """
        Idempotent shape operation: Add new shape or update existing one based on node_key.
        
        This is the RECOMMENDED method for creating diagrams that can be safely re-run.
        Uses node_key as stable identity to prevent duplicate shapes on re-execution.
        
        Args:
            node_key: Unique identifier for this logical node (required)
            text: Text to display in the shape
            shape_type: Type of shape (Rectangle, Diamond, etc.)
            x, y: Position coordinates (in inches)
            width, height: Shape dimensions (in inches)
            use_professional_formatting: Apply professional typography, colors, and layout.
                Default False preserves template formatting (RECOMMENDED for Chinese text).
                Set True only when creating diagrams from scratch without good templates.
        
        Returns:
            Tuple of (shape object or None, action taken: "added" | "updated" | "replaced")
        
        Example:
            shape, action = builder.add_or_update_shape(
                node_key="node_1",
                text="Process Step",
                shape_type="Rectangle",
                x=4.0, y=5.0
            )
            print(f"Shape {action}")  # "added", "updated", or "replaced"
        """
        if not self.current_page:
            print("Error: No current page set")
            return None, "error"
        
        # Index existing shapes by key
        nodes_by_key, _ = index_shapes_by_key(self.current_page, self)
        
        existing_shape = nodes_by_key.get(node_key)
        
        if existing_shape:
            # Shape exists - check if we need to replace it
            existing_type = self._get_master_key(existing_shape)
            desired_type = shape_type
            
            # Check if shape type matches closely enough
            needs_replacement = not self._shape_types_compatible(existing_shape, shape_type)
            
            if needs_replacement:
                # Replace with new shape type
                new_shape = self._replace_shape_preserving_connections(
                    existing_shape, shape_type, text, x, y, width, height, use_professional_formatting
                )
                if new_shape:
                    success = set_shape_prop(new_shape, 'NodeKey', node_key)
                    if not success:
                        print(f"Warning: Failed to set NodeKey '{node_key}' on replaced shape ID {getattr(new_shape, 'ID', '?')}")
                    return new_shape, "replaced"
                else:
                    return None, "error"
            else:
                # Update in place
                self._update_shape_properties(
                    existing_shape, text, x, y, width, height, use_professional_formatting
                )
                return existing_shape, "updated"
        else:
            # Shape doesn't exist - try fallback matching (text-equality first)
            fallback_shape = find_shape_by_fallback(
                self.current_page, self, text, x, y, shape_type
            )

            if fallback_shape is None:
                # Second fallback: adopt the nearest *unkeyed* shape within 0.5 in
                # of the requested position regardless of its text.  This prevents
                # creating duplicate shapes on top of empty template placeholders.
                ADOPT_RADIUS = 0.5  # inches
                best: Optional[Any] = None
                best_dist = float("inf")
                for candidate in self.current_page.child_shapes:
                    try:
                        if self._is_connector(candidate):
                            continue
                        existing_key = get_shape_prop(candidate, "NodeKey")
                        if existing_key:
                            continue  # already keyed – leave it alone
                        cx = float(getattr(candidate, "x", None) or 0)
                        cy = float(getattr(candidate, "y", None) or 0)
                        dist = ((cx - x) ** 2 + (cy - y) ** 2) ** 0.5
                        if dist < ADOPT_RADIUS and dist < best_dist:
                            best = candidate
                            best_dist = dist
                    except Exception:
                        continue
                if best is not None:
                    fallback_shape = best
                    print(
                        f"Info: Positional adoption of unkeyed shape ID "
                        f"{getattr(best, 'ID', '?')} (dist={best_dist:.2f} in) "
                        f"for node_key='{node_key}'"
                    )

            if fallback_shape:
                # Found a matching shape without key - adopt it
                success = set_shape_prop(fallback_shape, 'NodeKey', node_key)
                if not success:
                    print(f"Warning: Failed to set NodeKey '{node_key}' on adopted shape ID {getattr(fallback_shape, 'ID', '?')}")
                self._update_shape_properties(
                    fallback_shape, text, x, y, width, height, use_professional_formatting
                )
                return fallback_shape, "adopted"
            else:
                # Create new shape
                new_shape = self.add_shape(text, shape_type, x, y, width, height, use_professional_formatting)
                if new_shape:
                    success = set_shape_prop(new_shape, 'NodeKey', node_key)
                    if not success:
                        print(f"Warning: Failed to set NodeKey '{node_key}' on shape ID {getattr(new_shape, 'ID', '?')}")
                        print(f"Shape type: {self._get_master_key(new_shape)}, Text: {text}")
                    return new_shape, "added"
                else:
                    return None, "error"
    
    def add_or_update_connector(self, edge_key: str, from_node_key: str, to_node_key: str,
                               label: str = "", routing_style: str = "right_angle",
                               from_glue_point: Optional[str] = None, 
                               to_glue_point: Optional[str] = None) -> Tuple[Optional[Any], str]:
        """
        Idempotent connector operation: Add new connector or update existing one based on edge_key.
        Now supports precise connection points for enhanced connector placement.
        
        Args:
            edge_key: Unique identifier for this connector (use compute_edge_key helper)
            from_node_key: Source node key
            to_node_key: Target node key
            label: Optional text label for the connector
            routing_style: Routing style ('straight', 'right_angle', 'curved')
            from_glue_point: Optional connection point on source shape (e.g., 'Right', 'Top')
            to_glue_point: Optional connection point on target shape (e.g., 'Left', 'Bottom')
        
        Returns:
            Tuple of (connector object or None, action taken: "added" | "updated" | "error")
        """
        # Import at function start to avoid UnboundLocalError
        from .shape_identity import get_shape_prop, set_shape_prop
        
        if not self.current_page:
            print("Error: No current page set")
            return None, "error"
        
        # Index existing shapes and connectors by key
        nodes_by_key, edges_by_key = index_shapes_by_key(self.current_page, self)
        
        # Get source and target shapes
        from_shape = nodes_by_key.get(from_node_key)
        to_shape = nodes_by_key.get(to_node_key)
        
        # CRITICAL FIX: If shapes not found by key, try to find and assign keys
        if not from_shape:
            # Try to find shape without key and assign the key
            print(f"Info: Source node '{from_node_key}' not found by key. Searching for unkeyed shapes...")
            
            # Look for shapes without NodeKey that might match
            for shape in self.current_page.child_shapes:
                if not self._is_connector(shape) and not get_shape_prop(shape, 'NodeKey'):
                    # Check if this could be our target shape by text content
                    shape_text = getattr(shape, 'text', '').strip()
                    if shape_text and (from_node_key.lower() in shape_text.lower() or 
                                     shape_text.lower() in from_node_key.lower()):
                        # Found a potential match - assign the key
                        print(f"  Found potential match: Shape ID {shape.ID} with text '{shape_text}'")
                        set_shape_prop(shape, 'NodeKey', from_node_key)
                        from_shape = shape
                        nodes_by_key[from_node_key] = shape
                        print(f"  [OK] Assigned NodeKey '{from_node_key}' to shape ID {shape.ID}")
                        break
            
            # If still not found, check recently added shapes
            if not from_shape:
                # Get the most recent shapes (last few added)
                recent_shapes = [s for s in self.current_page.child_shapes 
                               if not self._is_connector(s)][-10:]  # Last 10 shapes
                for shape in recent_shapes:
                    if not get_shape_prop(shape, 'NodeKey'):
                        print(f"  Checking recent shape ID {shape.ID} with text '{getattr(shape, 'text', '')}' for key '{from_node_key}'")
                        # Ask user or auto-assign based on some heuristic
                        set_shape_prop(shape, 'NodeKey', from_node_key)
                        from_shape = shape
                        nodes_by_key[from_node_key] = shape
                        print(f"  [OK] Assigned NodeKey '{from_node_key}' to recent shape ID {shape.ID}")
                        break
        
        if not to_shape:
            # Try to find shape without key and assign the key
            print(f"Info: Target node '{to_node_key}' not found by key. Searching for unkeyed shapes...")
            
            # Look for shapes without NodeKey that might match
            for shape in self.current_page.child_shapes:
                if not self._is_connector(shape) and not get_shape_prop(shape, 'NodeKey'):
                    # Check if this could be our target shape by text content
                    shape_text = getattr(shape, 'text', '').strip()
                    if shape_text and (to_node_key.lower() in shape_text.lower() or 
                                     shape_text.lower() in to_node_key.lower()):
                        # Found a potential match - assign the key
                        print(f"  Found potential match: Shape ID {shape.ID} with text '{shape_text}'")
                        set_shape_prop(shape, 'NodeKey', to_node_key)
                        to_shape = shape
                        nodes_by_key[to_node_key] = shape
                        print(f"  [OK] Assigned NodeKey '{to_node_key}' to shape ID {shape.ID}")
                        break
            
            # If still not found, check recently added shapes
            if not to_shape:
                # Get the most recent shapes (last few added)
                recent_shapes = [s for s in self.current_page.child_shapes 
                               if not self._is_connector(s)][-10:]  # Last 10 shapes
                for shape in recent_shapes:
                    if not get_shape_prop(shape, 'NodeKey'):
                        print(f"  Checking recent shape ID {shape.ID} with text '{getattr(shape, 'text', '')}' for key '{to_node_key}'")
                        # Ask user or auto-assign based on some heuristic
                        set_shape_prop(shape, 'NodeKey', to_node_key)
                        to_shape = shape
                        nodes_by_key[to_node_key] = shape
                        print(f"  [OK] Assigned NodeKey '{to_node_key}' to recent shape ID {shape.ID}")
                        break
        
        if not from_shape:
            available_keys = list(nodes_by_key.keys())
            print(f"Error: Source node '{from_node_key}' not found. Available node keys: {available_keys}")
            print(f"Hint: Ensure the node is created with add_or_update_shape() before connecting it.")
            return None, "error"
        if not to_shape:
            available_keys = list(nodes_by_key.keys())
            print(f"Error: Target node '{to_node_key}' not found. Available node keys: {available_keys}")
            print(f"Hint: Ensure the node is created with add_or_update_shape() before connecting it.")
            return None, "error"
        
        from_shape_id = str(getattr(from_shape, 'ID', ''))
        to_shape_id = str(getattr(to_shape, 'ID', ''))
        
        existing_connector = edges_by_key.get(edge_key)
        
        # If not found by exact edge key, look for any connector between same nodes
        if not existing_connector:
            # Try to find any existing connector between these nodes, regardless of label
            base_key = compute_edge_key(from_node_key, to_node_key, "")  # Edge key without label
            for key, connector in edges_by_key.items():
                if key.startswith(base_key):
                    existing_connector = connector
                    break
        
        if existing_connector:
            # Update existing connector
            if label:
                try:
                    # For connectors, we need to create/update the Text element in XML
                    if hasattr(existing_connector, 'xml') and existing_connector.xml is not None:
                        import xml.etree.ElementTree as ET
                        ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
                        
                        # Find or create Text element
                        text_elem = existing_connector.xml.find('.//v:Text', ns)
                        if text_elem is None:
                            text_elem = existing_connector.xml.find('.//Text')
                        
                        if text_elem is None:
                            # Create Text element
                            text_elem = ET.SubElement(existing_connector.xml, '{http://schemas.microsoft.com/office/visio/2012/main}Text')
                        
                        text_elem.text = label
                    else:
                        # Fallback to property assignment
                        existing_connector.text = label
                except Exception as e:
                    print(f"Warning: Failed to set connector label: {e}")
            
            # Update EdgeKey property to match new label
            set_shape_prop(existing_connector, 'EdgeKey', edge_key)
            
            # Ensure it's still connected correctly with glue, applying glue points
            reconnect_success = self.reconnect_shapes(
                str(getattr(existing_connector, 'ID', '')), 
                from_shape_id, 
                to_shape_id,
                from_glue_point,
                to_glue_point
            )
            if not reconnect_success:
                print(f"Warning: Failed to reconnect existing connector, but continuing...")
            # Update routing after ensuring glue connection
            self.auto_route_connector(str(getattr(existing_connector, 'ID', '')), routing_style)
            
            # Re-set label after routing (routing might clear it)
            if label:
                try:
                    # For connectors, we need to create/update the Text element in XML
                    if hasattr(existing_connector, 'xml') and existing_connector.xml is not None:
                        import xml.etree.ElementTree as ET
                        ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
                        
                        # Find or create Text element
                        text_elem = existing_connector.xml.find('.//v:Text', ns)
                        if text_elem is None:
                            text_elem = existing_connector.xml.find('.//Text')
                        
                        if text_elem is None:
                            # Create Text element
                            text_elem = ET.SubElement(existing_connector.xml, '{http://schemas.microsoft.com/office/visio/2012/main}Text')
                        
                        text_elem.text = label
                    else:
                        # Fallback to property assignment
                        existing_connector.text = label
                except Exception as e:
                    print(f"Warning: Failed to re-set connector label after routing: {e}")
            
            # Verify the connector still has proper glue connections after update
            from_shape = nodes_by_key.get(from_node_key)
            to_shape = nodes_by_key.get(to_node_key)
            if from_shape and to_shape:
                if not self._verify_connector_glue(existing_connector, from_shape, to_shape):
                    print(f"Warning: Connector glue verification failed after update")
            
            return existing_connector, "updated"
        else:
            # Create new connector
            new_connector = self.connect_shapes(from_shape_id, to_shape_id, 
                                              from_glue_point, to_glue_point)
            
            # Validate connector was created (connect_shapes now returns connector object or None)
            if new_connector is None:
                print(f"Error: Failed to create connector between {from_node_key} and {to_node_key}")
                return None, "error"
            
            # Note: Skip _is_connector check here - we just created it programmatically
            # The vsdx.Connect.create() or manual creation guarantees it's a connector
            # Checking again can fail due to cache/master issues
            
            # Set the edge key
            set_shape_prop(new_connector, 'EdgeKey', edge_key)
            
            # Verify edge key was set
            verify_key = get_shape_prop(new_connector, 'EdgeKey')
            if verify_key != edge_key:
                print(f"Warning: Edge key verification failed. Expected '{edge_key}', got '{verify_key}'")
            
            # Set label if provided
            if label:
                try:
                    # For connectors, we need to create/update the Text element in XML
                    if hasattr(new_connector, 'xml') and new_connector.xml is not None:
                        import xml.etree.ElementTree as ET
                        ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
                        
                        # Find or create Text element
                        text_elem = new_connector.xml.find('.//v:Text', ns)
                        if text_elem is None:
                            text_elem = new_connector.xml.find('.//Text')
                        
                        if text_elem is None:
                            # Create Text element
                            text_elem = ET.SubElement(new_connector.xml, '{http://schemas.microsoft.com/office/visio/2012/main}Text')
                        
                        text_elem.text = label
                    else:
                        # Fallback to property assignment
                        new_connector.text = label
                except Exception as e:
                    print(f"Warning: Failed to set connector label: {e}")
            
            # Apply routing style - use connector object directly instead of looking up by ID
            try:
                if routing_style and routing_style != 'straight':
                    # Apply routing directly to the connector object
                    if hasattr(new_connector, 'set_cell_value'):
                        if routing_style == 'right_angle':
                            new_connector.set_cell_value('ShapeRouteStyle', '16')  # Orthogonal
                            new_connector.set_cell_value('ConLineRouteExt', '0')  # Default routing
                        elif routing_style == 'curved':
                            new_connector.set_cell_value('ShapeRouteStyle', '17')  # Curved
                        print(f"[OK] Applied {routing_style} routing style to connector")
                    else:
                        print(f"Warning: Cannot set routing style - connector lacks set_cell_value method")
                else:
                    print(f"[OK] Using straight routing (no routing applied)")
            except Exception as routing_error:
                print(f"Warning: Failed to apply routing style '{routing_style}': {routing_error}")
            
            # CRITICAL FIX: Force save after connector creation to ensure persistence
            # This addresses the issue where connectors appear created but don't show in Visio
            try:
                # First, ensure the connector is properly indexed
                if hasattr(self.current_page, '_shapes'):
                    # Access private shapes to force re-indexing
                    _ = len(self.current_page._shapes)
                
                # Force save to temporary memory to commit changes
                if hasattr(self.visio_file, 'save_in_memory'):
                    print("Force saving connector to memory...")
                    self.visio_file.save_in_memory()
                    
                # Alternative: Mark the file as modified to ensure save commits changes
                if hasattr(self.visio_file, '_modified'):
                    self.visio_file._modified = True
                    
            except Exception as persist_error:
                print(f"Warning: Could not force persist connector: {persist_error}")
                # Continue anyway - connector might still work
            
            # CRITICAL FIX: Force connector visibility by setting proper line properties
            try:
                connector_id = str(getattr(new_connector, 'ID', ''))
                if hasattr(new_connector, 'set_cell_value'):
                    # Ensure connector has visible line properties
                    new_connector.set_cell_value('LineWeight', '0.01388889')  # 1pt
                    new_connector.set_cell_value('LineColor', '0')  # Black
                    new_connector.set_cell_value('LinePattern', '1')  # Solid
                    new_connector.set_cell_value('EndArrow', '4')  # Arrow head
                    new_connector.set_cell_value('LineColorTrans', '0')  # No transparency
                    print(f"Set line properties for connector {connector_id}")
            except Exception as line_prop_error:
                print(f"Warning: Failed to set line properties: {line_prop_error}")
            
            # Re-set label after routing (routing might clear it)
            if label:
                try:
                    # For connectors, we need to create/update the Text element in XML
                    if hasattr(new_connector, 'xml') and new_connector.xml is not None:
                        import xml.etree.ElementTree as ET
                        ns = {'v': 'http://schemas.microsoft.com/office/visio/2012/main'}
                        
                        # Find or create Text element
                        text_elem = new_connector.xml.find('.//v:Text', ns)
                        if text_elem is None:
                            text_elem = new_connector.xml.find('.//Text')
                        
                        if text_elem is None:
                            # Create Text element
                            text_elem = ET.SubElement(new_connector.xml, '{http://schemas.microsoft.com/office/visio/2012/main}Text')
                        
                        text_elem.text = label
                    else:
                        # Fallback to property assignment
                        new_connector.text = label
                except Exception as e:
                    print(f"Warning: Failed to re-set connector label after routing: {e}")
            
            # Final verification: check connector is in edges_by_key
            # Note: This is informational only - connector exists even if not indexed yet
            try:
                nodes_by_key_verify, edges_by_key_verify = index_shapes_by_key(self.current_page, self)
                if edge_key not in edges_by_key_verify:
                    print(f"Info: Connector created but not yet in edge index (will be indexed on next operation)")
            except Exception as index_error:
                print(f"Info: Could not verify edge index: {index_error}")
            
            # VISIBILITY CHECK: Verify connector will be visible in Visio
            try:
                visibility_result = self.verify_connector_visibility(new_connector)
                if not visibility_result['visible']:
                    print(f"[WARN]  WARNING: Connector may not be visible! Issues: {visibility_result['issues']}")
                    # Try to fix visibility issues
                    if hasattr(new_connector, 'set_cell_value'):
                        new_connector.set_cell_value('LinePattern', '1')  # Solid line
                        new_connector.set_cell_value('LineWeight', '0.01388889')  # 1pt
                        new_connector.set_cell_value('Transparency', '0')  # Fully opaque
                        print(f"  Applied visibility fixes to connector")
            except Exception as vis_error:
                print(f"Info: Could not verify connector visibility: {vis_error}")
            
            return new_connector, "added"
    
    def prune_unmatched_shapes(self, valid_node_keys: Set[str], valid_edge_keys: Set[str], connector_management: str = 'smart_reconnect') -> Dict[str, int]:
        """
        Delete shapes and connectors not present in the valid key sets with advanced connector management.
        
        This enables "prune mode" where unmatched shapes are removed.
        Locked shapes and background elements are preserved.
        
        Args:
            valid_node_keys: Set of node keys that should be kept
            valid_edge_keys: Set of edge keys that should be kept
            connector_management: How to handle connectors when removing shapes:
                - 'smart_reconnect': Try to reconnect through deleted shapes (preserves flow)
                - 'remove_connectors': Remove all connected connectors (simple cleanup) 
                - 'validate_first': Check for connector issues before any removal
        
        Returns:
            Dictionary with counts and statistics
        """
        if not self.current_page:
            return {"nodes_deleted": 0, "edges_deleted": 0, "orphaned_cleaned": 0, "ambiguities_resolved": 0}
        
        # Step 1: Validate current connector integrity if requested
        if connector_management == 'validate_first':
            integrity = self.validate_connector_integrity()
            print(f"Pre-prune connector validation: {integrity['valid_connectors']}/{integrity['total_connectors']} valid")
            if integrity['issues']:
                print(f"Found {len(integrity['issues'])} connector issues before pruning")
        
        nodes_deleted = 0
        edges_deleted = 0
        
        # Separate nodes and connectors for proper handling
        nodes_to_remove: List[Any] = []
        connectors_to_remove: List[Any] = []
        
        for shape in list(self.current_page.child_shapes):
            try:
                # Check if shape is locked or protected
                if self._is_shape_protected(shape):
                    continue
                
                is_connector = self._is_connector(shape)
                
                if is_connector:
                    edge_key = get_shape_prop(shape, 'EdgeKey')
                    if edge_key and edge_key not in valid_edge_keys:
                        connectors_to_remove.append(shape)
                        edges_deleted += 1
                else:
                    node_key = get_shape_prop(shape, 'NodeKey')
                    # Only delete shapes that have a key (managed by us) but are not in valid set
                    if node_key and node_key not in valid_node_keys:
                        nodes_to_remove.append(shape)
                        nodes_deleted += 1
            
            except Exception as e:
                print(f"Warning: Error checking shape for pruning: {e}")
                continue
        
        # Step 2: Handle node removal with advanced connector management
        for shape in nodes_to_remove:
            try:
                shape_id = str(getattr(shape, 'ID', ''))
                if connector_management == 'smart_reconnect':
                    # Use advanced removal with smart reconnection
                    success = self.remove_shape_with_connector_management(shape_id, 'smart_reconnect')
                    if not success:
                        print(f"Warning: Advanced removal failed for shape {shape_id}, using simple removal")
                        shape.remove()
                elif connector_management == 'remove_connectors':
                    # Use simple connector cleanup
                    self.remove_shape_with_connector_management(shape_id, 'remove_connectors')
                else:
                    # Fallback to basic removal
                    shape.remove()
            except Exception as e:
                print(f"Warning: Could not remove shape {getattr(shape, 'ID', '?')}: {e}")
        
        # Step 3: Remove untracked connectors
        for connector in connectors_to_remove:
            try:
                connector.remove()
            except Exception as e:
                print(f"Warning: Could not remove connector {getattr(connector, 'ID', '?')}: {e}")
        
        # Step 4: Cleanup orphaned connectors and resolve ambiguities
        orphaned_cleaned = self.cleanup_orphaned_connectors()
        ambiguity_results = self.resolve_connector_ambiguity()
        
        # Step 5: Final validation
        final_integrity = self.validate_connector_integrity()
        
        return {
            "nodes_deleted": nodes_deleted, 
            "edges_deleted": edges_deleted,
            "orphaned_cleaned": orphaned_cleaned,
            "ambiguities_resolved": ambiguity_results['resolved_ambiguities'],
            "duplicates_removed": ambiguity_results['removed_duplicates'],
            "final_connector_integrity": final_integrity['integrity_score']
        }
    
    def _shape_types_compatible(self, shape: Any, desired_type: str) -> bool:
        """Check if existing shape is compatible with desired type (no replacement needed)."""
        try:
            shape_type = (getattr(shape, 'shape_type', '') or '').lower()
            master = getattr(shape, 'master', None)
            master_name = (getattr(master, 'name', '') or '').lower() if master else ''
            
            desired = desired_type.lower()
            
            # Exact or partial match
            if desired in shape_type or desired in master_name:
                return True
            
            # Semantic equivalents
            equivalents = {
                'rectangle': ['process', 'box'],
                'diamond': ['decision', 'rhombus'],
                'ellipse': ['circle', 'oval'],
                'roundedrectangle': ['terminal', 'terminator', 'rounded'],
                'parallelogram': ['data', 'io'],
                'hexagon': ['preparation', 'prep'],
            }
            
            for base_type, aliases in equivalents.items():
                if desired in aliases or desired == base_type:
                    if base_type in shape_type or base_type in master_name:
                        return True
                    for alias in aliases:
                        if alias in shape_type or alias in master_name:
                            return True
            
            return False
        
        except Exception:
            return False
    
    def _replace_shape_preserving_connections(self, old_shape: Any, new_shape_type: str,
                                              text: str, x: float, y: float,
                                              width: float, height: float,
                                              use_professional_formatting: bool) -> Optional[Any]:
        """
        Replace a shape with a new type while preserving connections and position.
        
        This is the core of the idempotent replacement logic.
        """
        try:
            # Store properties from old shape
            old_id = str(getattr(old_shape, 'ID', ''))
            old_x = float(getattr(old_shape, 'x', x) or x)
            old_y = float(getattr(old_shape, 'y', y) or y)
            
            # Find connected connectors
            connected_connectors = self._find_connected_connectors(old_shape)
            
            # Find a template shape of the desired type
            shape_catalog: Dict[str, List[Any]] = {}
            for shape in self._iter_shapes(self.current_page.child_shapes):
                if self._is_connector(shape) or self._is_guide(shape):
                    continue
                master_name = self._get_master_key(shape)
                shape_catalog.setdefault(master_name, []).append(shape)
            
            candidate_templates = self._select_shape_templates(new_shape_type, shape_catalog)
            template_shape = candidate_templates[0] if candidate_templates else None
            
            if not template_shape:
                print(f"Error: No template shape for type '{new_shape_type}'")
                return None
            
            # Create new shape from template
            new_shape_xml = self.visio_file.copy_shape(template_shape.xml, self.current_page)
            
            # Find the newly created shape by matching XML
            new_shape = None
            if self.current_page.child_shapes:
                for shape in reversed(self.current_page.child_shapes):
                    if shape.xml == new_shape_xml:
                        new_shape = shape
                        break
                
                # Fallback: use last shape if XML matching fails
                if not new_shape:
                    new_shape = self.current_page.child_shapes[-1]
            
            if new_shape:
                
                # Apply position and size
                new_shape.set_cell_value('PinX', str(old_x))
                new_shape.set_cell_value('PinY', str(old_y))
                new_shape.set_cell_value('Width', str(width))
                new_shape.set_cell_value('Height', str(height))
                
                # Set text
                new_shape.text = text
                
                # Apply professional formatting if requested
                if use_professional_formatting:
                    self._apply_professional_formatting(new_shape, new_shape_type)
                
                # Reconnect all connectors
                if connected_connectors:
                    self._reconnect_shape(old_shape, new_shape, connected_connectors)
                
                # Remove old shape
                old_shape.remove()
                
                return new_shape
        
        except Exception as e:
            print(f"Error replacing shape: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _update_shape_properties(self, shape: Any, text: str, x: float, y: float,
                                 width: float, height: float,
                                 use_professional_formatting: bool):
        """Update an existing shape's properties without replacing it."""
        try:
            # Always snap ALL dimensions to grid for consistency
            x = snap_to_grid(x)
            y = snap_to_grid(y)
            width = snap_to_grid(width)
            height = snap_to_grid(height)
            
            # Check if position actually changed to avoid unnecessary connector rerouting
            old_x = float(shape.cell_value('PinX') or getattr(shape, 'x', 0) or 0)
            old_y = float(shape.cell_value('PinY') or getattr(shape, 'y', 0) or 0)
            position_changed = abs(old_x - x) > 0.01 or abs(old_y - y) > 0.01
            
            # Update text
            if text and text != getattr(shape, 'text', ''):
                shape.text = text
            
            # Update position with validation
            shape.set_cell_value('PinX', str(x))
            shape.set_cell_value('PinY', str(y))
            
            # Update size
            shape.set_cell_value('Width', str(width))
            shape.set_cell_value('Height', str(height))
            
            # Ensure anchor point is centered
            try:
                shape.set_cell_value('LocPinX', str(width / 2.0))
                shape.set_cell_value('LocPinY', str(height / 2.0))
            except Exception:
                pass
            
            # Reapply professional formatting if requested
            if use_professional_formatting:
                shape_type = getattr(shape, 'shape_type', 'Rectangle')
                self._apply_professional_formatting(shape, shape_type)
            
            # Reroute connectors only if position changed
            if position_changed:
                self._reroute_connectors_near_shape(shape)
        
        except Exception as e:
            print(f"Warning: Error updating shape properties: {e}")
    
    def _is_shape_protected(self, shape: Any) -> bool:
        """Check if a shape is protected/locked and should not be deleted."""
        try:
            # Check lock flags
            if hasattr(shape, 'cell_value'):
                lock_flags = [
                    'LockDelete',
                    'LockSelect',
                    'LockMove',
                    'LockCrop',
                    'LockBegin',
                    'LockEnd'
                ]
                for flag in lock_flags:
                    value = shape.cell_value(flag)
                    if value and str(value) == '1':
                        return True
            
            # Check if it's a background shape or container
            shape_type = (getattr(shape, 'shape_type', '') or '').lower()
            if 'background' in shape_type or 'container' in shape_type or 'swimlane' in shape_type:
                return True
            
            # Check layer membership (shapes on locked layers)
            # This would require more complex layer inspection
            
            return False
        
        except Exception:
            # When in doubt, don't delete
            return True
    
    def get_all_node_keys(self) -> List[str]:
        """Get all node keys currently in the diagram."""
        if not self.current_page:
            return []
        
        nodes_by_key, _ = index_shapes_by_key(self.current_page, self)
        return list(nodes_by_key.keys())
    
    def get_all_edge_keys(self) -> List[str]:
        """Get all edge keys currently in the diagram."""
        if not self.current_page:
            return []
        
        _, edges_by_key = index_shapes_by_key(self.current_page, self)
        return list(edges_by_key.keys())
