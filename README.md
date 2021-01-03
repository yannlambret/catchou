# fan-controller

Fan speed controller for Raspberry Pi 4.

Relies on ```pigpio``` and ```gpiozero``` python libraries.

## Prerequisites

You have to run pigpio daemon (a.k.a. pigpiod) in order to use this script.
There is not native systemd integration for the daemon itself, so one option
is to use cron at system startup:

```
$ sudo crontab -l
@reboot /usr/bin/pigpiod -s 1 -m -t 0
```

## Setup

```text
$ git clone https://github.com/yannlambret/catchou.git && cd catchou
$ sudo cp fan-controller.default /etc/default/fan-controller
$ sudo cp fan-controller.py /usr/bin/fan-controller
$ sudo cp fan-controller.service /etc/systemd/system/
```

Edit ```/etc/default/fan-controller``` with the desired values. You can
then enable and start the controller:

```
sudo systemctl enable fan-controller --now
```
