"""Save the supplied search function for independent, in-memory mutation checks."""
from pathlib import Path
root = Path(__file__).resolve().parents[3]
source = (root / 'app/db.py').read_text()
start, end = source.index('def search_logs('), source.index('\ndef get_log_context(')
Path(__file__).with_name('baseline_search.py').write_text(source[start:end])
