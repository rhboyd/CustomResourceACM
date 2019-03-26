from __future__ import print_function
from crhelper import CfnResource
import logging
import time

logger = logging.getLogger(__name__)
helper = CfnResource(json_logging=False, log_level="DEBUG", boto_level="CRITICAL")

RP = "ResourceProperties"
WA = "WaitAttempt"
CA = "CertArn"
RR = "ResourceRecord"
HZS = "HostedZones"
CAF = "CertificateArn"
C = "Certificate"
DVO = "DomainValidationOptions"


@helper.poll_create
def poll_create(event, context):
    acm = _client(event, "acm")
    hosted_zone = event[RP]["HostedZoneName"]
    record_name = event[RP].get("RecordName", None)

    fqdn = hosted_zone
    if record_name:
        fqdn = "{}.{}".format(record_name, hosted_zone)

    logger.info("FQDN: {}".format(fqdn))
    acm_request_response = acm.request_certificate(
        DomainName=fqdn,
        ValidationMethod="DNS",
        Options={"CertificateTransparencyLoggingPreference": "ENABLED"},
    )

    cert_arn = acm_request_response[CAF]
    logger.info("{} {}".format(CA, cert_arn))
    cert_details = acm.describe_certificate(CertificateArn=cert_arn)
    validation_options = cert_details[C][DVO][0]
    while RR not in validation_options:
        cert_details = acm.describe_certificate(CertificateArn=cert_arn)
        validation_options = cert_details[C][DVO][0]
        time.sleep(10)

    validation_record_details = validation_options[RR]
    logging.info("MakeDNS: {}".format(validation_record_details))

    r53 = _client(event, "route53")

    hosted_zones = r53.list_hosted_zones_by_name(DNSName=hosted_zone)

    if not (
        len(hosted_zones[HZS]) > 0 and hosted_zones[HZS][0]["Name"] == hosted_zone + "."
    ):
        raise RuntimeError("Need at least 1 HZ with name : {}".format(hosted_zone))

    hosted_zone_id = hosted_zones[HZS][0]["Id"]

    r53.change_resource_record_sets(
        HostedZoneId=hosted_zone_id,
        ChangeBatch={
            "Changes": [
                {
                    "Action": "UPSERT",
                    "ResourceRecordSet": {
                        "Name": validation_record_details["Name"],
                        "Type": validation_record_details["Type"],
                        "TTL": 300,
                        "ResourceRecords": [
                            {"Value": validation_record_details["Value"]}
                        ],
                    },
                }
            ]
        },
    )
    validated = _await_validation(cert_arn, acm, context, event)
    if validated:
        helper.Data.update({"Arn": cert_arn})
        return True

    # Will trigger again in two minutes to see if validation is finished
    return False


def handler(event, context):
    helper(event, context)


def _target_region(ev):
    tr = os.getenv("AWS_DEFAULT_REGION")
    region = "Region"
    target_region = "TargetRegion"
    if RP in ev:
        ARP = ev[RP]
        tr = ARP.get(region, ARP.get(target_region, tr))
    logging.info("Target {} {}".format(region, tr))
    return tr


def _client(event, client_type):
    r = _target_region(event)
    return boto3.client(client_type, region_name=r)


def _await_validation(arn, acm, context, event):
    logger.info("Checking for validation.")
    resp = acm.list_certificates(CertificateStatuses=["ISSUED"])
    if any(cert[CAF] == arn for cert in resp["CertificateSummaryList"]):
        logger.info("Cert found")
        return True

    logger.info("Cert not found")
    return False