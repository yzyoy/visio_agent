"""
VSDX file structure validator and fixer
Ensures compatibility with web viewers and online Visio services
"""
import zipfile
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
import os
from pathlib import Path


class VSDXValidationIssue:
    """Represents a validation issue found in VSDX file"""
    
    SEVERITY_ERROR = "error"
    SEVERITY_WARNING = "warning"
    SEVERITY_INFO = "info"
    
    def __init__(self, severity: str, category: str, message: str, fix_available: bool = False):
        self.severity = severity
        self.category = category
        self.message = message
        self.fix_available = fix_available
    
    def __str__(self):
        icon = "❌" if self.severity == self.SEVERITY_ERROR else "⚠️" if self.severity == self.SEVERITY_WARNING else "ℹ️"
        fix_hint = " [Auto-fixable]" if self.fix_available else ""
        return f"{icon} [{self.category}] {self.message}{fix_hint}"


def validate_vsdx_structure(filepath: str, verbose: bool = False) -> List[VSDXValidationIssue]:
    """
    Validate VSDX file structure for web viewer compatibility
    
    Args:
        filepath: Path to VSDX file
        verbose: If True, print detailed validation info
        
    Returns:
        List of validation issues found
    """
    issues = []
    
    if not os.path.exists(filepath):
        issues.append(VSDXValidationIssue(
            VSDXValidationIssue.SEVERITY_ERROR,
            "file",
            f"File not found: {filepath}"
        ))
        return issues
    
    if not filepath.lower().endswith('.vsdx'):
        issues.append(VSDXValidationIssue(
            VSDXValidationIssue.SEVERITY_WARNING,
            "file",
            f"File does not have .vsdx extension: {filepath}"
        ))
    
    try:
        with zipfile.ZipFile(filepath, 'r') as zf:
            file_list = zf.namelist()
            
            if verbose:
                print(f"\n📦 Validating VSDX: {filepath}")
                print(f"   Total files in archive: {len(file_list)}")
            
            # Check required files
            required_files = {
                '[Content_Types].xml': 'Content Types definition',
                '_rels/.rels': 'Package relationships',
                'visio/document.xml': 'Main document',
            }
            
            for req_file, description in required_files.items():
                if req_file not in file_list:
                    issues.append(VSDXValidationIssue(
                        VSDXValidationIssue.SEVERITY_ERROR,
                        "structure",
                        f"Missing required file: {req_file} ({description})"
                    ))
                elif verbose:
                    print(f"   ✓ Found: {req_file}")
            
            # Validate Content_Types.xml
            if '[Content_Types].xml' in file_list:
                try:
                    content = zf.read('[Content_Types].xml')
                    root = ET.fromstring(content)
                    
                    # Check namespace
                    expected_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
                    if expected_ns not in root.tag:
                        issues.append(VSDXValidationIssue(
                            VSDXValidationIssue.SEVERITY_WARNING,
                            "xml",
                            "Content_Types.xml has unexpected namespace",
                            fix_available=True
                        ))
                    
                    if verbose:
                        defaults = root.findall('.//{http://schemas.openxmlformats.org/package/2006/content-types}Default')
                        print(f"   Content Types: {len(defaults)} default types registered")
                    
                except ET.ParseError as e:
                    issues.append(VSDXValidationIssue(
                        VSDXValidationIssue.SEVERITY_ERROR,
                        "xml",
                        f"Invalid XML in [Content_Types].xml: {e}"
                    ))
                except Exception as e:
                    issues.append(VSDXValidationIssue(
                        VSDXValidationIssue.SEVERITY_WARNING,
                        "xml",
                        f"Could not parse [Content_Types].xml: {e}"
                    ))
            
            # Validate _rels/.rels
            if '_rels/.rels' in file_list:
                try:
                    content = zf.read('_rels/.rels')
                    root = ET.fromstring(content)
                    
                    # Check for relationships
                    rels_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
                    relationships = root.findall(f'.//{{{rels_ns}}}Relationship')
                    
                    if len(relationships) == 0:
                        issues.append(VSDXValidationIssue(
                            VSDXValidationIssue.SEVERITY_WARNING,
                            "relationships",
                            "No relationships found in _rels/.rels"
                        ))
                    elif verbose:
                        print(f"   Relationships: {len(relationships)} found")
                    
                except ET.ParseError as e:
                    issues.append(VSDXValidationIssue(
                        VSDXValidationIssue.SEVERITY_ERROR,
                        "xml",
                        f"Invalid XML in _rels/.rels: {e}"
                    ))
            
            # Validate visio/document.xml
            if 'visio/document.xml' in file_list:
                try:
                    content = zf.read('visio/document.xml')
                    root = ET.fromstring(content)
                    
                    # Check Visio namespace
                    expected_ns = "http://schemas.microsoft.com/office/visio/2012/main"
                    if expected_ns not in root.tag:
                        issues.append(VSDXValidationIssue(
                            VSDXValidationIssue.SEVERITY_WARNING,
                            "xml",
                            "document.xml has unexpected Visio namespace"
                        ))
                    
                    if verbose:
                        print(f"   ✓ document.xml is valid XML")
                    
                except ET.ParseError as e:
                    issues.append(VSDXValidationIssue(
                        VSDXValidationIssue.SEVERITY_ERROR,
                        "xml",
                        f"Invalid XML in visio/document.xml: {e}"
                    ))
            
            # Check for pages
            page_files = [f for f in file_list if f.startswith('visio/pages/page') and f.endswith('.xml')]
            if len(page_files) == 0:
                issues.append(VSDXValidationIssue(
                    VSDXValidationIssue.SEVERITY_ERROR,
                    "structure",
                    "No page files found in visio/pages/"
                ))
            elif verbose:
                print(f"   Pages: {len(page_files)} found")
            
            # Check file size (web viewers may have limits)
            file_size = os.path.getsize(filepath)
            if file_size > 50 * 1024 * 1024:  # 50MB
                issues.append(VSDXValidationIssue(
                    VSDXValidationIssue.SEVERITY_WARNING,
                    "size",
                    f"File size is large ({file_size / (1024*1024):.1f} MB), may have issues with web viewers"
                ))
            elif verbose:
                print(f"   File size: {file_size / 1024:.1f} KB")
            
    except zipfile.BadZipFile:
        issues.append(VSDXValidationIssue(
            VSDXValidationIssue.SEVERITY_ERROR,
            "file",
            "File is not a valid ZIP/VSDX archive"
        ))
    except Exception as e:
        issues.append(VSDXValidationIssue(
            VSDXValidationIssue.SEVERITY_ERROR,
            "unknown",
            f"Unexpected error during validation: {e}"
        ))
    
    if verbose:
        if issues:
            print(f"\n   Found {len(issues)} issue(s):")
            for issue in issues:
                print(f"   {issue}")
        else:
            print(f"\n   ✅ All checks passed!")
    
    return issues


