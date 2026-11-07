"""Run a movement-replication room with python server.py --host 0.0.0.0."""

import argparse
import asyncio

from network import RoomServer


async def serve(args):
    room = RoomServer(args.seed,args.max_players)
    port = await room.start(args.host,args.port)
    print(f'PlanePlane server listening on {args.host}:{port}',flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await room.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--seed',type=int,default=1)
    parser.add_argument('--max-players',type=int,choices=range(1,101),default=100)
    try:
        asyncio.run(serve(parser.parse_args()))
    except KeyboardInterrupt:
        pass
