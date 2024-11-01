import glob
import numpy as np
from astropy.io import fits
import matplotlib.pyplot as plt
from scipy.stats import zscore
from scipy.signal import find_peaks


def cr_catalogue(data_dir="", zscore_limit=2.5):
    # Get image list
    cr_list = sorted(glob.glob(f'{data_dir}/img*_cr.cat'))
    if not cr_list:
        print("No cr files found.")
        return

    all_rms_b = []

    # Loop over images
    for cat_file in cr_list:
        # Read CR.cat file with the updated format
        cat_data = np.loadtxt(cat_file, usecols=(0, 1, 2, 3, 4, 5), comments='#')

        sids, xs, ys, rms_a, rms_b, thetas = cat_data.T

        # Add cr_file values to list
        all_rms_b.extend(rms_b)


    # print(f'All yrms list: {all_yrms}')
    counts, bin_edges = np.histogram(all_rms_b, bins=100, range=(0,3), density=True)

    # Calculate z-scores for the bin counts
    z_scores = zscore(counts)

    # Identify bins that are considered spikes
    spike_bins = np.where(z_scores > zscore_limit)[0]

    if len(spike_bins) > 0:
        # Get the bin edges corresponding to the start and end of the main spike
        spike_start_edge = float(bin_edges[spike_bins[0]])
        spike_end_edge = float(bin_edges[spike_bins[len(spike_bins) -1 ] + 1])

        print(f"The main spike starts at: {spike_start_edge}")
        print(f"The main spike ends at: {spike_end_edge}")

        # Plotting the histogram with main spike highlighted
        plt.hist(all_rms_b, bins=100, range=(0, 3), edgecolor='black', density=True, color='blue')

        # Highlighting the main spike range in red
        plt.axvspan(spike_start_edge, spike_end_edge, color='red', alpha=0.5)

        # Adding labels and title
        plt.xlabel('Yrms (px)')
        plt.ylabel('N (norm)')
        plt.title('Histogram with Main Spike Range Highlighted (Z-Score)')

        plt.show()

        return [spike_start_edge, spike_end_edge]
    else:
        print("No spikes found.")
