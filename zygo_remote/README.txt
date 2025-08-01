This directory contains code to run to remotely acquire Zygo data.

The remote computer triggers Zygo acquisitions, which are then processed on the Zygo computer and the phase data is sent back to the remote computer.

Files are:
- ZygoSocket_ZygoSide:
  - Script to be run on the Zygo computer. 
  - This acts as a client that acquires data when requested and then passes it back to the other computer.
  - This script should be run from within the "MX" GUI's scripting section

- ZygoSocket_DMSide_NoDMUse:
  - Script to be run on the remote computer. 
  - This acts as the server which triggers acquisition of the Zygo data remotely.
  - This particular version is an example which is designed with DM use in mind, but which doesn't actually connect to the DM.
    Thus, this can be used to test the communication.

- ZygoSocket_DMSide:
  - This is more fleshed-out version of the above script.
  - This version actually connects to the DM and sets it flat.
  - This version can be built-upon to do DM-Zygo tests

- ZygoImage_DMResampler:
  - Code showing how we can rotate and downsample a Zygo image to match DM actuator format

- *.npy Files:
  - These are just 2 sample files I used for testing out the Image_DMResampler