#!/usr/bin/env python
"""
Log cryostat info

@file      logdet.py
@brief     temperature and pressure logger
@author    David Hale <dhale@astro.caltech.edu>
@date      2022-01-03

HOW TO USE:

1. create a .ini file (see format below) to define the project name,
        lakeshore host, etc.
2. ensure that ROOTPATH/index-html-src.in exists (source for index.html file)
3. ensure that ROOTPATH/dygraph-combined.js exists
        (Javascript which does the graphing)
4. run this script with the .ini file as an argument,
        i.e. "logtemp.py myfile.ini" (may be run from command line or cron)

.ini file requirements:

[logger]       <-- required first line
name=          <-- project name
temphost=      <-- hostname for temperature source
            (i.e. Lakeshore, terminal server, etc.)
tempport=      <-- port number for temperature server
temprate=      <-- rate in seconds at which to log temperature
tempchans=     <-- comma separated list of Lakeshore channels
                (i.e. A,B,C1, etc.)
templabels=    <-- comma separated list of labels for temperature channels
                (i.e., Cold Plate, Radiation Shield, etc.)
heaterchans=   <-- comma separated list of heater channels
heaterlabels=  <-- comma separated list of heater labels
presshost=     <-- hostname for pressure server
pressport=     <-- port number of pressure server
pressrate=     <-- rate in seconds at which to log pressure

"""

import traceback
import argparse
import configparser
import socket
import select
import sys
import time
from datetime import datetime,timedelta
from random import uniform
import os
import signal
import threading
import numpy

YEAR = datetime.now().strftime("%Y")
ROOTPATH = "/home/detlab/public_html"

# random period retry boundaries --
# for retry, wait a random period between RND0 and RND1 seconds
RND0 = 1
RND1 = 5
MAX_RETRIES = 3

SOCK_TIMEOUT=5
MUTEX_TIMEOUT=10

mutex_temp = threading.Lock()
mutex_press = threading.Lock()

# Pfeiffer TPG control codes
#
ACK  = b'\x06\x0d\x0a'
NAK  = b'\x15\x0d\x0a'
ENQ  = b'\x05'

# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
class ProgramKilled( Exception ):
    """ Class to handle program killed """

# -----------------------------------------------------------------------------
# @fn     signal_handler
# @brief  function called when a signal is received
# @param  signum
# @param  frame
# @return none
# -----------------------------------------------------------------------------
def signal_handler( signum, frame ):
    """ Signal handler """
    raise ProgramKilled

# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
class Job( threading.Thread ):
    """ Class to handle jobs """
    def __init__( self, interval, execute, *inargs, **kwargs ):
        threading.Thread.__init__( self )
        self.daemon = False
        self.stopped = threading.Event()
        self.interval = interval
        self.execute = execute
        self.args = inargs
        self.kwargs = kwargs

    def stop( self ):
        """ Stop thread """
        self.stopped.set()
        self.join()

    def run( self ):
        """ Run thread """
        self.execute( *self.args, **self.kwargs )
        while not self.stopped.wait( self.interval.total_seconds() ):
            self.execute( *self.args, **self.kwargs )


# -----------------------------------------------------------------------------
# @fn     open_socket
# @brief  opens a socket to a given host:port
# @param  host
# @param  port
# @return On success returns a handle to that socket.
#         On error, returns False
# -----------------------------------------------------------------------------
def open_socket(host,port):
    """ Open socket """
    sock = None
    for res in socket.getaddrinfo(host, port, socket.AF_INET,
                                  socket.SOCK_STREAM):
        af_type, socktype, proto, _, sock_addr =res
        try:
            sock = socket.socket(af_type, socktype, proto)
            sock.settimeout(SOCK_TIMEOUT)
        except socket.error:
            sock = None
            continue
        try:
            sock.connect(sock_addr)
        except socket.error as msg:
            tb_str = traceback.format_exception(etype=type(msg), value=msg,
                                                tb=msg.__traceback__)
            print("".join(tb_str))
            sock.close()
            sock = None
            continue
        break
    if sock is None:
        print( time.ctime(),
               '(open_socket) ERROR: could not open socket on %s:%s'
               % (host, port), file=sys.stderr )
        return False
    sock.settimeout(SOCK_TIMEOUT)
    return sock


