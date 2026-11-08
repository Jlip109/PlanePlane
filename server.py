"""Run a movement-replication room with python server.py --host 0.0.0.0."""

import argparse
import asyncio
import os
import sys

from network import RoomServer


async def serve(args):
    room = RoomServer(args.seed,args.max_players,args.location)
    if args.websocket is None:
        port = await room.start(args.host,args.port)
        print(f'PlanePlane server listening on {args.host}:{port}',flush=True)
    else:
        port = await room.start_websocket(args.host,args.websocket)
        print(f'PlanePlane online server listening on ws://{args.host}:{port}',flush=True)
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
    from climate import LOCATIONS
    parser.add_argument('--location',choices=[p[0] for p in LOCATIONS],help='Pin a test location; default chooses randomly each round')
    parser.add_argument('--websocket',type=int,nargs='?',const=8080,default=None,metavar='PORT',
                        help='Serve over WebSocket for online play (cloud hosts set $PORT)')
    if os.environ.get('PORT') and '--websocket' not in sys.argv:
        sys.argv += ['--host','0.0.0.0','--websocket',os.environ['PORT']]
    try:
        asyncio.run(serve(parser.parse_args()))
    except KeyboardInterrupt:
        pass
