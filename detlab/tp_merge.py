#!/usr/bin/env python
"""Merge Temperature and Pressure data into a single csv file

    Args:
        press_file (str) - filename with pressure data
        temp_file (str) - filename with temperature data
        --press_time_column (str) - pressure time column name (default 'Time')
        --temp_time_column (str) - temperature time column name (default 'time')
        --time_sample (str) - time sample interval (default '1min')
        --output_file (str) - filename for output csv data (default 'data.csv')
"""

import argparse
import pandas as pd
import matplotlib.pyplot as plt

parser = argparse.ArgumentParser(description='Merge Temperature and Pressure '
                                             'data into a single csv file')
parser.add_argument('press_file', default=None,
                    help='.csv file with pressure time series')
parser.add_argument('temp_file', default=None,
                    help='.csv file with temperature time series')
parser.add_argument('--press_time_column', default="Time",
                    type=str, help='Pressure time column name (default "Time")')
parser.add_argument('--temp_time_column', default="time",
                    type=str, help='Temperature time column name (default "time")')
parser.add_argument('--time_sample', default="1min",
                    type=str, help='Time sampling interval')
parser.add_argument('--output_file', default="data.csv",
                    type=str, help='Output file name (default "data.csv")')
args = parser.parse_args()

if __name__ == "__main__":
    pfile = args.press_file
    tfile = args.temp_file

    # Read Pressure data
    pd_p = pd.read_csv(pfile, parse_dates=True)
    pd_p[args.press_time_column] = pd.to_datetime(pd_p[args.press_time_column],
                                                  unit="ms")
    pd_p.set_index(args.press_time_column, inplace=True)
    pd_p.plot(title="Pressure time series")
    plt.ylabel("mTorr")
    plt.show()

    # Read Temperature data
    pd_t = pd.read_csv(tfile)
    pd_t[args.temp_time_column] = pd.to_datetime(pd_t[args.temp_time_column],
                                                 unit="ms")
    pd_t.set_index(args.temp_time_column, inplace=True)
    pd_t.plot(title="Temperature time series")
    plt.ylabel("deg C")
    plt.show()

    pd_t_resamp = pd_t.resample(args.time_sample).ffill().reindex(pd_p.index)

    plt.plot(pd_p["pressure"], pd_t_resamp['Value'])
    plt.title("Pressure versus Temperature time series")
    plt.xlabel("mTorr")
    plt.ylabel("deg C")
    plt.show()

    pd_p["temperature"] = pd_t_resamp["Value"]

    pd_p.to_csv(args.output_file)

    pd_p["ratio"] = pd_t_resamp["Value"] / pd_p["pressure"]
    pd_p["ratio"].plot(title="Temperature / Pressure time series")
    plt.ylabel("deg C/mTorr")
    plt.show()
