#!/usr/bin/python3
# write single register via modbus tcp
# usage example: ./writetcpreg.py 192.168.16.1:502 0x3635 0x1

from sajmodbustcp import SajModbusTcp
from sys import argv, stdout, stderr
import logging

FORMAT = '%(asctime)s %(message)s'
logging.basicConfig(format=FORMAT)
logging.getLogger().setLevel(logging.DEBUG)


def normalize_hex(argument: str) -> int:

    base = 10
    start = 0

    if argument[:2] == "0x":
        base = 16
        start = 2

    return int(argument[start:], base)


if len(argv) < 4:
    print("Usage: %s <server_ip:port> <register> <value>" % (argv[0],))
    print("Example: %s 192.168.1.30 0x3635 0x1" % (argv[0],))
    exit()

server_ip, server_port = argv[1].split(":")
register = normalize_hex(argv[2])
value = normalize_hex(argv[3])

saj = SajModbusTcp(server_ip, server_port, 3, 3, 0.2)
saj.connect()

try:
    ret = saj.write(register, value)
    print("wrote %4x" % (ret,))
except Exception as e:
    logging.error("an exception occurred: %s" % (e,))

saj.shutdown()
