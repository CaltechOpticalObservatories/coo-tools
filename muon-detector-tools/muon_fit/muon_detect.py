import glob
import numpy as np
from astropy.io import fits
from scipy.stats import norm
import matplotlib.pyplot as plt
from muon_fit.muon_sample import muon_sample
from muon_fit.plot_cr import plot_cr
from muon_fit.plot_histogram import plot_histogram


def muon_detect(data_dir="", mw0=0.62, mw1=0.73, gplot=None, hplot=None, ps=None, crplot=None, verbose=None):
    # Initial parameters
    bin_size = 0.025

    # Get list of fits images
    all_fits_files = sorted(glob.glob(f'{data_dir}/*.fits'))

    # Filter out files that end with '_seg.fits'
    im_list = [f for f in all_fits_files if not f.endswith('_seg.fits')]

    if not im_list:
        print("No image files found.")
        return

    allbig = np.empty(0, dtype=np.float32)
    allsmall = np.empty(0, dtype=np.float32)
    p = 0

    # Loop over images
    for im_file in im_list:
        print(f"Processing: {im_file}")
        # Read image and segmentation files
        im = fits.getdata(im_file)
        seg = fits.getdata(f"{im_file.split('.')[0]}_seg.fits")

        # Read the corresponding CR.cat file with the updated format
        cat_file = f"{im_file.split('.')[0]}_cr.cat"
        cat_data = np.loadtxt(cat_file, usecols=(0, 1, 2, 3, 4, 5), comments='#')

        sids, xs, ys, rms_a, rms_b, thetas = cat_data.T
        thetas = np.deg2rad(thetas)  # Convert angles from degrees to radians

        nseg = len(sids)
        big = np.full(nseg, -1.0, dtype=np.float32)
        small = np.full(nseg, -1.0, dtype=np.float32)

        for j in range(nseg):
            sno = sids[j]
            costh = np.cos(thetas[j])

            t = np.where(seg == sno)[1]
            if len(t) > 0:
                ind = np.array(np.unravel_index(t, seg.shape))

                # Get the range of x-points
                xs_range = [np.min(ind[1]), np.max(ind[1])]
                nx = xs_range[1] - xs_range[0] + 1

                if mw0 <= rms_b[j] <= mw1 and costh >= 0.7 and rms_a[j] > 9.0:
                    if verbose:
                        print(f"Segment {sno} passed")

                    sg = np.zeros(nx, dtype=np.float32)
                    for i in range(nx):
                        # Call muon_sample to fit CR
                        sig = muon_sample(im, seg, sno, xs_range[0] + i, gplot=gplot)
                        sg[i] = sig

                    # Ensure we have enough valid points to fit the data
                    valid = (sg > 0)
                    print(f'{np.sum(valid)} valid points for sno {sno}')
                    if np.sum(valid) >= 9:  # Minimum valid points to perform a fit
                        xx = np.arange(xs_range[0], xs_range[1] + 1)
                        sgth = sg * costh

                        # Attempt to fit a line to the valid points
                        coef = np.polyfit(xx[valid], sgth[valid], 1)

                        # Evaluate the polynomial fit
                        yfit = np.polyval(coef, xx)

                        # Calculate residuals and apply a weight mask
                        diff = sgth - yfit
                        weight_mask = np.abs(diff) < 2  # Example weight filter

                        # Ensure there are valid weights
                        if np.any(weight_mask):
                            big[j] = np.max(yfit[weight_mask])
                            small[j] = np.min(yfit[weight_mask])

                            if big[j] > 0 and small[j] > 0:
                                allbig = np.append(allbig, big[j])
                                allsmall = np.append(allsmall, small[j])
                                p += 1

                            # Optional crplot
                            if crplot:
                                plot_cr(xx, sg, yfit, sno, verbose)
                        else:
                            print(f"No valid weights for fitting in segment {sno}")
                    else:
                        print(f"Not enough valid points for fitting in segment {sno}")
            else:
                print(f"Could not find segment {sno}")

        big = big[big > 0]
        small = small[small > 0]
        print(f'{im_file}: N CRs = {len(big)}')
        
        # plot histogram
        if hplot:
            plot_histogram(im_file, big, small, bin_size)


    allbig = allbig[allbig > 0]
    allsmall = allsmall[allsmall > 0]

    # Final histogram over all files
    print(f"allbig and allsmall lengths: {len(allbig)} vs {len(allsmall)}")
    diflen = np.sqrt(allbig ** 2 - allsmall ** 2) * 15.0
    diflen2 = np.sqrt(allbig ** 2 - (1/12)) * 15.0 # (1/12^(1/2))**2 is 1/12

    print(f"Processed {len(im_list)} images, {p} muon CRs")

    # Create the histograms
    bin_width = 0.25
    bins = np.arange(0, 50 + bin_width, bin_width)

    # First histogram (σMAX - σMIN)
    hist1, bin_edges1 = np.histogram(diflen[diflen <= 50], bins=bins)

    # Second histogram (σMAX - 1/12^(1/2))
    hist2, bin_edges2 = np.histogram(diflen2[diflen2 <= 50], bins=bins)

    # Plotting the histograms
    plt.figure(figsize=(10, 6))

    # Plot both histograms
    counts1, edges1, _ = plt.hist(bin_edges1[:-1], bins, histtype='step', weights=hist1, label='σMAX - σMIN', color='green', linestyle='-')
    counts2, edges2, _ = plt.hist(bin_edges2[:-1], bins, histtype='step', weights=hist2, label='σMAX - 1/12^(1/2)', color='blue', linestyle='-')

    # Calculate the center of each bin to use in the fit
    bin_centers1 = (bin_edges1[:-1] + bin_edges1[1:]) / 2
    bin_centers2 = (bin_edges2[:-1] + bin_edges2[1:]) / 2

    # Calculate the mean and standard deviation for each dataset
    mean1, std_dev1 = norm.fit(np.repeat(bin_centers1, hist1.astype(int)))
    mean2, std_dev2 = norm.fit(np.repeat(bin_centers2, hist2.astype(int)))

    # Create a range of values for the Gaussian curves
    x_values1 = np.linspace(bin_edges1[0], bin_edges1[-1], 1000)
    x_values2 = np.linspace(bin_edges2[0], bin_edges2[-1], 1000)

    # Calculate the Gaussian curve for each dataset
    gaussian1 = norm.pdf(x_values1, mean1, std_dev1)
    gaussian2 = norm.pdf(x_values2, mean2, std_dev2)

    # Plot the Gaussian curves
    plt.plot(x_values1, gaussian1 * sum(hist1) * (bin_edges1[1] - bin_edges1[0]), color='green', linestyle='--', label='Gaussian Fit σMAX - σMIN')
    plt.plot(x_values2, gaussian2 * sum(hist2) * (bin_edges2[1] - bin_edges2[0]), color='blue', linestyle='--', label='Gaussian Fit σMAX - 1/12^(1/2)')

    # Display mean and variance
    textstr1 = f'σMAX - σMIN:\nMean (μ): {mean1:.2f}\nVariance (σ²): {std_dev1**2:.2f}'
    textstr2 = f'σMAX - 1/12^(1/2):\nMean (μ): {mean2:.2f}\nVariance (σ²): {std_dev2**2:.2f}'
    plt.text(0.05, 0.95, textstr1 + '\n' + textstr2, transform=plt.gca().transAxes, fontsize=10,
            verticalalignment='top', bbox=dict(boxstyle='round,pad=0.5', edgecolor='gray', facecolor='white'))



    # Find the max values and their positions for each histogram
    max_count1 = max(counts1)
    max_count2 = max(counts2)
    max_pos1 = edges1[np.argmax(counts1)]
    max_pos2 = edges2[np.argmax(counts2)]

    # Annotate max values on the plot
    plt.annotate(f'Max: {int(max_count1)}', xy=(max_pos1, max_count1), 
                xytext=(max_pos1 - 3, max_count1), ha='left',
                arrowprops=dict(facecolor='black', arrowstyle='->'))

    plt.annotate(f'Max: {int(max_count2)}', xy=(max_pos2, max_count2), 
                xytext=(max_pos2 + 3, max_count2), ha='right',
                arrowprops=dict(facecolor='black', arrowstyle='->'))

    # Adding labels and title
    plt.title('Diffusion Lengths')
    plt.xlabel('Diffusion Length (µm)')
    plt.ylabel('N')
    plt.legend(loc='upper right')
    plt.xlim(2,20)

    # Display the plot
    plt.show()
