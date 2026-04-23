"""
Logging system for Visio operations
Saves all operations to indexed log directories
"""
import os
import json
import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import shutil
import tempfile


class VisioLogger:
    """Logger for Visio diagram operations"""
    
    def __init__(self, base_log_dir: str = ".state/log"):
        """
        Initialize logger with indexed subdirectories
        
        Args:
            base_log_dir: Base directory for all logs
        """
        self.base_log_dir = Path(base_log_dir)
        self.base_log_dir.mkdir(exist_ok=True)
        
        # Find next available index
        self.session_index = self._get_next_index()
        self.session_dir = self.base_log_dir / str(self.session_index)
        self.session_dir.mkdir(exist_ok=True)
        
        # Create log file
        self.log_file = self.session_dir / "operations.log"
        self.operations_file = self.session_dir / "operations.json"
        self.metadata_file = self.session_dir / "metadata.json"
        
        # Initialize logs
        self.operations = []
        self._write_metadata()
        
        self._log_message(f"Session started: {self.session_index}")
    
    def _get_next_index(self) -> int:
        """Get next available index for session directory"""
        existing_indices = []
        for item in self.base_log_dir.iterdir():
            if item.is_dir() and item.name.isdigit():
                existing_indices.append(int(item.name))
        
        return max(existing_indices, default=-1) + 1
    
    # ---- robust json io ----
    def _atomic_write_json(self, path: Path, data: Dict[str, Any]):
        """Safely write JSON to a file using an atomic replace.

        Uses a uniquely named temporary file in the same directory to avoid
        race conditions when multiple writes occur concurrently.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), prefix=f"{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        finally:
            # If replace succeeded, tmp_path no longer exists; ignore errors
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass

    def _read_metadata_file(self) -> Dict[str, Any]:
        if not self.metadata_file.exists():
            return {}
        try:
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    return {}
                return json.loads(content)
        except Exception:
            # Corrupted/partial file; fall back to empty to keep service running
            return {}

    def _write_metadata(self):
        """Write session metadata"""
        metadata = {
            "session_index": self.session_index,
            "start_time": datetime.datetime.now().isoformat(),
            "operations_count": 0,
            "files_processed": [],
        }
        self._atomic_write_json(self.metadata_file, metadata)
    
    def _update_metadata(self, **kwargs):
        """Update metadata file"""
        metadata = self._read_metadata_file()
        
        metadata.update(kwargs)
        metadata["last_updated"] = datetime.datetime.now().isoformat()
        self._atomic_write_json(self.metadata_file, metadata)
    
    def _log_message(self, message: str):
        """Write message to log file"""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    
    def log_operation(self, operation: str, details: Dict[str, Any], 
                     result: str, success: bool = True):
        """
        Log a Visio operation
        
        Args:
            operation: Name of the operation
            details: Operation parameters
            result: Result message
            success: Whether operation succeeded
        """
        timestamp = datetime.datetime.now().isoformat()
        
        operation_log = {
            "timestamp": timestamp,
            "operation": operation,
            "details": details,
            "result": result,
            "success": success
        }
        
        self.operations.append(operation_log)
        
        # Write to operations file atomically
        self._atomic_write_json(self.operations_file, self.operations)
        
        # Write to log file
        status = "SUCCESS" if success else "FAILED"
        self._log_message(f"[{status}] {operation}: {result}")
        
        # Update metadata
        self._update_metadata(
            operations_count=len(self.operations),
            last_operation=operation
        )
    
    def log_file_operation(self, filepath: str, operation: str = "processed"):
        """Log file operation and update metadata"""
        # Update metadata with file info
        metadata = self._read_metadata_file()
        
        files_processed = metadata.get("files_processed", [])
        if filepath not in files_processed:
            files_processed.append(filepath)
        
        self._update_metadata(files_processed=files_processed)
        self._log_message(f"File {operation}: {filepath}")
    
    def save_diagram_copy(self, source_path: str, label: str = "output"):
        """
        Save a copy of the diagram to the log directory
        
        Args:
            source_path: Path to the source diagram
            label: Label for the saved file
        """
        if not os.path.exists(source_path):
            self._log_message(f"Cannot save copy: {source_path} not found")
            return
        
        # Create filename with timestamp
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        basename = Path(source_path).stem
        extension = Path(source_path).suffix
        
        dest_filename = f"{label}_{basename}_{timestamp}{extension}"
        dest_path = self.session_dir / dest_filename
        
        try:
            shutil.copy2(source_path, dest_path)
            self._log_message(f"Saved diagram copy: {dest_filename}")
        except Exception as e:
            self._log_message(f"Error saving diagram copy: {e}")

    def get_summary(self) -> Dict[str, Any]:
        """Get session summary"""
        metadata = self._read_metadata_file()
        
        return {
            "session_index": self.session_index,
            "session_dir": str(self.session_dir),
            "operations_count": len(self.operations),
            "files_processed": metadata.get("files_processed", []),
            "start_time": metadata.get("start_time"),
            "last_updated": metadata.get("last_updated"),
        }
    
    def close(self):
        """Close the logger session"""
        self._log_message(f"Session ended: {self.session_index}")
        self._update_metadata(
            end_time=datetime.datetime.now().isoformat(),
            status="completed"
        )


# Global logger instance
_logger: Optional[VisioLogger] = None


def get_logger() -> VisioLogger:
    """Get or create global logger instance"""
    global _logger
    if _logger is None:
        _logger = VisioLogger()
    return _logger


def log_operation(operation: str, details: Dict[str, Any], result: str, success: bool = True):
    """Convenience function to log operation"""
    logger = get_logger()
    logger.log_operation(operation, details, result, success)


def log_file_operation(filepath: str, operation: str = "processed"):
    """Convenience function to log file operation"""
    logger = get_logger()
    logger.log_file_operation(filepath, operation)


def save_diagram_copy(source_path: str, label: str = "output"):
    """Convenience function to save diagram copy"""
    logger = get_logger()
    logger.save_diagram_copy(source_path, label)


def get_session_summary() -> Dict[str, Any]:
    """Get current session summary"""
    logger = get_logger()
    return logger.get_summary()

