# Automotive Image Builder – targets

When building images, a target is specified. This chooses the target
hardware board, and affects things like what kernel is used and what
specific configuration options are needed to boot on that hardware.

This document gives some highlevel descriptions of the available
targets.

## Virtual machine targets

These are useful during development, and "qemu" is actually the
default target if none is specified. The automotive-image-runner (air)
tool that ships with automotive-image-builder is a good way to run
these images.

 * qemu - targets standard EFI based virtual machine
 * abootqemu - targets non-accelerated virtual machine using android
   boot (use --aboot option in air)
 * qbootqemukvm - targets kvm-accelerated virtual machine using
   android boot (use --aboot option in air)

## Hardware boards

These are actual hardware boards, mostly automotive specific (although
some are generic like the raspberry pi).

### Generic boards

These are targets that work for many types of board with a single
shared build. These targets should be preferred over board specific
targets. Sometimes boards need some hw specific setup be used with the
generic image, such as firmware installation or configuration.

 * ebbr - Generic target for systems compliant with the EBBR Specification (for example Renesas RCar S4 or NXP S32G)

### Qualcomm boards

 * ride4_sa8775p_sx - Qualcomm RIDESX4 board,  Rev 1, 2, & 2.5, with SCMI enabled firmware.
 * ride4_sa8775p_sx_r3 - Qualcomm RIDESX4 board,  Rev 3, with SCMI enabled firmware.
 * ride4_sa8650p_sx_r3 - Qualcomm, SA8650P SX Rev3 SoC

### TI boards

 * am62sk - TI SK-AM62 Evaluation Board (NOTE: prefer ebbr target)
 * am69sk - TI SK-AM69 Evaluation Board (NOTE: prefer ebbr target)
 * beagleplay - TI BeaglePlay Board (NOTE: prefer ebbr target)
 * j784s4evm - TI J784S4XEVM Evaluation Board (NOTE: prefer ebbr target)
 * tda4vm_sk - TI SK-TDA4VM Evaluation Board (NOTE: prefer ebbr target)

### Other boards

 * rpi4 - Raspberry PI 4 (needs recent EFI supporting firmware)
 * ccimx93dvk - Digi Connectcore 93 board
 * imx8qxp_mek - Multisensory Enablement Kit i.MX 8QuadXPlus MEK CPU Board

## Cloud targets

These allow creating images that easily run in the cloud. Useful for development and testing.

 * aws - Targets images running in the AWS cloud
 * azure - Targets images running in the azure cloud

## Special targets

 * pc - Intended to run on a normal PC or laptop, so uses the regular
   centos kernel instead of the automotive kernel to ensure
   compatibility and support of typical PC hardware.
