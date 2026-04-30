"""
Logging system for Visio operations
Saves all operations to indexed log directories
"""
import os
import json
import logging
import datetime
import threading
import traceback as _traceback
from pathlib import Path
from typing import Any, Dict, Optional
import shutil
import tempfile
import time


_handler_local = threading.local()


class _VisioLogHandler(logging.Handler):
    """Routes Python WARNING/ERROR/CRITICAL records into a VisioLogger session.

    Uses a thread-local flag to prevent re-entrant calls when the handler
    itself performs I/O that could trigger further log records.
    """

    def __init__(self, visio_logger: "VisioLogger", level: int = logging.WARNING):
        super().__init__(level)
        self._visio_logger = visio_logger

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(_handler_local, "emitting", False):
            return
        _handler_local.emitting = True
        try:
            level = record.levelname
            msg = record.getMessage()

            tb = ""
            if record.exc_info:
                tb = "\n" + "".join(_traceback.format_exception(*record.exc_info)).rstrip()

            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{timestamp}] [{level}] [{record.name}] {msg}{tb}\n"

            with open(self._visio_logger.log_file, "a", encoding="utf-8") as fh:
                fh.write(log_entry)

            op = {
                "timestamp": datetime.datetime.now().isoformat(),
                "operation": f"{level}:{record.name}",
                "details": {
                    "logger": record.name,
                    "level": level,
                    "module": record.module,
                    "lineno": record.lineno,
                },
                "result": msg + tb,
                "success": record.levelno < logging.ERROR,
            }
            self._visio_logger.operations.append(op)
            self._visio_logger._atomic_write_json(
                self._visio_logger.operations_file,
                self._visio_logger.operations,
            )
        except Exception:
            pass
        finally:
            _handler_local.emitting = False


class VisioLogger:
    """Logger for Visio diagram operations"""
    
    def __init__(self, base_log_dir: Optional[str] = None):
        """
        Initialize logger with indexed subdirectories
        
        Args:
            base_log_dir: Base directory for all logs. Defaults to
                VISIO_LOG_DIR or .state/log.
        """
        self.base_log_dir = Path(base_log_dir or os.environ.get("VISIO_LOG_DIR", ".state/log"))
        self.base_log_dir.mkdir(parents=True, exist_ok=True)
        
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

        # Attach Python logging bridge so WARNING/ERROR from any module
        # (agno, visio_core, etc.) land in this session's log file.
        self._py_log_handler = _VisioLogHandler(self)
        logging.getLogger().addHandler(self._py_log_handler)

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
            last_error: Optional[Exception] = None
            for attempt in range(3):
                try:
                    os.replace(tmp_path, path)
                    last_error = None
                    break
                except PermissionError as exc:
                    last_error = exc
                    time.sleep(0.05 * (attempt + 1))
            if last_error is not None:
                raise last_error
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

        status = "SUCCESS" if success else "FAILED"
        self._log_message(f"[{status}] {operation}: {result}")

        try:
            self._atomic_write_json(self.operations_file, self.operations)
        except Exception as exc:
            self._log_message(
                f"[WARNING] Failed to persist operations.json for {operation}: {exc}"
            )

        try:
            self._update_metadata(
                operations_count=len(self.operations),
                last_operation=operation
            )
        except Exception as exc:
            self._log_message(
                f"[WARNING] Failed to update metadata for {operation}: {exc}"
            )
    
    def log_file_operation(self, filepath: str, operation: str = "processed"):
        """Log file operation and update metadata"""
        # Update metadata with file info
        metadata = self._read_metadata_file()
        
        files_processed = metadata.get("files_processed", [])
        if filepath not in files_processed:
            files_processed.append(filepath)

        try:
            self._update_metadata(files_processed=files_processed)
        except Exception as exc:
            self._log_message(
                f"[WARNING] Failed to update metadata for file operation {operation}: {exc}"
            )
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
    
    def log_warning(self, message: str, details: Optional[Dict[str, Any]] = None):
        """Explicitly record a WARNING entry from within tool code."""
        self._log_message(f"[WARNING] {message}")
        op = {
            "timestamp": datetime.datetime.now().isoformat(),
            "operation": "WARNING",
            "details": details or {},
            "result": message,
            "success": False,
        }
        self.operations.append(op)
        try:
            self._atomic_write_json(self.operations_file, self.operations)
        except Exception as exc:
            self._log_message(
                f"[WARNING] Failed to persist WARNING entry to operations.json: {exc}"
            )

    def close(self):
        """Close the logger session"""
        logging.getLogger().removeHandler(self._py_log_handler)
        self._log_message(f"Session ended: {self.session_index}")
        try:
            self._update_metadata(
                end_time=datetime.datetime.now().isoformat(),
                status="completed"
            )
        except Exception as exc:
            self._log_message(f"[WARNING] Failed to finalize session metadata: {exc}")


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


def log_warning(message: str, details: Optional[Dict[str, Any]] = None):
    """Convenience function to log a warning"""
    get_logger().log_warning(message, details)

