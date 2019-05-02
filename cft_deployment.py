#!/usr/bin/env python3
import argparse
import json
import logging
import sys
import warnings

import boto3
from botocore.exceptions import ClientError
from retrying import retry

warnings.filterwarnings("ignore")

cfn_states = {
    "transition_states": [
        'CREATE_IN_PROGRESS', 'DELETE_IN_PROGRESS', 'ROLLBACK_IN_PROGRESS',
        'UPDATE_IN_PROGRESS', 'UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS',
        'UPDATE_COMPLETE_CLEANUP_IN_PROGRESS', 'UPDATE_ROLLBACK_IN_PROGRESS', 'REVIEW_IN_PROGRESS'],
    "update_states": ['CREATE_COMPLETE', 'UPDATE_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE'],
    "delete_states": ['ROLLBACK_COMPLETE', 'ROLLBACK_FAILED', 'DELETE_FAILED', 'DELETE_COMPLETE']
}

logging.basicConfig(
    format='%(levelname) -5s %(asctime)s %(funcName)- -20s: %(message)s',
    datefmt='%d-%b-%y %H:%M:%S',
    level=logging.INFO)


def wait_for_complete(cft_client, cft_stack_name):

    @retry(
        wait_fixed=60 * 1000,
        retry_on_result=lambda result: result is None,
        retry_on_exception=lambda ex: False)
    def wait_loop():
        stack_status = get_stack_status(cft_client, cft_stack_name)
        if stack_status not in cfn_states['transition_states']:
            return stack_status
        logging.info(
            f'StackStatus of {cft_stack_name} : {stack_status}.Waiting till State changes ....... ')

    status = wait_loop()

    return status


def get_stack_status(cft_client, cft_stack_name):

    logging.info(f'Get current stack status for : {cft_stack_name}')
    paginator = cft_client.get_paginator('describe_stacks')

    stack_iterator = paginator.paginate()
    for response in stack_iterator:
        for stack in response['Stacks']:
            if cft_stack_name == stack['StackName']:
                return stack['StackStatus']

    return False


def cft_validate_stack(cft_client, cft_stack_name, cft_template_url):

    logging.info(
        f'Validating Stack {cft_stack_name} template for any Validation errors')

    try:
        response = cft_client.validate_template(
            TemplateURL=cft_template_url
        )
    except Exception as e:
        logging.exception(f'Validation error occurred in template and exception logged as :: {e}')
        raise SystemExit    


def role_arn_to_session(role_arn, session_name):
    """
        Assumes a role and returns boto session 

    :param role_arn: role to assume
    :param session_name: session name 
    :return: boto3 Session object
    """

    lab = boto3.Session()
    client = lab.client('sts', verify=False)
    response = client.assume_role(
        RoleArn=role_arn,
        RoleSessionName=session_name,
    )
    return boto3.Session(
        aws_access_key_id=response['Credentials']['AccessKeyId'],
        aws_secret_access_key=response['Credentials']['SecretAccessKey'],
        aws_session_token=response['Credentials']['SessionToken'])


def cft_update_stack(cft_client, stack_name, cft_template_url, cft_params, cft_tags):

    try:
        response = cft_client.update_stack(
            StackName=stack_name,
            TemplateURL=cft_template_url,
            Parameters=cft_params,
            Capabilities=["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM"],
            Tags=cft_tags)

        if response['ResponseMetadata']['HTTPStatusCode'] == 200:

            stack_completion_status = wait_for_complete(cft_client, stack_name)

            if stack_completion_status == 'UPDATE_COMPLETE':

                logging.info(
                    f'{stack_name} Stack UPDATED successfully.Current State {stack_completion_status}')
            else:
                for event in cft_client.describe_stack_events(
                        StackName=stack_name)['StackEvents']:
                    del event['Timestamp']
                    print(f'{json.dumps(event,indent=2)}')
                logging.error(
                    f"{stack_name} Stack Couldn't be UPDATED.Current State {stack_completion_status}.Stack Events logged")
                raise SystemExit
        else:
            logging.error(
                f"{stack_name} Stack Couldnt be UPDATED.Error Calling API {json.dumps(response)}")
            raise SystemExit

    except ClientError as e:
        if e.response['Error']['Message'] == 'No updates are to be performed.':
            logging.info(
                f'Stack {stack_name} Already Updated.Nothing to update')
        else:
            logging.error(f"Exception UPDATING Stack {stack_name} :: {e}")
            raise SystemExit
    except Exception as e:
        logging.exception(f"Exception UPDATING Stack {stack_name} :: {e}")
        raise SystemExit


def cft_delete_stack(cft_client, stack_name):

    try:
        response = cft_client.delete_stack(StackName=stack_name)

        if response['ResponseMetadata']['HTTPStatusCode'] == 200:

            stack_completion_status = wait_for_complete(cft_client, stack_name)

            if not stack_completion_status:
                logging.info(f'{stack_name} Stack DELETED successfully')
            else:
                logging.error(f"{stack_name} Stack Couldn't be DELETED.Check Stack Events.")
                raise SystemExit

    except Exception as e:
        logging.exception(f"Exception DELETING Stack {stack_name} :: {e}")
        raise SystemExit
    

