# coding: utf-8

from __future__ import print_function

import os
import time
import subprocess
import tempfile
import socket
import select
import sys

from collections import Mapping

from twisted.application.service import IServiceCollection
from twisted.application.internet import UNIXServer

from twisted.conch.manhole import ColoredManhole
from twisted.conch.insults import insults
from twisted.conch.telnet import TelnetTransport, TelnetBootstrapProtocol

from twisted.internet import protocol

import logging
logger = logging.getLogger(__name__)

__all__ = [
    'ManholeService',
]

_ManholeShell = ColoredManhole


class ManholeService(UNIXServer):

    name = "manhole"

    def __init__(self, socket_file, namespace):

        self.namespace = namespace
        self.factory = protocol.ServerFactory()
        self.factory.protocol = self._buildProtocol

        UNIXServer.__init__(
            self,
            address=socket_file,
            factory=self.factory,
            mode=0600,
            wantPID=1,
        )

    def _buildProtocol(self):
        return TelnetTransport(
            TelnetBootstrapProtocol,
            insults.ServerProtocol,
            _ManholeShell,
            dict(self.namespace),
        )


# ---

def _scan_app_services(acc, root, prefix):
    vc = 0
    for s in root:
        sname = s.name
        if not sname:
            vc += 1
            sname = "$%d" % vc
        acc[prefix + sname] = s
        if IServiceCollection.providedBy(s):
            _scan_app_services(acc, s, sname + ".")
    return acc


class ServiceScanner(Mapping):

    def __init__(self, root):
        self._root = IServiceCollection(root)

    def scan(self):
        return _scan_app_services({}, self._root, "")

    def __getitem__(self, sname):
        return self.scan()[sname]

    def get(self, sname, default=None):
        return self.scan().get(sname, default)

    def __iter__(self):
        return iter(self.scan())

    def __len__(self):
        return len(self.scan())

    def __repr__(self):
        return "<ServiceScanner: %r>" % self.scan()


# -- manhole client


def exec_manhole_client(sock_file):
    if _check_telnet_exists():
        _exec_telnet_unix_client(sock_file)
    else:
        print("!command 'telnet' is not found", file=sys.stderr)
        time.sleep(2)
        _exec_simple_unix_client(sock_file)


def _check_telnet_exists():
    try:
        subprocess.Popen(["telnet"]).kill()
        return True
    except OSError:
        return False


def _commute_sockets(sock1, sock2):
    try:
        while 1:
            toread, _, _ = select.select([sock1, sock2], [], [])
            for sa in toread:
                data = sa.recv(4096)
                if not data:
                    return
                sb = sock1 if sa is sock2 else sock2
                sb.send(data)
    except KeyboardInterrupt:
        pass


def _exec_simple_unix_client(sock_file):

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(sock_file)

    try:
        while 1:
            toread, _, _ = select.select([sys.stdin, sock], [], [])
            for sa in toread:
                if sa is sock:
                    data = sa.recv(4096)
                    if not data:
                        break
                    sys.stdout.write(data)
                    sys.stdout.flush()
                elif sa is sys.stdin:
                    data = sa.readline()
                    sock.send(data)
                else:
                    raise Exception("assertion")

    except KeyboardInterrupt:
        sys.exit(0)
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
    else:
        sys.exit(0)
    finally:
        sock.close()


def _run_forward_unix_to_tcp():
    _, sock_file, port_file = sys.argv
    _forward_unix_to_tcp(sock_file, port_file)


def _forward_unix_to_tcp(sock_file, port_file):

    # `telnet` on most linuxes doesn't support unix domain sockets
    # use separate process just to commute `unix` <-> `random tcp port`

    _, sock_file, port_file = sys.argv
    s1_listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s1_listen.settimeout(10)
    s1_listen.bind(("127.0.0.1", 0))

    port = s1_listen.getsockname()[-1]
    with open(port_file, 'w') as f:
        f.write(str(port))

    try:
        s1_listen.listen(0)
        sock1, _ = s1_listen.accept()
        s1_listen.close()

        sock2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock2.connect(sock_file)

        _commute_sockets(sock1, sock2)

    finally:
        s1_listen.close()
        sock1.close()
        sock2.close()


def _maybe_kill(p):
    try:
        if p:
            p.kill()
    except OSError:
        pass


def _exec_telnet_unix_client(sock_file):

    port_file = tempfile.mktemp(suffix="_twoost_port_box")

    p1, p2 = None, None
    try:
        p1 = subprocess.Popen([
            "python", "-c",
            "from twoost.manhole import _run_forward_unix_to_tcp as f; f()",
            sock_file,
            port_file,
        ])

        # wait port number for 5 secons
        for i in range(1000):
            time.sleep(0.05)
            if os.path.exists(port_file):
                break
        else:
            p1.kill()
            raise Exception("unable to load tcp port")

        with open(port_file) as f:
            port = int(f.readline())
        os.unlink(port_file)

        subprocess.call(["telnet", "-L", "-E", "127.0.0.1", str(port)])

    except KeyboardInterrupt:
        pass

    finally:
        _maybe_kill(p1)
        subprocess.call(["tput", "reset"])
