#!/usr/bin/env python2

import threading
import socket
from time import sleep, time
from datetime import datetime
import re

import submeter

class ThermoRaspMeter(submeter.SubMeter):
    def __init__(self, name, thermorasp):
        submeter.SubMeter.__init__(self, name, thermorasp)

class TermoRasp(threading.Thread):
    defaultProps = {
        "name": "ThermoRasp",
        "host": "localhost",
        "port": 50007,
    }
    
    SLEEP_TIME = 1 #seconds to sleep after refresh
    MAX_REFRESH_TIME = 600 #seconds after which the sensors will be
                        #deemed disconnected if there was no timestamp change
    SOCKET_TIMEOUT = 5 #seconds to wait for socket
    
    def __init__(self, **kwargs):
        threading.Thread.__init__(self)
        for attr, value in TermoRasp.defaultProps.items():
            if attr not in kwargs:
                kwargs[attr] = value        
        self.name = kwargs["name"]
        self.host = kwargs["host"]
        self._stop_event = threading.Event()
        self.meters = {}
        
        try:
            self.port = int(kwargs["port"])
        except ValueError:
            print("Invalid port " + kwargs["port"])
            return

        #print("Initiating ThermoRasp at {}:{}".format(self.host, self.port))
        r = self.getReadings()
        if not r:
            print("Failed to connect to ThermoRasp at {}:{}".format(self.host, self.port))
            return
        lines = r.split("\n")
        fields = lines[0].split()
        meter_names = fields[2:]
        
        if len(lines) < 2:
            print("Invalid reply from ThermoRasp at {}:{}".format(self.host, self.port))
            return
        self._ts_offset = time() - self._parseTimestamp(lines[1])
        
        for name in meter_names:
            self.meters[name] = ThermoRaspMeter(name, self)
        
    def run(self):
        while not self._stop_event.is_set():
            #print("Refreshing ThermoRasp values")
            r = self.getReadings()
            if not r:
                print("No reply from ThermoRasp at {}:{}".format(self.host, self.port))
                self._setAllIsConnStatus(False)
                sleep(self.SLEEP_TIME)
                continue
            lines = r.split("\n")
            if len(lines) < 2:
                print("Invalid reply from ThermoRasp at {}:{}".format(self.host, self.port))
                self._setAllIsConnStatus(False)
                sleep(self.SLEEP_TIME)
                continue
            fields = lines[0].split()
            meter_names = fields[2:]
            
            readings = lines[1].split(" ")[2:]
            for i, name in enumerate(meter_names):
                try:
                    reading = float(readings[i])
                except ValueError:
                    self.meters[name].is_connected = False
                    #print("Invalid or empty value for {} of ThermoRasp at {}:{}".format(name, self.host, self.port))
                    continue
                self.meters[name].present_value = reading
                self.meters[name].is_connected = True
                
            if abs(time() - self._parseTimestamp(lines[1]) - self._ts_offset) > self.MAX_REFRESH_TIME:
                self._setAllIsConnStatus(False)
                
            sleep(self.SLEEP_TIME)
                
    def stop(self):
        self._stop_event.set()
        
    def getReadings(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.SOCKET_TIMEOUT)
        if s.connect_ex((self.host, self.port)) != 0:
            return None
        data = b""
        new_data_len = 1
        while new_data_len != 0:
            new_data = s.recv(64)
            new_data_len = len(new_data)
            data += new_data
        s.close()
        return data.decode("utf-8")
        
    def _parseTimestamp(self, date_str):
        if re.match("\\d+-\\d+-\\d+T\\d+:\\d+:\\d+\\.\\d+", date_str):
            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%f").timestamp()
        elif re.match("\\d+-\\d+-\\d+T\\d+:\\d+:\\d+", date_str):
            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S").timestamp()
        else:
            return 0
        
    def _setAllIsConnStatus(self, status):
        for name, meter in self.meters.items():
            meter.is_connected = status

def getMeters(config):
    thermorasp = TermoRasp(**config)
    return list(thermorasp.meters.values())
    
if __name__ == "__main__":
    print(getMeters({"host": "fhlthermorasp", "port": 50007}))