def fix_vsdx_with_aspose(filepath: str) -> bool:
    """
    Fix VSDX file by re-saving with Aspose.Diagram
    This ensures full compatibility with Microsoft specifications
    
    Args:
        filepath: Path to VSDX file to fix
        
    Returns:
        True if successful, False otherwise
    """
    try:
        import aspose.diagram as ad
        
        print(f"🔧 Attempting to fix VSDX with Aspose.Diagram...")
        
        # Load and re-save
        diagram = ad.Diagram(filepath)
        
        # Create backup of original
        backup_path = filepath + ".backup"
        if os.path.exists(filepath):
            import shutil
            shutil.copy2(filepath, backup_path)
            print(f"   📋 Created backup: {backup_path}")
        
        # Save with Aspose (this fixes structure issues)
        diagram.save(filepath, ad.SaveFileFormat.VSDX)
        
        print(f"   ✅ File fixed and saved: {filepath}")
        
        # Clean up backup if fix was successful
        if os.path.exists(backup_path):
            os.remove(backup_path)
            print(f"   🗑️  Removed backup (fix successful)")
        
        return True
        
    except ImportError:
        print(f"   ⚠️  Aspose.Diagram not available (install: pip install aspose-diagram-python)")
        return False
    except Exception as e:
        print(f"   ❌ Aspose fix failed: {e}")
        
        # Restore backup if it exists
        backup_path = filepath + ".backup"
        if os.path.exists(backup_path):
            import shutil
            shutil.copy2(backup_path, filepath)
            os.remove(backup_path)
            print(f"   ↩️  Restored from backup")
        
        return False


def validate_and_fix_vsdx(filepath: str, auto_fix: bool = True, verbose: bool = True) -> Dict[str, Any]:
    """
    Complete validation and fixing workflow for VSDX files
    
    Args:
        filepath: Path to VSDX file
        auto_fix: If True, attempt to auto-fix issues with Aspose
        verbose: If True, print detailed information
        
    Returns:
        Dictionary with validation results and fix status
    """
    result = {
        'filepath': filepath,
        'valid': False,
        'issues': [],
        'fixed': False,
        'errors': 0,
        'warnings': 0,
    }
    
    # Initial validation
    issues = validate_vsdx_structure(filepath, verbose=verbose)
    result['issues'] = [str(issue) for issue in issues]
    result['errors'] = sum(1 for issue in issues if issue.severity == VSDXValidationIssue.SEVERITY_ERROR)
    result['warnings'] = sum(1 for issue in issues if issue.severity == VSDXValidationIssue.SEVERITY_WARNING)
    
    # Determine if valid
    result['valid'] = result['errors'] == 0
    
    # Attempt fix if needed and requested
    if not result['valid'] and auto_fix:
        if verbose:
            print(f"\n🔧 Attempting auto-fix...")
        
        fixed = fix_vsdx_with_aspose(filepath)
        result['fixed'] = fixed
        
        if fixed:
            # Re-validate after fix
            if verbose:
                print(f"\n🔍 Re-validating after fix...")
            
            issues_after = validate_vsdx_structure(filepath, verbose=verbose)
            result['issues_after_fix'] = [str(issue) for issue in issues_after]
            result['errors_after_fix'] = sum(1 for issue in issues_after if issue.severity == VSDXValidationIssue.SEVERITY_ERROR)
            result['warnings_after_fix'] = sum(1 for issue in issues_after if issue.severity == VSDXValidationIssue.SEVERITY_WARNING)
            result['valid'] = result['errors_after_fix'] == 0
    
    return result


def print_validation_summary(result: Dict[str, Any]):
    """Print a nice summary of validation results"""
    print(f"\n{'='*70}")
    print(f"📊 VSDX Validation Summary")
    print(f"{'='*70}")
    print(f"File: {result['filepath']}")
    print(f"Status: {'✅ Valid' if result['valid'] else '❌ Invalid'}")
    print(f"Errors: {result['errors']}")
    print(f"Warnings: {result['warnings']}")
    
    if result.get('fixed'):
        print(f"\n🔧 Auto-fix Applied: Yes")
        if 'errors_after_fix' in result:
            print(f"   Errors after fix: {result['errors_after_fix']}")
            print(f"   Warnings after fix: {result['warnings_after_fix']}")
    
    if result['issues']:
        print(f"\nIssues found:")
        for issue in result['issues']:
            print(f"  {issue}")
    
    print(f"{'='*70}\n")

