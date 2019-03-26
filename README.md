# CustomResourceACM

This repository contains a [CloudFormation custom resource](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/template-custom-resources.html) for provisioning and validating an [AWS ACM](https://aws.amazon.com/certificate-manager/) certificate.

While you can provision an [ACM Certificate via CloudFormation](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-certificatemanager-certificate.html), you aren't able to perform the validation with CloudFormation. This custom resource fills the gap by validating the certificate using DNS validation.

# Usage

There are two steps to using this custom resource: deploying the custom resource Lambda and using the custom resource in a CloudFormation template.

## Deploying the custom resource Lambda

The custom resource uses the [custom-resource-helper library](https://github.com/aws-cloudformation/custom-resource-helper) and is deployed using AWS SAM. [See here for instructions on installing SAM](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html).

To deploy, run the following commands:

```bash
$ pip3 install crhelper -t ./acm_register/
$ aws s3 mb s3://<S3-BUCKET-NAME>
$ sam package \
    --output-template-file packaged.yaml \
    --s3-bucket <S3-BUCKET-NAME> \
    --template-file acm.yaml
$ aws cloudformation deploy \
    --template-file packaged.yaml \
    --stack-name acm-custom-resource \
    --capabilities CAPABILITY_IAM
```

This will deploy the custom resource function and register its ARN as the `ACMRegisterFunction` Export.

## Using the custom resource Lambda

The next step is to use the custom resource in a CloudFormation stack. There is an example in `template.yaml` in this directory.

To use it, run:

```bash
aws cloudformation deploy \
  --template-file template.yaml \
  --stack-name acm-register-test \
  --parameter-overrides DOMAIN=<DOMAIN> RECORD=<RECORD>
```

Replace `<DOMAIN>` with your base domain and `<RECORD>` with the record you want.

For example, if you wanted to create a certificate for `api.my-app.com`, you would use:

```bash
aws cloudformation deploy \
  --template-file template.yaml \
  --stack-name acm-register-test \
  --parameter-overrides DOMAIN=my-app.com RECORD=api
```
