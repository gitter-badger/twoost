# coding: utf-8

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
            ColoredManhole,
            self.namespace,
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


# -- client

def _main_forward_unix_to_tcp():

    # `telnet` on most linuxes doesn't support unix domain sockets
    # use separate process just to commute `unix` <-> `tcp`

    _, sock_file, port_write_to_file = sys.argv

    src_listen = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    src_listen.settimeout(100)
    src_listen.bind(('127.0.0.1', 0))

    port = src_listen.getsockname()[-1]
    with open(port_write_to_file, 'w') as f:
        f.write(str(port))

    src_listen.listen(1)
    in_s, _ = src_listen.accept()
    out_s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    out_s.connect(sock_file)

    print("forward %r -> port %r", sock_file, port)

    try:
        while 1:
            socket_list = [in_s, out_s]
            read_sockets, _, _ = select.select(socket_list, [], [])
            for sock in read_sockets:
                data = sock.recv(4096)
                if not data:
                    return
                socki = in_s if sock is out_s else out_s
                socki.send(data)
    except KeyboardInterrupt:
        pass
    finally:
        src_listen.close()
        in_s.close()
        out_s.close()


def _telnet_unix_client(sock_file):

    port_file = tempfile.mktemp(suffix="_twoost_port_box")

    try:
        p = subprocess.Popen([
            "python", "-c",
            "from twoost.manhole import _main_forward_unix_to_tcp as f; f()",
            sock_file,
            port_file
        ])

        for i in range(100):
            time.sleep(0.01)
            if os.path.exists(port_file):
                break
        else:
            p.kill()
            raise Exception("unable to load tcp port")

        with open(port_file) as f:
            port = int(f.readline())

        subprocess.call([
            "telnet",
            "127.0.0.1",
            str(port),
        ])

    except KeyboardInterrupt:
        pass
    finally:
        os.unlink(port_file)
