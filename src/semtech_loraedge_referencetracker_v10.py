""" Lambda Function for LoRa Edge(TM) Tracker Reference Design 

This function is designed to take the Modem-E inside the device
and use the LoRa Cloud(TM) API to do the following:

# Forward Port 199 data to cloud solver
# Process returns from cloud solver
# If cloud solver requires a downlink, send provided downlink
# If cloud solver returns a scan, send returned scan to cloud solver (gnss/wifi) 

.. note:: This lambda requires permissions for: 
    logs:CreateLogGroup, logs:CreateLogStream, logs:PutLogEvents, and 
    iotwireless:SendDataToWirelessDevice
    Also, remember to add CS_KEY from Lambda environment

:param event: The data from a LoRaWAN device
:type event: JSON
:param context: The AWS IoT Core context
:type context: context format
:returns: a dictionary with the status code and body
:rtype: dictionary


Copyright 2021 @Semtech

Permission is hereby granted, free of charge, to any person obtaining a copy of 
this software and associated documentation files (the "Software"), to deal in 
the Software without restriction, including without limitation the rights to 
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies 
of the Software, and to permit persons to whom the Software is furnished to do 
so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all 
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR 
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, 
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE 
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER 
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, 
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE 
SOFTWARE.


"""

import json
import http.client
from base64 import b64decode,b64encode
import struct
from datetime import datetime,timezone
from itertools import islice
import os
import boto3


# Access point for the AWS IoT Core Wireless (LoRaWAN)
client = boto3.client('iotwireless')

