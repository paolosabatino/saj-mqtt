from struct import pack, unpack_from
import struct
import threading
import random
import paho.mqtt.client as paho
import logging


class SajMqtt(object):

    # Default timeout
    TIMEOUT = 15

    # Default maximum number of register to read per request. Cannot exceed 123 registers (0x7b)
    MAX_REGISTERS_PER_REQUEST = 0x64

    # Default slave address
    SLAVE_ADDRESS = 0x1

    MODBUS_READ_REQUEST = 0x03  # The 0x03 modbus request is "read multiple register"
    MODBUS_WRITE_REQUEST = 0x06  # The 0x06 modbus request is "write single register"

    def __init__(self, broker: str, username: str, password: str, serial: str):

        self.serial = serial

        self.broker = broker
        self.username = username
        self.password = password

        self.thread = None
        self.client = None

        self.is_connected = threading.Event()
        self.is_connected.clear()

        self.timeout = SajMqtt.TIMEOUT
        self.maxRegistersPerRequest = SajMqtt.MAX_REGISTERS_PER_REQUEST
        self.address = SajMqtt.SLAVE_ADDRESS

        self.pending = dict()
        self.condition = threading.Condition()

    @staticmethod
    def _computeCRC(msg: str) -> int:
        """
            CRC algorithm for modbus protocol, taken from:
            https://stackoverflow.com/questions/69369408/calculating-crc16-in-python-for-modbus
            and adapted to swap buffers
        :param msg:
        :return:
        """
        crc = 0xFFFF
        for n in range(len(msg)):
            crc ^= msg[n]
            for i in range(8):
                if crc & 1:
                    crc >>= 1
                    crc ^= 0xA001
                else:
                    crc >>= 1
        return ((crc & 0xff) << 8) | (crc >> 8)

    def listen(self):

        logging.debug("starting saj mqtt library")

        self.pending.clear()

        self.thread = threading.Thread(target=self.funcMqttListener, daemon=False)
        self.thread.start()

        is_ready = self.is_connected.wait(self.timeout)

        if is_ready is False:
            self.shutdown()
            raise TimeoutError("connection to mqtt timed out")

        logging.debug("started saj mqtt library")

    def shutdown(self):

        logging.debug("shutting down saj mqtt library")

        if self.client:
            self.client.disconnect()

        if self.thread:
            self.thread.join()
            self.thread = None

        self.is_connected.clear()

        logging.info("shat down saj mqtt library")

    def funcMqttListener(self):

        logging.info("starting mqtt listening thread")

        broker_ip = self.broker

        client = paho.Client(client_id="py-saj-mqtt-%d" % (threading.get_native_id(),))
        client.username_pw_set(self.username, self.password)

        client.on_message = self.mqttOnMessage
        client.on_connect = self.mqttOnConnect
        client.on_disconnect = self.mqttOnDisconnect
        client.on_publish = self.mqttOnPublish
        client.on_subscribe = self.mqttOnSubscribe

        client.connect(broker_ip, port=1883, keepalive=60)

        self.client = client

        client.loop_forever()

        self.client = None

        logging.info("stopping mqtt listening thread")

    def mqttOnMessage(self, client, userdata, message, tmp=None):

        key = None

        try:

            req_id, req_type, length, timestamp = self._parsePacketHead(message.payload)

            req_type -= 0x100

            # Verify there is a request that is waiting for a proper answer in our set
            # If we don't find a match, that message is not for us and we ignore it
            key = (req_id, req_type)
            if key not in self.pending:
                return

            logging.debug("received message - topic: %s - qos: %d - " % (message.topic, message.qos))
            logging.debug("message: %s" % (":".join("%02x" % (byte,) for byte in message.payload),))
            logging.debug("Packet length: %d bytes - Request ID: %4x - Request type: %4x" % (length, req_id, req_type))
            logging.debug("Timestamp: %d" % (timestamp,))

            if req_type == SajMqtt.MODBUS_READ_REQUEST:
                content = self._parsePacketRead(message.payload)
            elif req_type == SajMqtt.MODBUS_WRITE_REQUEST:
                content = self._parsePacketWrite(message.payload)
            else:
                raise ValueError("unexpected request type: %d" % (req_type,))

            self.pending[key] = content

            self.condition.acquire()
            self.condition.notify_all()
            self.condition.release()

        except struct.error as se:
            logging.warning("ignored malformed packet, reason: %s" % (se,))
        except ValueError as ve:
            logging.warning("ignored packet, reason: %s" % (ve,))
            if key:
                self.pending[key] = ve

    def mqttOnConnect(self, client, fixOsc, flags, rc):
        logging.debug("mqtt connected")

        client.subscribe(topic=f"saj/{self.serial}/data_transmission_rsp", qos=0)

    def mqttOnDisconnect(self, client, userdata, rc):
        logging.debug("mqtt disconnected")

    def mqttOnPublish(self, client, userdata, mid):
        logging.debug("mqtt message published")

    def mqttOnSubscribe(self, client, userdata, mid, granted_qos):
        logging.debug("mqtt topic subscribed")
        self.is_connected.set()

    @staticmethod
    def _forgeReadRequestPacket(register_start: int, register_count: int, address: int):
        """
            Given the start and count registers, forge the MQTT packet for the
            request to handle a multiple register read
        """
        # Build the modbus content part of the MQTT packet
        content = pack(">BBHH", address, SajMqtt.MODBUS_READ_REQUEST, register_start, register_count)
        crc16 = SajMqtt._computeCRC(content)

        # Assemble the modbus content into the MQTT packet framework
        req_id = int(random.random() * 65536)
        rnd = int(random.random() * 65536)

        packet = pack(">HBBH", req_id, 0x58, 0xc9, rnd) + content + pack(">H", crc16)

        logging.debug("Request ID: %04x - CRC16: %04x - Random: %04x" % (req_id, crc16, rnd))
        logging.debug("Length: %d bytes" % (len(packet),))

        packet = pack(">H", len(packet)) + packet

        return req_id, rnd, SajMqtt.MODBUS_READ_REQUEST, packet

    @staticmethod
    def _forgeWriteRequestPacket(register: int, value: int, address: int):
        """
            Given the register and the value to write into, forge tha MQTT packet
            to initiate a write single register request.
        """
        # Build the modbus content part of the MQTT packet
        content = pack(">BBHH", address, SajMqtt.MODBUS_WRITE_REQUEST, register, value)
        crc16 = SajMqtt._computeCRC(content)

        # Assemble the modbus content into the MQTT packet framework
        req_id = int(random.random() * 65536)
        rnd = int(random.random() * 65536)

        packet = pack(">HBBH", req_id, 0x58, 0xc9, rnd) + content + pack(">H", crc16)

        logging.debug("Request ID: %04x - CRC16: %04x - Random: %04x" % (req_id, crc16, rnd))
        logging.debug("Length: %d bytes" % (len(packet),))

        logging.debug("Request: %s" % (":".join("%02x" % (byte,) for byte in packet),))

        packet = pack(">H", len(packet)) + packet

        return req_id, rnd, SajMqtt.MODBUS_WRITE_REQUEST, packet

    @staticmethod
    def _parsePacketHead(packet: bytes) -> tuple:
        length, req_id, timestamp, req_type = unpack_from(">HHIH", packet, 0x00)
        return req_id, req_type, length, timestamp

    @staticmethod
    def _parsePacketRead(packet: bytes) -> bytes:
        size, = unpack_from(">B", packet, 0xa)
        content = packet[0xb:0xb + size]

        crc16, = unpack_from(">H", packet, 0xb + size)

        # CRC is calculated starting from "request" at offset 0x3a
        calc_crc = SajMqtt._computeCRC(packet[0x8:0xb + size])

        logging.debug("Register size: %d" % (size,))
        logging.debug("Register content: %s" % (":".join("%02x" % (byte,) for byte in content),))
        logging.debug("CRC16: %x: %s" % (crc16, "ok" if crc16 == calc_crc else "bad"))

        if crc16 != calc_crc:
            raise ValueError("a crc error occurred")

        return content

    @staticmethod
    def _parsePacketWrite(packet: bytes) -> int:
        # Although the documentation says that, exactly as modbus protocol mandates, the answer
        # is the very same as request, here we get back the written value and the origin CRC,
        # plus they are byte-swapped (little endian).
        # register, value, crc16 = unpack_from(">HHH", packet, 0xa)
        value, prev_crc16 = unpack_from("<HH", packet, 0xa)
        crc16, = unpack_from(">H", packet, 0xe)

        # CRC is calculated starting from "request" at offset 0x3a
        calc_crc = SajMqtt._computeCRC(packet[0x8:0xe])

        logging.debug("CRC16: %x: %s" % (crc16, "ok" if crc16 == calc_crc else "bad"))

        if crc16 != calc_crc:
            raise ValueError("a crc error occurred")

        return value

    def query(self, start: int, count: int) -> bytes:
        """
            Query the Saj inverter for register starting from a integer for a number of given count.
        """
        def predicate():
            nonlocal keys

            for key in keys:
                if self.pending[key] is None:
                    return False

            return True

        if not self.client.is_connected():
            raise ConnectionError("mqtt client is not connected")

        keys = list()
        end = start + count
        topic = f"saj/{self.serial}/data_transmission"

        # As long as there is a maximum number of registers than can be read at once, split the request
        # into multiple requests and wait for the answers
        while start < end:

            length = min(end - start, self.maxRegistersPerRequest)
            req_id, rnd, req_type, packet = self._forgeReadRequestPacket(start, length, self.address)

            key = (req_id, req_type)
            keys.append(key)

            self.pending[key] = None
            self.client.publish(topic=topic, payload=packet, qos=2, retain=False)

            start += length

        self.condition.acquire()
        is_ready = self.condition.wait_for(predicate, self.timeout)
        self.condition.release()

        # if is_ready flag is false, the condition timed out
        if is_ready is False:
            for key in keys:
                del self.pending[key]
            raise TimeoutError("response to query request timed out")

        exc = None
        for key in keys:
            if isinstance(self.pending[key], Exception):
                exc = self.pending[key]

        if exc:
            for key in keys:
                del self.pending[key]
            raise exc

        data = bytearray()
        for key in keys:
            data += self.pending[key]
            del self.pending[key]

        return data

    def write(self, register: int, value: int) -> int:
        def predicate():
            nonlocal key
            return self.pending[key] is not None

        if not self.client.is_connected():
            raise ConnectionError("mqtt client is not connected")

        req_id, rnd, req_type, packet = self._forgeWriteRequestPacket(register, value, self.address)

        key = (req_id, req_type)
        self.pending[key] = None

        topic = f"saj/{self.serial}/data_transmission"
        self.client.publish(topic=topic, payload=packet, qos=0, retain=False)

        self.condition.acquire()
        is_ready = self.condition.wait_for(predicate, self.timeout)
        self.condition.release()

        result = self.pending[key]
        del self.pending[key]

        if is_ready is False:
            raise TimeoutError("response to write request timed out")

        if isinstance(result, Exception):
            raise result

        return result