# -----------------------------------------------------------------------------
# @fn     read_tpg
# @brief
# @param  sock
# -----------------------------------------------------------------------------
def read_tpg( sock ):
    """ Read TPG controller """
    while True:
        ready = select.select( [sock], [], [], 3 )
        if ready[0]:
            ret = sock.recv(1024)
        else:
            print( time.ctime(), "(read_tpg) select timeout")
            ret = None
            break
        if b'\n' in ret:
            break
    return ret


# -----------------------------------------------------------------------------
# @fn     sen_onoff
# @brief  turn sensor on/off
# @param  host
# @param  port
# -----------------------------------------------------------------------------
def sen_onoff(host, port,
              onoff1=0, onoff2=0, onoff3=0, onoff4=0, onoff5=0, onoff6=0):
    """ Set sensor state
    Inputs:
        0 - No status change
        1 = Turn gauge off
        2 = Turn gauge on

    """

    # don't let another thread run this at the same time
    if mutex_press.locked():
        print( time.ctime(), "(sen_onoff) ERROR: mutex locked" )
        return 'BSY'

    # acquire mutex lock and open socket
    mutex_press.acquire( blocking=True, timeout=MUTEX_TIMEOUT )

    sock = open_socket(host, port)

    if not sock:
        mutex_press.release()
        print( time.ctime(), "(sen_onoff) ERROR creating socket" )
        return 'ERR'

    # create an empty list, then start adding things to it (in order) for the return value
    retlist= [datetime.now().strftime("%D %T")]

    # first the date is added, then each channel requested in the order requested

    try:
        # send command to set state of sensors
        cmd = b'SEN,%d,%d,%d,%d,%d,%d\r\n' % (onoff1, onoff2, onoff3, onoff4, onoff5, onoff6)
        # print(cmd)
        sock.sendall( cmd )

        # first response is ACK
        ret = read_tpg( sock )

        if ret == ACK:
            sock.sendall( ENQ )
        else:
            print( time.ctime(), "(sen_onoff) ERROR: didn't receive ACK" )
            print("received: ", ret)
            sock.close()
            mutex_press.release()
            return 'ERR'

        # second response is the status
        ret = read_tpg( sock )
        ans = ret.decode( 'UTF-8' )
        ans = ans.split(',')

        for stat in ans:
            retlist.append( int( stat ))

    except Exception as e:
        print( time.ctime(), "(sen_onoff) exception: ", str(e) )
        sock.close()
        mutex_press.release()
        return 'ERR'

    sock.close()
    mutex_press.release()

    return retlist


# -----------------------------------------------------------------------------
# @fn     sen_stat
# @brief  sensor status (0 - no gauge, 1 - off, 2 - on)
# @param  host
# @param  port
# -----------------------------------------------------------------------------
def sen_stat(host, port):
    """ Get sensor state

    Return:
        0 - Gauge cannot be turned on/off
        1 - Gauge turned off
        2 - Gauge turned on
    """

    # don't let another thread run this at the same time
    if mutex_press.locked():
        print( time.ctime(), "(sen_stat) ERROR: mutex locked" )
        return 'BSY'

    # acquire mutex lock and open socket
    mutex_press.acquire( blocking=True, timeout=MUTEX_TIMEOUT )

    sock = open_socket(host, port)

    if not sock:
        mutex_press.release()
        print( time.ctime(), "(sen_stat) ERROR creating socket" )
        return 'ERR'

    # create an empty list, then start adding things to it (in order) for the return value
    retlist= [datetime.now().strftime("%D %T")]

    # first the date is added, then each channel requested in the order requested

    try:
        # send command to get sensor states
        sock.sendall( b'SEN\r\n' )

        # first response is ACK
        ret = read_tpg( sock )

        if ret == ACK:
            sock.sendall( ENQ )
        else:
            print( time.ctime(), "(sen_stat) ERROR: didn't receive ACK" )
            return 'ERR'

        # second response is the status
        ret = read_tpg( sock )
        ans = ret.decode( 'UTF-8' )
        ans = ans.split(',')

        for stat in ans:
            retlist.append( int(stat) )

    except Exception as e:
        print( time.ctime(), "(sen_stat) exception: ", str(e) )
        sock.close()
        mutex_press.release()
        return 'ERR'

    sock.close()
    mutex_press.release()

    return retlist


