# Cisco Phone Auto Configuration & TFTP Server

A lightweight automation tool for configuring Cisco IP Phones using TFTP.

## Overview

This project automates the configuration process of Cisco IP Phones.

The application includes a built-in TFTP server and automatically generates the required phone configuration files based on a provided sample configuration and configuration data.

Instead of manually creating individual configuration files for each phone, the application scans the configuration directory, processes the available data, generates the required files, and makes them available through TFTP.

## Features

* Built-in TFTP Server
* Automatic Cisco IP Phone configuration file generation
* Sample configuration based workflow
* Automatic scanning of configuration files
* Support for multiple Cisco IP Phones
* Reduces manual configuration time
* Simple deployment and usage

## How It Works

1. Provide the sample Cisco phone configuration file.
2. Place the phone/configuration data in the configuration folder.
3. Start the application.
4. The application scans the configuration files.
5. Required Cisco phone configuration files are generated automatically.
6. The built-in TFTP server provides the files to the Cisco IP Phone.
7. The phone downloads its configuration and applies the settings.

## Requirements

* Windows / Linux
* Python 3.x
* Cisco IP Phone
* Network connectivity between the phone and the server

## Usage

```bash
python main.py
```

Then configure the Cisco IP Phone TFTP server address to point to the machine running this application.

## Configuration

The project uses a sample configuration file as a template.

Modify the sample configuration according to your environment and provide the required configuration files in the designated configuration directory.

The application handles the generation of the final phone configuration files automatically.

## Example

```text
sample/
    sample-config.xml

config/
    1001/
    1002/
    1003/
```

The application processes the configuration data and generates the required files for each phone.

## Use Cases

This tool is useful for:

* Cisco IP Phone deployments
* VoIP lab environments
* Automated phone provisioning
* Bulk phone configuration
* Cisco voice/network administrators
* Testing and development environments

## Disclaimer

This project is an independent automation tool and is not affiliated with or endorsed by Cisco Systems, Inc.

## License

See the `LICENSE` file for license information.
