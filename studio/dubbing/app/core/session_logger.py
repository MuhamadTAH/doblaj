import logging
from contextlib import contextmanager
from pathlib import Path

@contextmanager
def session_log_context(session_id: str):
    """
    Context manager that temporarily attaches a FileHandler to the root logger
    to capture all logs during the execution of a job session.
    """
    if not session_id:
        yield
        return

    root_logger = logging.getLogger()
    
    # Path to the session's job.log
    # Adjust path if data folder is elsewhere, but usually it's at project root
    base_dir = Path(__file__).resolve().parent.parent.parent
    log_file = base_dir / "data" / "jobs" / "sessions" / session_id / "job.log"
    
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        # If we can't create the directory (e.g. permission error), just yield and skip logging
        logging.getLogger(__name__).warning(f"Could not create log directory for {session_id}: {e}")
        yield
        return

    # Check if a handler for this exact file is already attached (to prevent duplicates)
    log_file_str = str(log_file.absolute())
    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler) and handler.baseFilename == log_file_str:
            # Already logging to this file in this context/process
            yield
            return
            
    fh = logging.FileHandler(log_file_str)
    fh.setLevel(logging.DEBUG)  # Capture everything down to DEBUG
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    
    root_logger.addHandler(fh)
    try:
        yield
    finally:
        root_logger.removeHandler(fh)
        fh.close()