# -----------------------------------------------------------------------------
# @fn     get_tpg
# @brief  send command to TPG
# @param  host
# @param  port
# -----------------------------------------------------------------------------
def get_tpg(host, port):
    """ Get TPG reading """

    # don't let another thread run this at the same time
    if mutex_press.locked():
        print( time.ctime(), "(get_tpg) ERROR: mutex locked" )
        return 'BSY'

    # acquire mutex lock and open socket
    mutex_press.acquire( blocking=True, timeout=MUTEX_TIMEOUT )

    sock = open_socket(host, port)

    if not sock:
        mutex_press.release()
        print( time.ctime(), "(get_tpg) ERROR creating socket" )
        return 'ERR'

    # create an empty list, then start adding things to it (in order) for the return value
    retlist= [datetime.now().strftime("%D %T")]

    # first the date is added, then each channel requested in the order requested

    try:
        # send command to read pressure
        sock.sendall( b'PR1\r\n' )

        # first response is ACK
        ret = read_tpg( sock )

        if ret == ACK:
            sock.sendall( ENQ )
        else:
            print( time.ctime(), "(get_tpg) ERROR: didn't receive ACK" )

        # second response is the pressure
        ret = read_tpg( sock )
        ans = ret.decode( 'UTF-8' )
        ans = ans.split(',')

        retpress = float( ans[1] ) * 1000.
        retlist.append( retpress )

    except Exception as e:
        print( time.ctime(), "(get_tpg) exception: ", str(e) )
        sock.close()
        mutex_press.release()
        return 'ERR'

    sock.close()
    mutex_press.release()

    return retlist


# -----------------------------------------------------------------------------
# @fn     get_temps
# @brief  send command to Lakeshore to read temps and heaters
# @param  host
# @param  port
# @param  channels, a list of temperature channels to read, IE. ['A','B', etc.]
# @param  heaters, a list of heaters to read, IE. ['1','2']
# @return list of return values in the order of the channels submitted
#
# When talking to the Perle terminal server, if busy then this function will
# return 'BSY'. If there was an error opening the socket then it returns 'ERR'.
# Values that can't be converted to float are returned as numpy.nan
#
# return list is [ <date>, <ch1>, <ch2>, ..., <heater1>, ... ]
#
# -----------------------------------------------------------------------------
def get_temps(host, port, channels, heaters=None):
    """ Get temperatures """

    # don't let another thread run this at the same time
    if heaters is None:
        heaters = []
    if mutex_temp.locked():
        print( time.ctime(), "(get_temps) ERROR: mutex locked" )
        return 'BSY'

    # acquire mutex lock and open socket
    mutex_temp.acquire( blocking=True, timeout=MUTEX_TIMEOUT )

    sock = open_socket(host, port)

    if not sock:
        mutex_temp.release()
        print( time.ctime(), "(get_temps) ERROR creating socket" )
        return 'ERR'

    # create an empty list, then start adding things to it (in order) for the return value
    retlist= [datetime.now().strftime("%D %T")]

    # first the date is added, then each channel requested in the order requested

    # add the temperature and heaters into one list
    chanlist = channels + heaters

    # read all requested channels
    for chit in chanlist:
        try:
            # if the channel ch is not a digit ('A', 'C2', etc.) then it's a temperature channel
            if not chit.isdigit():
                message = "KRDG? %s\n" % chit
            # otherwise if it's a digit ('1', '2') then it's a heater
            else:
                message = "HTR? %s\n" % chit

            # send the appropriate message
            sock.sendall( message.encode( 'UTF-8' ) )

            # read bytes up until we get endchar
            endchar='\n'
            datl=[]
            temp=''
            while endchar not in temp:
                # recv up to 1k but it's always going to be delivered in multiple, smaller chunks
                temp = sock.recv(1024).decode('UTF-8')

                # the Perle terminal servers can only accept one connection at a time,
                # and will return this if you try to exceed that
                if 'Selected hunt group busy' in temp:
                    print( time.ctime(), "(get_temps) multiple simultaneous connections forbidden" )
                    sock.close()
                    mutex_temp.release()
                    return 'BSY'

                # the end of the message -- get out
                if endchar in temp:
                    datl.append(temp[:temp.find(endchar)])
                    break

                # if not the end of message then append what was just read into the dat list
                datl.append(temp)

                if len(datl)>1:
                    last=datl[-2]+datl[-1]
                    if endchar in last:
                        datl[-2]=last[:last.find(endchar)]
                        datl.pop()
                        break

            # done receiving data so join all of the dat[] list together, convert to float,
            # and append it to the return value list
            retlist.append( float(''.join(datl)) )

        except Exception as e:
            print( time.ctime(), "(get_temps) exception: ", str(e) )
            retlist.append( numpy.nan )
            sock.close()
            mutex_temp.release()
            return 'ERR'

    sock.close()
    mutex_temp.release()

    return retlist


