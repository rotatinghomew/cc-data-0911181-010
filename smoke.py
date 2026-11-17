import json
from pathlib import Path
import threading
from urllib.request import urlopen
from app.analysis import ROUTES
from app.service import make_server
from app.storage import Store


def main():
    store=Store(Path(__file__).parent/'data')
    server=make_server(store)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        for path in ['/health',*ROUTES]:
            with urlopen('http://127.0.0.1:'+str(server.server_port)+path,timeout=5) as response:
                result=json.load(response)
                print(path,json.dumps(result,ensure_ascii=False,allow_nan=False))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__=='__main__':
    main()
