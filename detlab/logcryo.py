#!/usr/bin/env python
"""
Log cryostat info

@file      logcryo.py
@brief     temperature and pressure logger
@author    David Hale <dhale@astro.caltech.edu>
@date      2022-01-03

REQUIREMENTS:

1. install dygraph.min.js in the web server's document root js directory:
    e.g., sudo cp dygraph.min.js /Library/WebServer/Documents/js/
2. install dygraph.css in the web server's document root css directory:
    e.g., sudo cp dygraph.css /Library/WebServer/Documents/css/

HOW TO USE:

1. edit logcryo.json file (see format below) to define the project name,
        influxdb connection (optional), logging root, controller hosts,
        channel info, etc.
2. for temperatures, it is assumed that heater channels are numbers, while
        sensor channels are single letters (see example below).
2. if using influxdb, it assumes that a bucket with an uppercase name of the
        project exists in the DB.

*.json file requirements:
{
    "name": <project name>
    "influxdb_url": <influxdb url>
    "influxdb_token": <influxdb auth token>
    "influxdb_org": <influxdb organization name>
    "logroot": <logging root directory>
    "temphost": <hostname or IP address for temperature source (str)>
                (i.e. Lakeshore, terminal server, etc.)
    "tempport": <port number for temperature server (int)>
    "temprate": <rate in seconds at which to log temperature (int)>
    "tempchans": <comma separated list of Lakeshore channels, including heaters (str)>
                (e.g. A,B,C1,1,2 etc.)
    "temphdrs": <comma separated list of labels for temperature channels (str)>
                (e.g. A:CP, B:RS, 1:HTRCCD etc.)
    "tempfmts": <comma separated format strings for temperature channels (str)>
                (e.g. {:.3f}, {:.4f} etc.)
    "presshost": <hostname or IP for pressure server (str)>
    "pressport": <port number of pressure server (int)>
    "pressrate": <rate in seconds at which to log pressure (int)>
    "pressnumchans": <number of pressure controller channels (int)>
    "presschans": <integer list of pressure gauge channels (int list)>
                (e.g. [1,3,5])
    "presshdrs": <comma separated list of labels for pressure channels (str)>
                (e.g. 1:DWR, 3:CHM, 5:PRT)
    "pressfmts": <comma separated format strings for pressure channels (str)>
                (e.g. {:.3f}, {:.4f} etc.)
}

2. run this script with the .json file as an argument,
        i.e. "logcryo.py myfile.json" (can be run from command line or cron)
"""

import traceback
import argparse
import json
import socket
import select
import sys
import time
from datetime import datetime,timedelta
from random import uniform
import os
import glob
import signal
import threading
from pathlib import Path
import numpy

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

SRC_PATH = os.path.dirname(str(Path(__file__)))

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
# @class  ProgramKilled
# @brief  program killed exception
# @param  none
# @return none
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
    print(f"Signal handler called with signal {signum} received")
    _ = frame
    raise ProgramKilled

# -----------------------------------------------------------------------------
# @class   Job
# @brief   Class for handling threading jobs
# @inherit threading.Thread
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
def open_socket(host, port):
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
# @brief  read TPG controller
# @param  sock
# @return TPG response
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
# @param  chan - channel to operate on
# @param  onoff - True to turn on, False to turn off
# @param  **hconfig - configuration dictionary
# @return command response
# -----------------------------------------------------------------------------
def sen_onoff(chan, onoff, **hconfig):
    """ Set sensor state
    Inputs:
        chan: Pressure controller sensor channel number (int)
        onoff: True to turn on, False to turn off
        **hconfig: Hardware configuration

        Returns for each channel:
        0 - No status change
        1 = Turn gauge off
        2 = Turn gauge on

    """
    if chan in hconfig['presschans']:
        print( time.ctime(), "Channel not configured: %d" % chan )
        return 'ERR'

    num_chans = hconfig['pressnumchans']

    onoff_dict = {}
    for ichan in range( 1, num_chans + 1 ):
        if chan == ichan:
            if onoff:
                onoff_dict[ichan] = 2
            else:
                onoff_dict[ichan] = 1
        else:
            onoff_dict[ichan] = 0
    # don't let another thread run this at the same time
    if mutex_press.locked():
        print( time.ctime(), "(sen_onoff) ERROR: mutex locked" )
        return 'BSY'

    # acquire mutex lock and open socket
    mutex_press.acquire( blocking=True, timeout=MUTEX_TIMEOUT )

    sock = open_socket(hconfig['presshost'], hconfig['pressport'])

    if not sock:
        mutex_press.release()
        print( time.ctime(), "(sen_onoff) ERROR creating socket" )
        return 'ERR'

    # create an empty list, then start adding things to it (in order) for the return value
    retlist= [datetime.now().strftime("%D %T")]

    # first the date is added, then each channel requested in the order requested

    try:
        # send command to set state of sensors
        cmd = b'SEN'
        for ichan in range(1, num_chans + 1):
            cmd += b',%d' % onoff_dict[ichan]
        cmd += b'\r\n'

        print(cmd)
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

    except Exception as ex:
        print( time.ctime(), "(sen_onoff) exception: ", str(ex) )
        sock.close()
        mutex_press.release()
        return 'ERR'

    sock.close()
    mutex_press.release()

    return retlist

