import scipy.ndimage as ndi
import numpy as np

'''
---- Example Usage ----
import ZygoImage_DMResampler as resamp

# Load the sample Zygo image
original = np.load("F_map_phasearray.npy")

# Rotate it to match DM orientation
dm_angle = 142
rotated = resamp.rotate_phase_map(original, dm_angle)

# Downsample it to match DM shape
dm_shape = (28,28)
downsampled = resamp.downsample_phase_map(rotated, dm_shape)

# Display the results
import matplotlib.pyplot as plt
plt.figure(); plt.imshow(original); plt.title("Original")
plt.figure(); plt.imshow(rotated); plt.title("Rotated Only")
plt.figure(); plt.imshow(downsampled); plt.title("Rotated + Block-Average Downsampled")
'''


def rotate_phase_map(phase_map, angle=142):
    return ndi.rotate(phase_map, angle, reshape=False)

def downsample_phase_map(phase_map, new_shape):
    """
    Downsample a 2D phase map by block averaging to match new_shape.
    
    Parameters:
        phase_map (np.ndarray): The original 2D phase map (e.g., 561x561).
        new_shape (tuple): The desired output shape (e.g., 28x28).
        
    Returns:
        np.ndarray: The downsampled phase map.
    """
    M, N = phase_map.shape
    m, n = new_shape
    
    # Ensure dimensions are divisible (or crop for simplicity)
    crop_M = (M // m) * m
    crop_N = (N // n) * n
    cropped = phase_map[:crop_M, :crop_N]

    # Reshape and average
    reshaped = cropped.reshape(m, crop_M // m, n, crop_N // n)
    downsampled = reshaped.mean(axis=(1, 3))
    
    return downsampled
