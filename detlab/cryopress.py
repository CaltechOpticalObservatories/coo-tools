#!/usr/bin/env python
"""
    @file      cryopress.py
    @brief     communcations client for Pfeiffer TPG 361 pressure gauge
    @author    David Hale <dhale@astro.caltech.edu>
    @date      2015-09-25
    @modified  2015-09-25
    @modified  2015-10-07 corrected timestamp %M to %m

"""

import errno
import os
import sys
import json
from datetime import datetime
import socket
import select
import argparse

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

# -----------------------------------------------------------------------------
# control codes
# -----------------------------------------------------------------------------
ACK  = b'\x06\x0d\x0a'
NCK  = b'\x15\x0d\x0a'
ENQ  = b'\x05'

# -----------------------------------------------------------------------------
# @fn     power_state
# @brief  return power status string based on numeric value for SEN,0 command
# -----------------------------------------------------------------------------
def power_state(argument):
    """ Get Power State """
    switcher = {
        0: "gauge cannot be turned on/off",
        1: "gauge turned off",
        2: "gauge turned on"
    }
    return switcher.get(argument, "unknown")

# -----------------------------------------------------------------------------
# @fn     pressure_error
# @brief  return error string based on numeric value for PR1 command
# -----------------------------------------------------------------------------
def pressure_error(argument):
    """ Get Pressure Error String """
    switcher = {
        0: "OK",
        1: "underrange",
        2: "overrange",
        3: "sensor error",
        4: "sensor off",
        5: "no sensor",
        6: "identification error",
    }
    return switcher.get(argument, "unknown")

# -----------------------------------------------------------------------------
# @fn     get_reply
# @brief  read socket until <LF> and return reply
# -----------------------------------------------------------------------------
def get_reply():
    """ Get Reply String """
    reply = None
    while True:
        ready = select.select([sock],[],[],3)
        if ready[0]:
            reply = sock.recv(1024)
        else:
            print("get_reply: select timeout")
            break
        if b'\n' in reply:
            break
    return reply

# -----------------------------------------------------------------------------
# @fn     send_command
# @brief  append <CR><LF> to command and send over socket
# -----------------------------------------------------------------------------
def send_command(command):
    """ Send Command String """
    command = command + "\r\n"
    sock.sendall(command.encode( 'UTF-8' ))

def read_pressure(read_type):
    """ Read Pressure """

    retlist = [datetime.now().strftime("%D %T")]
    for ichan in config['presschans']:

        send_command('PR%d' % ichan)
        rep=get_reply()
        if rep==ACK:
            sock.sendall(ENQ)
        else:
            print("read_pressure: didn't receive ACK")

        sock.sendall(ENQ)
        rep=get_reply()
        ans=rep.decode( 'UTF-8' )
        ans=ans.split(',')

        try:
            retlist.append(float(ans[1])*1000.)

            if read_type== "read":
                print(float(ans[1])*1000.," mTorr chan ", ichan)
        except IndexError:
            print("read_pressure: didn't receive any data")
            retlist.append(-1.0)

        if int(ans[0]) != 0:
            print(pressure_error(int(ans[0])))

    return retlist

# -----------------------------------------------------------------------------
# @fn     main
# @brief  the main function starts here
# -----------------------------------------------------------------------------
if __name__ == "__main__":

    parser=argparse.ArgumentParser(description='Pfeiffer TPG controller')
    parser.add_argument('config_file',
                        help='.json file with configuration parameters',
                        default=None)
    parser.add_argument('--power', metavar='[on|off|?]', nargs=1,
                        type=str, help='turn gauge on|off or read state with ?')
    parser.add_argument('--read', action='store_true',
                        help='read pressure measurement')
    parser.add_argument('--log', action='store_true',
                        help='log pressure measurement')
    parser.add_argument('--com', metavar='mnemonic', nargs=1, type=str,
                        help='send mnemonic command string to controller (no spaces!)')
    args=parser.parse_args()

    # read config file
    if args.config_file:
        with open(args.config_file) as cfg_fl:
            config = json.load(cfg_fl)
    else:
        with open('logcryo.json') as cfg_fl:
            config = json.load(cfg_fl)

    if 'influxdb_host' in config and 'influxdb_token' in config and 'influxdb_org' in config:
        config['influxdb_client'] = True
    else:
        config['influxdb_client'] = False
    # -----------------------------------------------------------------------------
    # where the pressure gauge is located
    # -----------------------------------------------------------------------------
    host = config['presshost']
    port = config['pressport']

    if len(sys.argv)==1:
        sys.exit(1)

    sock = None
    try:
        # open socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect( (host, port) )
        sock.setblocking(False)

        # send command to read pressure (the "read" parameter causes printing to stdout)
        if args.read:
            read_pressure("read")

        # send command to read pressure
        if args.log:
            LOG_FILE = "pressure.log"
            timestamp = datetime.now().strftime("%Y-%m-%dT%X")
            # if the log file has grown over 1MB in size then rename it and start a new log file
            # (assuming it exists, of course)
            if os.path.exists(LOG_FILE):
                if os.path.getsize(LOG_FILE) > 1024000:
                    os.rename(LOG_FILE, LOG_FILE + "." + timestamp)
            # open file for append
            # read the pressure now (the "log" parameter is non-verbose)
            pressure  = read_pressure("log")

            if config['influxdb_client']:
                print("Connecting to InfluxDB...")
                db_client = InfluxDBClient(url=config['influxdb_host'],
                                           token=config['influxdb_token'],
                                           org=config['influxdb_org'])
                write_api = db_client.write_api(write_options=SYNCHRONOUS)
                for ichan in config['presschans']:
                    point = (
                        Point("measurement")
                        .tag("channel", ichan)
                        .field("pressure", pressure[ichan])
                    )
                    print("Writing to InfluxDB... ", point)
                    write_api.write(bucket=config['name'].upper(),
                                    org=config['influxdb_org'],
                                    record=point)

            new_day = not os.path.exists(LOG_FILE)

            pressfile = open(LOG_FILE, 'a')

            if new_day:
                hdr = 'datetime, ' + config['presshdrs']
                pressfile.write(hdr + '\n')

            list_format = '{:}, ' + config['pressfmts'] + '\n'

            pressfile.write(list_format.format(*pressure))
            pressfile.close()

        # turn power on|off
        if args.power:
            cmd = 'SEN'
            if args.power[0] == 'on':
                for chan in range(1, config['pressnumchans']):
                    if chan in config['presschans']:
                        cmd += ',2'
                    else:
                        cmd += ',0'
            elif args.power[0] == 'off':
                for chan in range(1, config['pressnumchans']):
                    if chan in config['presschans']:
                        cmd += ',1'
                    else:
                        cmd += ',0'
            # or query the power status
            elif args.power[0] == '?':
                pass
            else:
                print("power: must specify on|off|?")
                sys.exit(1)
            send_command(cmd)
            ret=get_reply()
            if ret==ACK:
                sock.sendall(ENQ)
                ret=get_reply()
                answer = ret.decode( 'UTF-8' )
                answer = answer.split(',')
                for i, stat in enumerate(answer):
                    print("Sen %d: %s" % (i+1, power_state(int( stat ))))
            else:
                print("power: didn't receive ACK")

        # send arbitrary command, specified on command line
        if args.com:
            send_command(args.com[0])
            ret=get_reply()
            if ret==ACK:
                sock.sendall(ENQ)
            else:
                print("com: didn't receive ACK")
            ret=get_reply()
            print(ret)

    except socket.error as sock_err:
        if sock_err.errno == errno.EHOSTUNREACH:
            print("error")
    finally:
        if sock:
            sock.close()