# -----------------------------------------------------------------------------
# @fn     sen_stat
# @brief  sensor status (0 - no gauge, 1 - off, 2 - on)
# @param  **hconfig - configuration dictionary
# @param  port
# @return status list with one entry per sensor
# -----------------------------------------------------------------------------
def sen_stat(**hconfig):
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

    sock = open_socket(hconfig['presshost'], hconfig['pressport'])

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

    except Exception as ex:
        print( time.ctime(), "(sen_stat) exception: ", str(ex) )
        sock.close()
        mutex_press.release()
        return 'ERR'

    sock.close()
    mutex_press.release()

    return retlist

# -----------------------------------------------------------------------------
# @fn     get_tpg
# @brief  send command to TPG
# @param  **hconfig - configuration dictionary
# @return TPG response
# -----------------------------------------------------------------------------
def get_tpg(**hconfig):
    """ Get TPG reading """

    # don't let another thread run this at the same time
    if mutex_press.locked():
        print( time.ctime(), "(get_tpg) ERROR: mutex locked" )
        return 'BSY'

    # acquire mutex lock and open socket
    mutex_press.acquire( blocking=True, timeout=MUTEX_TIMEOUT )

    sock = open_socket(hconfig['presshost'], hconfig['pressport'])

    if not sock:
        mutex_press.release()
        print( time.ctime(), "(get_tpg) ERROR creating socket" )
        return 'ERR'

    # create an empty list, then start adding things to it (in order) for the return value
    retlist= [datetime.now().strftime("%D %T")]

    # first the date is added, then each channel requested in the order requested

    try:
        for ichan in hconfig['presschans']:
            # send command to read pressure
            sock.sendall( b'PR%d\r\n' % ichan )

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

            if hconfig['influxdb_client']:
                print("Connecting to InfluxDB...")
                db_client = InfluxDBClient(url=hconfig['influxdb_url'],
                                           token=hconfig['influxdb_token'],
                                           org=hconfig['influxdb_org'])
                write_api = db_client.write_api(write_options=SYNCHRONOUS)
                point = (
                    Point("measurement")
                    .tag("channel", ichan)
                    .field("pressure", retpress)
                )
                print("Writing to InfluxDB... ", point)
                write_api.write(bucket=hconfig['name'].upper(),
                                org=hconfig['influxdb_org'],
                                record=point)

    except Exception as ex:
        print( time.ctime(), "(get_tpg) exception: ", str(ex) )
        sock.close()
        mutex_press.release()
        return 'ERR'

    sock.close()
    mutex_press.release()

    return retlist

