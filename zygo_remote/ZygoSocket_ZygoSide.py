import socket
import time
import struct
import numpy as np

from zygo import instrument, mx, ui
from zygo.units import Units
import h5py

# === CONFIGURATION ===
SERVER_IP = '131.215.200.31'   # Replace with SERVER's IP
PORT = 5000                 # Must match SERVER-side
TIMEOUT_SEC = 300  # 5 minutes
SLEEP_INTERVAL = 0.1

# Name for file used when writing data (will be constantly overwritten)
TMP_FILE_PROC = r'C:\tmp\zygo_socket_procfile.datx'
TMP_FILE_RAW = r'c:\tmp\zygo_socket_rawfile.datx'

# Define datatype for the elements of the Zygo phase array
    # Must match analogous value in DM_Side
PHASE_ARRAY_DTYPE = np.float64


# === Zygo constants === 
M2NM = 1e9
ZYGO_WAVELENGTH = 632.8e-9  # [nm]

nm_units = Units.NanoMeters.name
wave_units = Units.Waves.name

# "path"s to Zygo elements on MX GUI
RMS_PATH = ("Analysis", "Surface", "RMS")
SURF_PLOT_PATH = ("Analysis", "Surface", "Surface", "3D Surface Data")

# === HELPER FUNCTIONS ===
#-- Function to read surface from FULL .datx file
    # FULL means a file saved via mx.save_data()
def read_datx_surface_fromfull(filename):
    with h5py.File(filename, 'r') as h5file:
        assert 'Measurement' in list(h5file.keys()), 'No "Measurement" key found. Double-check the file'
        
        # Get surface attributes
        surface = np.array(h5file['Measurement']['Surface'])
        surface_attrs = h5file['Measurement']['Surface'].attrs
        
        # Define a mask from the "no data" key
        mask = np.ones_like(surface).astype(bool)
        mask[surface == surface_attrs['No Data']] = 0
        
        # Mask the data and scale to nanometers
        surface[~mask] = 0
        surface *= surface_attrs['Interferometric Scale Factor'][0] * surface_attrs['Wavelength'] * M2NM 
    return surface, mask

#-- Function to read surface from 3DSurface .datx file
    # 3DSurface means a file saved via ui.get_control().save_data()

    # The key BENEFIT of this method is that it keeps the image-processing applied
    #   by the user on the MX GUI (ie. zernike subtraction, masks, etc.)
    
    # NOTE: this whole function is super hack-y. Ideally we would clean this up more
def read_datx_surface_from3Dui(filename):
    with h5py.File(filename, 'r') as h5file:
        assert 'Data' in list(h5file.keys()), 'No "Data" key found. Double-check the file'
        
        # Get the surface data access name
            # This is very hack-y... but it works
        surf_name = list(h5file['Data']['Surface'])[0]
        
        # Get surface attributes
        surface = np.array(h5file['Data']['Surface'][surf_name])
        
        # Define a mask from the "no data" key
        mask = np.ones_like(surface).astype(bool)
            # Hack: assume the max value is the "invalid" data value
            # This assumption is based on what I saw when I looked at the data - seems like a very large
            #   number was used to denote invalid values
            # worst-case of this assumption is that you remove the single max value... that's not a problem
        mask[surface == surface.max()] = 0
        
        # Mask the data and scale to nanometers
        surface[~mask] = 0
        interferometric_scale_factor = mx.get_control_number(("Instrument", "Measurement Setup", "Interferometric Scale Factor"))
        surface *= interferometric_scale_factor * ZYGO_WAVELENGTH * M2NM 
    return surface, mask

