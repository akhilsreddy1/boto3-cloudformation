## boto3-cloudformation

Perform operations on a CFT like Create,update and Delete Stacks

Takes a parmater file(refer sample here) as input and performs operations like create,update and deletion of stacks based on the current stack status.

- `Creates a new stack if stack does not exists`

- `Updates the existing stack if stack already exists`

- `Deletes the stack if it cannot be updated / created`


## Sample Execution :

```
python3 cft_deployment.py -p parameters.json -e test-account
