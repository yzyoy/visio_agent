"""
Metadata generator for auto-generating keywords and use_cases
from template and stencil scan data
"""
from typing import List, Dict, Any, Set


class MetadataGenerator:
    """Auto-generates keywords and use cases from scan data"""
    
    # Category-specific keyword mappings
    CATEGORY_KEYWORDS = {
        'flowchart': ['workflow', 'process', 'decision', 'flow', 'diagram', 'procedure', 'logic'],
        'org_chart': ['organization', 'hierarchy', 'structure', 'management', 'team', 'reporting', 'personnel'],
        'network': ['network', 'topology', 'infrastructure', 'server', 'router', 'connection', 'IT'],
        'database': ['database', 'schema', 'data model', 'entity', 'relationship', 'table', 'SQL'],
        'uml': ['UML', 'class', 'sequence', 'use case', 'diagram', 'object', 'model'],
        'timeline': ['timeline', 'schedule', 'milestone', 'event', 'chronology', 'date', 'planning'],
        'layout': ['layout', 'design', 'arrangement', 'space', 'floor plan', 'architecture'],
        'cloud': ['cloud', 'AWS', 'Azure', 'GCP', 'service', 'infrastructure', 'architecture'],
        'general': ['diagram', 'visualization', 'chart', 'graphics', 'illustration'],
    }
    
    # Category-specific use case mappings
    CATEGORY_USE_CASES = {
        'flowchart': [
            'Business process documentation',
            'Workflow design',
            'Decision tree mapping',
            'Algorithm visualization',
            'Standard operating procedures'
        ],
        'org_chart': [
            'Company organization structure',
            'Team hierarchy visualization',
            'Reporting relationships',
            'Department organization',
            'Management structure'
        ],
        'network': [
            'Network topology design',
            'IT infrastructure planning',
            'System architecture',
            'Network documentation',
            'Data center layout'
        ],
        'database': [
            'Database schema design',
            'Data model documentation',
            'Entity relationship diagrams',
            'Database structure planning',
            'Data flow design'
        ],
        'uml': [
            'Software design',
            'System architecture',
            'Class structure design',
            'Sequence flow documentation',
            'Object-oriented modeling'
        ],
        'timeline': [
            'Project planning',
            'Event scheduling',
            'Milestone tracking',
            'Historical timelines',
            'Roadmap planning'
        ],
        'layout': [
            'Office space planning',
            'Floor plan design',
            'Facility layout',
            'Seating arrangements',
            'Room design'
        ],
        'cloud': [
            'Cloud architecture design',
            'Multi-cloud planning',
            'Service deployment diagrams',
            'Infrastructure as Code visualization',
            'Cloud migration planning'
        ],
        'general': [
            'General diagramming',
            'Visual communication',
            'Concept illustration',
            'Information visualization',
            'Documentation'
        ],
    }
    
    # Common shape type to keyword mappings
    SHAPE_TYPE_KEYWORDS = {
        'Rectangle': ['process', 'step', 'action', 'task'],
        'Diamond': ['decision', 'condition', 'choice', 'branching'],
        'RoundedRectangle': ['start', 'end', 'terminal', 'begin'],
        'Parallelogram': ['data', 'input', 'output', 'I/O'],
        'Circle': ['connector', 'junction', 'reference'],
        'Ellipse': ['event', 'state', 'condition'],
        'Triangle': ['indicator', 'warning', 'alert'],
        'Star': ['highlight', 'important', 'featured'],
        'Arrow': ['direction', 'flow', 'pointer', 'indicator'],
        'Cloud': ['cloud', 'service', 'remote', 'external'],
        'Database': ['database', 'storage', 'data', 'repository'],
        'Server': ['server', 'host', 'node', 'machine'],
        'Computer': ['computer', 'device', 'workstation', 'PC'],
        'Person': ['person', 'user', 'role', 'actor'],
        'Document': ['document', 'file', 'report', 'paper'],
    }
    
    @staticmethod
    def generate_template_metadata(scan_data: Dict[str, Any], category: str = 'general') -> Dict[str, List[str]]:
        """
        Generate keywords and use_cases for a template based on scan data
        
        Args:
            scan_data: Scan result from TemplateScanner
            category: Template category (flowchart, org_chart, network, etc.)
            
        Returns:
            Dictionary with 'keywords' and 'use_cases' lists
        """
        keywords = set()
        use_cases = []
        
        # 1. Add category-based keywords and use cases
        category_lower = category.lower()
        if category_lower in MetadataGenerator.CATEGORY_KEYWORDS:
            keywords.update(MetadataGenerator.CATEGORY_KEYWORDS[category_lower])
            use_cases = MetadataGenerator.CATEGORY_USE_CASES.get(category_lower, []).copy()
        else:
            keywords.update(MetadataGenerator.CATEGORY_KEYWORDS['general'])
            use_cases = MetadataGenerator.CATEGORY_USE_CASES['general'].copy()
        
        # 2. Extract keywords from shape types
        total_shapes = scan_data.get('total_shapes', {})
        if total_shapes:
            for shape_type in total_shapes.keys():
                if shape_type in MetadataGenerator.SHAPE_TYPE_KEYWORDS:
                    keywords.update(MetadataGenerator.SHAPE_TYPE_KEYWORDS[shape_type])
        
        # 3. Extract keywords from text content (use sample_texts only)
        sample_texts = scan_data.get('sample_texts', [])
        
        # Extract significant words from texts (simple approach)
        text_keywords = MetadataGenerator._extract_keywords_from_texts(sample_texts)
        keywords.update(text_keywords)
        
        # 4. Add complexity-based keywords
        complexity = scan_data.get('complexity', 'simple')
        if complexity == 'complex':
            keywords.add('detailed')
            keywords.add('comprehensive')
        elif complexity == 'simple':
            keywords.add('basic')
            keywords.add('simple')
        
        # 5. Add page-related keywords if multiple pages
        if scan_data.get('has_multiple_pages', False) or scan_data.get('total_pages', 1) > 1:
            keywords.add('multi-page')
            keywords.add('comprehensive')
        
        # 6. Infer additional use cases based on shape patterns
        additional_use_cases = MetadataGenerator._infer_use_cases_from_shapes(
            total_shapes, scan_data.get('total_connectors', 0)
        )
        use_cases.extend(additional_use_cases)
        
        # Remove duplicates and limit size
        keywords_list = sorted(list(keywords))[:15]  # Limit to 15 keywords
        use_cases_list = list(dict.fromkeys(use_cases))[:10]  # Limit to 10 unique use cases
        
        return {
            'keywords': keywords_list,
            'use_cases': use_cases_list
        }
    
    @staticmethod
    def generate_stencil_metadata(scan_data: Dict[str, Any], category: str = 'general') -> Dict[str, List[str]]:
        """
        Generate keywords and use_cases for a stencil based on scan data
        
        Args:
            scan_data: Scan result from StencilScanner
            category: Stencil category (network, cloud, flowchart, database, etc.)
            
        Returns:
            Dictionary with 'keywords' and 'use_cases' lists
        """
        keywords = set()
        use_cases = []
        
        # 1. Add category-based keywords and use cases
        category_lower = category.lower()
        if category_lower in MetadataGenerator.CATEGORY_KEYWORDS:
            keywords.update(MetadataGenerator.CATEGORY_KEYWORDS[category_lower])
            use_cases = MetadataGenerator.CATEGORY_USE_CASES.get(category_lower, []).copy()
        else:
            keywords.update(MetadataGenerator.CATEGORY_KEYWORDS['general'])
            use_cases = MetadataGenerator.CATEGORY_USE_CASES['general'].copy()
        
        # 2. Extract keywords from master names
        master_names = scan_data.get('master_names', [])
        master_keywords = MetadataGenerator._extract_keywords_from_names(master_names)
        keywords.update(master_keywords)
        
        # 3. Add complexity-based keywords
        complexity = scan_data.get('complexity', 'simple')
        master_count = scan_data.get('master_count', 0)
        
        if complexity == 'complex' or master_count > 50:
            keywords.add('extensive')
            keywords.add('comprehensive')
            keywords.add('large')
        elif complexity == 'simple' or master_count < 10:
            keywords.add('basic')
            keywords.add('minimal')
            keywords.add('simple')
        
        keywords.add('shapes')
        keywords.add('stencil')
        
        # 4. Infer use cases from master name patterns
        additional_use_cases = MetadataGenerator._infer_stencil_use_cases_from_names(master_names)
        use_cases.extend(additional_use_cases)
        
        # Remove duplicates and limit size
        keywords_list = sorted(list(keywords))[:15]  # Limit to 15 keywords
        use_cases_list = list(dict.fromkeys(use_cases))[:10]  # Limit to 10 unique use cases
        
        return {
            'keywords': keywords_list,
            'use_cases': use_cases_list
        }
    
    @staticmethod
    def _extract_keywords_from_texts(texts: List[str]) -> Set[str]:
        """Extract meaningful keywords from text content"""
        keywords = set()
        
        # Common technical and business terms to look for
        relevant_terms = [
            'process', 'workflow', 'decision', 'start', 'end', 'data', 'input', 'output',
            'manager', 'director', 'employee', 'team', 'department',
            'server', 'database', 'network', 'router', 'switch', 'firewall',
            'cloud', 'service', 'application', 'system', 'user',
            'project', 'task', 'milestone', 'deadline', 'schedule',
            'document', 'report', 'analysis', 'plan', 'strategy',
            'customer', 'client', 'vendor', 'supplier', 'partner',
        ]
        
        for text in texts[:50]:  # Check first 50 texts
            text_lower = text.lower()
            for term in relevant_terms:
                if term in text_lower:
                    keywords.add(term)
        
        return keywords
    
    @staticmethod
    def _extract_keywords_from_names(names: List[str]) -> Set[str]:
        """Extract meaningful keywords from master/shape names"""
        keywords = set()
        
        for name in names[:100]:  # Check first 100 names
            name_lower = name.lower()
            
            # Look for common technical terms
            if any(term in name_lower for term in ['server', 'database', 'storage']):
                keywords.add('IT infrastructure')
                keywords.add('server')
            
            if any(term in name_lower for term in ['cloud', 'aws', 'azure', 'gcp']):
                keywords.add('cloud computing')
                keywords.add('cloud services')
            
            if any(term in name_lower for term in ['network', 'router', 'switch', 'firewall']):
                keywords.add('networking')
                keywords.add('network devices')
            
            if any(term in name_lower for term in ['person', 'user', 'employee', 'manager']):
                keywords.add('people')
                keywords.add('organizational')
            
            if any(term in name_lower for term in ['arrow', 'connector', 'line']):
                keywords.add('connectors')
                keywords.add('flow')
            
            if any(term in name_lower for term in ['rectangle', 'circle', 'diamond', 'shape']):
                keywords.add('basic shapes')
                keywords.add('geometry')
        
        return keywords
    
    @staticmethod
    def _infer_use_cases_from_shapes(shapes: Dict[str, int], connector_count: int) -> List[str]:
        """Infer additional use cases based on shape composition"""
        use_cases = []
        
        # High connector count suggests workflow/process
        if connector_count > 5:
            use_cases.append('Process flow documentation')
        
        # Diamond shapes suggest decision trees
        if 'Diamond' in shapes and shapes['Diamond'] > 2:
            use_cases.append('Decision tree design')
        
        # Many rectangles suggest organizational or process diagrams
        if 'Rectangle' in shapes and shapes['Rectangle'] > 10:
            use_cases.append('Structured diagram creation')
        
        # Database shapes suggest data modeling
        if 'Database' in shapes:
            use_cases.append('Data architecture planning')
        
        # Person/user shapes suggest org charts
        if 'Person' in shapes or 'User' in shapes:
            use_cases.append('Organizational structure')
        
        return use_cases
    
    @staticmethod
    def _infer_stencil_use_cases_from_names(master_names: List[str]) -> List[str]:
        """Infer use cases from master shape names"""
        use_cases = []
        names_lower = [n.lower() for n in master_names[:100]]
        all_names = ' '.join(names_lower)
        
        # Network/IT infrastructure
        if any(term in all_names for term in ['server', 'router', 'switch', 'firewall', 'network']):
            use_cases.append('IT infrastructure diagrams')
        
        # Cloud architecture
        if any(term in all_names for term in ['cloud', 'aws', 'azure', 'gcp', 'kubernetes']):
            use_cases.append('Cloud architecture design')
        
        # Database/data modeling
        if any(term in all_names for term in ['database', 'table', 'entity', 'schema']):
            use_cases.append('Database design')
        
        # Organizational
        if any(term in all_names for term in ['person', 'employee', 'manager', 'team', 'user']):
            use_cases.append('Organization charts')
        
        # Flowcharts
        if any(term in all_names for term in ['process', 'decision', 'flow', 'start', 'end']):
            use_cases.append('Process flowcharts')
        
        return use_cases

