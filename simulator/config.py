#endpoint-type iot:Data-ATS --region us-east-2
#{x
#    "endpointAddress": "a3lhxzikpqmbfa-ats.iot.us-east-2.amazonaws.com"
#}

 
ENDPOINT  = "a3lhxzikpqmbfa-ats.iot.us-east-2.amazonaws.com"  # <-- replace this
PORT      = 8883          # MQTT over TLS - always 8883 for AWS IoT Core
# Cert paths - relative to simulator/ folder
CERT_PATH = "certs/device-cert.pem.crt"
KEY_PATH  = "certs/private.pem.key"
CA_PATH   = "certs/AmazonRootCA1.pem"
 
CLIENT_ID = "mes-simulator"
TOPIC     = "mes/machines"   # messages publish to mes/machines/CNC-01 etc.
 
# Alert thresholds
DOWNTIME_ALERT_MINUTES = 5   # alert if machine down longer than this
PUBLISH_INTERVAL_SEC   = 5   # send a reading every 5 seconds
