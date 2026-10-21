"""Bundled network boundary for deterministic pytest and standalone unittest runs."""
import ipaddress
import socket


def _loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == 'localhost'


def deny_external_network():
    original = socket.socket.connect
    resolve = socket.getaddrinfo

    def connect(sock, address):
        if sock.family in {socket.AF_INET,socket.AF_INET6} and not _loopback(address[0]):
            raise AssertionError('External dispatch is forbidden in deterministic tests; use an explicit live evaluation command')
        return original(sock,address)

    def getaddrinfo(host,*args,**kwargs):
        if host is not None and not _loopback(host.decode() if isinstance(host,bytes) else host):
            raise AssertionError('External DNS is forbidden in deterministic tests; provide a fixed resolver')
        return resolve(host,*args,**kwargs)

    socket.socket.connect=connect
    socket.getaddrinfo=getaddrinfo
    return original,resolve