#-- Function to trigger a Zygo measurement and get phase array
def get_fresh_zygo_phase():
    # Trigger a Zygo measurement (including analysis)
    print("Starting Measurement...")
    acq_task = instrument.measure(wait=True)

    acq_task.measure_task.wait()
    print("measurement complete")

    # Print RMS value reported on GUI (within Zygo mask, and with Zernike's subtracted)
    rms_nm = mx.get_result_number(RMS_PATH, nm_units)
    rms_wave = mx.get_result_number(RMS_PATH, wave_units)
    print(f"RMS on GUI: {rms_nm:0.2f} {nm_units} ({rms_wave:0.4f} {wave_units})")

    # Save the Surface data - ONLY the 3D surface 
    #   (will overwrite to same file every time)
    ui.get_control(SURF_PLOT_PATH).save_data(TMP_FILE_PROC)

    # Extract the phase from the file
    surface_proc, mask_proc = read_datx_surface_from3Dui(TMP_FILE_PROC)

    # Save the full mx file 
    mx.save_data(TMP_FILE_RAW)

    # Extract the phase from the raw file
    surface, mask = read_datx_surface_fromfull(TMP_FILE_RAW)

    processed = {   'phase': surface_proc, 
                    'mask': mask_proc}
    raw = { 'phase': surface,
            'mask': mask}
    return {'processed': processed, 'raw':raw}

# === SOCKET SETUP ===
print(f"Connecting to DM at {SERVER_IP}:{PORT}")
client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client_socket.settimeout(TIMEOUT_SEC)

try:
    client_socket.connect((SERVER_IP, PORT))
except socket.timeout:
    raise RuntimeError("Could not connect to DM computer")

client_socket.settimeout(SLEEP_INTERVAL)

print("\nConnected to DM Computer")

# === MAIN LOOP ===
try:
    while True:
        # === WAIT FOR MEASURE COMMAND ===
        cmd = None
        for i in range(int(TIMEOUT_SEC / SLEEP_INTERVAL)):
            if i % 50 == 0:
                print(f"   Waiting for 'Measure' cue... itr {i}")
            try:
                data = client_socket.recv(1024).decode().strip()
                if data.lower() == 'measure':
                    cmd = 'measure'
                    break
                elif data.lower() == 'stop':
                    cmd = 'stop'
                    break
            except socket.timeout:
                continue

        if cmd == 'stop':
            print("Stop received.")
            break
        elif cmd != 'measure':
            raise RuntimeError("DM Computer did not respond or sent unexpected command")

        # === RECEIVE MEASURE HEADER ===
        measure_header = 'INVALID'
        for i in range(int(TIMEOUT_SEC / SLEEP_INTERVAL)):
            if i % 50 == 0:
                print(f"   Waiting for measure header... itr {i}")
            try:
                data = client_socket.recv(1024).decode().strip()
                if data.lower() not in ['measure', 'stop']:
                    measure_header = data
                    break
            except socket.timeout:
                continue

        if measure_header == 'INVALID':
            raise RuntimeError("Invalid measurement header was received")

        print(f"Received measure header: {measure_header}")

        # === TAKE ZYGO MEASUREMENT ===
        print(f"Measuring: {measure_header}")
        
        # TAKE Zygo measurement
        # TODO: replace with actual measurement call
        result = get_fresh_zygo_phase()
        processed = result['processed']

        # Parse phase data
        phase_array = processed['phase']

        # For Debugging:
        print(phase_array)

        # === FORMAT AND SEND PHASE ARRAY MESSAGE ===
        # Return the measure header
        client_socket.sendall(measure_header.encode())

        # Format the the phase array
        array_bytes = phase_array.astype(PHASE_ARRAY_DTYPE).tobytes()
        array_shape = phase_array.shape
        shape_bytes = struct.pack('!II', *array_shape)  # Send shape as 2 unsigned ints

        # Send the phase data (including array shape)
        client_socket.sendall(shape_bytes + array_bytes)

        # Send the measure tail
        measure_tail = measure_header.strip('BEG') + 'END'
        client_socket.sendall(measure_tail.encode())

        print(f"Done with: {measure_header}")

finally:
    client_socket.close()
    print("Connection closed.")
