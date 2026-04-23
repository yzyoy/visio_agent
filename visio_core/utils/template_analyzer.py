"""
Template analyzer utility for intelligent template analysis using LLM.

Pure library module — no agno import. The injected ``model`` is expected
to expose either ``.complete(prompt_str) -> str`` or the agno-style
``.response([msg]).content`` protocol (see
:mod:`visio_core.utils.smart_matcher` for the same adapter pattern).
"""
from typing import List, Dict, Any, Optional
import json

from .smart_matcher import _complete as _llm_complete


class TemplateAnalyzer:
    """Analyzes templates using LLM to extract insights"""
    
    @staticmethod
    def extract_keywords(texts: List[str], model, max_keywords: int = 10) -> List[str]:
        """
        Extract relevant keywords from shape texts using LLM
        
        Args:
            texts: List of text strings from shapes
            model: LLM model instance (OpenAIChat or compatible)
            max_keywords: Maximum number of keywords to extract
            
        Returns:
            List of extracted keywords
        """
        if not texts:
            return []
        
        try:
            # Prepare the text sample (limit to avoid token overflow)
            text_sample = "\n".join(texts[:100])  # First 100 texts
            
            prompt = f"""Analyze the following text extracted from a Visio diagram template and extract {max_keywords} relevant technical keywords that best describe the content and domain.

Text from diagram:
{text_sample}

Requirements:
- Extract {max_keywords} most relevant keywords
- Focus on technical terms, technologies, concepts, and domain-specific terminology
- Return ONLY a JSON array of keywords, nothing else
- Example format: ["keyword1", "keyword2", "keyword3"]

Keywords:"""

            response_text = _llm_complete(model, prompt)

            try:
                start_idx = response_text.find('[')
                end_idx = response_text.rfind(']') + 1
                if start_idx >= 0 and end_idx > start_idx:
                    json_str = response_text[start_idx:end_idx]
                    keywords = json.loads(json_str)
                    return keywords[:max_keywords] if isinstance(keywords, list) else []
            except json.JSONDecodeError:
                keywords = [k.strip().strip('"\'') for k in response_text.replace('\n', ',').split(',')]
                return [k for k in keywords if k and len(k) > 2][:max_keywords]
                
        except Exception as e:
            print(f"Error extracting keywords: {e}")
            return []
    
    @staticmethod
    def generate_use_cases(texts: List[str], template_info: Dict[str, Any], model, max_cases: int = 5) -> List[str]:
        """
        Generate appropriate use cases for the template using LLM
        
        Args:
            texts: List of text strings from shapes
            template_info: Dictionary with template metadata (pages, shapes, etc.)
            model: LLM model instance
            max_cases: Maximum number of use cases to generate
            
        Returns:
            List of use case descriptions
        """
        if not texts:
            return []
        
        try:
            # Prepare context
            text_sample = "\n".join(texts[:50])  # First 50 texts
            shape_types = ", ".join(template_info.get('total_shapes', {}).keys())
            num_pages = template_info.get('total_pages', 1)
            complexity = template_info.get('complexity', 'unknown')
            
            prompt = f"""Analyze this Visio diagram template and suggest {max_cases} practical use cases or scenarios where this template would be most appropriate.

Template Information:
- Pages: {num_pages}
- Complexity: {complexity}
- Shape types: {shape_types}

Sample text from diagram:
{text_sample}

Requirements:
- Suggest {max_cases} specific, practical use cases
- Focus on business or technical scenarios
- Each use case should be concise (one sentence)
- Return ONLY a JSON array of use case strings
- Example format: ["use case 1", "use case 2"]

Use cases:"""

            response_text = _llm_complete(model, prompt)

            try:
                start_idx = response_text.find('[')
                end_idx = response_text.rfind(']') + 1
                if start_idx >= 0 and end_idx > start_idx:
                    json_str = response_text[start_idx:end_idx]
                    use_cases = json.loads(json_str)
                    return use_cases[:max_cases] if isinstance(use_cases, list) else []
            except json.JSONDecodeError:
                lines = [line.strip().strip('-•*"\'') for line in response_text.split('\n')]
                use_cases = [line for line in lines if line and len(line) > 10 and len(line) < 200]
                return use_cases[:max_cases]
                
        except Exception as e:
            print(f"Error generating use cases: {e}")
            return []
    
    @staticmethod
    def generate_summary(template_info: Dict[str, Any], model) -> str:
        """
        Generate a comprehensive summary of the template using LLM
        
        Args:
            template_info: Dictionary with complete template metadata
            model: LLM model instance
            
        Returns:
            Summary description string
        """
        try:
            # Prepare context
            filename = template_info.get('filename', 'Unknown')
            num_pages = template_info.get('total_pages', 1)
            complexity = template_info.get('complexity', 'unknown')
            sample_texts = template_info.get('sample_texts', [])
            shape_types = ", ".join(template_info.get('total_shapes', {}).keys())
            total_shape_count = sum(template_info.get('total_shapes', {}).values())
            
            # Get page details if available
            pages_detail = template_info.get('pages_detail', [])
            pages_info = ""
            if pages_detail:
                pages_info = "\n\nPage structure:\n"
                for page in pages_detail[:3]:  # First 3 pages
                    pages_info += f"- {page['name']}: {len(page['groups'])} groups, {page['ungrouped_shapes']['total']} ungrouped shapes\n"
            
            text_sample = "\n".join(sample_texts[:20])
            
            prompt = f"""Create a comprehensive 2-3 sentence description of this Visio diagram template that explains its purpose and content.

Template: {filename}
- Pages: {num_pages}
- Total shapes: {total_shape_count}
- Complexity: {complexity}
- Shape types: {shape_types}{pages_info}

Sample content:
{text_sample}

Requirements:
- Write 2-3 clear, informative sentences
- Describe the template's purpose and main content
- Mention the domain or use case
- Be specific based on the content shown
- Write in a professional tone

Summary:"""

            summary = _llm_complete(model, prompt).strip()
            
            # Clean up the summary
            if summary.lower().startswith('summary:'):
                summary = summary[8:].strip()
            
            return summary if summary else "No description available"
            
        except Exception as e:
            print(f"Error generating summary: {e}")
            return "No description available"
    
    @staticmethod
    def analyze_template(template_info: Dict[str, Any], model) -> Dict[str, Any]:
        """
        Perform complete analysis of a template: keywords, use cases, and summary
        
        Args:
            template_info: Dictionary with complete template scan results
            model: LLM model instance
            
        Returns:
            Dictionary with 'keywords', 'use_cases', and 'summary' keys
        """
        try:
            # Use sample_texts only (all_texts removed to reduce bloat)
            sample_texts = template_info.get('sample_texts', [])
            
            # Extract keywords
            print("  Extracting keywords...")
            keywords = TemplateAnalyzer.extract_keywords(sample_texts, model, max_keywords=10)
            
            # Generate use cases
            print("  Generating use cases...")
            use_cases = TemplateAnalyzer.generate_use_cases(sample_texts, template_info, model, max_cases=5)
            
            # Generate summary
            print("  Generating summary...")
            summary = TemplateAnalyzer.generate_summary(template_info, model)
            
            return {
                'keywords': keywords,
                'use_cases': use_cases,
                'summary': summary
            }
            
        except Exception as e:
            print(f"Error in template analysis: {e}")
            return {
                'keywords': [],
                'use_cases': [],
                'summary': 'No description available'
            }