# -----------------------------------------------------------------------------
# @fn     get_press
# @brief  send command to pressure gauge to read pressure
# @param  none
# @return none
#
# This function is called by the scheduler.
# -----------------------------------------------------------------------------
def get_press(host, port):
    """ Get pressures """

    mutex_press.acquire()

    sock = open_socket(host, port)

    if not sock:
        return 'ERR'

    data={}
    bytesread=0
    reply=''

    sock.sendall(b'#01RD\r')
    time.sleep(0.2)

    while bytesread<13:
        ready=select.select([sock],[],[],3)
        if ready[0]:
            temp = sock.recv(1024).decode( 'UTF-8' )
            reply=reply+temp
            bytesread += len(temp)
        else:
            print( time.ctime(), "(get_press) select timeout" )
            return 'ERR'

    pressure = float(reply[3:12])
    print( time.ctime(), "(get_press) pressure=", pressure )

    data['press'] = pressure

    data['time'] = datetime.now().strftime("%D %T")

    mutex_press.release()
    return data


# -----------------------------------------------------------------------------
# @fn     check_files
# @brief  checks that the needed file structure exists
# @param  logfile, name of log file (csv) that the logger will create
# @return True on success, False on error
# -----------------------------------------------------------------------------
def check_files( logfile ):
    """ Check if logfile exists """

    # the directory of where data files will be saved
    project_path='/home/detlab/public_html/deimos'
    save_path = project_path + "/" + YEAR + "/" + datetime.now().strftime("%Y%m%d")

    # check that all the needed support files are in place
    #
    try:
        # create the log files (and directories, if needed)
        ldir = os.path.dirname( logfile )
        if not os.path.exists(ldir):
            print( time.ctime(), "(check_files) creating path %s" % ldir )
            os.makedirs(ldir)

        # index.html file for this particular date displays the graph of today's data
        html = save_path + "/index.html"

        # if it doesn't exist then create one by reading the template
        # and replacing "PROJECT" with the actual project name (in upper case)
        if not os.path.exists(html):
            print( time.ctime(), "(check_files) creating %s" % html )
            index_html_outfile = open( html, 'a' )
            # the template is htmsrc
            htmsrc = ROOTPATH + "/index-html-src.in"
            if not os.path.exists( htmsrc ):
                print( time.ctime(), "(check_files) ERROR: missing htmsrc file: ", htmsrc )
                return False
            # a list of things to find and replace (project name and heater labels)
            findlist = [ "PROJECT", "HEATERLABELONE", "HEATERLABELTWO" ]
            # the list of things to replace them with
            replacelist = [ project_name.upper() ]
            replacelist += heater_labels
            with open( htmsrc ) as inputfile:
                # read a line at a time from "htmsrc" file
                for line in inputfile:
                    # perform any needed replacements
                    for flist, rlist in zip( findlist, replacelist):
                        line = line.replace( flist, rlist )
                    # write back the line (with any replacements) to the index.html file
                    index_html_outfile.write( line )
            inputfile.close()
            index_html_outfile.close()

        # create a symbolic link to dygraph if needed --
        # dygraph-combined.js is the Javascript which does the graphing magic.
        # need to have at least a symlink in each directory
        dylink = save_path + "/dygraph-combined.js"
        if not os.path.exists(dylink):
            # The actual Javascript is here
            dysrc  = ROOTPATH + "/dygraph-combined.js"
            os.symlink(dysrc, dylink)
            print( time.ctime(), "(check_files) creating symlink %s -> %s" % (dylink, dysrc) )

    except Exception as e:
        print( time.ctime(), "(check_files) exception:", str(e) )
        return False

    return True


