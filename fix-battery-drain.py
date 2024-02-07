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
    REG_APP_MODE = 0x3247
    REG_BATTERY_CURRENT = 0x406a

    FLAG_REVERSE_FLOW_PREVENT = 0x1
    FLAG_REVERSE_FLOW_ALLOW = 0x0

    # The threshold power which, if exceeded, will apply the fix
    THRESHOLD = -5  # Watts

    NORMAL_CYCLE_DURATION = 120  # in seconds
    FIX_CYCLE_DURATION = 1800  # in seconds

    APP_MODE_SELF_USE = 0x0
    APP_MODE_PASSIVE = 0x3

    def __init__(self):
        self.run = False
        self.sajmqtt = None

        self.is_fix_applied = None
        self.app_mode = None

    def preventReverseFlow(self):
        self.sajmqtt.write(FixBatteryDrain.REG_REVERSE_FLOW, FixBatteryDrain.FLAG_REVERSE_FLOW_PREVENT)
        self.is_fix_applied = True

    def allowReverseFlow(self):
        self.sajmqtt.write(FixBatteryDrain.REG_REVERSE_FLOW, FixBatteryDrain.FLAG_REVERSE_FLOW_ALLOW)
        self.is_fix_applied = False

    def applySelfUse(self):
        self.sajmqtt.write(FixBatteryDrain.REG_APP_MODE, FixBatteryDrain.APP_MODE_SELF_USE)
        self.app_mode = FixBatteryDrain.APP_MODE_SELF_USE

    def applyPassive(self):
        self.sajmqtt.write(FixBatteryDrain.REG_APP_MODE, FixBatteryDrain.APP_MODE_PASSIVE)
        self.app_mode = FixBatteryDrain.APP_MODE_PASSIVE

    def doCycleSelfUse(self, battery_current, power_pv, power_meter):
        """
        Do the
        :param is_fix_applied:
        :param battery_current:
        :param power_pv:
        :param power_meter:
        :return:
        """

        new_duration = None

        # When battery has minimal charging and there is no photovoltaic
        # power, plus there is some load, then it means that the battery SOC has
        # reached low watermark
        if -1.0 <= battery_current <= -0.01 and power_pv == 0 and power_meter > 0:
            # Turn off the flow prevention, we are moving into passive mode and
            # don't need that
            logging.info("Moving into passive mode, status: battery_current: %.2f, power_pv: %d, power_meter: %d" %
                         (battery_current, power_pv, power_meter), )
            self.applyPassive()
            self.allowReverseFlow()

            new_duration = FixBatteryDrain.FIX_CYCLE_DURATION

        else:

            if self.is_fix_applied is False:
                if power_pv == 0 and power_meter < FixBatteryDrain.THRESHOLD:
                    logging.info("Apply fix, status: battery_current: %.2f, power_pv: %d, power_meter: %d" %
                                 (battery_current, power_pv, power_meter), )
                    self.preventReverseFlow()
                    new_duration = FixBatteryDrain.FIX_CYCLE_DURATION

            elif self.is_fix_applied is True and power_meter >= 0:
                logging.info("Restoring condition, status: battery_current: %.2f, power_pv: %d, power_meter: %d" %
                             (battery_current, power_pv, power_meter), )
                self.allowReverseFlow()
                new_duration = FixBatteryDrain.NORMAL_CYCLE_DURATION

        return new_duration

    def doCyclePassiveMode(self, battery_current, power_pv, power_meter):
        """
            If in passive mode, as soon as we notice any kind of photovoltaic power
            move out from passive mode and restore self use
        :param battery_current:
        :param power_pv:
        :param power_meter:
        :return:
        """
        new_duration = None

        if power_pv > 0:
            logging.info("Moving into self use mode, status: battery_current: %.2f, power_pv: %d, power_meter: %d" %
                         (battery_current, power_pv, power_meter), )
            self.applySelfUse()
            self.allowReverseFlow()

            new_duration = FixBatteryDrain.NORMAL_CYCLE_DURATION

        return new_duration

    def start(self, broker, serial):
        self.sajmqtt = sajmqtt.SajMqtt(broker, "empty_user", "empty_pass", serial)
        self.sajmqtt.listen()

        self.run = True

        # Get the current state
        while self.is_fix_applied is None or self.app_mode is None:
            try:
                self.is_fix_applied, = unpack_from(">H", self.sajmqtt.query(FixBatteryDrain.REG_REVERSE_FLOW, 1))
                self.is_fix_applied = self.is_fix_applied == 1
                self.app_mode, = unpack_from(">H", self.sajmqtt.query(FixBatteryDrain.REG_APP_MODE, 1))
            except:
                time.sleep(10)

        duration = FixBatteryDrain.NORMAL_CYCLE_DURATION

        logging.info("fix-battery-drain set up, initial fix state is %s, app mode is %d" % ("on" if self.is_fix_applied else "off", self.app_mode))

        while self.run:

            try:

                power_pv, = unpack_from(">h", self.sajmqtt.query(FixBatteryDrain.REG_PHOTOVOLTAIC_TOTAL, 1))
                power_meter, = unpack_from(">h", self.sajmqtt.query(FixBatteryDrain.REG_SMART_METER_LOAD, 1))
                battery_current, = unpack_from(">h", self.sajmqtt.query(FixBatteryDrain.REG_BATTERY_CURRENT, 1))
                battery_current = battery_current * 0.01

                new_duration = None

                if self.app_mode == FixBatteryDrain.APP_MODE_SELF_USE:
                    new_duration = self.doCycleSelfUse(battery_current, power_pv, power_meter)
                elif self.app_mode == FixBatteryDrain.APP_MODE_PASSIVE:
                    new_duration = self.doCyclePassiveMode(battery_current, power_pv, power_meter)

                if new_duration is not None:
                    duration = new_duration

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

try:
    fixBatteryDrain.shutdown()
except:
    pass

exit(exit_code)
