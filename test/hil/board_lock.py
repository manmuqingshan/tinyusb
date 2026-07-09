#!/usr/bin/env python3
"""Per-board advisory locks for the HIL rig.

Arbitrates board access between dev sessions and CI's hil_test.py without
stopping the actions-runner. Locks are kernel flocks: the kernel releases
them automatically when the holder process dies, so stale locks are
impossible (/tmp also clears on reboot).

Usage:
  board_lock.py hold BOARD [BOARD...] --reason TEXT
  board_lock.py hold --all [--config test/hil/tinyusb.json] --reason TEXT
  board_lock.py release BOARD [BOARD...] | release --all
  board_lock.py status

A holder process holds ALL boards given in one `hold` call; releasing any of
them kills that holder and releases all of its boards.
"""
import argparse
import fcntl
import json
import os
import select
import signal
import sys
import time

LOCK_DIR = '/tmp/tinyusb-hil-locks'


def lock_path(board: str) -> str:
    return os.path.join(LOCK_DIR, f'{board}.lock')


def boards_from_config(config: str) -> list:
    try:
        with open(config) as f:
            return [b['name'] for b in json.load(f)['boards']]
    except (OSError, ValueError, KeyError) as e:
        print(f'ERROR: cannot read board roster {config}: {e}', file=sys.stderr)
        sys.exit(1)


def read_info(board: str):
    try:
        with open(lock_path(board)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def is_locked(board: str) -> bool:
    """True if some live process currently holds the flock."""
    path = lock_path(board)
    if not os.path.exists(path):
        return False
    with open(path) as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
            return False
        except OSError:
            return True


def cmd_hold(boards, reason):
    os.makedirs(LOCK_DIR, exist_ok=True)
    already = [b for b in boards if is_locked(b)]
    if already:
        for b in already:
            print(f'ERROR: {b} already locked: {read_info(b)}', file=sys.stderr)
        return 1
    # The holder signals success through this pipe. A generic is_locked()
    # poll would be fooled by a RIVAL invocation's flock — only the holder
    # itself knows whether it won every board.
    r_fd, w_fd = os.pipe()
    pid = os.fork()
    if pid > 0:
        os.close(w_fd)
        os.waitpid(pid, 0)  # reap intermediate child
        ready, _, _ = select.select([r_fd], [], [], 10)
        ok = bool(ready) and os.read(r_fd, 1) == b'1'
        os.close(r_fd)
        if ok:
            print(f'held: {", ".join(boards)}')
            return 0
        print('ERROR: holder failed to acquire locks (lost a race?)', file=sys.stderr)
        return 1
    # intermediate child: detach, then spawn the actual holder
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    # holder (grandchild): acquire all flocks, signal the parent, sleep until killed
    os.close(r_fd)
    try:
        handles = []
        for b in boards:
            # O_RDWR without O_TRUNC: never truncate before the flock is
            # held — a losing racer must not wipe the winner's holder info.
            fd = os.open(lock_path(b), os.O_RDWR | os.O_CREAT, 0o666)
            fh = os.fdopen(fd, 'r+')
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fh.truncate(0)
            fh.seek(0)
            json.dump({'pid': os.getpid(), 'reason': reason,
                       'since': time.strftime('%Y-%m-%dT%H:%M:%S%z')}, fh)
            fh.flush()
            handles.append(fh)
    except OSError:
        try:
            os.write(w_fd, b'0')
        except OSError:
            pass
        os._exit(1)  # lost a race; parent reports the failure
    os.write(w_fd, b'1')
    os.close(w_fd)
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    while True:
        signal.pause()


def cmd_release(boards):
    pids = set()
    for b in boards:
        if not is_locked(b):
            continue
        info = read_info(b) or {}
        if info.get('pid'):
            pids.add(info['pid'])
    for holder in sorted(pids):
        try:
            os.kill(holder, signal.SIGTERM)
            print(f'released holder pid {holder}')
        except ProcessLookupError:
            pass
    time.sleep(0.3)
    still = [b for b in boards if is_locked(b)]
    if still:
        print(f'ERROR: still locked: {", ".join(still)}', file=sys.stderr)
        return 1
    return 0


def cmd_status():
    if not os.path.isdir(LOCK_DIR):
        print('no locks')
        return 0
    any_locked = False
    for fn in sorted(os.listdir(LOCK_DIR)):
        if not fn.endswith('.lock'):
            continue
        b = fn[:-5]
        if is_locked(b):
            any_locked = True
            print(f'{b}: {read_info(b)}')
    if not any_locked:
        print('no locks')
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p_hold = sub.add_parser('hold')
    p_hold.add_argument('boards', nargs='*')
    p_hold.add_argument('--all', action='store_true')
    p_hold.add_argument('--config', default='test/hil/tinyusb.json')
    p_hold.add_argument('--reason', required=True)
    p_rel = sub.add_parser('release')
    p_rel.add_argument('boards', nargs='*')
    p_rel.add_argument('--all', action='store_true')
    sub.add_parser('status')
    a = ap.parse_args()
    if a.cmd == 'hold':
        boards = boards_from_config(a.config) if a.all else a.boards
        if not boards:
            ap.error('no boards given (name boards or use --all)')
        sys.exit(cmd_hold(boards, a.reason))
    if a.cmd == 'release':
        if a.all:
            boards = ([fn[:-5] for fn in os.listdir(LOCK_DIR) if fn.endswith('.lock')]
                      if os.path.isdir(LOCK_DIR) else [])
        else:
            boards = a.boards
        if not boards:
            ap.error('no boards given (name boards or use --all)')
        sys.exit(cmd_release(boards))
    sys.exit(cmd_status())


if __name__ == '__main__':
    main()