# -----------------------------------------------------------------------------
# @fn     logpress
# @brief  workhorse function, calls get_press and does the logging
# @param  none
# @return none
#
# This function is called by the scheduler.
# -----------------------------------------------------------------------------
def logpress():
    press_host='131.215.200.34'
    press_port=8000
    project_path='/home/detlab/public_html/deimos'

    # create log file and needed paths if necessary
    save_path = project_path + "/" + YEAR + "/" + datetime.now().strftime("%Y%m%d")
    logfile = save_path + "/press.csv"
    if not check_files( logfile ):
        print( time.ctime(), "(logpress) ERROR setting up file structure" )
        return

    retry_count = 0
    # keep trying until not busy, or give up on error, until MAX_RETRIES
    while retry_count < MAX_RETRIES:
        print(time.ctime(), "(logpress) calling sen_stat(%s, %d)" % (press_host, press_port) )
        senstat = sen_stat( press_host, press_port )
        if senstat[1] == 0:
            senstat = sen_onoff(press_host, press_port, onoff1=2)
        print(senstat)
        print( time.ctime(), "(logpress) calling get_tpg(%s, %d)" % ( press_host, press_port ) )
        tpgpress = get_tpg( press_host, press_port )
        print(tpgpress)

        tpgpressfile = None
        if tpgpress is None:
            # no attempt to log nor try again on error
            break
        if tpgpress == 'ERR':
            # no attempt to log nor try again on error
            break
        if tpgpress != 'BSY':
            try:
                write_tpg_header = os.path.exists(logfile)

                tpgpressfile = open(logfile, 'a')

                if write_tpg_header:
                    tpgpressfile.write( 'datetime, pressure\n' )

                format_list = '{:}, {:.4f}\n'

                tpgpressfile.write( format_list.format(*tpgpress) )
                tpgpressfile.close()
                break

            except Exception as e:
                print( time.ctime(), "(logpress) exception:", str(e) )
                if tpgpressfile is not None:
                    tpgpressfile.close()
                return

        # wait some random period between RND0 and RND1 sec before trying again
        retrytime = uniform(RND0,RND1)
        retry_count += 1
        if retry_count < MAX_RETRIES:
            print( time.ctime(),
                   "(logpress) attempt # %d failed, trying again "
                   "in %.2f seconds" % (retry_count, retrytime) )
            time.sleep(retrytime)

        if ( retry_count >= MAX_RETRIES ) and ( tpgpress == 'BSY' ):
            print( time.ctime(),
                   "(logpress) attempt # %d failed. max retries reached, "
                   "giving up!" % retry_count )
            return

    print( time.ctime(), "(logpress) exiting" )
    return


