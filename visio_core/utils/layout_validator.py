#!/usr/bin/env python3
"""
Comprehensive Visio Layout Validator
Analyzes detailed layout reports and provides quality assessments and recommendations.
"""

import json
import xml.etree.ElementTree as ET
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
import statistics
from dataclasses import dataclass

@dataclass
class LayoutIssue:
    """Represents a layout issue with severity and fix recommendation."""
    severity: str  # 'critical', 'warning', 'minor'
    category: str  # 'overlap', 'alignment', 'spacing', 'bounds'
    description: str
    shapes_involved: List[str]
    recommended_fix: str
    fix_priority: int  # 1-10, higher is more urgent

@dataclass
class QualityMetrics:
    """Overall layout quality metrics."""
    overall_score: float  # 0-100
    alignment_score: float
    spacing_score: float
    overlap_score: float
    bounds_score: float
    grade: str  # A, B, C, D, F
    total_issues: int
    critical_issues: int
    
class VisioLayoutValidator:
    """Advanced layout validation and quality analysis system."""
    
    def __init__(self, precision_threshold: float = 0.01):
        """
        Initialize validator.
        
        Args:
            precision_threshold: Minimum distance in inches to consider as misalignment
        """
        self.precision_threshold = precision_threshold
        self.issues: List[LayoutIssue] = []
        
    def validate_layout_report(self, report_data: Dict[str, Any]) -> QualityMetrics:
        """Analyze a layout report and generate quality metrics."""
        self.issues.clear()
        
        # Extract data from report
        shapes = report_data.get('shapes', {})
        if isinstance(shapes, dict):
            shapes_list = list(shapes.values())
        else:
            shapes_list = shapes
            
        spatial_relationships = report_data.get('spatial_relationships', {})
        anomalies = report_data.get('anomalies', [])
        page_dims = report_data.get('page_dimensions', {})
        
        # Run validation checks
        self._check_overlaps(shapes_list, spatial_relationships)
        self._check_alignment(shapes_list)
        self._check_spacing(shapes_list)
        self._check_page_bounds(shapes_list, page_dims)
        self._analyze_anomalies(anomalies)
        
        # Calculate quality scores
        return self._calculate_quality_metrics(shapes_list)
    
    def _check_overlaps(self, shapes: List[Dict], spatial_rels: Dict):
        """Check for problematic overlaps between shapes."""
        overlaps = spatial_rels.get('overlaps', [])
        
        for overlap in overlaps:
            # Handle both dict and tuple formats
            if isinstance(overlap, dict):
                shape1_id = str(overlap.get('shape1', ''))
                shape2_id = str(overlap.get('shape2', ''))
                overlap_area = overlap.get('overlap_area', 0)
            else:
                # Assume tuple format (shape1, shape2, area)
                shape1_id, shape2_id, overlap_area = str(overlap[0]), str(overlap[1]), overlap[2]
            
            if overlap_area > 0.01:  # Significant overlap (> 0.01 sq inches)
                severity = 'critical' if overlap_area > 0.25 else 'warning'
                self.issues.append(LayoutIssue(
                    severity=severity,
                    category='overlap',
                    description=f"Shapes {shape1_id} and {shape2_id} overlap by {overlap_area:.3f} sq inches",
                    shapes_involved=[shape1_id, shape2_id],
                    recommended_fix=f"Move shapes apart or resize to eliminate {overlap_area:.3f} sq inch overlap",
                    fix_priority=9 if severity == 'critical' else 6
                ))
    
    def _check_alignment(self, shapes: List[Dict]):
        """Check for alignment issues."""
        if len(shapes) < 2:
            return
            
        # Group shapes by approximate Y coordinates for horizontal alignment check
        y_groups = {}
        x_groups = {}
        
        for shape in shapes:
            if shape.get('type') == 'Connector':
                continue
                
            pos = shape.get('position', {})
            y = pos.get('y', 0)
            x = pos.get('x', 0)
            
            # Find or create Y group
            y_group_key = None
            for existing_y in y_groups.keys():
                if abs(y - existing_y) < self.precision_threshold:
                    y_group_key = existing_y
                    break
            
            if y_group_key is None:
                y_group_key = y
                y_groups[y_group_key] = []
            y_groups[y_group_key].append(shape)
            
            # Find or create X group  
            x_group_key = None
            for existing_x in x_groups.keys():
                if abs(x - existing_x) < self.precision_threshold:
                    x_group_key = existing_x
                    break
                    
            if x_group_key is None:
                x_group_key = x
                x_groups[x_group_key] = []
            x_groups[x_group_key].append(shape)
        
        # Check for near-alignments that should probably be exact
        self._check_near_alignments(y_groups, 'horizontal')
        self._check_near_alignments(x_groups, 'vertical')
    
    def _check_near_alignments(self, groups: Dict, alignment_type: str):
        """Check for shapes that are almost but not quite aligned."""
        tolerance = self.precision_threshold * 3  # Slightly larger tolerance for "near" alignment
        
        # Look for groups that are close to each other
        group_positions = list(groups.keys())
        for i, pos1 in enumerate(group_positions):
            for pos2 in group_positions[i+1:]:
                if abs(pos1 - pos2) < tolerance:
                    # These groups are close - they should probably be aligned
                    shapes1 = groups[pos1]
                    shapes2 = groups[pos2]
                    
                    if len(shapes1) > 0 and len(shapes2) > 0:
                        shape_ids = [s.get('id', 'unknown') for s in shapes1 + shapes2]
                        self.issues.append(LayoutIssue(
                            severity='minor',
                            category='alignment',
                            description=f"Shapes are nearly {alignment_type}ly aligned but off by {abs(pos1 - pos2):.3f} inches",
                            shapes_involved=[str(sid) for sid in shape_ids],
                            recommended_fix=f"Align shapes {alignment_type}ly to improve visual consistency",
                            fix_priority=3
                        ))
    
    def _check_spacing(self, shapes: List[Dict]):
        """Check for inconsistent spacing between shapes."""
        non_connector_shapes = [s for s in shapes if s.get('type') != 'Connector']
        
        if len(non_connector_shapes) < 3:
            return
            
        # Calculate distances between all pairs
        distances = []
        shape_pairs = []
        
        for i, shape1 in enumerate(non_connector_shapes):
            pos1 = shape1.get('position', {})
            x1, y1 = pos1.get('x', 0), pos1.get('y', 0)
            
            for shape2 in non_connector_shapes[i+1:]:
                pos2 = shape2.get('position', {})
                x2, y2 = pos2.get('x', 0), pos2.get('y', 0)
                
                # Calculate center-to-center distance
                distance = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
                distances.append(distance)
                shape_pairs.append((shape1.get('id'), shape2.get('id')))
        
        if len(distances) >= 3:
            # Check for spacing consistency
            mean_distance = statistics.mean(distances)
            std_distance = statistics.stdev(distances) if len(distances) > 1 else 0
            
            # Flag pairs with very inconsistent spacing
            for dist, (id1, id2) in zip(distances, shape_pairs):
                if abs(dist - mean_distance) > std_distance * 2 and std_distance > 0.5:
                    self.issues.append(LayoutIssue(
                        severity='minor',
                        category='spacing',
                        description=f"Inconsistent spacing: {dist:.2f} inches vs average {mean_distance:.2f}",
                        shapes_involved=[str(id1), str(id2)],
                        recommended_fix="Adjust spacing to match other shape pairs for visual consistency",
                        fix_priority=2
                    ))
    
    def _check_page_bounds(self, shapes: List[Dict], page_dims: Dict):
        """Check if shapes are outside reasonable page bounds."""
        if not page_dims:
            return
            
        page_width = page_dims.get('width', 8.5)
        page_height = page_dims.get('height', 11)
        margin = 0.5  # Half-inch margin
        
        for shape in shapes:
            if shape.get('type') == 'Connector':
                continue
                
            pos = shape.get('position', {})
            size = shape.get('size', {})
            
            x, y = pos.get('x', 0), pos.get('y', 0)
            width, height = size.get('width', 0), size.get('height', 0)
            
            # Check bounds
            left = x - width/2
            right = x + width/2
            bottom = y - height/2
            top = y + height/2
            
            issues = []
            if left < margin:
                issues.append('too close to left edge')
            if right > page_width - margin:
                issues.append('too close to right edge')
            if bottom < margin:
                issues.append('too close to bottom edge')
            if top > page_height - margin:
                issues.append('too close to top edge')
                
            if issues:
                self.issues.append(LayoutIssue(
                    severity='warning',
                    category='bounds',
                    description=f"Shape {shape.get('id')} is {', '.join(issues)}",
                    shapes_involved=[str(shape.get('id'))],
                    recommended_fix="Move shape away from page edges to ensure proper printing and visibility",
                    fix_priority=4
                ))
    
    def _analyze_anomalies(self, anomalies: List[Dict]):
        """Convert detected anomalies to layout issues."""
        for anomaly in anomalies:
            severity = anomaly.get('severity', 'minor')
            self.issues.append(LayoutIssue(
                severity=severity,
                category='anomaly',
                description=anomaly.get('description', 'Unknown anomaly'),
                shapes_involved=anomaly.get('affected_shapes', []),
                recommended_fix=anomaly.get('recommendation', 'Review and fix manually'),
                fix_priority=8 if severity == 'critical' else 5 if severity == 'warning' else 1
            ))
    
    def _calculate_quality_metrics(self, shapes: List[Dict]) -> QualityMetrics:
        """Calculate overall quality metrics based on detected issues."""
        total_shapes = len([s for s in shapes if s.get('type') != 'Connector'])
        if total_shapes == 0:
            total_shapes = 1  # Avoid division by zero
            
        critical_issues = len([i for i in self.issues if i.severity == 'critical'])
        warning_issues = len([i for i in self.issues if i.severity == 'warning'])
        minor_issues = len([i for i in self.issues if i.severity == 'minor'])
        
        # Calculate category-specific scores (0-100)
        overlap_issues = len([i for i in self.issues if i.category == 'overlap'])
        alignment_issues = len([i for i in self.issues if i.category == 'alignment'])
        spacing_issues = len([i for i in self.issues if i.category == 'spacing'])
        bounds_issues = len([i for i in self.issues if i.category == 'bounds'])
        
        # Score calculation (penalize issues relative to shape count)
        overlap_score = max(0, 100 - (overlap_issues * 50 / total_shapes * 100))
        alignment_score = max(0, 100 - (alignment_issues * 20 / total_shapes * 100))
        spacing_score = max(0, 100 - (spacing_issues * 15 / total_shapes * 100))
        bounds_score = max(0, 100 - (bounds_issues * 30 / total_shapes * 100))
        
        # Weighted overall score
        overall_score = (
            overlap_score * 0.4 +      # Overlaps are most critical
            alignment_score * 0.25 +  
            spacing_score * 0.2 +
            bounds_score * 0.15
        )
        
        # Apply critical issue penalty
        if critical_issues > 0:
            overall_score = min(overall_score, 50)  # Cap at 50% if critical issues exist
            
        # Determine letter grade
        if overall_score >= 90:
            grade = 'A'
        elif overall_score >= 80:
            grade = 'B'
        elif overall_score >= 70:
            grade = 'C'
        elif overall_score >= 60:
            grade = 'D'
        else:
            grade = 'F'
            
        return QualityMetrics(
            overall_score=overall_score,
            alignment_score=alignment_score,
            spacing_score=spacing_score,
            overlap_score=overlap_score,
            bounds_score=bounds_score,
            grade=grade,
            total_issues=len(self.issues),
            critical_issues=critical_issues
        )
    
    def generate_fix_recommendations(self) -> List[Dict[str, Any]]:
        """Generate prioritized fix recommendations."""
        # Sort issues by priority (higher first)
        sorted_issues = sorted(self.issues, key=lambda x: x.fix_priority, reverse=True)
        
        recommendations = []
        for issue in sorted_issues:
            recommendations.append({
                'severity': issue.severity,
                'category': issue.category,
                'description': issue.description,
                'affected_shapes': issue.shapes_involved,
                'recommended_action': issue.recommended_fix,
                'priority': issue.fix_priority
            })
            
        return recommendations
    
    def load_report_from_file(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Load layout report from JSON or XML file."""
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Report file not found: {file_path}")
            
        if path.suffix.lower() == '.json':
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        elif path.suffix.lower() == '.xml':
            return self._parse_xml_report(path)
        else:
            raise ValueError(f"Unsupported file format: {path.suffix}")
    
    def _parse_xml_report(self, xml_path: Path) -> Dict[str, Any]:
        """Parse XML layout report into dictionary format."""
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        # Basic XML to dict conversion - this would need to be more sophisticated
        # for complex XML structures
        report = {}
        
        # Extract shapes
        shapes_elem = root.find('.//shapes')
        if shapes_elem is not None:
            shapes = {}
            for shape_elem in shapes_elem.findall('shape'):
                shape_id = shape_elem.get('id')
                shape_data = {
                    'id': shape_id,
                    'type': shape_elem.get('type', 'Shape'),
                    'text': shape_elem.findtext('text', ''),
                    'position': {
                        'x': float(shape_elem.findtext('position/x', 0)),
                        'y': float(shape_elem.findtext('position/y', 0))
                    },
                    'size': {
                        'width': float(shape_elem.findtext('size/width', 0)),
                        'height': float(shape_elem.findtext('size/height', 0))
                    }
                }
                shapes[shape_id] = shape_data
            report['shapes'] = shapes
        
        return report

def validate_layout_file(report_file_path: str, precision_threshold: float = 0.01) -> Tuple[QualityMetrics, List[Dict]]:
    """Convenience function to validate a layout report file."""
    validator = VisioLayoutValidator(precision_threshold)
    report_data = validator.load_report_from_file(report_file_path)
    
    metrics = validator.validate_layout_report(report_data)
    recommendations = validator.generate_fix_recommendations()
    
    return metrics, recommendations
