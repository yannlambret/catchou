#!/usr/bin/env python3

"""Fan speed controller for Raspberry Pi 4.

Usage:
  fan-controller.py --min-dc=<n> --max-dc=<n> [--precision=<n>] [--pwm-pin=<n>] [--pwm-freq=<n>] [--debug]
  fan-controller.py (-h | --help)

Options:
  -h --help        Show this help message and exit.
  --min-dc=<n>     Minimal duty cycle value (%).
  --max-dc=<n>     Maximal duty cycle value (%).
  --precision=<n>  Number of subdivisions for duty cycle range.
                   Valid values are 5, 10, 25, 50. [default: 10]
  --pwm-pin=<n>    GPIO pin number for PWM signal. [default: 23]
  --pwm-freq=<n>   PWM signal frequency (Hz). [default: 40000]
  --debug          Activate debug logging.
"""

import logging
import re
import signal
import sys
import threading

from math import floor
from time import sleep

import pigpio

from docopt import docopt
from docopt import  DocoptExit
from gpiozero import CPUTemperature
from tenacity import retry
from tenacity import wait_exponential


# pylint: disable=invalid-name


# -- Script configuration
#
#    Pin 14: Ground
#    Pin 16: PWM (GPIO 23)
#
#    Setup for a be quiet! Pure Wings 2 120mm fan (12V)
#
#    * --pwm-pin   => 23
#    * --pwm-freq  => 40000 NOTE: use '/usr/bin/pigpiod -s 1 -m -t 0' command
#    * --min-dc    => 20
#    * --max-dc    => 40
#    * --precision => 10


# -- Logging
formatter = '%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'

handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter(formatter))

logger = logging.getLogger()
logger.addHandler(handler)


class FanControllerCfg():
    """Wrapper for controller runtime values."""
    def __init__(self, params):
        # From 0°C up to 30+(max_temp-min_temp)//precision°C,
        # min_dc will be applied
        self.min_temp = 30
        # Starting from 80°C, max_dc will be applied
        self.max_temp = 80
        self.temp_step = (self.max_temp-self.min_temp)//params.get('precision')
        self._temp_range = list(
            range(self.min_temp, self.max_temp+self.temp_step, self.temp_step)
        )
        self._dc_step = (params.get('max_dc')-params.get('min_dc'))//params.get('precision')
        self._dc_range = list(
            range(params.get('min_dc'), params.get('max_dc')+self._dc_step, self._dc_step)
        )
        self._params = params

    @property
    def pwm_pin(self):
        # pylint: disable=missing-docstring
        return self._params.get('pwm_pin')

    @property
    def pwm_freq(self):
        # pylint: disable=missing-docstring
        return self._params.get('pwm_freq')

    @property
    def min_dc(self):
        # pylint: disable=missing-docstring
        return self._params.get('min_dc')

    @property
    def max_dc(self):
        # pylint: disable=missing-docstring
        return self._params.get('max_dc')

    @property
    def runtime_values(self):
        """Create a mapping between temperature steps and specific duty cycle values."""
        return dict(zip(self._temp_range, self._dc_range))



class FanController():
    """Controller for the CPU fan."""
    def __init__(self, cfg=None):
        self._cfg = cfg
        self._dc = 0
        self._cpu = CPUTemperature()
        # This attribute is initialized
        # in a dedicated method (see below)
        self._pi = None

    @retry(wait=wait_exponential(max=5))
    def pigpio_setup(self):
        """GPIO setup."""
        # The retrying setup is here to prevent a controller
        # failure if pigpiod daemon is not running yet
        self._pi = pigpio.pi(show_errors=False)
        if not self._pi.connected:
            logger.debug('cannot connect to pigpio daemon, waiting...')
            raise RuntimeError
        self._pi.set_PWM_frequency(self._cfg.pwm_pin, self._cfg.pwm_freq)
        self._pi.set_PWM_range(self._cfg.pwm_pin, 100)
        logger.info('pigpio configuration completed')

    def loop(self, event):
        """Start the fan and update duty cycle according to the CPU temperature."""
        logger.info('requested PWM frequency: %dHz', self._cfg.pwm_freq)
        logger.info('current PWM frequency: %dHz', self._pi.get_PWM_frequency(self._cfg.pwm_pin))
        while not event.isSet():
            temp = floor(self._cpu.temperature)
            logger.debug('temperature: %d°C', temp)
            temp = temp//self._cfg.temp_step*self._cfg.temp_step
            temp = self._cfg.min_temp if temp < self._cfg.min_temp else temp
            temp = self._cfg.max_temp if temp > self._cfg.max_temp else temp
            dc = self._cfg.runtime_values.get(temp)
            logger.debug('duty cycle: %d%%', dc)
            if dc != self._dc:
                self._dc = dc
                self._pi.set_PWM_dutycycle(self._cfg.pwm_pin, dc)
            sleep(1)
        # Stop the fan and clean up resources
        self._pi.set_PWM_dutycycle(self._cfg.pwm_pin, 0)
        self._pi.stop()


if __name__ == '__main__':
    threading.current_thread().name = 'controller-main'
    # CLI options parsing
    try:
        arguments = docopt(__doc__)
    except DocoptExit as e:
        sys.exit(e)
    # CLI options validation
    for k, v in arguments.items():
        if not isinstance(v, bool) and not v.isdigit():
            error = 'Error: option \'{}\' value is not a valid number'.format(k)
            raise SystemExit(error)
    args = {
        re.sub(r'-{1,2}', lambda m: '_' if m.group(0) == '-' else '', k): int(v)
        for k, v in arguments.items()
    }
    if args.get('precision') not in [5, 10, 25, 50]:
        error = 'Error: invalid precision value. Valid values are 5, 10, 25, and 50.'
        raise SystemExit(error)
    if args.get('min_dc') not in range(0, 96):
        error = 'Error: min duty cycle value should belong to [0,95]'
        raise SystemExit(error)
    if args.get('max_dc') not in range(5, 101):
        error = 'Error: max duty cycle value should belong to [5,100]'
        raise SystemExit(error)
    if args.get('min_dc') >= args.get('max_dc'):
        error = 'Error: min duty cycle value should be less than max duty cycle value.'
        raise SystemExit(error)
    if (args.get('max_dc')-args.get('min_dc')) % args.get('precision'):
        error = 'Error: duty cycle range should be a multiple of precision value.'
        raise SystemExit(error)
    # Set logging level
    logging_level = logging.DEBUG if args.get('debug') else logging.INFO
    logger.setLevel(logging_level)
    # Start controller loop
    controller = FanController(cfg=FanControllerCfg(args))
    controller.pigpio_setup()
    e = threading.Event()
    t = threading.Thread(name='controller-loop', target=controller.loop, args=(e,))
    logger.info('starting controller loop')
    t.start()
    # Stop controller loop on SIGTERM
    def signal_handler(signum, frame):
        logger.info('stopping controller loop on SIGTERM')
        e.set()
    signal.signal(signal.SIGTERM, signal_handler)
