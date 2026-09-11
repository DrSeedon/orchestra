"""Hash the actual FastMCP registry across fresh interpreters; no provider calls."""
import hashlib
import json
from app import mcp_stdio
mcp_stdio._apply_access_mode()
material=[{'name':t.name,'description':t.description,'parameters':t.parameters}
          for t in mcp_stdio.mcp._tool_manager.list_tools()]
print(json.dumps({'count':len(material),'sha256':hashlib.sha256(json.dumps(material,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}))
