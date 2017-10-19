# AWS ECS Task plugin

Three providers in this plugin:

* WorkflowNodeSteps: 
  * exec

## To build and install

Run the following commands to install the plugins:

    pip install rundeck-awsecs-plugin/requirements.txt
    zip -r rundeck-awsecs-plugin.zip rundeck-awsecs-plugin
    cp rundeck-awsecs-plugin.zip $RDECK_BASE/libext


## TODO

* ResourceModelSource: Lists the clusters as nodes
* NodeExecutor: Run a container in a cluster via Command step or Commands page.
