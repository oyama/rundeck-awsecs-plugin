# -*- coding: utf-8 -*-

from __future__ import print_function
from pprint import pprint
import re
import sys
import time
import boto3
from botocore.exceptions import ClientError


class Task:
    def __init__(self,
                 cluster='defaut', image='alpine', cmd='hostname',
                 name=None, log_group=None, environment=[],
                 region='ap-northeast-1',
                 aws_access_key_id=None, aws_secret_access_key=None):
        if aws_access_key_id is not None and aws_secret_access_key is not None:
            self.ecs = boto3.client('ecs',
                                    region_name=region,
                                    aws_access_key_id=aws_access_key_id,
                                    aws_secret_access_key=aws_secret_access_key)
            self.logs = boto3.client('logs',
                                    region_name=region,
                                    aws_access_key_id=aws_access_key_id,
                                    aws_secret_access_key=aws_secret_access_key)
        else:
            self.ecs = boto3.client('ecs')
            self.logs = boto3.client('logs')
        self.name = name
        self.region = region
        self.cluster = cluster
        self.image = image
        self.cmd = cmd
        self.task_arn = None
        self.log_group = log_group
        self.memory = 300
        self.cpu = 0
        self.environment = environment

    def start(self, verbose=False):
        arn = self._get_task_definition_arn()
        if arn is None:
            arn = self._create_task_definition()
            if arn is None:
                return False

        containers = []
        command = []
        command.append('/bin/bash')
        command.append('-c')
        command.append(self.cmd)
        containers.append({
            'name': self.task_name(),
            'command': command
        })
        try:
            result = self.ecs.run_task(
                cluster=self.cluster,
                taskDefinition=arn,
                count=1,
                overrides={'containerOverrides': containers})
            if len(result['failures']) > 0:
                pprint(result['failures'])
                return False
            self.task_arn = result['tasks'][0]['taskArn']
        except self.ecs.exceptions.ClusterNotFoundException as e:
            print('cluster not found:', self.cluster, file=sys.stderr)
            return False

        if verbose:
            print('Task Details:', file=sys.stderr)
            print(('https://{region}.console.aws.amazon.com/ecs/home'
                   '?region={region}#/clusters/{cluster}/tasks/{task}/details'
                   ).format(
                      region=self.region,
                      cluster=self.cluster,
                      task=self._task_id(self.task_arn)),
                  file=sys.stderr)
            print('Task Logs:', file=sys.stderr)
            print(('https://{region}.console.aws.amazon.com/cloudwatch/home'
                   '?region={region}#logEventViewer'
                   ':group={group};stream={stream}').format(
                      region=self.region,
                      group=self._log_group(),
                      stream=self._log_stream()),
                  file=sys.stderr)
        return True

    def stop(self):
        self.ecs.stop_task(cluster=self.cluster, task=self.task_arn,
                           reason='stop by ecs_task command')

    def is_finished(self):
        if self.task_arn is None:
            print('task_arn is None', file=sys.stderr)
            return True
        result = self.ecs.describe_tasks(cluster=self.cluster,
                                         tasks=[self.task_arn])
        if len(result['tasks']) == 0:
            print('missing task:', self.task_arn, file=sys.stderr)
            return False
        for task in result['tasks']:
            if task['lastStatus'] != 'STOPPED':
                return False
        return True

    def exit_code(self):
        if self.task_arn is None:
            print('task_arn is None', file=sys.stderr)
            return None
        result = self.ecs.describe_tasks(cluster=self.cluster,
                                         tasks=[self.task_arn])
        if len(result['tasks']) == 0:
            print('cannot find task', self.task_arn, file=sys.stderr)
            return None
        task = result['tasks'][0]
        if task['lastStatus'] != 'STOPPED':
            return None
        if 'stoppedReason' in task:
            if task['stoppedReason'] != 'Essential container in task exited':
                print(task['stoppedReason'], file=sys.stderr)
        for c in task['containers']:
            status = {'exitCode': 255}
            if 'exitCode' in c:
                status['exitCode'] = c['exitCode']
            if 'reason' in c:
                status['reason'] = re.sub(r'\n+$', '', c['reason'])
            if len(result['failures']) > 0:
                status['failures'] = result['failures']
            return status
        return None

    def _task_id(self, arn):
        return re.sub(r'^[^/]+/', '', arn)

    def _log_stream(self):
        task_arn = self._task_id(self.task_arn)
        return '{prefix}/{taskDefinition}/{taskArn}'.format(
            prefix='ecs-task',
            taskDefinition=self.task_name(),
            taskArn=task_arn)

    def get_logs(self, start_at=0):
        log_stream = self._log_stream()
        streams = self.logs.describe_log_streams(
                                 logGroupName=self._log_group(),
                                 logStreamNamePrefix=log_stream)
        result = []
        for s in streams['logStreams']:
            events = {}
            events = self.logs.get_log_events(
                                    logGroupName=self._log_group(),
                                    logStreamName=s['logStreamName'],
                                    startTime=start_at+1)
            for e in events['events']:
                result.append({'message': e['message'],
                               'timestamp': e['timestamp']})
        return result

    def task_name(self):
        name = self.name
        if name is None:
            name = re.sub(r'[^a-zA-Z0-9_-]', '_', self.image)
        return "rundeck-ecs-task-plugin-{name}".format(name=name)

    def _get_task_definition_arn(self):
        arn = None
        try:
            result = self.ecs.describe_task_definition(
                                     taskDefinition=self.task_name())
            arn = result['taskDefinition']['taskDefinitionArn']
        except ClientError as e:
            msg = e.response['Error']['Message']
            if msg == 'Unable to describe task definition.':
                return None
            raise e
        return arn

    def _is_exists_log_group(self, name):
        arn = None
        groups = []
        try:
            result = self.logs.describe_log_groups(logGroupNamePrefix=name)
            groups = result['logGroups']
        except ClientError as e:
            return False
        return len(groups) > 0

    def _create_log_group(self, name):
        if self._is_exists_log_group(name):
            return True
        result = self.logs.create_log_group(logGroupName=name)
        return self._is_exists_log_group(name)

    def _log_group(self):
        if self.log_group is None:
            image = re.sub(r'[^a-zA-Z0-9_-]', '_', self.image)
            return '/rundeck/ecs/{cluster}/{image}/tasks'.format(
                       cluster=self.cluster,
                       image=image)
        return self.log_group

    def _create_task_definition(self):
        if not self._create_log_group(self._log_group()):
            max_retry = 60
            while not self._is_exists_log_group(self._log_group()):
                time.sleep(1)
                max_retry -= 1
                if max_retry <= 0:
                    pprint('cannot create log group', file=sys.stderr)
                    return None

        shaved_cmd = re.sub(r'[^a-zA-Z0-9/.-]', '_', self.cmd)
        stream_prefix = 'ecs-task'
        result = self.ecs.register_task_definition(
            family=self.task_name(),
            networkMode='bridge',
            containerDefinitions=[{
                'cpu': self.cpu,
                'name': self.task_name(),
                'image': self.image,
                'memory': self.memory,
                'links': [],
                'portMappings': [],
                'volumesFrom': [],
                'mountPoints': [],
                'essential': True,
                'environment': self.environment,
                'logConfiguration': {
                    'logDriver': "awslogs",
                    'options': {
                        'awslogs-group': self._log_group(),
                        'awslogs-region': self.region,
                        'awslogs-stream-prefix': stream_prefix
                    }
                }
            }],
            volumes=[],
            placementConstraints=[])
        return result['taskDefinition']['taskDefinitionArn']