# -----------------------------------------------------------------------------
# @fn     get_temps
# @brief  send command to Lakeshore to read temps and heaters
# @param  **hconfig - configuration dictionary
# @return list of return values in the order of the channels submitted
# -----------------------------------------------------------------------------
def get_temps(**hconfig):
    """ Get temperatures """

    # don't let another thread run this at the same time
    if mutex_temp.locked():
        print( time.ctime(), "(get_temps) ERROR: mutex locked" )
        return 'BSY'

    # acquire mutex lock and open socket
    mutex_temp.acquire( blocking=True, timeout=MUTEX_TIMEOUT )

    sock = open_socket(hconfig['temphost'], hconfig['tempport'])

    if not sock:
        mutex_temp.release()
        print( time.ctime(), "(get_temps) ERROR creating socket" )
        return 'ERR'

    # create an empty list, then start adding things to it (in order) for the return value
    retlist= [datetime.now().strftime("%D %T")]

    # first the date is added, then each channel requested in the order requested

    # add the temperature and heaters into one list
    chanlist = hconfig['tempchans'].split(',')

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

            # done receiving data so join all the dat[] list together, convert to float,
            # and append it to the return value list
            retlist.append( float(''.join(datl)) )

        except Exception as ex:
            print( time.ctime(), "(get_temps) exception: ", str(ex) )
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
# @param  **hconfig - configuration dictionary
# @return none
# -----------------------------------------------------------------------------
def get_press(**hconfig):
    """ Get pressures """

    mutex_press.acquire()

    sock = open_socket(hconfig['presshost'], hconfig['pressport'])

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
# @param  save_path, path where log file (csv) will be created
# @param  **fargs - configuration dictionary
# @return True on success, False on error
# -----------------------------------------------------------------------------
def check_files( save_path, **fargs ):
    """ Check if files in save_path exist """

    # check that all the needed support files are in place
    #
    try:
        # create the log files (and directories, if needed)
        if not os.path.exists(save_path):
            print( time.ctime(), "(check_files) creating path %s" % save_path )
            os.makedirs(save_path)

        # index.html file for this particular date displays the graph of today's data
        html = save_path + "/index.html"

        # if it doesn't exist then create one by reading the template
        # and replacing "PROJECT" with the actual project name (in upper case)
        if not os.path.exists(html):
            print( time.ctime(), "(check_files) creating %s" % html )
            index_html_outfile = open( html, 'a' )
            # the template is htmsrc
            if SRC_PATH:
                htmsrc = SRC_PATH + "/index-html-src.in"
            else:
                htmsrc = "index-html-src.in"
            if not os.path.exists( htmsrc ):
                print( time.ctime(), "(check_files) ERROR: missing htmsrc file: ", htmsrc )
                return False
            # a list of things to find and replace (project name and heater labels)
            findlist = [ "PROJECT", "HEATERLABELONE", "HEATERLABELTWO" ]
            # the list of things to replace them with
            replacelist = [ fargs['name'].upper() ]
            replacelist += [ fargs['heater_header'][0] ]
            replacelist += [ fargs['heater_header'][1] ]
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

    except Exception as ex:
        print( time.ctime(), "(check_files) exception:", str(ex) )
        return False

    return True


# -----------------------------------------------------------------------------
# @fn     make_index
# @brief  creates index html for days of logging
# @param  index_path, path to directory where date index will be maintained
# @param  **fargs - configuration dictionary
# @return True on success, False on error
# -----------------------------------------------------------------------------
def make_index(index_path, **fargs):
    """ Create index of dates """
    curr_year = os.path.basename(index_path)
    index_html = index_path + "/index.html"
    ihfile = open( index_html, "w" )
    ihfile.write( "<!-- This file is automatically generated !-->\n" )
    ihfile.write( "<!-- Any manual edits will be lost        !-->\n" )
    ihfile.write( "\n" )
    ihfile.write( "<html>\n" )
    ihfile.write( "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\"\n>" )
    ihfile.write( "<head>\n" )
    ihfile.write("<style type=\"text/css\">\n" )
    ihfile.write( "</style>\n" )
    ihfile.write( "</head>\n" )
    ihfile.write( "<h3>%s data logs %s</h3>\n" % (fargs['name'].upper(), curr_year) )
    ihfile.write("\n")

    lastmonth = 0
    date_list = glob.glob( index_path + "/%s????" % curr_year )
    date_list.sort(reverse=True)
    for datef in date_list:
        yeardate = os.path.basename(datef)
        mm = yeardate[4:6]
        dd = yeardate[6:]
        if int(mm) != lastmonth:
            ihfile.write( "<br>\n" )
            lastmonth = int(mm)
        ihfile.write("<a href=\"%s\">%s-%s-%s</a><br>\n" % ( yeardate, curr_year, mm, dd ) )

