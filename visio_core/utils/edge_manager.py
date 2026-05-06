"""  
Edge-Centric Management Module

Provides rigorous edge management capabilities for structural processing workflows.
Ensures connection integrity during shape addition and deletion cycles.
"""

from typing import Dict, List, Any, Optional, Tuple, Set
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class EdgeDirection(Enum):
    """Edge directionality types"""
    UNIDIRECTIONAL = "unidirectional"
    BIDIRECTIONAL = "bidirectional"
    

class EdgeType(Enum):
    """Edge relationship types"""
    DATA_FLOW = "data_flow"
    CONTROL_FLOW = "control_flow"
    DEPENDENCY = "dependency"
    ASSOCIATION = "association"
    AGGREGATION = "aggregation"
    COMPOSITION = "composition"
    

@dataclass
class EdgeMetadata:
    """Complete edge metadata container"""
    edge_id: str
    source_id: Optional[str] = None
    target_id: Optional[str] = None
    direction: EdgeDirection = EdgeDirection.UNIDIRECTIONAL
    edge_type: EdgeType = EdgeType.DATA_FLOW
    label: str = ""
    style_properties: Dict[str, Any] = field(default_factory=dict)
    data_attributes: Dict[str, Any] = field(default_factory=dict)
    routing_points: List[Tuple[float, float]] = field(default_factory=list)
    z_order: int = 0
    referenced_shape_ids: Set[str] = field(default_factory=set)
    has_complete_endpoints: bool = False
    

@dataclass 
class EdgeInventory:
    """Complete edge inventory for a diagram"""
    edges: Dict[str, EdgeMetadata] = field(default_factory=dict)
    shape_to_edges: Dict[str, Set[str]] = field(default_factory=dict)  # shape_id -> edge_ids
    source_to_edges: Dict[str, Set[str]] = field(default_factory=dict)  # source_id -> edge_ids
    target_to_edges: Dict[str, Set[str]] = field(default_factory=dict)  # target_id -> edge_ids
    