def cft_create_stack(parameter_data, cft_params, cft_tags, cft_template_url, cft_role):

    cft_stack_name = parameter_data['StackName']
    cft_client = role_arn_to_session(cft_role, 'cftsession').client(
        'cloudformation', region_name=parameter_data['RegionId'], verify=False)

    current_stack_status = get_stack_status(cft_client, cft_stack_name)

    # Validate the template before creating stacks.
    cft_validate_stack(cft_client, cft_stack_name, cft_template_url)

    if current_stack_status:

        logging.info(f"Stack :: {cft_stack_name} already exists")
        if current_stack_status not in cfn_states['transition_states'] and current_stack_status in cfn_states['update_states']:
            logging.info(
                f"Stack :: {cft_stack_name} will be UPDATED due to its current statue -->  {current_stack_status}")

            cft_update_stack(cft_client, cft_stack_name,
                             cft_template_url, cft_params, cft_tags)

        else:
            logging.info(
                f"Stack :: {cft_stack_name} exists and couldnt be UPDATED due to its current transition/failed state --> {current_stack_status}.")

            if current_stack_status in cfn_states['transition_states']:
                    stack_completion_status = wait_for_complete(cft_client, stack_name)

        if current_stack_status in cfn_states['delete_states']:

            logging.info(
                f"{cft_stack_name} will be DELETED due to its current state")

            cft_delete_stack(cft_client, cft_stack_name)

    else:
        logging.info(f"{cft_stack_name} being CREATED")
        try:
            response = cft_client.create_stack(
                StackName=cft_stack_name,
                TemplateURL=cft_template_url,
                Parameters=cft_params,
                OnFailure='ROLLBACK',
                Capabilities=['CAPABILITY_IAM'],
                Tags=cft_tags)

            if response['ResponseMetadata']['HTTPStatusCode'] == 200:

                stack_completion_status = wait_for_complete(
                    cft_client, cft_stack_name)

                if stack_completion_status == 'CREATE_COMPLETE':
                    logging.info(
                        f'{cft_stack_name} Stack CREATED successfully.Current State {stack_completion_status}')
                else:
                    for event in cft_client.describe_stack_events(
                            StackName=cft_stack_name)['StackEvents']:
                        del event['Timestamp']
                        print(f'{json.dumps(event,indent=2)}')
                    logging.error(
                        f"{cft_stack_name} Stack Couldn't be CREATED.Current State {stack_completion_status}.Stack Events logged")
                    raise SystemExit
            else:
                logging.error(
                    f"{cft_stack_name} Stack Couldnt be CREATED.Error Calling API {json.dumps(response)}")
                raise SystemExit

        except Exception as e:
            logging.exception("Exception CREATING Stack :: {e}")
            raise SystemExit


def parse_parameters(param_file, environment):
    logging.info(f'Fetching Parameters from {param_file}')
    try:
        with open(param_file, mode='r') as f:
            parameter_data = json.load(f)

        mandatory_params = ['RegionId', 'StackName', 'Environment']

        if all(k in parameter_data for k in mandatory_params):

            # Specific parameters to environment
            cft_params = list(parameter_data['Environment'].get(
                environment).get('Parameters', ''))
            # global parameters
            if parameter_data.get('Parameters'):
                if parameter_data['Parameters'][0]['ParameterKey'] == "Environment":
                    parameter_data['Parameters'][0]['ParameterValue'] = environment
                    for i in parameter_data.get('Parameters'):
                        cft_params.append(i)
            # Tags if present
            cft_tags = list(parameter_data.get('Tags', ''))
            if len(cft_tags) > 0:
                cft_tags[0]['Value'] = environment
            cft_template_url = parameter_data['Environment'].get(environment, '')[
                'TemplateUrl']
            cft_role = parameter_data['Environment'].get(environment, '')[
                'Role_Arn']
            return parameter_data, cft_params, cft_tags, cft_template_url, cft_role
        else:
            logging.error(
                f'Mandatory parameters:{mandatory_params} are missing in Parameters file.Exiting ')
            sys.exit(1)
    except IOError:
        logging.error(f'File {param_file} not found,or unable to open,Exiting')
        raise SystemExit
    except Exception as e:
        logging.exception(f'Failed with exception :: {e}')
        raise SystemExit


def main():
    parser = argparse.ArgumentParser(
        description='Deployment script parameters')

    parser.add_argument(
        '-p',
        '--params',
        dest='parameter_file',
        required=True,
        help="Parmater template file for CFT , in json format")
    parser.add_argument(
        '-e',
        '--environment',
        dest='environment',
        required=True,
        help="Environment")

    args = parser.parse_args()

    logging.info('Starting Deployment')

    parameter_data, cft_params, cft_tags, cft_template_url, cft_role = parse_parameters(
        args.parameter_file, args.environment)

    cft_create_stack(parameter_data, cft_params,
                     cft_tags, cft_template_url, cft_role)

    logging.info('Deployment completed')


if __name__ == '__main__':
    main()
