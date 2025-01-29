#!/usr/bin/env python
"""Merge Temperature and Pressure data into a single csv file

    Args:
        press_file (str) - filename with pressure data
        temp_file (str) - filename with temperature data
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
    # Get Time/Date column
    p_cols = list(pd_p.columns)
    p_time_col = 'Time'
    for pcol in p_cols:
        if 'ime' in pcol or 'ate' in pcol:
            p_time_col = pcol
    # Convert to datetime format
    pd_p[p_time_col] = pd.to_datetime(pd_p[p_time_col], unit="ms")
    # Set datetime as index
    pd_p.set_index(p_time_col, inplace=True)
    # Get pressure column
    p_col = list(pd_p.columns)[0]
    # Remove null values
    pd_p.dropna(subset=[p_col], inplace=True)
    # Set column name to 'Pressure'
    pd_p.rename(columns={p_col: 'Pressure'}, inplace=True)
    # Plot Pressure time series
    pd_p.plot(title="Pressure time series")
    plt.ylabel("mTorr")
    plt.show()

    # Read Temperature data
    pd_t = pd.read_csv(tfile)
    # Get Time/Date column
    t_cols = list(pd_t.columns)
    t_time_col = 'Time'
    for tcol in t_cols:
        if 'ime' in tcol or 'ate' in tcol:
            t_time_col = tcol
    # Convert to datetime format
    pd_t[t_time_col] = pd.to_datetime(pd_t[t_time_col], unit="ms")
    # Set datetime as index
    pd_t.set_index(t_time_col, inplace=True)
    # Get Temperature column
    t_col = list(pd_t.columns)[0]
    # Remove null values
    pd_t.dropna(subset=[t_col], inplace=True)
    # Set column name to 'Temperature'
    pd_t.rename(columns={t_col: 'Temperature'}, inplace=True)
    # Plot Temperature time series
    pd_t.plot(title="Temperature time series")
    plt.ylabel("deg C")
    plt.show()

    # Resample to requested time_sample interval
    pd_t_resamp = pd_t.resample(args.time_sample).ffill().reindex(pd_p.index)

    # Plot Pressure versus Temperature
    plt.plot(pd_p['Pressure'], pd_t_resamp['Temperature'])
    plt.title("Pressure versus Temperature")
    plt.xlabel("mTorr")
    plt.ylabel("deg C")
    plt.show()

    # Add Temperature column to Pressure data frame
    pd_p['Temperature'] = pd_t_resamp['Temperature']

    # Write out csv file
    pd_p.to_csv(args.output_file)

    # Plot Temperature / Pressure
    pd_p["ratio"] = pd_t_resamp['Temperature'] / pd_p['Pressure']
    pd_p["ratio"].plot(title="Temperature / Pressure time series")
    plt.ylabel("deg C/mTorr")
    plt.show()
