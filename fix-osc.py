#!/usr/bin/python3
# script to fix trashy chinese inverter
# usage example: ./fix-osc.py 192.168.16.1 H1S2602J2119E01121

from struct import unpack_from
from time import time
from sys import argv
import threading
import logging
from sajmqtt import SajMqtt

FORMAT = '%(asctime)s %(message)s'
logging.basicConfig(format=FORMAT)
logging.getLogger().setLevel(logging.INFO)


class FixOsc(object):

    STATE_NORMAL = "normal"
    STATE_FIX_OSC = "fix_osc"
    TIMEOUT_FIX_OSC = 300  # default minimum fix time, in seconds
    MAX_TIMEOUT_FIX_OSC = 1800  # maximum fix time, in seconds
    FIX_RELAX_MILD = 300
    DELAY_DEFAULT = 30
    DELAY_SHORT = 5

    POWER_LIMITED = 100
    POWER_NOMINAL = 6000

    def __init__(self, broker_ip: str, serial: str):

        self.thread = None
        self.run = False
        self.event = threading.Event()

        self.serial = serial
        self.broker_ip = broker_ip

        self.state = (FixOsc.STATE_NORMAL, None)
        self.lastfixtime = 0
        self.timeout = FixOsc.TIMEOUT_FIX_OSC

    def start(self):

        self.run = True
        self.thread = threading.Thread(target=self.thread_func)
        self.thread.start()
        self.thread.join()

    def doAction(self, current_state: str, data: bytes, mqtt: SajMqtt):

        delay = FixOsc.DELAY_DEFAULT

        try:
            power_pv, power_battery, power_grid, apower_grid, power_inverter, apower_inverter, power_backup, apower_backup = unpack_from(
                ">hhhhhhHH", data, 0x0)

            logging.debug("pv: %d, battery: %d, grid: %d, inverter: %d, backup: %d" %
                          (power_pv, power_battery, power_grid, power_inverter, power_backup))

            if current_state is FixOsc.STATE_NORMAL:
                is_fix_required = self.is_fix_required(power_pv, power_battery, power_grid, power_backup)

                if is_fix_required is True:
                    logging.info(
                        f"fix required, state -> photovoltaic: {power_pv}, battery: {power_battery}, grid: {power_grid}, backup: {power_backup}")
                    self.do_transition_to_fix_osc(mqtt)

            if current_state is FixOsc.STATE_FIX_OSC:
                if self.can_exit_fix(power_pv, power_battery, power_grid, power_backup):
                    logging.info(
                        f"exit from osc mode, state -> photovoltaic: {power_pv}, battery: {power_battery}, grid: {power_grid}, backup: {power_backup}")
                    self.do_transition_out_fix_osc(mqtt)

            if 10 < power_pv < 150:
                delay = FixOsc.DELAY_SHORT

        except ValueError as ve:
            logging.error("MQTT data could not be interpreted. Reason: %s" % (ve,))

        return delay

    def thread_func(self):

        logging.info("fixosc thread started")

        mqtt = SajMqtt(self.broker_ip, "empty_user", "empty_pass", self.serial)
        mqtt.listen()

        event = self.event
        lastquery = 0
        delay = FixOsc.DELAY_DEFAULT

        while self.run:

            event.wait(timeout=1)
            event.clear()

            current_state, argument = self.state

            if time() - lastquery > delay:

                logging.debug(f"current state {current_state}, arg: {argument}")

                try:
                    data = mqtt.query(0x40a5, 8)
                    lastquery = time()
                    delay = self.doAction(current_state, data, mqtt)
                except Exception as e:
                    logging.error("an exception occurred: %s" % (e,))

            if current_state is FixOsc.STATE_FIX_OSC:
                if time() - argument > self.timeout:
                    logging.info("exit from oscillation fix mode due to timeout")
                    self.do_transition_out_fix_osc(mqtt)

        mqtt.shutdown()

        logging.info("thread terminated")

    def shutdown(self):
        self.run = False
        self.event.set()
        if self.thread:
            self.thread.join()
            self.thread = None

    def is_fix_required(self, power_pv, power_battery, power_grid, power_backup) -> bool:

        # photovoltaic power is > 150W, no need for fix
        if power_pv > 250:
            return False

        # backup power usage is > 150W, no need for fix
        if power_backup > 150:
            return False

        # battery power is positive if battery is GIVING power
        # grid power is positive if grid is ABSORBING power

        # fix required if battery is giving more than 500 Watts
        # and grid is absorbing above 500 watts
        if power_battery > 500 and power_grid > 500:
            return True

        # fix required if battery power absorbing is above 500 Watts
        # and grid is giving above 500 watts:
        if power_battery < -500 and power_grid < -500:
            return True

        return False

    def can_exit_fix(self, power_pv, power_battery, power_grid, power_backup) -> bool:

        # if photovoltaic power is > 150W, can exit the fix state
        if power_pv > 250:
            return True

        # if backup power requered is > 150W, can exit the fix state
        if power_backup > 150:
            return True

        return False

    def do_transition_to_fix_osc(self, mqtt: SajMqtt):

        # doubles the fix timeout if a fix happened in the last 5 minutes
        if time() - self.lastfixtime < FixOsc.FIX_RELAX_MILD:
            self.timeout = min(self.timeout * 2, FixOsc.MAX_TIMEOUT_FIX_OSC)
        else:
            self.timeout = FixOsc.TIMEOUT_FIX_OSC

        logging.info("transition to fix osc, timeout for restoring condition: %d seconds" % (self.timeout,))

        try:
            mqtt.write(0x3249, FixOsc.POWER_LIMITED)
            self.state = (FixOsc.STATE_FIX_OSC, time())
        except Exception as e:
            logging.error("could not write register to fix osc. Reason: %s" % (e,))

    def do_transition_out_fix_osc(self, mqtt):

        try:
            mqtt.write(0x3249, FixOsc.POWER_NOMINAL)
            self.state = (FixOsc.STATE_NORMAL, None)
            self.lastfixtime = time()
        except Exception as e:
            logging.error("could not write register to restore condition. Reason: %s" % (e,))


if len(argv) < 3:
    print("Usage: %s <broker_ip> <serial>" % (argv[0],))
    exit()

broker_ip = argv[1]
serial = argv[2]
exit_code = 0

fixOsc = FixOsc(broker_ip, serial)

try:
    fixOsc.start()
except KeyboardInterrupt:
    pass
except:
    exit_code = 1

fixOsc.shutdown()
exit(exit_code)
