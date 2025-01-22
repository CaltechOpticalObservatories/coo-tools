#!/usr/bin/env python
"""Merge Temperature and Pressure data into a single csv file"""
import sys
import pandas as pd
import matplotlib.pyplot as plt


if __name__ == "__main__":
    pfile = sys.argv[1]
    tfile = sys.argv[2]

    # Read Pressure data
    pd_p = pd.read_csv(pfile, parse_dates=True)
    pd_p["Time"] = pd.to_datetime(pd_p["Time"], unit="ms")
    pd_p.set_index("Time", inplace=True)
    pd_p.plot()
    plt.show()

    # Read Temperature data
    pd_t = pd.read_csv(tfile)
    pd_t["time"] = pd.to_datetime(pd_t["time"], unit="ms")
    pd_t.set_index("time", inplace=True)
    pd_t.plot()
    plt.show()

    pd_t_resamp = pd_t.resample('1min').ffill().reindex(pd_p.index)

    plt.plot(pd_p["pressure"], pd_t_resamp['Value'])
    plt.show()

    pd_p["temperature"] = pd_t_resamp["Value"]

    pd_p.to_csv('data.csv')
