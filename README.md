# saj-mqtt
Python library and code to read and write registers via MQTT to SAJ H1 and similar power inverters

## Dependencies

The code here depends upon pymodbus library.
You can install it via **pip** or via operating system package manager (**apt**, **yum**, **dnd**, ...)

## Configure the MQTT broker

You should have a local MQTT broker in your home network (or even outside, but it is heavily discouraged due to
plain and unencrypted communication). This is outside the purpose of this document; if you are
using Linux, take a look for Mosquitto which is very easy to setup.
If you have Home Assistant running in your network, you can also use its broker.
The broker should allow anonymous authentication.

## Configure the inverter
You need to configure the inverter (actually the Wifi communication module AIO3 attached to the inverter) to talk with the local MQTT broker and not directly with the SAJ broker; to do that, you have two options:

- change the MQTT broker using eSAJ Home app (see [this](https://play.google.com/store/apps/details?id=com.saj.esolarhome)) to your local MQTT broker
- poison your local DNS to redirect the MQTT messages to your broker. This consists in telling your home router to point to your broker IP when domain **mqtt.saj-solar.com** is queried by the inverter, so refer to your router capabilities to handle this. This may require some time for the inverter to discover that the broker IP changed, so you may want to remove and reinstall the Wifi AIO3 module to restart it.

## The library and companion scripts

### sajmqtt.py

This is the main threaded library. It can be imported by other python scripts to enable communication via a
simple sequential I/O paradigm. See the other scripts as easy examples.

### readregs.py

Simple script that accepts four arguments to command line and queries the inverter via MQTT protocol for the 
given registers

### writereg.py

Simple script that accepts four arguments to command lin and writes a single register to the inverter via
MQTT protocol

### parsedata.py

This script accepts on the stdin the binary registers read from the inverter at address 0x4000 and parse 
the content according to the datasheet to provide realtime information about the inverter status.

It can be used piped to `readregs.py` this way:

```commandline
python3 readregs.py <mqtt_broker_ip> <inverter_serial> 0x4000 0x100 2> /dev/null | python3 parsedata.py -p
```

### fix-osc.py

Script that tries to mitigate the swinging oscillation of SAJ H1 inverters with the infamous v1.344 firmware.
It listens and queries the inverter from time to time to detect the characteristic bug where there is high battery
drain and high grid export or high battery charge and high grid import at the same time.
When this condition is detected, it writes a value to register 0x3249 that limits the import and
export current to a reasonably low value.
The script then restores, after 5 minutes, the original condition and keep listening for
further swinging condition. If the condition happens again in less than 5 minutes from the last
event, the script apply the mitigation again, but keeps it for 10 minutes, and so on.

You can run it with:

```commandline
python3 fix-osc.py <mqtt_broker_ip> <inverter_serial>
```

or install as a systemd service with the instructions below

### Installation on linux/debian machine

This manual installation instructions have been tested on debian linux system, but
should work with any operating system with **systemd** init system.

1. Clone the repository via git with `git clone 'https://github.com/paolosabatino/saj-mqtt.git'`
2. Move into the repository with `cd saj-mqtt`
3. Give the python scripts the execution permission with `chmod +x *.py`
4. Edit the `fix-osc.service` with your favourite editor
5. Change `WorkingDirectory` with the path where the python scripts are
6. Change `ExecStart` pointing to the complete path where `fix-osc.py` script resides, the MQTT broker address and the inverter serial address
7. Copy the systemd service with `sudo cp fix-osc.service /etc/systemd/system`
8. Reload systemd and enable the service `sudo systemctl daemon-reload && sudo systemctl enable fix-osc`

## Other resources

There is a Home Assistant integration for SAJ H1 inverters made by me available at https://github.com/paolosabatino/saj-mqtt-ha/tree/master
