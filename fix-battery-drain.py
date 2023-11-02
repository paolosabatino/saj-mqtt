#!/usr/bin/python3
# script to fix battery drain on trashy chinese inverter
# usage example: ./fix-battery-drain.py 192.168.16.1 H1S2602J2119E01121

from struct import unpack_from
import time
from sys import argv
import logging

import sajmqtt
from sajmqtt import SajMqtt

FORMAT = '%(asctime)s %(message)s'
logging.basicConfig(format=FORMAT)
logging.getLogger().setLevel(logging.INFO)


class FixBatteryDrain(object):

    REG_PHOTOVOLTAIC_TOTAL = 0x40a5
    REG_SMART_METER_LOAD = 0x40a1
    REG_REVERSE_FLOW = 0x3635

    FLAG_REVERSE_FLOW_PREVENT = 0x1
    FLAG_REVERSE_FLOW_ALLOW = 0x0

    # The threshold power which, if exceeded, will apply the fix
    THRESHOLD = -5  # Watts

    NORMAL_CYCLE_DURATION = 120  # in seconds
    FIX_CYCLE_DURATION = 21600  # in seconds

    def __init__(self):
        self.run = False
        self.sajmqtt = None

    def start(self, broker, serial):
        self.sajmqtt = sajmqtt.SajMqtt(broker, "empty_user", "empty_pass", serial)
        self.sajmqtt.listen()

        self.run = True
        is_fix_applied = None

        # Get the current state
        while is_fix_applied is not None:
            try:
                is_fix_applied, = unpack_from(">H", self.sajmqtt.query(FixBatteryDrain.REG_REVERSE_FLOW, 1))
                is_fix_applied = is_fix_applied == 1
            except:
                time.sleep(10)

        duration = FixBatteryDrain.NORMAL_CYCLE_DURATION

        logging.info("fix-battery-drain set up, initial fix state is %s" % ("on" if is_fix_applied else "off",))

        while self.run:

            try:

                power_pv, = unpack_from(">h", self.sajmqtt.query(FixBatteryDrain.REG_PHOTOVOLTAIC_TOTAL, 1))
                power_meter, = unpack_from(">h", self.sajmqtt.query(FixBatteryDrain.REG_SMART_METER_LOAD, 1))

                if is_fix_applied is False:
                    if power_pv == 0 and power_meter < FixBatteryDrain.THRESHOLD:
                        logging.info("Apply fix, status: power_pv: %d, power_meter: %d" % (power_pv, power_meter),)
                        self.sajmqtt.write(FixBatteryDrain.REG_REVERSE_FLOW, FixBatteryDrain.FLAG_REVERSE_FLOW_PREVENT)
                        is_fix_applied = True
                        duration = FixBatteryDrain.FIX_CYCLE_DURATION

                elif is_fix_applied is True and power_meter >= 0:
                    logging.info("Restoring condition, status: power_pv: %d, power_meter: %d" % (power_pv, power_meter), )
                    self.sajmqtt.write(FixBatteryDrain.REG_REVERSE_FLOW, FixBatteryDrain.FLAG_REVERSE_FLOW_ALLOW)
                    is_fix_applied = False
                    duration = FixBatteryDrain.NORMAL_CYCLE_DURATION

            except TimeoutError as e:
                logging.error(e,)
                duration = FixBatteryDrain.NORMAL_CYCLE_DURATION

            time.sleep(duration)

    def shutdown(self):
        self.run = False

        if self.sajmqtt:
            self.sajmqtt.shutdown()


# entry point

if len(argv) < 3:
    print("Usage: %s <broker_ip> <serial>" % (argv[0],))
    exit()

broker_ip = argv[1]
serial = argv[2]
exit_code = 0

fixBatteryDrain = FixBatteryDrain()
try:
    fixBatteryDrain.start(broker_ip, serial)
except KeyboardInterrupt:
    pass
except TimeoutError as e:
    logging.error("Timeout error on initialization: %s" % (e,))
    exit_code = 1

fixBatteryDrain.shutdown()
exit(exit_code)
