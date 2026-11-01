"""Fill text templates with recipient data and write the merged messages."""
from .merge import build_messages
from .recipients import load_recipients
from .template import load_template, render

__version__ = "0.6.2"
