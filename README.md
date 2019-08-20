## boto3-cloudformation

Perform operations on a CFT like Create,update and Delete Stacks

Takes a parmater file(refer sample here) as input and performs operations like create,update and deletion of stacks based on the current stack status.

``a) Creates if stack does not exists
``b) Updates the stack if stack already exists 
``c) Deletes the stack if it cannot be updated / created 


## Sample Execution :

```
python3 cft_deployment.py -p parameters.json -e test-account
