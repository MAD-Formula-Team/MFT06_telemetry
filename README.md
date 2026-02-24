# Telemetry System for MFT06

MFT06 is the sixth iteration of the Formula Student car developed by the team. This repository contains the embedded firmware for a wireless telemetry system that reads data from the vehicle CAN bus and transmits it in real time to a base station using LoRa radio. It consists of two firmware targets, one for the transmitter installed in the car and one for the receiver at the base station, along with a PC-side visualization tool called RoboWin.

---

## Hardware

The system is built around two identical Heltec WiFi LoRa 32 V3 boards, one installed in the car and one at the base station. The choice of LoRa (Long Range) radio technology prioritizes communication range over raw bandwidth, which is the correct trade-off for a circuit environment where the car may be hundreds of meters away.

**Car-side (Transmitter)**
- Heltec WiFi LoRa 32 V3
- MCP2515 CAN bus controller, connected via SPI, reading data from the vehicle CAN network at 1 Mbps

**Base-side (Receiver)**
- Heltec WiFi LoRa 32 V3
- Connected via USB to a laptop running the RoboWin visualization software
- OLED display showing live link quality metrics

**Radio link**
- Frequency: 869.5 MHz (European ISM band)
- Spreading Factor: 7 (fastest LoRa setting, minimizes air time)
- Bandwidth: 125 kHz
- Coding Rate: 4/7
- TX Power: 22 dBm

---

## Project Development and Embedded Software

The firmware is written in C++ using the Arduino framework and is built with PlatformIO. The project contains two separate firmware targets that share the same source directory:

- `coche_tx` compiles the transmitter firmware (`TX.cpp`), excluding the receiver file
- `base_rx` compiles the receiver firmware (`RX.cpp`), excluding the transmitter file

This avoids maintaining two separate projects while keeping the builds clean.

**Transmitter logic (`TX.cpp`)**

Handles reading CAN bus messages and transmitting them over LoRa to the base station.

**Receiver logic (`RX.cpp`)**

Handles receiving LoRa packets and forwarding them as a CSV serial stream to the connected laptop, while displaying live link quality metrics on the OLED.

---

## How to Run

**Requirements**
- PlatformIO (CLI or IDE extension for VS Code / CLion)
- Two Heltec WiFi LoRa 32 V3 boards
- MCP2515 CAN controller wired to the transmitter board as defined in `TX.cpp`


---

## Features

- Wireless CAN bus telemetry over LoRa with a range suitable for circuit use
- Binary packet format minimizing air time and latency
- Drop-based transmission strategy ensuring data freshness over completeness
- Per-ID deduplication to reduce redundant transmissions of static signals
- Sequence numbering on every packet to allow packet loss quantification at the receiver
- Live link quality monitoring (RSSI, SNR, packet rate) on the receiver OLED
- Serial CSV output compatible with external visualization tools
- Two independent PlatformIO build environments from a single codebase

## How to flash the software
With the VSCode plugin, we choose the enviroment using the folder with the dot; the (`base_rx`) for the receiver and (`coche_tx`) for the transmitter. To flash the RX or TX file, we use the right arrow in the bar below. This will compile and upload via serial the file into the correspondig ESP32 (which must be connected via USB to the cumputer)

<img width="635" height="36" alt="image" src="https://github.com/user-attachments/assets/bb09bbeb-80e4-4b13-b716-a114afa78503" />

<img width="893" height="103" alt="image" src="https://github.com/user-attachments/assets/a4a485aa-77ab-4417-941e-76ddd3061670" />



---

## UI and Data Visualization

**OLED display (receiver board)**

The receiver board shows a live signal quality dashboard. It displays the total packets received, CRC error count, current RSSI in dBm with a visual progress bar, SNR, packets per second, and a qualitative signal strength label ranging from "EXCELENTE" to "MUY DEBIL". This gives the engineer at the base station an immediate visual indication of link health without needing a laptop.

**RoboWin - WIP**

RoboWin is the PC-side visualization tool that reads and plots in real time the data received from the base station. It is currently under active development.

Current features:

- Real time data visualization with dynamic multi-channel plots
- Automatic connection and reconnection to the receiver board via USB serial
- Data recency indicators through text color: green for data received in the last 2 seconds, orange for older data, grey for signals never received in the current session
- Raw CAN data messages and their correspondig values in a dedicated page.

Planned features:

- Data logging to CSV or equivalent format
- Plot screenshot export
- Interactive plots
- Sending custom CAN signals to the car
- Lap time visualization
- Web interface
---

## Known Limitations

LoRa is a low-bandwidth radio technology. The system is designed for range, not throughput. 
On a vehicle with a dense CAN network, the drop rate can be significant if many unique message IDs are active simultaneously. 
Engineers should be aware that the telemetry stream is not a complete log of all CAN traffic. For complete data capture, a local SD card logger or CAN logger on the vehicle should be used in parallel.

