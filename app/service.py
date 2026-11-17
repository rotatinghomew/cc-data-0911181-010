import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .analysis import ROUTES
from .journal import Journal
from .workflow import OPERATIONS
from .storage import DataError, Store, single


def dispatch(store, path, query):
    if path == '/health':
        return {'status': 'ok', 'tables': store.inventory()}
    if path == '/api/records':
        name = single(query, 'table')
        if name is None:
            raise DataError('table required')
        return {'rows': store.table(name)}
    if path not in ROUTES:
        raise KeyError(path)
    return ROUTES[path](store, query)


def make_server(store, host='127.0.0.1', port=0, journal=None):
    journal=journal or Journal()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlsplit(self.path)
            try:
                payload = dispatch(store, parsed.path, parse_qs(parsed.query, keep_blank_values=True))
                status = 200
            except KeyError:
                status, payload = 404, {'error': 'not found'}
            except DataError as error:
                status, payload = 400, {'error': str(error)}
            except Exception:
                status, payload = 500, {'error': 'internal failure'}
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            operation=urlsplit(self.path).path.removeprefix('/api/workflow/')
            try:
                if not self.path.startswith('/api/workflow/') or operation not in OPERATIONS:
                    raise KeyError(operation)
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=65536:
                    raise DataError('invalid request size')
                payload=json.loads(self.rfile.read(size))
                if not isinstance(payload,dict):
                    raise DataError('object payload required')
                result=OPERATIONS[operation](store,journal,payload)
                status=200
            except KeyError as error:
                status,result=400,{'error':'unknown operation or missing field: '+str(error)}
            except (DataError,ValueError,TypeError) as error:
                status,result=400,{'error':str(error)}
            body=json.dumps(result,ensure_ascii=False,allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            return

    return ThreadingHTTPServer((host, port), Handler)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['summary', 'serve', 'check'])
    parser.add_argument('--data', default=str(Path(__file__).parents[1] / 'data'))
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--state',default=':memory:')
    args = parser.parse_args()
    store = Store(args.data)
    if args.action == 'check':
        print(json.dumps({'tables': store.inventory(), 'fingerprint': store.fingerprint()},
                         ensure_ascii=False, indent=2))
    elif args.action == 'summary':
        from .reporting import report
        print(json.dumps(report(store), ensure_ascii=False, indent=2, allow_nan=False))
    else:
        server = make_server(store, args.host, args.port, Journal(args.state))
        print('Listening on http://' + args.host + ':' + str(server.server_port), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