# Build API from environment variables
# API_URI nominally 'das.loracloud.com'
API_URI=os.environ['ApiUrl']
# Use the send method for interaction with API
DEV_API='/api/v1/uplink/send'
ADD_DEV_URI=API_URI+DEV_API
# Secrets pulled from environment variable
CS_KEY=os.environ['CS_KEY']
myHeaders= {'Authorization': CS_KEY, 'Content-Type': 'application/json'}
# Timestamp converter
iso2ts   = lambda iso: datetime.strptime(iso, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()

# Iterator function for Tag-Length-Value (TLV) formats
TAG_FIELD_LENGTH = 2
LENGTH_FIELD_LENGTH = 2
# Parse TLV fields, 
def tlv_parser(tlv_string):
    it = iter(tlv_string)
    while tag := "".join(islice(it, TAG_FIELD_LENGTH)):
        length = int("".join(islice(it, LENGTH_FIELD_LENGTH)),16)
        value = "".join(islice(it, length*2))
        yield (tag, length, value)
    
# Send a downlink message via LoRaWAN
def send_downlink(id: str, transmitMode: int, payload: str, port: int)->dict:
    downResp = client.send_data_to_wireless_device(
                        Id=id, 
                        TransmitMode=transmitMode, 
                        PayloadData=payload, 
                        WirelessMetadata={
                            'LoRaWAN': {
                                'FPort': port
                            },
                        }
                )        
    return downResp

# Send an HTTPS request
def send_https(uri: str, method: str, api: str, myData: str, myHeaders: str)->str:
    conn = http.client.HTTPSConnection(uri)    
    conn.request(method, api, myData, myHeaders)
    response = conn.getresponse()
    retVal = response.read().decode()
    conn.close()
    
    return (retVal)
    
# Parse the full sensor packet    
def parse_sensors_full(data)->dict:
    version = int(data[0:1], 16)
    move_history = int(data[1:2], 16)
    temperature = int(data[2:6], 16) / 100
    acc_charge = int(data[6:10], 16)
    voltage = int(data[10:14], 16) / 1000

    return {
        "type": "sensor_full",
        "version": version,
        "move_history": move_history,
        "temperature_C": temperature,
        "accumulated_charge": acc_charge,
        "battLevel" : 100*(2400-acc_charge)/2400,        
        "voltage": voltage,
    }

# Parse the short sensor packet   
def parse_sensors_basic(data)->dict:
    version = int(data[0:1], 16)
    move_history = int(data[1:2], 16)

    return {
        "type": "sensor_basic",
        "version": version,
        "move_history": move_history,
    }
   
# Lambda processing
def lambda_handler(event, context):
    data = {}
    lw = event['WirelessMetadata']['LoRaWAN']
    DevEui = lw['DevEui']
    deveui = '-'.join(DevEui[i:i+2] for i in range(0,len(DevEui),2))
    data['deveui'] = deveui.upper()
    DEVEUI = deveui.upper()
    deveui = DEVEUI.lower()
    data['fcnt'] = lw['FCnt']
    data['port'] = lw['FPort']
    data['dr'] = lw['DataRate']
    data['freq'] = lw['Frequency']
    data['timestamp'] = lw['Timestamp']
    data['id'] = event['WirelessDeviceId']
    data['payload']  =  b64decode(event['PayloadData']).hex()
    print('event:{}'.format(event))
    retVal = {}
    if (int(data.get('port',0)) != 199) :
        print('Packet not on Port 199, received: {}'.format(data['port']))
        retVal['error']         = 'Port number 199 expected, receieved: {}'.format(data['port'])
        retVal['statusCode']    = 400
        retVal['msgtype']       = "Error"
        retVal['DevEUI']        = DEVEUI
        retVal['timestamp']     = data['timestamp']            
        return retVal
    else:
        # Received port 199, forward the payload to CS/cloud solver

        # First check if the FCNT is less than 2
        # If yes, tell the CS the device has re-joined
        # Note the selection of "<2" to ensure we get a couple of opportunities 
        # on restart (the first couple of messages aren't from a stream)
        if (data['fcnt']<2):
            ## Send joining
            print("Send a joining message")
            joinResponse = send_https(API_URI, 'POST', DEV_API, 
                            json.dumps({deveui:{"msgtype":"joining"}}),
                            myHeaders)
            print('joinResponse: {}'.format(joinResponse))
            
        # Sending message to CS    
        dmsmsg = json.dumps({
        deveui: {
            "fcnt":       data['fcnt'],
            "port":       data['port'],
            "payload":    data['payload'],
            "dr":         int(data.get('dr',0)),
            "freq":       int(data.get('freq', 868100000)),
            "timestamp":  int(iso2ts(data['timestamp']))
        }
        })
        print('dmsmsg:{}'.format(dmsmsg))
        outerResponse = send_https(API_URI, 'POST', DEV_API, dmsmsg, myHeaders)
        print('type:{}, outerResponse:{}'.format(type(outerResponse),outerResponse))
        td = json.loads(outerResponse)
        print('CS resp:{}'.format(td))
        if ('result' in td):
            # Deliver downlink to end device (if present)
            if ('dnlink' in td['result'][deveui]['result'].keys()):
                downlink = td['result'][deveui]['result']['dnlink']
                if downlink is not None:
                    print('Sending a downlink message: {}'.format(downlink))
                    port = 150 if downlink['port'] == 0 else 199
                    payload = b64encode(bytes.fromhex(downlink['payload'])).decode('ascii')
                    downResponse = send_downlink(data['id'], 0, payload,port)
                    print('downlink response:{}'.format(downResponse))    
            # Parse message for interesting content, wifi scan, gnss scan, etc.
            for x in td['result'][deveui]['result'].items():
                k,v = x
                # Note that ALL data uploads from the 
                #   LoRa Edge(TM) Tracker Reference Design are sent as 
                #   stream_records (ROSE). Therefore all data must first be 
                #   processed for stream records; then processed again once the 
                #   original content is extracted
                if ((k=='stream_records') and (isinstance(v,list))):
                    for i in range(len(v)):
                        if (isinstance(v[i],list)):
                            pl = v[i][1]
                            for tlv in tlv_parser(pl):
                                tag,length,val = tlv        
                                print('received tag:{},length:{},value:{}'.format(tag,length,val))
                                if (tag.upper() == '0E'): # type 0x0E == wifi scan
                                    ts = int(val[2:10], 16)
                                    ptimestamp = int(iso2ts(data['timestamp']))
                                    print('ts={}, packet_timestamp={}'.format(ts,ptimestamp))
                                    timestamp = ptimestamp if ts == 0 else ts                         
                                    payload = '01'+val[10:]                            
                                    # send the wifi scan
                                    # take the RSSI+MAC scan info and
                                    # preprend "01" to indicate scan U-WIFILOC-MACRSSI
                                    MSG_WIFI = {
                                        "msgtype":"wifi",
                                        "payload": payload,
                                        "timestamp": timestamp,
                                        }
                                    MSG_SEND = {}
                                    MSG_SEND[deveui] = MSG_WIFI
                                    myData= json.dumps(MSG_SEND)
                                    print('Sending a wifi message to CS: {} (wifi msg len={})'.format(myData, length))
                                    ir = send_https(API_URI, 'POST', DEV_API, myData, myHeaders)                                
                                    if ('result' in ir):
                                        print('wifi location result:{}'.format(ir))
                                        r = json.loads(ir)
                                        wifi_response = r['result'][deveui]['result']['position_solution']
                                        if wifi_response is not None:
                                            # Valid WiFi solution
                                            if ('gdop' in wifi_response):
                                                gdop = wifi_response['llh']['gdop']
                                            else:
                                                gdop = -1
                                            loc = {
                                                "msgtype"  : "wifi",
                                                "DevEUI"   : DEVEUI,    
                                                'latitude' : wifi_response['llh'][0],
                                                'longitude': wifi_response['llh'][1],
                                                'altitude' : wifi_response['llh'][2],
                                                'acc'      : wifi_response['accuracy'],
                                                'gdop'     : gdop,
                                                'timestamp': wifi_response['timestamp'],
                                            }                                    
                                            retVal['wifi_location'] = loc
                                            retVal['statusCode'] = 200
                                        else: 
                                            print('wifi location/None: {}'.format(ir))
                                    else:
                                        print('wifi location error: {}'.format(ir))
                                elif (tag.upper() == '08'): # type 8 == wifi scan
                                    # send the wifi scan
                                    # take the RSSI+MAC scan info and
                                    # preprend "01" to indicate scan U-WIFILOC-MACRSSI
                                    MSG_WIFI = {
                                        "msgtype":"wifi",
#                                        "payload": '01'+pl[4:],
                                        "payload": '01'+val,
                                        "timestamp": iso2ts(data['timestamp']),
                                        }
                                    MSG_SEND = {}
                                    MSG_SEND[deveui] = MSG_WIFI
                                    myData= json.dumps(MSG_SEND)
                                    print('Sending a wifi message to CS:{}'.format(myData))
                                    ir = send_https(API_URI, 'POST', DEV_API, myData, myHeaders)     
                                    if ('result' in ir):
                                        print('wifi location result:{}'.format(ir))
                                        r = json.loads(ir)
                                        wifi_response = r['result'][deveui]['result']['position_solution']
                                        if wifi_response is not None:
                                            # Valid WiFi return 
                                            if ('gdop' in wifi_response):
                                                gdop = wifi_response['llh']['gdop']
                                            else:
                                                gdop = -1
                                            loc = {
                                                "msgtype"  : "wifi",
                                                "DevEUI"   : DEVEUI,    
                                                'latitude' : wifi_response['llh'][0],
                                                'longitude': wifi_response['llh'][1],
                                                'altitude' : wifi_response['llh'][2],
                                                'acc'      : wifi_response['accuracy'],
                                                'gdop'     : gdop,
                                                'timestamp': wifi_response['timestamp'],
                                            }                                    
                                            retVal['wifi_location'] = loc
                                            retVal['statusCode'] = 200
                                        else: 
                                            print('wifi location/None: {}'.format(ir))
                                    else:
                                        print('wifi location error: {}'.format(r))
    
                                elif (tag.upper() == '09'): # type 9 == accelerometer data
                                    retAcc = {"msgtype" : "accelerometer",
                                            "DevEUI"    : DEVEUI,
                                    }                                
                                    values = struct.unpack(">Bhhhh", bytes.fromhex(val))
                                    accVals = {}
                                    motArr = []
                                    for i in range(8):
                                        if (values[0] & (1<<i)):
                                            motArr.append('Motion')
                                        else:
                                            motArr.append('Still')
                                    # Last 8 update periods motion
                                    accVals['motArr'] = motArr
                                    # accel in milli-g
                                    accVals['xAcc_mg'] = values[1]/1000.0
                                    accVals['yAcc_mg'] = values[2]/1000.0
                                    accVals['zAcc_mg'] = values[3]/1000.0
                                    accVals['Temp_C'] = values[4]/100
                                    print('acceleration :{}'.format(accVals))
                                    retAcc["accVals"] = accVals
                                    retVal['accelerometer'] = retAcc
                                    retVal['statusCode'] = 200
                                elif (tag.upper() == '0A'):   # Parse charge
                                    modemCharge = struct.unpack(">L", bytes.fromhex(val))[0]
                                    retAcc["modemCharge"] = modemCharge
                                    retAcc['battLevel'] = 100*(2400-modemCharge)/2400
                                    retVal['statusCode'] = 200
                                    print('modem charge: {}  mAh'.format(modemCharge))
                                elif (tag.upper() == '0B'):  # Parse voltage
                                    modemVolt = float(struct.unpack(">H", bytes.fromhex(val))[0])/1000.0
                                    print('modem voltage: {}  V'.format(modemVolt))
                                    retAcc['modemVolt'] = modemVolt
                                    retVal['statusCode'] = 200
                                elif (tag.upper() == '0D'):  # Parse sensors
                                    if (length==1):
                                        retVal['sensors'] = parse_sensors_basic(val)
                                    elif (length==7):
                                        retVal['sensors'] = parse_sensors_full(val)
                                    print('sensor:{}'.format(retVal['sensors']))
                                    retVal['statusCode'] = 200                                    
                                elif ((tag.upper() == '05') or (tag.upper() == '06') or 
                                        (tag.upper() == '07')): # type 5, 6 or 7 == GNSS NAV from PCB(6) or Patch(7) antenna
                                    print('Received GNSS NAV msg from antenna type: {}'.format(tag))
                                    MSG_GNSS = {
                                        "msgtype":"gnss",
                                        "payload": val,
                                        "timestamp": iso2ts(data['timestamp']),
                                        }
                                    MSG_SEND = {}
                                    MSG_SEND[deveui] = MSG_GNSS
                                    myData= json.dumps(MSG_SEND)
                                    print('Sending a gnss message to CS:{}'.format(myData))
                                    ir = send_https(API_URI, 'POST', DEV_API, myData, myHeaders)                                  
                                    if ('result' in ir):
                                        print('gnss location result:{}'.format(ir))
                                        # Deliver downlink if present
                                        r = json.loads(ir)
                                        if ('dnlink' in r['result'][deveui]['result'].keys()):
                                            downlink = r['result'][deveui]['result']['dnlink']
                                            if downlink is not None:
                                                print('Sending a downlink message: {}'.format(downlink))
                                                port = 150 if downlink['port'] == 0 else 199
                                                payload = b64encode(bytes.fromhex(downlink['payload'])).decode('ascii')
                                                downResponse = send_downlink(data['id'], 0, payload, port)
                                                print('downlink response:{}'.format(downResponse))
                                        gnss_response = r['result'][deveui]['result']['position_solution']
                                        if gnss_response is not None:
                                            # Valid GNSS response
                                            loc = {
                                                "msgtype"  : "gnss",
                                                "soltype"  : val,
                                                "DevEUI"   : DEVEUI,    
                                                'latitude' : gnss_response['llh'][0],
                                                'longitude': gnss_response['llh'][1],
                                                'altitude' : gnss_response['llh'][2],
                                                'acc'      : gnss_response['accuracy'],
                                                'gdop'     : gnss_response['gdop'],
                                                'timestamp': gnss_response['timestamp'],
                                                #'capture_time_utc' : gnss_response['capture_time_utc'],
                                                #'capture_time_gps' : gnss_response['capture_time_gps'],                                        
                                            }           
                                            # Handle the case where there are more than one GNSS type in a message
                                            gnss_key = 'gnss_location'   
                                            if ('gnss_location' in retVal):
                                                gnss_key = 'gnss_location_'+tag.upper()
                                            retVal[gnss_key] = loc
                                            retVal['statusCode'] = 200
                                        else:
                                            print('gnss location error/None: {}'.format(r))
                                    else:
                                        print('gnss location error: {}'.format(ir))
            # This is the return for valid data decode
            retVal['statusCode']    = 200
            retVal['msgtype']       = 'Reference'
            retVal['DevEUI']        = DEVEUI
            retVal['timestamp']     = data['timestamp']   
            return retVal
            
        # This is the return in case the     
        retVal['error']         = 'Error, Bad CS response: {}'.format(td)
        retVal['statusCode']    = 404
        retVal['msgtype']       = 'Error'
        retVal['DevEUI']        = DEVEUI
        retVal['timestamp']     = data['timestamp']       
        return retVal
