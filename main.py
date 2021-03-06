#!/usr/bin/env python3

import configparser
from sys import exit, version_info
import threading
import time
from uuid import getnode
from os import path

from bacpypes import __version__ as bacpypes_version
from bacpypes.core import run as bacpypesrun
from bacpypes.primitivedata import Real, CharacterString, Unsigned, Boolean
from bacpypes.basetypes import EngineeringUnits
from bacpypes.object import AnalogInputObject
from bacpypes.app import BIPSimpleApplication
from bacpypes.service.device import LocalDeviceObject
from bacpypes.service.object import ReadWritePropertyMultipleServices

import dustmeter
import thermorasp
import pumpstation
METERS = {"dustmeters": dustmeter, "thermorasps": thermorasp, "pumpstations": pumpstation}

class DataThread(threading.Thread):
    def __init__(self, meters, objs):
        threading.Thread.__init__(self)
        threading.Thread.setName(self, "dataThread")
        self.meters = meters
        self.objs = objs
        self.flag_stop = False
    
    def run(self):
        while not self.flag_stop:
            time.sleep(1)
            for obj in self.objs:
                objname = str(obj._values["objectName"])
                for meter in self.meters:
                    if meter.name == objname:
                        obj._values["outOfService"] = Boolean(not meter.is_connected)
                        obj._values["presentValue"] = Real(meter.getPresentValue())
                        
    def stop(self):
        self.flag_stop = True

if __name__ == "__main__":
    if not path.exists("server.cfg"):
        print("Error: File server.cfg not found.")
        exit(1)
    
    cparser = configparser.ConfigParser()
    cparser.read("server.cfg")
    
    if not "server" in cparser:
        print("Invalid config: No server section")
        exit(1)
    
    required_keys = {"ip", "port", "objectname", "vendoridentifier",
        "location", "vendorname", "modelname", "description"}
    missing_keys = required_keys - set(cparser["server"].keys())
    if len(missing_keys) != 0:
        print("Missing config keys in server section: "
            + (" ".join(missing_keys)))
        exit(1)

    device_info = {
        "ip": cparser["server"]["ip"],
        "netmask": 24,
        "port": cparser["server"]["port"],
        "objectName": cparser["server"]["objectName"],
        "objectIdentifier": getnode() >> (48 - 22),
        "vendorIdentifier": cparser["server"]["vendorIdentifier"],
        "location": cparser["server"]["location"],
        "vendorName": cparser["server"]["vendorName"],
        "modelName": cparser["server"]["modelName"],
        "softwareVersion": "bacpypes_{}_python{}.{}.{}".format(bacpypes_version, version_info[0], version_info[1], version_info[2]),
        "description": cparser["server"]["description"]
    }
    
    this_device = LocalDeviceObject(
        objectName=device_info["objectName"],
        objectIdentifier=device_info["objectIdentifier"],
        vendorIdentifier=device_info["vendorIdentifier"]
    )
    
    this_device._values["location"] = CharacterString(device_info["location"])
    this_device._values["vendorName"] = CharacterString(device_info["vendorName"])
    this_device._values["modelName"] = CharacterString(device_info["modelName"])
    this_device._values["applicationSoftwareVersion"] = CharacterString(device_info["softwareVersion"])
    this_device._values["description"] = CharacterString(device_info["description"])
    
    this_addr = "{}/{}:{}".format(device_info["ip"], device_info["netmask"], device_info["port"])
    print("bacnet server will listen at {}".format(this_addr))
    this_application = BIPSimpleApplication(this_device, this_addr)
    this_application.add_capability(ReadWritePropertyMultipleServices)
    this_device.protocolServicesSupported = this_application.get_services_supported().value
    
    meters_active = []
    ai_objs = []
    idx = 1
    print("Initializing meters...")
    for key, metermodule in METERS.items():
        if not key in cparser["server"]:
            print("No key '{}' in config server section. Skipping".format(key))
            continue
        metersections = cparser["server"][key].split()
        missing_metersections = set(metersections) - set(cparser.keys())
        if len(missing_metersections) != 0:
            print("Missing config sections for meters: "
                + "".join(missing_metersections))
            exit(1)
            
        for metersection in metersections:
            info = cparser[metersection]
            
            ms = metermodule.getMeters(info)
            print("Got {} meter(s) from {}".format(len(ms), metersection))
            meters_active.extend(ms)
            
            for m in ms:
                m.name = "{}_{}".format(metersection, m.name)
                ai_obj = AnalogInputObject(objectIdentifier=("analogInput", idx), objectName=m.name)
                if "description" in info:
                    ai_obj._values["description"] = CharacterString(info["description"])
                if "deviceType" in info:
                    ai_obj._values["deviceType"] = CharacterString(info["deviceType"])
                ai_obj._values["units"] = EngineeringUnits("noUnits")
                if "updateInterval" in info:
                    try:
                        updateInterval = int(info["updateInterval"])
                        if updateInterval < 0:
                            raise ValueError("Invalid negative value :" + info["updateInterval"])
                    except ValueError as e:
                        print("Value of updateInterval in section {}: {}".format(metersection, e))
                        exit(1)
                    ai_obj._values["updateInterval"] = Unsigned(updateInterval)
                if "resolution" in info:
                    try:
                        resolution = float(info["resolution"])
                    except ValueError as e:
                        print("Value of updateInterval in section {}: {}".format(metersection, e))
                        exit(1)
                    ai_obj._values["resolution"] = Real(resolution)
                this_application.add_object(ai_obj)
                ai_objs.append(ai_obj)
                
                idx += 1
            
    for m in meters_active:
        m.start()
    
    datathread = DataThread(meters_active, ai_objs)
    datathread.start()
    
    bacpypesrun()
    
    datathread.stop()
    datathread.join()
    
    for m in meters_active:
        m.stop()
        m.join()
