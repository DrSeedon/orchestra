"""Search project Markdown and source logs without a second database/index."""
from pathlib import Path
from app import db


def search(scope: str, query: str, *, limit: int = 5, cross_project: bool = False,
           kinds: list[str] | None = None) -> list[dict]:
    scope, query = scope.rstrip('/'), query.strip()
    if not scope or not query:
        raise ValueError('scope and query are required')
    limit = min(max(int(limit), 1), 50)
    with db._conn() as connection:
        registered = [r[0].rstrip('/') for r in connection.execute(
            "SELECT DISTINCT scope FROM tm_projects WHERE NULLIF(scope,'') IS NOT NULL")]
        if scope not in registered:
            raise ValueError('scope is not a registered project')
        scopes = registered if cross_project else [scope]
        results = []
        needle = query.casefold()
        for project_scope in scopes:
            root = Path(project_scope)
            for area in ('kb', 'workers', 'tasks'):
                for path in sorted((root / '.orchestra' / area).rglob('*.md')):
                    # A project symlink must not turn scoped search into arbitrary-file access.
                    if not path.resolve().is_relative_to(root.resolve()):
                        continue
                    try:
                        content = path.read_text(encoding='utf-8')
                    except (FileNotFoundError, UnicodeDecodeError):
                        continue
                    offset = content.casefold().find(needle)
                    if offset >= 0:
                        results.append({'source': 'file', 'area': area,
                            'line': content.count('\n', 0, offset) + 1, 'path': str(path.relative_to(root)),
                            'scope': project_scope, 'project': project_scope, 'content': content[max(0, offset-200):offset+1800]})
                        if len(results) >= limit:
                            return results
        filters = {
            'text': "l.type='text'",
            'user_msg': "(l.type='user_message' AND l.origin='user')",
            'agent_msg': "(l.type='user_message' AND l.origin!='user')",
        }
        selected = [filters[k] for k in kinds] if kinds else ["l.type IN ('text','user_message')"]
        if not selected:
            return results
        connection.create_function('casefold', 1, str.casefold, deterministic=True)
        scope_binds = ','.join('?' for _ in scopes)
        rows = connection.execute(
            "SELECT l.id,l.ts,l.type,l.origin,l.origin_detail,"
            "substr(l.content,MAX(1,instr(casefold(l.content),?)-200),2000) AS content,s.scope,s.name "
            f"FROM logs l JOIN sessions s ON s.id=l.session_id WHERE RTRIM(s.scope,'/') IN ({scope_binds}) "
            f"AND ({' OR '.join(selected)}) AND instr(casefold(l.content),?)>0 "
            'ORDER BY l.id DESC LIMIT ?', (needle, *scopes, needle, limit-len(results)))
        from app.events import MessageProvenance
        for row in rows:
            provenance = MessageProvenance.from_storage(row['origin'], row['origin_detail'])
            kind = 'text' if row['type'] == 'text' else 'user_msg' if provenance.origin == 'user' else 'agent_msg'
            results.append({'source': 'log', 'log_id': row['id'], 'scope': row['scope'],
                'project': row['scope'], 'session_name': row['name'], 'kind': kind,
                'author': provenance.senders[0] if provenance.senders else None,
                'content': row['content'], 'ts': row['ts']})
        return results