class EdgeCentricManager:
    """Manages edge-centric operations with integrity guarantees"""
    
    def __init__(self, diagram_builder):
        """
        Initialize EdgeCentricManager.
        
        Args:
            diagram_builder: Reference to DiagramBuilder instance
        """
        self.diagram_builder = diagram_builder
        self._edge_inventory: Optional[EdgeInventory] = None
        self._validation_errors: List[str] = []

    def invalidate_edge_inventory(self) -> None:
        """Drop the cached edge inventory for the current page."""
        self._edge_inventory = None

    def _discard_from_index(self, index: Dict[str, Set[str]], shape_id: Optional[str], edge_id: str) -> None:
        """Remove an edge id from an index and prune empty buckets."""
        if not shape_id:
            return
        bucket = index.get(str(shape_id))
        if not bucket:
            return
        bucket.discard(edge_id)
        if not bucket:
            index.pop(str(shape_id), None)

    def _store_edge_metadata(self, inventory: EdgeInventory, edge_meta: EdgeMetadata) -> None:
        """Insert or replace one edge in the cached inventory."""
        edge_id = str(edge_meta.edge_id)
        previous = inventory.edges.get(edge_id)
        if previous is not None:
            self._drop_edge_from_inventory(inventory, edge_id)

        inventory.edges[edge_id] = edge_meta

        for shape_id in edge_meta.referenced_shape_ids:
            inventory.shape_to_edges.setdefault(str(shape_id), set()).add(edge_id)

        if edge_meta.source_id:
            inventory.source_to_edges.setdefault(str(edge_meta.source_id), set()).add(edge_id)

        if edge_meta.target_id:
            inventory.target_to_edges.setdefault(str(edge_meta.target_id), set()).add(edge_id)

    def _drop_edge_from_inventory(self, inventory: EdgeInventory, edge_id: str) -> None:
        """Remove one edge from the cached inventory."""
        edge_meta = inventory.edges.pop(edge_id, None)
        if edge_meta is None:
            return

        for shape_id in edge_meta.referenced_shape_ids:
            self._discard_from_index(inventory.shape_to_edges, str(shape_id), edge_id)

        self._discard_from_index(inventory.source_to_edges, edge_meta.source_id, edge_id)
        self._discard_from_index(inventory.target_to_edges, edge_meta.target_id, edge_id)

    def update_inventory_after_connector_removal(self, connector_id: str) -> bool:
        """Incrementally prune one removed connector from the cached inventory."""
        if self._edge_inventory is None:
            return False

        self._drop_edge_from_inventory(self._edge_inventory, str(connector_id))
        return True

    def update_inventory_after_shape_deletion(self, shape_id: str, edge_results: Dict[str, Any]) -> bool:
        """Incrementally update cached inventory after removing one shape."""
        inventory = self._edge_inventory
        if inventory is None:
            return False

        deleted_shape_id = str(shape_id)
        removed_edge_ids = {
            str(edge_id)
            for edge_id in edge_results.get('connected_edge_ids', [])
            if edge_id is not None
        }
        removed_edge_ids.update(
            str(edge_id)
            for edge_id in edge_results.get('edges_removed', [])
            if edge_id is not None
        )

        for edge_id in removed_edge_ids:
            self._drop_edge_from_inventory(inventory, edge_id)

        inventory.shape_to_edges.pop(deleted_shape_id, None)
        inventory.source_to_edges.pop(deleted_shape_id, None)
        inventory.target_to_edges.pop(deleted_shape_id, None)

        for reconnect_info in edge_results.get('edges_reconnected', []):
            new_edge_id = reconnect_info.get('new_edge')
            if new_edge_id is None:
                continue

            connector = self.diagram_builder.get_shape_by_id(str(new_edge_id))
            if connector is None:
                self.invalidate_edge_inventory()
                return False

            edge_meta = self._extract_edge_metadata(connector)
            if edge_meta is None:
                self.invalidate_edge_inventory()
                return False

            self._store_edge_metadata(inventory, edge_meta)

        return True
        
    def build_edge_inventory(self, force_rebuild: bool = False) -> EdgeInventory:
        """
        Build complete edge inventory for current page.
        
        Args:
            force_rebuild: Force inventory rebuild even if cached
            
        Returns:
            EdgeInventory containing all edge metadata
        """
        if self._edge_inventory and not force_rebuild:
            return self._edge_inventory
            
        inventory = EdgeInventory()
        
        if not self.diagram_builder.current_page:
            self._edge_inventory = inventory
            return inventory
            
        # Scan all connectors and build inventory
        for shape in self.diagram_builder.current_page.child_shapes:
            if not self.diagram_builder._is_connector(shape):
                continue
                
            try:
                edge_meta = self._extract_edge_metadata(shape)
                if edge_meta:
                    self._store_edge_metadata(inventory, edge_meta)

            except Exception as e:
                logger.warning(f"Failed to extract edge metadata: {e}")
                
        self._edge_inventory = inventory
        return inventory
        
    def _extract_edge_metadata(self, connector) -> Optional[EdgeMetadata]:
        """
        Extract complete metadata from a connector shape.
        
        Args:
            connector: Connector shape object
            
        Returns:
            EdgeMetadata or None if extraction fails
        """
        try:
            edge_id = str(connector.ID)
            
            reference_summary = self.diagram_builder.get_connector_reference_summary(connector)
            if (
                not reference_summary['source']
                and not reference_summary['target']
                and not reference_summary['referenced_shape_ids']
            ):
                return None
                
            # Create base metadata
            edge_meta = EdgeMetadata(
                edge_id=edge_id,
                source_id=reference_summary['source'],
                target_id=reference_summary['target'],
                referenced_shape_ids=set(reference_summary['referenced_shape_ids']),
                has_complete_endpoints=bool(
                    reference_summary['source'] and reference_summary['target']
                ),
            )
            
            # Extract label
            edge_meta.label = getattr(connector, 'text', '') or ''
            
            # Extract style properties
            edge_meta.style_properties = self._extract_style_properties(connector)
            
            # Extract routing points
            edge_meta.routing_points = self._extract_routing_points(connector)
            
            # Extract custom properties
            edge_meta.data_attributes = self._extract_custom_properties(connector)
            
            # Determine directionality from arrow styles
            edge_meta.direction = self._determine_edge_direction(connector)
            
            return edge_meta
            
        except Exception as e:
            logger.warning(f"Failed to extract edge metadata: {e}")
            return None
            
    def _get_connector_endpoints(self, connector) -> Dict[str, Optional[str]]:
        """Extract source and target shape IDs from connector."""
        return self.diagram_builder._get_connector_endpoints(connector)
        
    def _extract_style_properties(self, connector) -> Dict[str, Any]:
        """Extract visual style properties from connector."""
        style = {}
        
        try:
            # Line weight
            if hasattr(connector, 'cell_value'):
                style['line_weight'] = connector.cell_value('LineWeight') or '0.75pt'
                style['line_color'] = connector.cell_value('LineColor') or 'RGB(0,0,0)'
                style['line_pattern'] = connector.cell_value('LinePattern') or '1'
                
                # Arrow styles
                style['begin_arrow'] = connector.cell_value('BeginArrow') or '0'
                style['end_arrow'] = connector.cell_value('EndArrow') or '4'
                
        except Exception as e:
            logger.debug(f"Failed to extract style properties: {e}")
            
        return style
        
    def _extract_routing_points(self, connector) -> List[Tuple[float, float]]:
        """Extract routing waypoints from connector geometry."""
        points = []
        
        try:
            if hasattr(connector, 'geometry') and connector.geometry:
                # Extract from geometry section if available
                pass  # Implementation depends on vsdx library capabilities
        except Exception:
            pass
            
        return points
        
    def _extract_custom_properties(self, connector) -> Dict[str, Any]:
        """Extract custom data properties from connector."""
        props = {}
        
        try:
            # Check for custom properties section
            if hasattr(connector, 'data'):
                for prop in connector.data:
                    props[prop.name] = prop.value
        except Exception:
            pass
            
        return props
        
    def _determine_edge_direction(self, connector) -> EdgeDirection:
        """Determine edge directionality from arrow configuration."""
        try:
            begin_arrow = connector.cell_value('BeginArrow') or '0'
            end_arrow = connector.cell_value('EndArrow') or '0'
            
            if begin_arrow != '0' and end_arrow != '0':
                return EdgeDirection.BIDIRECTIONAL
        except Exception:
            pass
            
        return EdgeDirection.UNIDIRECTIONAL
        
    def validate_edge_integrity(self) -> Tuple[bool, List[str]]:
        """
        Validate edge integrity across the diagram.
        
        Returns:
            Tuple of (is_valid, error_messages)
        """
        self._validation_errors = []
        inventory = self.build_edge_inventory()
        
        # Check for orphaned edges
        for edge_id, edge_meta in inventory.edges.items():
            reported_missing: Set[str] = set()

            if not edge_meta.has_complete_endpoints:
                self._validation_errors.append(
                    f"Edge {edge_id}: Connector has incomplete endpoints"
                )

            # Verify source exists
            if edge_meta.source_id:
                source_shape = self.diagram_builder.get_shape_by_id(edge_meta.source_id)
                if not source_shape:
                    reported_missing.add(edge_meta.source_id)
                    self._validation_errors.append(
                        f"Edge {edge_id}: Source shape {edge_meta.source_id} not found"
                    )
                
            # Verify target exists
            if edge_meta.target_id:
                target_shape = self.diagram_builder.get_shape_by_id(edge_meta.target_id)
                if not target_shape:
                    reported_missing.add(edge_meta.target_id)
                    self._validation_errors.append(
                        f"Edge {edge_id}: Target shape {edge_meta.target_id} not found"
                    )

            for referenced_shape_id in sorted(edge_meta.referenced_shape_ids):
                if referenced_shape_id in reported_missing:
                    continue
                if not self.diagram_builder.get_shape_by_id(referenced_shape_id):
                    self._validation_errors.append(
                        f"Edge {edge_id}: References missing shape {referenced_shape_id}"
                    )
                
        # Check for duplicate edges
        edge_pairs = {}
        for edge_id, edge_meta in inventory.edges.items():
            if not edge_meta.has_complete_endpoints:
                continue
            pair_key = f"{edge_meta.source_id}->{edge_meta.target_id}"
            if pair_key in edge_pairs:
                self._validation_errors.append(
                    f"Duplicate edge detected: {edge_id} duplicates {edge_pairs[pair_key]}"
                )
            else:
                edge_pairs[pair_key] = edge_id
                
        # Check for self-loops (if not allowed)
        for edge_id, edge_meta in inventory.edges.items():
            if not edge_meta.has_complete_endpoints:
                continue
            if edge_meta.source_id == edge_meta.target_id:
                self._validation_errors.append(
                    f"Self-loop detected: Edge {edge_id} connects shape to itself"
                )
                
        is_valid = len(self._validation_errors) == 0
        return is_valid, self._validation_errors
        
    def handle_shape_deletion(self, shape_id: str, reconnect_strategy: str = 'smart') -> Dict[str, Any]:
        """
        Handle edge management when deleting a shape.
        
        Args:
            shape_id: ID of shape being deleted
            reconnect_strategy: Strategy for handling edges
                - 'smart': Intelligently reconnect through deleted shape
                - 'remove': Remove all connected edges
                - 'preserve': Keep edges (will become orphaned)
                
        Returns:
            Dictionary with operation results
        """
        results = {
            'edges_removed': [],
            'edges_reconnected': [],
            'edges_orphaned': [],
            'connected_edge_ids': [],
            'errors': []
        }
        
        inventory = self.build_edge_inventory()
        
        # Find all edges connected to the shape
        connected_edge_ids = inventory.shape_to_edges.get(shape_id, set())
        results['connected_edge_ids'] = sorted(str(edge_id) for edge_id in connected_edge_ids)
        
        if reconnect_strategy == 'smart':
            # Categorize edges
            incoming_edges = []
            outgoing_edges = []
            
            for edge_id in connected_edge_ids:
                edge_meta = inventory.edges.get(edge_id)
                if not edge_meta or not edge_meta.has_complete_endpoints:
                    continue
                    
                if edge_meta.target_id == shape_id:
                    incoming_edges.append(edge_meta)
                elif edge_meta.source_id == shape_id:
                    outgoing_edges.append(edge_meta)
                    
            # Create bypass connections
            if len(incoming_edges) == 1 and len(outgoing_edges) == 1:
                # Simple case: one-to-one bypass
                self._create_bypass_edge(
                    incoming_edges[0], outgoing_edges[0], results
                )
            elif incoming_edges and outgoing_edges:
                # Complex case: many-to-many
                for in_edge in incoming_edges:
                    for out_edge in outgoing_edges:
                        self._create_bypass_edge(in_edge, out_edge, results)
                        
            # Remove original edges
            removed_edge_ids = set()
            for edge_meta in incoming_edges + outgoing_edges:
                if edge_meta.edge_id in removed_edge_ids:
                    continue
                if self._remove_edge(edge_meta.edge_id):
                    results['edges_removed'].append(edge_meta.edge_id)
                    removed_edge_ids.add(edge_meta.edge_id)

            # Remove any remaining edge that still references the deleted shape,
            # including half-connected or formula-only connectors.
            for edge_id in sorted(connected_edge_ids - removed_edge_ids):
                if self._remove_edge(edge_id):
                    results['edges_removed'].append(edge_id)
                    
        elif reconnect_strategy == 'remove':
            # Simply remove all connected edges
            for edge_id in sorted(connected_edge_ids):
                if self._remove_edge(edge_id):
                    results['edges_removed'].append(edge_id)
                    
        elif reconnect_strategy == 'preserve':
            # Edges will become orphaned
            results['edges_orphaned'].extend(connected_edge_ids)
            
        return results
        
    def _create_bypass_edge(self, in_edge: EdgeMetadata, out_edge: EdgeMetadata, results: Dict[str, Any]):
        """Create a bypass edge preserving metadata."""
        try:
            # Get the actual source and target for the bypass
            new_source_id = in_edge.source_id
            new_target_id = out_edge.target_id
            
            # Don't create self-loops
            if new_source_id == new_target_id:
                return
                
            # Create new edge with preserved metadata
            new_edge_id = self.diagram_builder.connect_shapes(new_source_id, new_target_id)
            
            if new_edge_id:
                # Get the new connector
                new_connector = self.diagram_builder.get_shape_by_id(str(new_edge_id))
                if new_connector:
                    # Preserve metadata
                    self._transfer_edge_metadata(in_edge, out_edge, new_connector)
                    
                results['edges_reconnected'].append({
                    'old_edges': [in_edge.edge_id, out_edge.edge_id],
                    'new_edge': new_edge_id,
                    'source': new_source_id,
                    'target': new_target_id
                })
                
        except Exception as e:
            results['errors'].append(f"Failed to create bypass edge: {e}")
            
    def _transfer_edge_metadata(self, in_edge: EdgeMetadata, out_edge: EdgeMetadata, connector):
        """Transfer metadata from old edges to new connector."""
        try:
            # Combine labels
            if in_edge.label and out_edge.label:
                connector.text = f"{in_edge.label} / {out_edge.label}"
            elif in_edge.label:
                connector.text = in_edge.label
            elif out_edge.label:
                connector.text = out_edge.label
                
            # Use the most specific style (prefer outgoing edge style)
            style_props = out_edge.style_properties or in_edge.style_properties
            if style_props and hasattr(connector, 'set_cell_value'):
                for prop, value in style_props.items():
                    if prop == 'line_weight':
                        connector.set_cell_value('LineWeight', value)
                    elif prop == 'line_color':
                        connector.set_cell_value('LineColor', value)
                        
        except Exception as e:
            logger.warning(f"Failed to transfer edge metadata: {e}")
            
    def _remove_edge(self, edge_id: str) -> bool:
        """Remove an edge from the diagram."""
        try:
            return self.diagram_builder.remove_connector(edge_id)
        except Exception as e:
            logger.error(f"Failed to remove edge {edge_id}: {e}")
            return False
            
    def handle_shape_insertion(self, new_shape_id: str, between_edge_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Handle edge management when inserting a new shape.
        
        Args:
            new_shape_id: ID of newly inserted shape
            between_edge_id: Optional edge to split for insertion
            
        Returns:
            Dictionary with operation results
        """
        results = {
            'edges_created': [],
            'edges_split': [],
            'errors': []
        }
        
        if between_edge_id:
            # Split edge insertion
            inventory = self.build_edge_inventory()
            edge_meta = inventory.edges.get(between_edge_id)
            
            if edge_meta and edge_meta.has_complete_endpoints:
                try:
                    # Create two new edges: source->new and new->target
                    edge1_id = self.diagram_builder.connect_shapes(
                        edge_meta.source_id, new_shape_id
                    )
                    edge2_id = self.diagram_builder.connect_shapes(
                        new_shape_id, edge_meta.target_id
                    )
                    
                    if edge1_id and edge2_id:
                        # Transfer metadata to new edges
                        edge1 = self.diagram_builder.get_shape_by_id(str(edge1_id))
                        edge2 = self.diagram_builder.get_shape_by_id(str(edge2_id))
                        
                        if edge1:
                            self._apply_edge_metadata(edge1, edge_meta)
                        if edge2:
                            self._apply_edge_metadata(edge2, edge_meta)
                            
                        # Remove original edge
                        self._remove_edge(between_edge_id)
                        
                        results['edges_split'].append({
                            'original_edge': between_edge_id,
                            'new_edges': [edge1_id, edge2_id],
                            'inserted_shape': new_shape_id
                        })
                        
                except Exception as e:
                    results['errors'].append(f"Failed to split edge: {e}")
            elif edge_meta:
                results['errors'].append(
                    f"Edge {between_edge_id} has incomplete endpoints and cannot be split"
                )
                    
        return results
        
    def _apply_edge_metadata(self, connector, edge_meta: EdgeMetadata):
        """Apply metadata to a connector."""
        try:
            if edge_meta.label:
                connector.text = edge_meta.label
                
            if edge_meta.style_properties and hasattr(connector, 'set_cell_value'):
                for prop, value in edge_meta.style_properties.items():
                    if prop == 'line_weight':
                        connector.set_cell_value('LineWeight', value)
                    elif prop == 'line_color':
                        connector.set_cell_value('LineColor', value)
                    elif prop == 'line_pattern':
                        connector.set_cell_value('LinePattern', value)
                        
        except Exception as e:
            logger.warning(f"Failed to apply edge metadata: {e}")
            
    def optimize_edge_routing(self, avoid_crossings: bool = True) -> Dict[str, int]:
        """
        Optimize edge routing to improve visual clarity.
        
        Args:
            avoid_crossings: Whether to try to minimize edge crossings
            
        Returns:
            Dictionary with optimization statistics
        """
        stats = {
            'edges_rerouted': 0,
            'crossings_eliminated': 0,
            'overlaps_resolved': 0
        }
        
        inventory = self.build_edge_inventory()
        
        # Re-route edges to avoid crossings
        if avoid_crossings:
            for edge_id, edge_meta in inventory.edges.items():
                connector = self.diagram_builder.get_shape_by_id(edge_id)
                if connector:
                    try:
                        # Apply optimal routing
                        self._apply_optimal_routing(connector, edge_meta)
                        stats['edges_rerouted'] += 1
                    except Exception as e:
                        logger.warning(f"Failed to optimize edge {edge_id}: {e}")
                        
        return stats
        
    def _apply_optimal_routing(self, connector, edge_meta: EdgeMetadata):
        """Apply optimal routing to minimize crossings and overlaps."""
        try:
            if hasattr(connector, 'set_cell_value'):
                # Use dynamic connector routing
                connector.set_cell_value('ConLineRouteExt', '2')  # Optimal
                connector.set_cell_value('ShapeRouteStyle', '1')  # Right angle
                
                # Force rerouting
                if hasattr(connector, 'reroute'):
                    connector.reroute()
                    
        except Exception as e:
            logger.debug(f"Failed to apply optimal routing: {e}")
            
    def generate_edge_report(self) -> Dict[str, Any]:
        """
        Generate comprehensive edge analysis report.
        
        Returns:
            Dictionary containing edge statistics and issues
        """
        inventory = self.build_edge_inventory()
        is_valid, errors = self.validate_edge_integrity()
        
        report = {
            'total_edges': len(inventory.edges),
            'edge_types': {},
            'orphaned_edges': [],
            'duplicate_edges': [],
            'self_loops': [],
            'validation_errors': errors,
            'is_valid': is_valid
        }
        
        # Count edge types
        for edge_meta in inventory.edges.values():
            edge_type = edge_meta.edge_type.value
            report['edge_types'][edge_type] = report['edge_types'].get(edge_type, 0) + 1
            
        # Find specific issues
        for error in errors:
            if 'not found' in error:
                edge_id = error.split(':')[0].replace('Edge', '').strip()
                report['orphaned_edges'].append(edge_id)
            elif 'Duplicate' in error:
                edge_id = error.split(':')[1].split('duplicates')[0].strip()
                report['duplicate_edges'].append(edge_id)
            elif 'Self-loop' in error:
                edge_id = error.split('Edge')[1].split('connects')[0].strip()
                report['self_loops'].append(edge_id)
                
        return report
