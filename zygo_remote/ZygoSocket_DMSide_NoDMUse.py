import socket
import time
import numpy as np
import struct
import atexit
import matplotlib.pyplot as plt

plt.ion()

import sys
sys.path.append('/home/nfiudev/dev/dechever/DMCharac/Code2024')
from DM_Sight import DM as dmlib

# === CONFIGURATION ===
HOST = '0.0.0.0'  # Accept connections on all interfaces
PORT = 5000
TIMEOUT_SEC = 300  # 5 minutes
SLEEP_INTERVAL = 0.1

# Define datatype for the elements of the Zygo phase array
    # Must match analogous value in Zygo_Side
PHASE_ARRAY_DTYPE = np.float64

# Zygo image rotation - used to clock the Zygo image to match the DM axes 
    # Or whatever coordinate system axes you want to work in...
ZYGO_IM_CLOCKING = 50  # [deg]

# === DM PREP CODE GOES HERE ===
# e.g., connect to DM, flatten, load desired patterns, etc.
#    This is anything you need to do before the main loop starts

## Connect to DM
#DM = dmlib()
## Guarantee that we cleanup the DM connection correctly
#def close_dm_conn():
#    DM.zeroAll()
#    DM.close()
#atexit.register(close_dm_conn)
#
## Set flatmap
#flat = np.load(DM.flatdir+'SightDM_2024Oct7_Mean400.npy')
#DM.setSurf(flat)

# === SOCKET SETUP ===
print(f"Waiting for Zygo to connect on port {PORT}")
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server_socket.bind((HOST, PORT))
server_socket.listen(1)

server_socket.settimeout(TIMEOUT_SEC)
try:
    conn, addr = server_socket.accept()
except socket.timeout:
    raise RuntimeError("Zygo did not connect in time")
print(f"Connected to Zygo at {addr}")

conn.settimeout(SLEEP_INTERVAL)

# === UTILITY FUNCTION - READ ZYGO IMAGE ===

def read_single_zygo_image(counter):
    # === Cue Zygo measure ===
    measure_header = f'SAMP{counter:05d}BEG'
    measure_tail = f'SAMP{counter:05d}END'

    conn.sendall(b'Measure')
    time.sleep(0.5)
    conn.sendall(measure_header.encode())
    print(f"Waiting for Zygo to measure and respond with header: {measure_header}")

    # === Wait for Zygo to echo the header ===
    header_confirmed = False
    buffer = b""
    for j in range(int(TIMEOUT_SEC / SLEEP_INTERVAL)):
        if j % 50 == 0:
            print(f"   Waiting for measure header... itr {j}")
        try:
            chunk = conn.recv(1024)
            buffer += chunk
            if measure_header.encode() in buffer:
                header_confirmed = True
                break
        except socket.timeout:
            continue

    if not header_confirmed:
        raise RuntimeError("Zygo computer did not respond or responded incorrectly")
    
    print("Zygo computer responded with correct header. Reading shape...")

    # === Read shape info (2 unsigned ints) ===
    #Clear anything in the buffer before the measure_header
    buffer_excess = buffer.find(measure_header.encode())
    buffer = buffer[buffer_excess:]

    # Make sure we've read enough to have the array_shape in the buffer
    while len(buffer) < len(measure_header) + 8:
        buffer += conn.recv(1024)

    # Extract the array shape
    header_offset = len(measure_header)
    array_start = header_offset + 8
    shape_data = buffer[header_offset:array_start]
    rows, cols = struct.unpack('!II', shape_data)

    print(f"Expecting array of shape ({rows}, {cols})")

    # === Read binary array ===
    expected_bytes = rows * cols * np.dtype(PHASE_ARRAY_DTYPE).itemsize
    remaining = expected_bytes + array_start - len(buffer) 

    array_confirmed = False
    for j in range(int(TIMEOUT_SEC / SLEEP_INTERVAL)):
        if remaining <= 0:
            array_confirmed = True
            break

        if j % 50 == 0:
            print(f"   Waiting for full array to arrive... itr {j}")
        
        try:
            chunk = conn.recv(min(4096, remaining))
            buffer += chunk
            remaining -= len(chunk)
        except socket.timeout:
            continue
    
    if not array_confirmed:
        raise RuntimeError("Failed to receive full phase array")

    array_data = buffer[array_start:array_start+expected_bytes]
    phase_array = np.frombuffer(array_data, dtype=PHASE_ARRAY_DTYPE).reshape((rows, cols))

    print("Phase array received")

    # === Wait for tail ===
    # This is just to make sure we truly receieved all the data
    
    tail_confirmed = False
    for j in range(int(TIMEOUT_SEC / SLEEP_INTERVAL)):
        if measure_tail.encode() in buffer:
            tail_confirmed = True
            break

        if j % 50 == 0:
            print(f"   Waiting for measure tail to arrive... itr {j}")
        
        try:
            chunk = conn.recv(1024)
            buffer += chunk
        except socket.timeout:
            continue

    if not tail_confirmed:
        raise RuntimeError("Failed to receive measure tail")

    print(f"Full data packet received")

    raw_comms_dict = {  "buffer":buffer, 
                        "header_offset": header_offset, 
                        "measure_header": measure_header, 
                        "measure_tail": measure_tail, 
                        "array_start": array_start,
                        "rows": rows,
                        "cols": cols }

    return phase_array, raw_comms_dict