# -----------------------------------------------------------------------------
# @fn     logtemp
# @brief  workhorse function, calls get_temps and does the logging
# @param  none
# @return none
#
# This function is called by the scheduler.
# -----------------------------------------------------------------------------
def logtemp():
    """ Log temperatures """

    print( time.ctime(), "(logtemp) starting" )

    # create log file and needed paths if necessary
    save_path = project_path + "/" + YEAR + "/" + datetime.now().strftime("%Y%m%d")
    logfile = save_path + "/temps.csv"
    if not check_files( logfile ):
        print( time.ctime(), "(logtemp) ERROR setting up file structure" )
        return

    retry_count = 0
    # keep trying until not busy, or give up on error, until MAX_RETRIES
    while retry_count < MAX_RETRIES:
        print( time.ctime(),
               "(logtemp) calling get_temps(%s, %s, %s, %s)" %
               ( temp_host, temp_port, temp_channels, heater_channels ) )
        lkstemps = get_temps(temp_host, temp_port, temp_channels, heater_channels)
        print( time.ctime(), "(logtemp) lkstemps=", lkstemps )

        lkstempfile = None
        if lkstemps is None:
            # no attempt to log nor try again on error
            break
        if lkstemps == 'ERR':
            # no attempt to log nor try again on error
            break
        if lkstemps != 'BSY':
            try:
                write_lks_header = os.path.exists(logfile)

                lkstempfile = open(logfile, 'a')

                if write_lks_header:
                    lkstempfile.write( 'datetime, ' + temp_header + '\n' )

                format_list = '{:}'
                for i in temp_channels:
                    format_list += ', {:.3f}'
                for i in heater_channels:
                    format_list += ', {:.3f}'
                format_list += '\n'

                lkstempfile.write( format_list.format(*lkstemps) )
                lkstempfile.close()
                break

            except Exception as e:
                print( time.ctime(), "(logtemp) exception:", str(e) )
                if lkstempfile is not None:
                    lkstempfile.close()
                return

        # wait some random period between RND0 and RND1 sec before trying again
        retrytime = uniform(RND0,RND1)
        retry_count += 1
        if retry_count < MAX_RETRIES:
            print( time.ctime(),
                   "(logtemp) attempt # %d failed, "
                   "trying again in %.2f seconds" % (retry_count, retrytime) )
            time.sleep(retrytime)

        if ( retry_count == MAX_RETRIES ) and ( lkstemps == 'BSY' ):
            print( time.ctime(),
                   "(logtemp) attempt # %d failed. max retries reached, "
                   "giving up!" % retry_count )
            return

    print( time.ctime(), "(logtemp) exiting" )
    return


