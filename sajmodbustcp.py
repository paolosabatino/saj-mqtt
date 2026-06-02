import threading
import logging
import time
from pymodbus.client import ModbusTcpClient

class SajModbusTcp(object):

    EXCEPTION_CODES = {
        1: "Illegal function",
        2: "Illegal data address",
        3: "Illegal data value",
        4: "Slave device failure",
        5: "Acknowledge (requested accepted, still processing)",
        6: "Slave device busy"
    }

    # Default timeout
    TIMEOUT = 15

    # Default maximum number of register to read per request. Cannot exceed 125 registers (0x7d)
    MAX_REGISTERS_PER_REQUEST = 0x64

    # Default slave address
    SLAVE_ADDRESS = 0x1

    def __init__(self, ip_address: str, port: int, timeout:float = 3, retries: int = 3, retries_delay: float = 1):

        self.ip_address = ip_address
        self.port = int(port)
        self.timeout = timeout
        self.retries = retries
        self.retries_delay = retries_delay

        self.client = ModbusTcpClient(host=self.ip_address, port=self.port, timeout=self.timeout, retries=1)

    def connect(self):

        logging.debug("connecting to %s:%d" % (self.ip_address, self.port))

        ret = self.client.connect()

        if not ret:
            raise Exception("could not connect")

        logging.debug("connected to %s:%d" % (self.ip_address, self.port))

    def shutdown(self):

        logging.debug("disconnecting from %s:%d" % (self.ip_address, self.port))

        if self.client:
            self.client.close()

        logging.debug("disconnected from %s:%d" % (self.ip_address, self.port))

    def query(self, start: int, count: int) -> bytes:
        """
            Query the Saj inverter for register starting from a integer for a number of given count.
        """

        data = bytearray()

        while count > 0:

            # We can't read too many registers at once, hence we split in multiple requests
            # reading at most MAX_REGISTERS_PER_REQUEST registers
            amount = min(count, SajModbusTcp.MAX_REGISTERS_PER_REQUEST)

            retries = self.retries
            response = None

            while True:

                try:

                    response = self.client.read_holding_registers(address=start, count=amount)

                    if response.isError() is False:
                        break

                    retries -= 1

                    exception_code = response.exception_code
                    reason = SajModbusTcp.EXCEPTION_CODES.get(exception_code, "Unknown")
                    logging.debug("request failed, exception code: %d, reason: %s, remaining attempts: %d" % (
                        exception_code, reason, retries,))

                except BrokenPipeError as bp:
                    logging.debug("request failed, exception: %s (%s), trying to reconnect, remaining attempts: %d" % (
                        bp, type(bp).__name__, retries,))

                    retries -= 1

                    self.shutdown()
                    self.connect()

                except Exception as e:

                    retries -= 1

                    logging.debug("request failed, exception: %s (%s), remaining attempts: %d" % (
                        e, type(e).__name__, retries,))

                if retries <= 0:
                    break

                time.sleep(self.retries_delay)

            if not response:
                raise Exception("no response")

            if response.isError():
                exception_code = response.exception_code
                reason = SajModbusTcp.EXCEPTION_CODES.get(exception_code, "Unknown")
                raise Exception("response error, reason: %s (%d)" % (reason, exception_code))

            for value in response.registers:
                data += int.to_bytes((value & 0xff00) >> 8)
                data += int.to_bytes(value & 0xff)

            start += amount
            count -= amount

        return data

    def write(self, register: int, value: int) -> int:
        """
            Write an inverter register with the given value
        :param register:
        :param value:
        :return:
        """

        retries = self.retries

        response = None

        while True:

            try:

                response = self.client.write_register(register, value)

                if response.isError() is False:
                    break

                retries-=1

                exception_code = response.exception_code
                reason = SajModbusTcp.EXCEPTION_CODES.get(exception_code, "Unknown")
                logging.debug("request failed, exception code: %d, reason: %s, remaining attempts: %d" % (
                    exception_code, reason, retries))


            except BrokenPipeError as bp:
                logging.debug("request failed, exception: %s (%s), trying to reconnect, remaining attempts: %d" % (
                    bp, type(bp).__name__, retries,))

                retries -= 1

                self.shutdown()
                self.connect()

            except Exception as e:

                retries -= 1

                logging.debug("request failed, exception: %s (%s), remaining attempts: %d" % (
                    e, type(e).__name__, retries,))

            if retries <= 0:
                break

            time.sleep(self.retries_delay)

        if not response:
            raise Exception("no response")

        if response.isError():
            exception_code = response.exception_code
            reason = SajModbusTcp.EXCEPTION_CODES.get(exception_code, "Unknown")
            raise Exception("response error, reason: %s (%d)" % (reason, exception_code))

        return value


