import logging
import os
import boto3
import time
import json
from urllib.request import build_opener, HTTPHandler, Request

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)

RP = 'ResourceProperties'
WA = 'WaitAttempt'
CA = 'CertArn'
RR = 'ResourceRecord'
HZS = 'HostedZones'
CAF = 'CertificateArn'
C = 'Certificate'
DVO = 'DomainValidationOptions'


def lambda_handler(event, context):
    logging.getLogger().setLevel(logging.INFO)
    try:
        logging.info('Input: %s', event)
        if event['RequestType'] == "Delete":
            send_response(event, context, "SUCCESS", {})
        acm = _client(event, 'acm')
        hosted_zone = event[RP]['HostedZoneName']
        record_name = event[RP].get('RecordName', None)
        wait_attempt = event[RP].get(WA, None)
        cert_arn = event[RP].get(CA, None)

        if wait_attempt and cert_arn:
            logging.info("Loop wait")
            _await_validation(cert_arn, acm, context, event)
        else:
            logging.info("New")
            fqdn = hosted_zone
            if record_name:
                fqdn = "{}.{}".format(record_name, hosted_zone)

            logging.info("FQDN: {}".format(fqdn))
            acm_reqeuest_response = acm.request_certificate(
                DomainName=fqdn,
                ValidationMethod='DNS',
                Options={
                    'CertificateTransparencyLoggingPreference': 'ENABLED'
                }
            )

            cert_arn = acm_reqeuest_response[CAF]
            logging.info("{} {}".format(CA, cert_arn))
            cert_details = acm.describe_certificate(CertificateArn=cert_arn)
            validation_options = cert_details[C][DVO][0]
            while RR not in validation_options:
                cert_details = acm.describe_certificate(CertificateArn=cert_arn)
                validation_options = cert_details[C][DVO][0]
                time.sleep(10)

            validation_record_details = validation_options[RR]
            logging.info("MakeDNS: {}".format(validation_record_details))

            r53 = _client(event, 'route53')

            hosted_zones = r53.list_hosted_zones_by_name(
                DNSName=hosted_zone
            )

            if not (len(hosted_zones[HZS]) > 0 and hosted_zones[HZS][0]['Name'] == hosted_zone + '.'):
                raise RuntimeError("Need at least 1 HZ with name : {}".format(hosted_zone))

            hosted_zone_id = hosted_zones[HZS][0]['Id']

            r53.change_resource_record_sets(
                HostedZoneId=hosted_zone_id,
                ChangeBatch={'Changes': [{'Action': 'UPSERT',
                                          'ResourceRecordSet': {'Name': validation_record_details['Name'],
                                                                'Type': validation_record_details['Type'], 'TTL': 300,
                                                                'ResourceRecords': [
                                                                    {'Value': validation_record_details['Value']}]}}]}
            )
            logging.info("wait")
            _await_validation(cert_arn, acm, context, event)
        logging.info("Done")
        attributes = {}
        attributes[CA] = cert_arn
        attributes['Arn'] = cert_arn
        send_response(event, context, "SUCCESS", attributes)
    except Exception as e:
        logging.exception(e)
        send_response(event, context, "FAILED", {})


def send_response(event, context, response_status, response_data):
    '''Send a resource manipulation status response to CloudFormation'''
    response_body = json.dumps({
        "Status": response_status,
        "Reason": "See the details in CloudWatch Log Stream: " + context.log_stream_name,
        "PhysicalResourceId": context.log_stream_name,
        "StackId": event['StackId'],
        "RequestId": event['RequestId'],
        "LogicalResourceId": event['LogicalResourceId'],
        "Data": response_data
    })

    LOGGER.info('ResponseURL: %s', event['ResponseURL'])
    LOGGER.info('ResponseBody: %s', response_body)

    opener = build_opener(HTTPHandler)
    request = Request(event['ResponseURL'], data=response_body.encode("utf-8"))
    request.add_header('Content-Type', '')
    request.add_header('Content-Length', len(response_body))
    request.get_method = lambda: 'PUT'
    response = opener.open(request)
    LOGGER.info("Status code: %s", response.getcode())
    LOGGER.info("Status message: %s", response.msg)


def _target_region(ev):
    tr = os.getenv('AWS_DEFAULT_REGION')
    region = 'Region'
    target_region = 'TargetRegion'
    if RP in ev:
        ARP = ev[RP]
        tr = ARP.get(region, ARP.get(target_region, tr))
    logging.info("Target {} {}".format(region, tr))
    return tr


def _client(event, client_type):
    r = _target_region(event)
    return boto3.client(client_type, region_name=r)


def _await_validation(arn, acm, context, event):
    while context.get_remaining_time_in_millis() > 10000:
        logging.info("Wait ACM")
        resp = acm.list_certificates(CertificateStatuses=['ISSUED'])
        if any(cert[CAF] == arn for cert in resp['CertificateSummaryList']):
            logging.info("Cert found")
            return
        time.sleep(10)
    wait_attempt = event[RP].get(WA, 0)
    if wait_attempt > 10:
        raise RuntimeError("Timed out")
    else:
        logging.info("Invoking")
        lambda_client = boto3.client("lambda")
        event[RP][WA] = wait_attempt + 1
        lambda_client.invoke(FunctionName=context.function_name, InvocationType='Event', Payload=json.dumps(event))