# -----------------------------------------------------------------------------
# @fn     logpress
# @brief  workhorse function, calls get_tpg and does the logging
# @param  **pconfig - configuration dictionary
# @return none
#
# This function is called by the scheduler.
# -----------------------------------------------------------------------------
def logpress(**pconfig):
    """ Log Pressure """

    project_path=os.path.join(pconfig['logroot'], pconfig['name'])
    print(time.ctime(), "(logpress) starting")

    curr_year = datetime.now().strftime("%Y")

    # create log file and needed paths if necessary
    save_path = project_path + "/" + curr_year + "/" + datetime.now().strftime("%Y%m%d")
    index_path = project_path + "/" + curr_year
    logfile = save_path + "/press.csv"
    dbfile = project_path + "/pressure.csv"
    if not check_files( save_path, **pconfig ):
        print( time.ctime(), "(logpress) ERROR setting up file structure" )
        return

    retry_count = 0
    # keep trying until not busy, or give up on error, until MAX_RETRIES
    while retry_count < MAX_RETRIES:
        print( time.ctime(), "(logpress) calling get_tpg(**pconfig)" )
        tpgpress = get_tpg( **pconfig )
        print(tpgpress)

        tpgpressfile = None
        dbpressfile = None
        if tpgpress is None:
            # no attempt to log nor try again on error
            break
        if tpgpress == 'ERR':
            # no attempt to log nor try again on error
            break
        if tpgpress != 'BSY':
            try:
                # new day?
                new_day = not os.path.exists(logfile)
                new_db = not os.path.exists(dbfile)

                tpgpressfile = open(logfile, 'a')
                dbpressfile = open(dbfile, 'a')

                if new_day:
                    hdr = 'datetime, ' + pconfig['presshdrs']
                    tpgpressfile.write( hdr + '\n' )
                    if not pconfig['logtemps']:
                        make_index(index_path, **pconfig)
                if new_db:
                    hdr = 'datetime, ' + pconfig['presshdrs']
                    dbpressfile.write( hdr + '\n' )

                list_format = '{:}, ' + pconfig['pressfmts'] + '\n'

                tpgpressfile.write( list_format.format(*tpgpress) )
                tpgpressfile.close()
                dbpressfile.write( list_format.format(*tpgpress) )
                dbpressfile.close()
                break

            except Exception as ex:
                print( time.ctime(), "(logpress) exception:", str(ex) )
                if tpgpressfile is not None:
                    tpgpressfile.close()
                if dbpressfile is not None:
                    dbpressfile.close()
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
# @param  **tconfig - configuration dictionary
# @return none
#
# This function is called by the scheduler.
# -----------------------------------------------------------------------------
def logtemp(**tconfig):
    """ Log temperatures """

    project_path = os.path.join(tconfig['logroot'], tconfig['name'])
    print( time.ctime(), "(logtemp) starting" )

    # create log file and needed paths if necessary
    curr_year = datetime.now().strftime("%Y")
    save_path = project_path + "/" + curr_year + "/" + datetime.now().strftime("%Y%m%d")
    index_path = project_path + "/" + curr_year
    logfile = save_path + "/temps.csv"
    if not check_files( save_path, **tconfig ):
        print( time.ctime(), "(logtemp) ERROR setting up file structure" )
        return

    retry_count = 0
    # keep trying until not busy, or give up on error, until MAX_RETRIES
    while retry_count < MAX_RETRIES:
        print( time.ctime(),
               "(logtemp) calling get_temps(**tconfig)" )
        lkstemps = get_temps(**tconfig)
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
                new_day = not os.path.exists(logfile)

                lkstempfile = open(logfile, 'a')

                if new_day:
                    hdr = 'datetime, ' + tconfig['temphdrs']
                    lkstempfile.write(hdr + '\n')
                    make_index(index_path, **tconfig)

                list_format = '{:}, ' + tconfig['tempfmts'] + '\n'

                lkstempfile.write( list_format.format(*lkstemps) )
                lkstempfile.close()
                break

            except Exception as ex:
                print( time.ctime(), "(logtemp) exception:", str(ex) )
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

    signal.signal( signal.SIGTERM, signal_handler )
    signal.signal( signal.SIGINT, signal_handler )

    parser=argparse.ArgumentParser(description='logger')
    parser.add_argument( 'config_file', help='.json file required to configure the logger' )
    args = parser.parse_args()

    with open(args.config_file) as cfg_fl:
        config = json.load(cfg_fl)

    # need to have a project name and it can't be empty
    #
    if 'name' in config:
        if not config['name']:
            print( time.ctime(), "(main) ERROR: 'name' in %s cannot be empty!" % args.config_file )
            sys.exit(1)
    else:
        print( time.ctime(), "(main) ERROR: %s missing config key 'name'" % args.config_file )
        sys.exit(1)

    if 'influxdb_url' in config and 'influxdb_token' in config and 'influxdb_org' in config:
        print(time.ctime(), "Will connect to influxDB.")
        config['influxdb_client'] = True
    else:
        print(time.ctime(), "Will NOT connect to influxDB.")
        config['influxdb_client'] = False

    # need to have a log root dir and it can't be empty
    #
    if 'logroot' in config:
        if not config['logroot']:
            print( time.ctime(), "(main) ERROR: 'logroot' in %s cannot be empty!" %
                   args.config_file )
            sys.exit(1)
    else:
        print( time.ctime(), "(main) ERROR: %s missing config key 'logroot'" % args.config_file )
        sys.exit(1)

    # get the temperature host and port numbers from the config file
    #
    if 'temphost' in config:
        config['logtemps'] = True
        print( time.ctime(), "(main) found temphost, logtemps is enabled" )
        if 'tempport' not in config:
            print( time.ctime(), "(main) ERROR: 'tempport' missing!")
            sys.exit(1)
    else:
        config['logtemps'] = False
        print( time.ctime(), "(main) missing temphost, logtemps is disabled" )

    # get the pressure host and port numbers from the config file
    #
    if 'presshost' in config:
        config['logpress'] = True
        print( time.ctime(), "(main) found presshost, logpress is enabled" )
        if 'pressport' not in config:
            print( time.ctime(), "(main) ERROR: 'pressport' missing!")
            sys.exit(1)
    else:
        config['logpress'] = False
        print( time.ctime(), "(main) missing presshost, logpress is disabled" )

    # If we're logging temperatures then get everything needed for that
    #
    if config['logtemps']:

        # get the temperature channels to log from the config file
        #
        if 'tempchans' in config:
            temp_channels = config['tempchans'].split(',')
        else:
            print( time.ctime(), "(main) ERROR: %s missing config key "
                                 "'tempchans'" % args.config_file )
            sys.exit(1)
        if temp_channels == ['']:
            temp_channels=[]          # if the input is blank, make sure it is length 0

        # get the temperature channel headers from the config file
        #
        if 'temphdrs' in config:
            temp_hdrs = config['temphdrs'].split(',')
            htr_hdrs = []
            for thdr in temp_hdrs:
                if "HTR" in thdr:
                    htr_hdrs.append(thdr)
            if len(htr_hdrs) != 2:
                htr_hdrs = ["HTR1", "HTR2"]
            config['heater_header'] = htr_hdrs
        else:
            print( time.ctime(), "(main) ERROR: %s missing config key "
                                 "'temphdrs'" % args.config_file )
            sys.exit(1)
        if temp_hdrs == ['']:
            temp_hdrs=[]            # if the input is blank, make sure it is length 0

                # get the temperature channel formats from the config file
        #
        if 'tempfmts' in config:
            temp_fmts = config['tempfmts'].split(',')
        else:
            print( time.ctime(), "(main) ERROR: %s missing config key "
                                 "'tempfmts'" % args.config_file )
            sys.exit(1)
        if temp_fmts == ['']:
            temp_fmts=[]            # if the input is blank, make sure it is length 0

        # must have the same number of temp headers, temp channels, and temp formats
        #
        if len(temp_channels) != len(temp_hdrs) or len(temp_channels) != len(temp_fmts):
            print( time.ctime(), "(main) ERROR: must have same number of "
                                 "tempchans (%d), temphdrs (%d) and tempfmts (%d)" %
                   ( len(temp_channels), len(temp_hdrs), len(temp_fmts) ) )
            sys.exit(1)

        # get temperature logging rate from config file
        #
        if 'temprate' not in config:
            config['temprate'] = 60
    else:
        config['heater_header'] = ["HTR1", "HTR2"]

    # If we're logging pressure then get everything needed for that
    #
    if config['logpress']:

        # get the pressure numbetr of channels the controller has from the config file
        #
        if 'pressnumchans' in config:
            press_num_channels = config['pressnumchans']
        else:
            print( time.ctime(), "(main) ERROR: %s missing config key "
                                 "'pressnumchans'" % args.config_file )
            sys.exit(1)
        if press_num_channels <= 0:
            print( time.ctime(), "(main) ERROR: 'pressnumchans' controller "
                                 "must have at least one channel" )
            sys.exit(1)

        # get the pressure channels to log from the config file
        #
        if 'presschans' in config:
            press_channels = config['presschans']
        else:
            print( time.ctime(), "(main) ERROR: %s missing config key "
                                 "'presschans'" % args.config_file )
            sys.exit(1)
        if len(press_channels) <= 0:
            print( time.ctime(), "(main) ERROR: 'presschans' must have "
                                 "at least one active channel" )
            sys.exit(1)

        # get the pressure channel headers from the config file
        #
        if 'presshdrs' in config:
            press_hdrs = config['presshdrs'].split(',')
        else:
            print( time.ctime(), "(main) ERROR: %s missing config key "
                                 "'presshdrs'" % args.config_file )
            sys.exit(1)
        if press_hdrs == ['']:
            press_hdrs=[]            # if the input is blank, make sure it is length 0

        # get the pressure channel formats from the config file
        #
        if 'pressfmts' in config:
            press_fmts = config['pressfmts'].split(',')
        else:
            print( time.ctime(), "(main) ERROR: %s missing config key "
                                 "'pressfmts'" % args.config_file )
            sys.exit(1)
        if press_fmts == ['']:
            press_fmts=[]            # if the input is blank, make sure it is length 0

        # must have the same number of press channels, headers, and formats
        #
        if len(press_channels) != len(press_hdrs) or len(press_channels) != len(press_fmts):
            print( time.ctime(), "(main) ERROR: must have same number of "
                                 "presschans (%d), presshdrs (%d), and pressfmts (%d)" %
                   ( len(press_channels), len(press_hdrs), len(press_fmts) ) )
            sys.exit(1)

        # get pressure logging rate from config file
        #
        if 'pressrate' not in config:
            config['pressrate'] = 60

    # create project directory if needed
    project_dir = os.path.join(config['logroot'], config['name'])
    if not os.path.exists( project_dir ):
        print( time.ctime(), "(main) creating ", project_dir )
        try:
            os.mkdir( project_dir )
        except Exception as exc:
            print( time.ctime(), "(main) exception creating directory:", str(exc) )

    config['jobs_started'] = 0
    # if we have everything needed for temperature logging then start a thread
    #
    if config['logtemps']:
        print( time.ctime(), "(main) starting temperature logging for %s" % config['name'] )
        temp_logging = Job( interval=timedelta(seconds=config['temprate']), execute=logtemp,
                            **config )
        temp_logging.start()
        config['jobs_started'] += 1
    else:
        temp_logging = None
        print( time.ctime(),
               "(main) temperature logging disabled: missing one or more of "
               "temphost, tempport, temprate, tempchans" )

    # if we have everything needed for pressure logging then start a thread
    #
    if config['logpress']:
        print( time.ctime(), "(main) starting pressure logging" )
        press_logging = Job( interval=timedelta(seconds=config['pressrate']), execute=logpress,
                            **config )
        press_logging.start()
        config['jobs_started'] += 1
    else:
        press_logging = None
        print( time.ctime(),
               "(main) pressure logging disabled: missing one or more of "
               "presshost, pressport, pressrate, presschans" )

    # nothing to do
    #
    if not config['jobs_started']:
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
