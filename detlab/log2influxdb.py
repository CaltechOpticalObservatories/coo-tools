#!/usr/bin/env python
""" log2influxdb - Tool for ingesting old CSV files into influxDB

    Uses .json config file with the same format as the logcryo.py routine.
"""
import sys
import os
import argparse
import json
import datetime
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

def parse_log_date(log_date):
    """ Parse dates from old log files
    expected format: MM/DD/YY HH:MM:SS
    transform to: YYYY-MM-DDTHH:MM:SS-08:00

    date_split = log_date.split()[0].split('/')
    time_str = log_date.split()[1]

    stamp = "20"+date_split[2]+"-"+date_split[0]+"-"+date_split[1]
    stamp += "T"+time_str+"-08:00"

    return stamp
    """

    try:
        dt_item = datetime.datetime.strptime(log_date, "%m/%d/%y %H:%M:%S")
        # Convert to the required format
        return dt_item.strftime("%Y-%m-%dT%H:%M:%S-08:00")
    except ValueError:
        print(f"Invalid date format: {log_date}")
        sys.exit(1)

# -----------------------------------------------------------------------------
# @fn     main
# @brief  the main function starts here
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Ingest CSV log file into InfluxDB')
    parser.add_argument('config_file', default=None,
                        help='.json file with configuration parameters')
    parser.add_argument('--logfile', required=True,
                        type=str, help='log file to ingest')
    args = parser.parse_args()

    if not os.path.exists(args.logfile):
        print("log file {} does not exist".format(args.logfile))
        sys.exit(1)

    if 'temp' in args.logfile:
        temp_log = True
        press_log = False
        ptag = 'temperature'
        units = 'C'
    elif 'press' in args.logfile:
        temp_log = False
        press_log = True
        ptag = 'pressure'
        units = 'mTorr'
    else:
        print("logfile must contain 'press' or 'temp'")
        sys.exit(1)

    with open(args.logfile, 'r') as logfile:
        lines = logfile.readlines()
        print("read {} lines".format(len(lines)))

    with open(args.config_file, 'r') as confgf:
        config = json.load(confgf)

    print("Connecting to InfluxDB...")
    db_client = InfluxDBClient(url=config['influxdb_url'],
                               token=config['influxdb_token'],
                               org=config['influxdb_org'])
    write_api = db_client.write_api(write_options=SYNCHRONOUS)

    hdrs = []
    time_stamp = None
    point_count = 0
    for line in lines:
        if 'datetime' in line:
            hdrs = line.split(',')
        else:
            data = line.split(',')
            for ichan, datum in enumerate(data):
                if ichan == 0:
                    time_stamp = parse_log_date(datum)
                else:
                    point = (Point("measurement")
                             .tag("channel", hdrs[ichan].strip())
                             .tag("units", units)
                             .time(time_stamp)
                             .field(ptag, float(datum)))
                    point_count += 1
                    if point_count % 1000 == 0:
                        print("Time Stamp: {}".format(time_stamp))
                        print("Point Count: {}".format(point_count))
                    write_api.write(bucket=config['name'].upper(),
                                    org=config['influxdb_org'],
                                    record=point,
                                    write_precision=WritePrecision.S)
