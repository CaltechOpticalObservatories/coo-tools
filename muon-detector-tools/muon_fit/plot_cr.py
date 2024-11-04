from matplotlib import pyplot as plt
import numpy as np

# Cosmic rays plot
def plot_cr(xx, sg, yfit, sno, verbose=False):
    # Set up plot appearance
    fig, ax = plt.subplots()
    ax.set_facecolor('white')
    ax.spines['bottom'].set_color('black')
    ax.spines['top'].set_color('black')
    ax.spines['left'].set_color('black')
    ax.spines['right'].set_color('black')

    # Font size and thickness
    th = 5
    si = 1.75
    ax.set_title(f'CR#: {sno}', fontsize=si * 10)
    ax.set_xlabel('X (px)', fontsize=si * 10, weight='bold')
    ax.set_ylabel('Signal (px)', fontsize=si * 10, weight='bold')
    ax.tick_params(axis='both', which='major', labelsize=si * 10, width=th)
    ax.set_xlim([xx.min() - 1, xx.max() + 1])
    ax.set_ylim([sg.min() - 1, sg.max() + 1])

    if verbose:
        print(f"xx: {xx} \nsg: {sg} \nyfit: {yfit}")

    # Plot the signal points
    ax.plot(xx, sg, 'o', label='Signal', color='blue', markersize=5)

    # Plot the linear fit
    ax.plot(xx, yfit, '--', label='Fit', linewidth=3, color='red')

    # Plot vertical lines marking the big and small values
    ax.axvline(x=xx.max(), linestyle=':', color='black', linewidth=2, label='Big Value')
    ax.axvline(x=xx.min(), linestyle=':', color='black', linewidth=2, label='Small Value')

    # Horizontal reference line at 1/sqrt(12)
    ax.axhline(y=1 / np.sqrt(12), linestyle='-.', color='black', linewidth=3)

    # # Add labels for big/small and 1/12^0.5
    # ax.text(1305, 0.3, '1/12$^{1/2}$', fontsize=si * 10)
    # ax.text(1284, 0.2, 'MAX', fontsize=si * 10)
    # ax.text(1325, 0.2, 'MIN', fontsize=si * 10)

    # Add legend
    ax.legend()

    # Show the plot
    plt.show()
