from matplotlib import pyplot as plt
import numpy as np

def plot_histogram(im_file, big, small, bin_size=0.025):
    plt.hist(big, bins=np.arange(0, 1.5, bin_size), alpha=0.7, label='Big')
    plt.hist(small, bins=np.arange(0, 1.5, bin_size), alpha=0.7, label='Small', linestyle='--')
    plt.title(im_file)
    plt.legend()
    plt.show()