# === MAIN LOOP ===
measure_counter = 0
#new_surf = DM.getSurf().copy()
try:
    while True:
        print(f"--- Start of iteration #{measure_counter} ---")
        measure_counter += 1

        # === Set DM surface ===
        # This can be whatever surface you want to apply
        
        # In this case, I'm applying a surface computed at the end of this loop
        # But you could also, for example, just apply a Zernike for the Zygo to measure
        #DM.setSurf(new_surf)

        input("Press any key to proceed...")

        # Give a moment for the DM surface to settle
        time.sleep(0.5)

        # === Read a Zygo image ===
        phase_array, raw_comms_dict = read_single_zygo_image(measure_counter)

        # === Use the array for whatever you want ===
        # Here is where you process the phase however you want
        # Eg. save the array, compute some correction, etc.
        # Ex: If you applied a Zernike, you could save the array for later processing

        # For testing purposes:
        plt.figure()
        plt.imshow(phase_array)

        buffer = raw_comms_dict["buffer"]
        header_offset = raw_comms_dict["header_offset"]
        measure_tail = raw_comms_dict["measure_tail"]
        plt.title(buffer[:header_offset].decode() + '\n' + buffer[buffer.find(measure_tail.encode()):buffer.find(measure_tail.encode())+len(measure_tail)+1].decode())

        #-- In this case, I want to "close the loop" on the Zygo image so...

        # Account for "dropped"/"missing" pixels in the Zygo image (mask them using np.nan maybe)

        # Clock the Zygo image to match the DM orientation

        # Downsample and crop the Zygo image to match the DM shape and size

        # Compute new DM shape 
            # This will be:
            # new_surf = phase_array * prop_gain * DM_NM_to_BMCUnit_conversion
            # new_surf += DM.getSurf() * DM.Mask

        # Optional: for tracking purposes, print the RMS WFE of this iteration
            # NOTE: make sure to account for the WFE Mask here!!
        print(f"RMS WFE on this iteration: {np.std(phase_array)}")


        print(f"End of iteration #{measure_counter}")
except KeyboardInterrupt:
    print("Keyboard Interrupt detected, killing loop...")

finally:
    # === Tell Zygo to stop ===
    try:
        conn.sendall(b'Stop')
        print("Stop sent")
    except e:
        print("Failed to send 'Stop' to Zygo computer")
        print(f"Error: {e}")

    # === Close connection ===
    conn.close()
    server_socket.close()
    print("Connection closed.")

#TODO: Once done with all iterations, save the final DM Map!!