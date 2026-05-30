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
        self.port = port
        self.timeout = timeout
        self.retries = retries
        self.retries_delay = retries_delay

        self.client = None

    def connect(self):

        if self.client:
            return

        logging.debug("starting saj modbus tcp library")

        client = ModbusTcpClient(host=self.ip_address, port=self.port, timeout=self.timeout, retries=1)
        ret = client.connect()

        if not ret:
            raise Exception("could not connect")

        self.client = client

        logging.debug("started saj modbus tcp library")

    def shutdown(self):

        logging.debug("shutting down saj modbus tcp library")

        if self.client:
            self.client.close()
            self.client = None

        logging.info("shat down saj modbus tcp library")

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

            while True:

                response = self.client.read_holding_registers(address=start, count=amount)

                if response.isError() is False:
                    break

                retries-=1

                exception_code = response.exception_code
                reason = SajModbusTcp.EXCEPTION_CODES.get(exception_code, "Unknown")
                logging.debug("request failed, exception code: %d, reason: %s, remaining attempts: %d" % (
                    exception_code, reason, retries,))

                if retries <= 0:
                    break

                time.sleep(self.retries_delay)

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

        while True:

            response = self.client.write_register(register, value)

            if response.isError() is False:
                break

            retries-=1

            exception_code = response.exception_code
            reason = SajModbusTcp.EXCEPTION_CODES.get(exception_code, "Unknown")
            logging.debug("request failed, exception code: %d, reason: %s, remaining attempts: %d" % (
                exception_code, reason, retries))

            if retries <= 0:
                break

            time.sleep(self.retries_delay)

        if response.isError():
            exception_code = response.exception_code
            reason = SajModbusTcp.EXCEPTION_CODES.get(exception_code, "Unknown")
            raise Exception("response error, reason: %s (%d)" % (reason, exception_code))

        return value


