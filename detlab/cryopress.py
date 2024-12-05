#!/usr/bin/env python
"""
    @file      tpg.py
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
# read config file
with open('logcryo.json') as cfg_fl:
    config = json.load(cfg_fl)
# -----------------------------------------------------------------------------
# where the pressure gauge is located
# -----------------------------------------------------------------------------
host = config['presshost']
port = config['pressport']

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
    while True:
        ready = select.select([sock],[],[],3)
        if ready[0]:
            reply = sock.recv(1024)
        else:
            print("get_reply: select timeout")
            break
        if b'\n' in reply:
            break
    return ret

# -----------------------------------------------------------------------------
# @fn     send_command
# @brief  append <CR><LF> to command and send over socket
# -----------------------------------------------------------------------------
def send_command(cmd):
    """ Send Command String """
    cmd = cmd + "\r\n"
    sock.sendall(cmd.encode( 'UTF-8' ))

def read_pressure(read_type):
    """ Read Pressure String """
    send_command('PR1')
    rep=get_reply()
    if rep==ACK:
        sock.sendall(ENQ)
    else:
        print("read: didn't receive ACK")

    sock.sendall(ENQ)
    rep=get_reply()
    ans=rep.decode( 'UTF-8' )
    ans=ans.split(',')

    if read_type== "log":
        return float(ans[1])*1000.
    if read_type== "read":
        print(float(ans[1])*1000.," mTorr")
        if int(ans[0]) != 0:
            print(pressure_error(int(ans[0])))
        return None

    return None

# -----------------------------------------------------------------------------
# @fn     main
# @brief  the main function starts here
# -----------------------------------------------------------------------------
if __name__ == "__main__":

    parser=argparse.ArgumentParser(description='Pfeiffer TPG 361 controller')
    parser.add_argument('--power', metavar='[on|off|?]', nargs=1,
                        type=str, help='turn gauge on|off or read state with ?')
    parser.add_argument('--read', action='store_true',
                        help='read pressure measurement')
    parser.add_argument('--log', action='store_true',
                        help='log pressure measurement')
    parser.add_argument('--com', metavar='mnemonic', nargs=1, type=str,
                        help='send mnemonic command string to controller (no spaces!)')
    args=parser.parse_args()

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
            fn = "pressure.log"
            timestamp = datetime.now().strftime("%Y-%m-%dT%X")
            # read the pressure now (the "log" parameter is non-verbose)
            pressure  = read_pressure("log")
            # if the log file has grown over 1MB in size then rename it and start a new log file
            # (assuming it exists, of course)
            if os.path.exists(fn):
                if os.path.getsize(fn) > 1024000:
                    os.rename(fn, fn+"."+timestamp)
            # open file for append
            logfile = open(fn, 'a+')
            logfile.write('{:} DEWPRESS={:}\n'.format(timestamp,pressure))
            logfile.close()

        # turn power on|off
        if args.power:
            if args.power[0] == 'on':
                send_command('SEN,2,0,0,0,0,0')
            elif args.power[0] == 'off':
                send_command('SEN,1,0,0,0,0,0')
            # or query the power status
            elif args.power[0] == '?':
                send_command('SEN,0,0,0,0,0,0')
            else:
                print("power: must specify on|off|?")
                sys.exit(1)
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

    except socket.error as se:
        if se.errno == errno.EHOSTUNREACH:
            print("error")
    finally:
        if sock:
            sock.close()