# -----------------------------------------------------------------------------
# @fn     main
# @brief  this is the "main" function
# @param  none
# @return none
#
# Sets up the scheduler to do the periodic logging
# -----------------------------------------------------------------------------
if __name__ == "__main__":

    global press_host
    global press_port
    global press_rate
    global temp_host
    global temp_port
    global temp_rate
    global project_name
    global project_path
    global temp_channels
    global temp_header
    global heater_channels

    jobs_started = 0

    signal.signal( signal.SIGTERM, signal_handler )
    signal.signal( signal.SIGINT, signal_handler )

    parser=argparse.ArgumentParser(description='logger')
    parser.add_argument( 'inifile', help='.ini file required to configure the logger' )
    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read( args.inifile )

    # need to have a [logger] section
    #
    if 'logger' not in config:
        print( time.ctime(), "(main) ERROR: %s missing section 'logger'" % args.inifile )
        sys.exit(1)

    # need to have a project name and it can't be empty
    #
    if 'name' in config['logger']:
        if not config['logger']['name']:
            print( time.ctime(), "(main) ERROR: 'name' in %s cannot be empty!" % args.inifile )
            sys.exit(1)
        project_name = config['logger']['name']
    else:
        print( time.ctime(), "(main) ERROR: %s missing config key 'name'" % args.inifile )
        sys.exit(1)

    # get the temperature host and port numbers from the ini file
    #
    if 'temphost' in config['logger']:
        logtemps = True
        print( time.ctime(), "(main) found temphost, logtemps is enabled" )
        temp_host = config['logger']['temphost']
    else:
        logtemps = False
        print( time.ctime(), "(main) missing temphost, logtemps is disaabled" )
    if 'tempport' in config['logger']:
        temp_port = config['logger']['tempport']

    # get the pressure host and port numbers from the ini file
    #
    if 'presshost' in config['logger']:
        islogpress = True
        press_host = config['logger']['presshost']
    else:
        islogpress = False
    if 'pressport' in config['logger']:
        press_port = int(config['logger']['pressport'])

    # If we're logging temperatures then get everything needed for that
    #
    if logtemps:

        # get the temperature channels to log from the ini file
        #
        if 'tempchans' in config['logger']:
            temp_channels = config['logger']['tempchans'].split(',')
        else:
            print( time.ctime(), "(main) ERROR: %s missing config key 'tempchans'" % args.inifile )
            sys.exit(1)
        if temp_channels == ['']:
            temp_channels=[]          # if the input is blank, make sure it is length 0

        # get the temperature channel labels from the ini file
        #
        if 'templabels' in config['logger']:
            temp_labels = config['logger']['templabels'].split(',')
        else:
            print( time.ctime(), "(main) ERROR: %s missing config key 'templabels'" % args.inifile )
            sys.exit(1)
        if temp_labels == ['']:
            temp_labels=[]            # if the input is blank, make sure it is length 0

        header_list = []

        # must have the same number of temp labels as temp channels
        #
        if len(temp_channels) == len(temp_labels):
            for chan, label in zip(temp_channels, temp_labels):
                header_list.append( chan+":"+label )
            temp_header = ', '.join( header_list )
        else:
            print( time.ctime(), "(main) ERROR: must have same number of tempchans (%d) as templabels (%d)" % \
                   ( len(temp_channels), len(temp_labels) ) )
            sys.exit(1)

        # get the heater channels to log from the ini file
        #
        if 'heaterchans' in config['logger']:
            heater_channels = config['logger']['heaterchans'].split(',')
        else:
            print( time.ctime(), "(main) ERROR: %s missing config key 'heaterchans'" % args.inifile )
            sys.exit(1)
        if heater_channels == ['']:
            heater_channels=[]        # if the input is blank, make sure it is length 0

        # get the heater channel labels from the ini file
        #
        if 'heaterlabels' in config['logger']:
            heater_labels = config['logger']['heaterlabels'].split(',')
        else:
            print( time.ctime(), "(main) ERROR: %s missing config key 'heaterlabels'" % args.inifile )
            sys.exit(1)
        if heater_labels == ['']:
            heater_labels=[]          # if the input is blank, make sure it is length 0

        # must have the same number of heater labels as heater channels
        #
        if len(heater_channels) == len(heater_labels):
            for chan, label in zip(heater_channels, heater_labels):
                header_list.append( chan+":"+label )
            temp_header += ', '.join( header_list )
        else:
            print( time.ctime(),
                   "(main) ERROR: must have same number of heaterchans (%d) as "
                   "heaterlabels (%d)" % \
                   ( len(heater_channels), len(heater_labels) ) )
            sys.exit(1)

        # get temperature logging rate from ini file
        #
        if 'temprate' in config['logger']:
            if config['logger']['temprate']:
                temp_rate = int( config['logger']['temprate'] )
            else:
                temp_rate = 60

    # If we're logging pressure then get everything needed for that
    #
    if islogpress:
        # get pressure logging rate from ini file
        #
        if 'pressrate' in config['logger']:
            if config['logger']['pressrate']:
                press_rate = int( config['logger']['pressrate'] )
            else:
                press_rate = 60

    project_path = ROOTPATH + "/" + project_name

    # create project directory if needed
    if not os.path.exists( project_path ):
        print( time.ctime(), "(main) creating ", project_path )
        try:
            os.mkdir( project_path )
        except Exception as e:
            print( time.ctime(), "(main) exception creating directory:", str(e) )

    # if we have everything needed for temperature logging then start a thread
    #
    if logtemps and temp_host and temp_port and temp_rate and ( temp_channels or heater_channels):
        print( time.ctime(), "(main) starting temperature logging for %s" % project_name )
        temp_logging = Job( interval=timedelta(seconds=temp_rate), execute=logtemp )
        temp_logging.start()
        jobs_started += 1
    else:
        temp_logging = False
        print( time.ctime(),
               "(main) temperature logging disabled: missing one or more of "
               "temphost, tempport, temprate, (tempchans | heaterchans)" )

    # if we have everything needed for pressure logging then start a thread
    #
    if islogpress and press_host and press_port and press_rate:
        print( time.ctime(), "(main) starting pressure logging" )
        press_logging = Job( interval=timedelta(seconds=press_rate), execute=logpress )
        press_logging.start()
        jobs_started += 1
    else:
        press_logging = False
        print( time.ctime(),
               "(main) pressure logging disabled: missing one or more of "
               "presshost, pressport, pressrate" )

    # nothing to do
    #
    if not jobs_started:
        print( time.ctime(), "(main) no logging started. bye!" )
        sys.exit(0)

    # sleep while the threads do the work
    #
    while True:
        try:
            time.sleep(1)
        except ProgramKilled:
            print( time.ctime(), "(main) program killed" )
            if temp_logging:
                temp_logging.stop()
            if press_logging:
                press_logging.stop()
            break
