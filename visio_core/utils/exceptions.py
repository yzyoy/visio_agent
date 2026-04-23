"""
Custom exceptions for Visio diagram operations

Provides structured error handling with actionable information for debugging.
"""


class VisioError(Exception):
    """Base exception for all Visio-related errors"""
    pass


class VisioShapeError(VisioError):
    """Base exception for shape-related errors"""
    
    def __init__(self, message: str, shape_id: str = None, suggestions: list = None):
        """
        Initialize shape error with context.
        
        Args:
            message: Error message
            shape_id: Optional shape ID that caused the error
            suggestions: Optional list of suggestions to fix the error
        """
        self.shape_id = shape_id
        self.suggestions = suggestions or []
        
        full_message = message
        if shape_id:
            full_message += f" (Shape ID: {shape_id})"
        if suggestions:
            full_message += "\n\nSuggestions:"
            for i, suggestion in enumerate(suggestions, 1):
                full_message += f"\n  {i}. {suggestion}"
        
        super().__init__(full_message)


class NoTemplateError(VisioShapeError):
    """Raised when no suitable template shape is found"""
    
    def __init__(self, shape_type: str, available_types: list = None):
        """
        Initialize template error.
        
        Args:
            shape_type: The shape type that was requested
            available_types: Optional list of available shape types on the page
        """
        self.shape_type = shape_type
        self.available_types = available_types or []
        
        message = f"No template shape found for type '{shape_type}'"
        
        suggestions = [
            f"Add at least one '{shape_type}' shape to the page manually",
            "Use an existing shape type from the page",
            "Load a diagram that contains the desired shape types"
        ]
        
        if available_types:
            avail_str = ', '.join(available_types[:5])
            suggestions.insert(1, f"Use one of these available types: {avail_str}")
        
        super().__init__(message, shape_id=None, suggestions=suggestions)


class InvalidShapeTypeError(VisioShapeError):
    """Raised when an invalid or unsupported shape type is requested"""
    
    def __init__(self, shape_type: str, valid_types: list = None):
        """
        Initialize invalid shape type error.
        
        Args:
            shape_type: The invalid shape type
            valid_types: Optional list of valid shape types
        """
        self.shape_type = shape_type
        self.valid_types = valid_types or []
        
        message = f"Invalid shape type: '{shape_type}'"
        
        suggestions = []
        if valid_types:
            valid_str = ', '.join(valid_types[:10])
            suggestions.append(f"Use one of these valid types: {valid_str}")
        else:
            suggestions.append("Check the shape type spelling and try again")
        
        super().__init__(message, shape_id=None, suggestions=suggestions)


class ShapeCreationError(VisioShapeError):
    """Raised when shape creation fails"""
    
    def __init__(self, shape_type: str, reason: str = None, original_exception: Exception = None):
        """
        Initialize shape creation error.
        
        Args:
            shape_type: The shape type that failed to create
            reason: Optional reason for failure
            original_exception: Optional original exception that caused the failure
        """
        self.shape_type = shape_type
        self.reason = reason
        self.original_exception = original_exception
        
        message = f"Failed to create shape of type '{shape_type}'"
        if reason:
            message += f": {reason}"
        
        suggestions = [
            "Ensure the diagram has been loaded correctly",
            "Check that the page is not locked or protected",
            "Try using a different shape type"
        ]
        
        if original_exception:
            suggestions.append(f"Original error: {str(original_exception)}")
        
        super().__init__(message, shape_id=None, suggestions=suggestions)


class ShapeNotFoundError(VisioShapeError):
    """Raised when a specified shape cannot be found"""
    
    def __init__(self, shape_id: str, page_name: str = None):
        """
        Initialize shape not found error.
        
        Args:
            shape_id: The shape ID that was not found
            page_name: Optional name of the page where the shape was searched
        """
        self.page_name = page_name
        
        message = f"Shape with ID '{shape_id}' not found"
        if page_name:
            message += f" on page '{page_name}'"
        
        suggestions = [
            "Use list_shapes() to see all available shape IDs",
            "Check if you're on the correct page",
            "Verify the shape ID is correct"
        ]
        
        super().__init__(message, shape_id=shape_id, suggestions=suggestions)


class PageError(VisioError):
    """Exception for page-related errors"""
    
    def __init__(self, message: str, page_name: str = None):
        """
        Initialize page error.
        
        Args:
            message: Error message
            page_name: Optional page name
        """
        self.page_name = page_name
        
        full_message = message
        if page_name:
            full_message += f" (Page: {page_name})"
        
        super().__init__(full_message)


class NoPageError(PageError):
    """Raised when no page is set or available"""
    
    def __init__(self):
        super().__init__(
            "No current page set. Load a diagram or create a page first.",
            page_name=None
        )


class ConnectorError(VisioShapeError):
    """Exception for connector-related errors"""
    
    def __init__(self, message: str, from_shape_id: str = None, to_shape_id: str = None):
        """
        Initialize connector error.
        
        Args:
            message: Error message
            from_shape_id: Optional source shape ID
            to_shape_id: Optional target shape ID
        """
        self.from_shape_id = from_shape_id
        self.to_shape_id = to_shape_id
        
        full_message = message
        if from_shape_id and to_shape_id:
            full_message += f" (From: {from_shape_id}, To: {to_shape_id})"
        
        suggestions = [
            "Verify both shape IDs exist using list_shapes()",
            "Ensure there's at least one connector in the diagram to use as template",
            "Check that the shapes are on the same page"
        ]
        
        super().__init__(full_message, shape_id=None, suggestions=suggestions)


class FileError(VisioError):
    """Exception for file I/O errors"""
    
    def __init__(self, message: str, filepath: str = None):
        """
        Initialize file error.
        
        Args:
            message: Error message
            filepath: Optional file path
        """
        self.filepath = filepath
        
        full_message = message
        if filepath:
            full_message += f" (File: {filepath})"
        
        super().__init__(full_message)

