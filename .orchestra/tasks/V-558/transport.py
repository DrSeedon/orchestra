"""CONNECT-only benchmark relay: provider hosts only; no repository/localhost fetches."""
import asyncio
ALLOWED={'chatgpt.com','api.openai.com','auth.openai.com','api.anthropic.com','platform.claude.com'}
class Relay:
    def __init__(self): self.events=[]
    async def client(self,r,w):
        peer=None
        try:
            header=await asyncio.wait_for(r.readuntil(b'\r\n\r\n'),10)
            line=header.split(b'\r\n',1)[0].decode('ascii')
            parts=line.split()
            target=parts[1] if len(parts)==3 else ''
            host,_,port=target.rpartition(':')
            allowed=len(parts)==3 and parts[0]=='CONNECT' and host in ALLOWED and port=='443'
            self.events.append({'target':target,'allowed':allowed})
            if not allowed:
                w.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n'); await w.drain();return
            upstream,peer=await asyncio.open_connection(host,443)
            w.write(b'HTTP/1.1 200 Connection established\r\n\r\n');await w.drain()
            async def pump(src,dst):
                while data:=await src.read(65536): dst.write(data);await dst.drain()
            tasks=[asyncio.create_task(pump(r,peer)),asyncio.create_task(pump(upstream,w))]
            done,pending=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in pending: task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
        except Exception as exc:
            self.events.append({'error':type(exc).__name__})
        finally:
            w.close()
            if peer:peer.close()
    async def start(self):
        self.server=await asyncio.start_server(self.client,'127.0.0.1',0)
        self.port=self.server.sockets[0].getsockname()[1]
        return self
    async def close(self):
        self.server.close();await self.server.wait_closed()
