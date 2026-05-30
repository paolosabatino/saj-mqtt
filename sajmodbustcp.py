import threading
import logging
from pymodbus.client import ModbusTcpClient

class SajModbusTcp(object):

    # Default timeout
    TIMEOUT = 15

    # Default slave address
    SLAVE_ADDRESS = 0x1

    def __init__(self, ip_address: str, port: int):

        self.ip_address = ip_address
        self.port = port

        self.client = None

    def listen(self):

        if self.client:
            return

        logging.debug("starting saj modbus tcp library")

        client = ModbusTcpClient(host=self.ip_address, port=self.port)
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
        response = self.client.read_holding_registers(address=start, count=count)

        if response.isError():
            raise Exception("response error")

        data = bytearray()
        for value in response.registers:
            data += int.to_bytes((value & 0xff00) >> 8)
            data += int.to_bytes(value & 0xff)

        return data

    def write(self, register: int, value: int) -> int:
        return 0


