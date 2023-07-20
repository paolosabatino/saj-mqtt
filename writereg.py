#!/usr/bin/python3
# information gathering for saj inverters through data_transmission mqtt topic
# usage example: ./writereg.py 192.168.16.1 H1S2602J2119E01121 0x3635 0x1

from sajmqtt import SajMqtt
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


if len(argv) < 5:
    print("Usage: %s <broker_ip> <serial> <register> <value>" % (argv[0],))
    print("Example: %s 192.168.1.30 H1S267K2429B029410 0x3635 0x1" % (argv[0],))
    exit()

broker_ip = argv[1]
serial = argv[2]
register = normalize_hex(argv[3])
value = normalize_hex(argv[4])

mqtt = SajMqtt(broker_ip, "empty_user", "empty_pass", serial)
mqtt.listen()

try:
    ret = mqtt.write(register, value)
    print("wrote %4x" % (ret,))
except Exception as e:
    logging.error("an exception occurred: %s" % (e,))

mqtt.shutdown()
