# Serverless Framework with Python

---

Example project using the [Serverless Framework](https://serverless.com), 
Python, AWS Lambda and AWS IoT Core Wireless (LoRaWAN) to interface between 
the LoRa Edge(TM) Tracker Reference Design and a cloud-based geolocation solver. 
This code utilizes the API will and if present it convert the ROSE-encoded stream into data 
sources or will store the stream to the data sources. These data sources include 
WiFi and GNSS scans which can be passed 
back to cloud server for position computation. While this example is developed 
for AWS Lambda using AWS IoT Core Wireless functions, it could be simply 
adapted to other platforms or environments as required.

---

## Deployment

### Secrets

Secrets are injected into your functions using environment variables. By 
defining variables in the provider section of the `serverless.yml` you add 
them to the environment of the deployed function. From there, you can reference 
them in your functions as well.

A specific variable that will be required is the token used to access cloud solver. 
```yml
provider:
  environment:
    DAS_KEY: ${env:DAS_KEY}
```
to your `serverless.yml`, and then you can add `DAS_KEY` to your environment 
variables to be deployed with your function.

### Setting Up AWS

*. Create AWS credentials including the following IAM policies: `AWSLambdaFullAccess`, `AmazonAPIGatewayAdministrator`, `AWSCloudFormationFullAccess`, and `iotwireless:SendDataToWirelessDevice`. For logging: `logs:CreateLogGroup`, `logs:CreateLogStream`, and `logs:PutLogEvents` 

## Solver Options

The cloud solver has been licensed to premier cloud partners including the [AWS Iot Core Device Location, AICDL](https://docs.aws.amazon.com/iot/latest/developerguide/device-location.html) service and [Traxmate Cloud for LoRaWAN](https://traxmate.io/solutions/tracking-integrations/traxmate-cloud-for-lorawan/).



