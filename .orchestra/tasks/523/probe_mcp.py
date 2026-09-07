import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method = request['method']
    if method == 'initialize':
        result = {'protocolVersion': '2024-11-05', 'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'home523-probe', 'version': '1'}}
    elif method == 'tools/list':
        result = {'tools': [{'name': 'audit_ping', 'description': 'Return the audit nonce.',
                             'inputSchema': {'type': 'object', 'properties': {}}}]}
    elif method == 'tools/call':
        result = {'content': [{'type': 'text', 'text': 'HOME523_MCP_OK'}]}
    else:
        result = {}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
