import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit

# Define Gaussian function for fitting
def gaussian(x, a, x0, sigma, offset):
    return a * np.exp(-(x - x0) ** 2 / (2 * sigma ** 2)) + offset

def muon_sample(im, seg, sno, x, gplot=False):
    """
    muon_sample - Return the y trace of a muon.
    """
    yivec = np.squeeze(im[:, x])
    ysvec = np.squeeze(seg[:, x])

    ny = len(ysvec)
    svec = np.where(ysvec == sno)[0]
    nsvec = len(svec)

    if nsvec > 0:
        y0 = max(min(svec) - 5, 0)
        y1 = min(max(svec) + 5, ny - 1)
        nfit = (y1 - y0) + 1

        if nfit <= 5:
            sig = -1.
            pk = -1.
        else:
            yf = yivec[y0:y1 + 1]
            xf = np.arange(nfit)

            try:
                popt, _ = curve_fit(gaussian, xf, yf, p0=[np.max(yf), np.median(xf), np.std(xf), np.min(yf)])
                sig = popt[2]  # sigma
                pk = popt[0]  # peak

                if gplot:
                    plt.plot(xf, yf - popt[3], 'o', label="Data")
                    plt.plot(xf, gaussian(xf, *popt) - popt[3], label="Gaussian Fit")
                    plt.title(f'Seg: {sno}, x: {x}')
                    plt.legend()
                    plt.show()

            except RuntimeError:
                sig = -1.
                pk = -1.
    else:
        sig = -1.
        pk = -1.

    return sig
