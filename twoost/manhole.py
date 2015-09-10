# coding: utf-8

import os
import sys
import socket
import select
import string

from twisted.manhole.telnet import ShellFactory, Shell

import logging
logger = logging.getLogger(__name__)


__all__ = [
    'AnonymousShell',
    'AnonymousShellFactory',
]

class AnonymousShell(Shell):

    mode = 'Command'

    def loginPrompt(self):
        # no login
        return ">>> "

    def welcomeMessage(self):
        processid = os.getpid()
        workerid = os.environ.get('TWOOST_WORKERID') or "-"
        return "manhole for %s, pid %s\r\n" % (workerid, processid)

    def doCommand(self, cmd):
        logger.info("execute cmd: %r", cmd)
        return Shell.doCommand(self, cmd)


class AnonymousShellFactory(ShellFactory):

    protocol = AnonymousShell

    def __init__(self, namespace=None):
        ShellFactory.__init__(self)
        self.namespace.update(namespace or {})


def _telnet_unix_client(sock_file):
    try:
        _telnet_unix_client_loop(sock_file)
    except KeyboardInterrupt:
        return


def _telnet_unix_client_loop(sock_file):

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(sock_file)

    sys.stdout.write("│ ")
    sys.stdout.flush()

    while True:

        socket_list = [sys.stdin, s]
        read_sockets, _, _ = select.select(socket_list , [], [])

        for sock in read_sockets:

            if sock is s:

                # incoming message from remote server
                data = sock.recv(4096)
                if not data:
                    # connection closed
                    sys.stderr.write("\n│!Connection was closed")
                    return
                else:
                    data = data.replace("\r\n", "\n").replace("\n", "\n│ ")
                    sys.stdout.write(data)
                    sys.stdout.flush()

            # user entered a message
            else:
                msg = sys.stdin.readline()
                if not msg:
                    return

                sys.stdout.write("│ ")
                sys.stdout.flush()

                if not msg.endswith("\r\n"):
                    msg = msg.rstrip("\n") + "\r\n"

                s.send(msg)
