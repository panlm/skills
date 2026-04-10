# EKS Pod Action Prerequisites Reference

## Scope

When the FIS action is any of the following types, you **MUST** complete the prerequisite
steps in this document before generating any configuration files:

- `aws:eks:pod-cpu-stress`
- `aws:eks:pod-delete`
- `aws:eks:pod-io-stress`
- `aws:eks:pod-memory-stress`
- `aws:eks:pod-network-blackhole-port`
- `aws:eks:pod-network-latency`
- `aws:eks:pod-network-packet-loss`

## Official Documentation (Required Reading)

Before generating any configuration files, you **MUST** call `aws___read_documentation` to read:
https://docs.aws.amazon.com/fis/latest/userguide/eks-pod-actions.html

## Prerequisites Checklist

### 1. Kubernetes RBAC — Managed via CFN Custom Resource (Lambda)

K8s RBAC resources (ServiceAccount, Role, RoleBinding) are **automatically managed**
by a Lambda-backed CFN Custom Resource. **No manual `kubectl apply` is required.**

The CFN template **MUST** include the following resources (in dependency order):

#### 1a. Lambda Execution Role

```yaml
FISRBACLambdaRole:
  Type: AWS::IAM::Role
  Properties:
    RoleName: !Sub 'FISRBACLambda-${AWS::StackName}'  # Must stay under 64 characters
    AssumeRolePolicyDocument:
      Version: '2012-10-17'
      Statement:
        - Effect: Allow
          Principal:
            Service: lambda.amazonaws.com
          Action: sts:AssumeRole
    ManagedPolicyArns:
      - arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    Policies:
      - PolicyName: EKSAccess
        PolicyDocument:
          Version: '2012-10-17'
          Statement:
            - Effect: Allow
              Action:
                - eks:DescribeCluster
              Resource: !Sub 'arn:aws:eks:${AWS::Region}:${AWS::AccountId}:cluster/${EKSClusterName}'
```

#### 1b. Lambda Execution Role's EKS Access Entry

Lambda Role must be registered in EKS to operate K8s resources. Use
`AmazonEKSClusterAdminPolicy` to grant the Lambda full K8s admin permissions
(needed to create/delete ServiceAccount, Role, RoleBinding):

```yaml
LambdaEKSAccessEntry:
  Type: AWS::EKS::AccessEntry
  DependsOn: FISRBACLambdaRole
  Properties:
    ClusterName: !Ref EKSClusterName
    PrincipalArn: !GetAtt FISRBACLambdaRole.Arn
    Username: fis-rbac-lambda
    Type: STANDARD
    AccessPolicies:
      - PolicyArn: arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy
        AccessScope:
          Type: cluster
```

#### 1c. Lambda Function (Inline Code)

Uses `ZipFile` inline Python code — no S3 deployment package needed:

```yaml
FISRBACLambdaFunction:
  Type: AWS::Lambda::Function
  DependsOn:
    - FISRBACLambdaRole
    - LambdaEKSAccessEntry
  Properties:
    FunctionName: !Sub 'fis-rbac-manager-${AWS::StackName}'
    Runtime: python3.12
    Handler: index.handler
    Role: !GetAtt FISRBACLambdaRole.Arn
    Timeout: 60
    Code:
      ZipFile: |
        import boto3, base64, json, urllib.request, urllib.error, os, re, time
        import cfnresponse

        def get_eks_token(cluster_name, region):
            """Generate EKS Bearer Token (same as aws eks get-token output)"""
            session = boto3.session.Session()
            client = session.client('eks', region_name=region)
            cluster_info = client.describe_cluster(name=cluster_name)['cluster']
            endpoint = cluster_info['endpoint']
            ca_data = cluster_info['certificateAuthority']['data']

            sts_client = session.client('sts', region_name=region)
            url = sts_client.generate_presigned_url(
                'get_caller_identity',
                Params={},
                ExpiresIn=60,
                HttpMethod='GET'
            )
            token = 'k8s-aws-v1.' + base64.urlsafe_b64encode(url.encode()).decode().rstrip('=')
            return endpoint, ca_data, token

        def k8s_request(method, path, endpoint, token, ca_data, body=None):
            """Call K8s API directly without kubectl"""
            import ssl, tempfile
            ca_bytes = base64.b64decode(ca_data)
            with tempfile.NamedTemporaryFile(delete=False, suffix='.crt') as f:
                f.write(ca_bytes)
                ca_file = f.name
            ctx = ssl.create_default_context(cafile=ca_file)
            url = endpoint + path
            data = json.dumps(body).encode() if body else None
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header('Authorization', f'Bearer {token}')
            req.add_header('Content-Type', 'application/json')
            try:
                with urllib.request.urlopen(req, context=ctx) as resp:
                    return resp.status, json.loads(resp.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
            finally:
                os.unlink(ca_file)

        def handler(event, context):
            props = event['ResourceProperties']
            cluster = props['ClusterName']
            namespace = props['Namespace']
            sa_name = props['ServiceAccountName']
            role_name = props['RoleName']
            binding_name = props['RoleBindingName']
            region = props['Region']

            try:
                endpoint, ca_data, token = get_eks_token(cluster, region)

                if event['RequestType'] in ('Create', 'Update'):
                    # 1. ServiceAccount
                    sa = {'apiVersion':'v1','kind':'ServiceAccount',
                          'metadata':{'name':sa_name,'namespace':namespace}}
                    k8s_request('POST', f'/api/v1/namespaces/{namespace}/serviceaccounts',
                                endpoint, token, ca_data, sa)

                    # 2. Role
                    role = {
                        'apiVersion':'rbac.authorization.k8s.io/v1','kind':'Role',
                        'metadata':{'name':role_name,'namespace':namespace},
                        'rules':[
                            {'apiGroups':[''],'resources':['configmaps'],
                             'verbs':['get','create','patch','delete']},
                            {'apiGroups':[''],'resources':['pods'],
                             'verbs':['create','list','get','delete','deletecollection']},
                            {'apiGroups':[''],'resources':['pods/ephemeralcontainers'],
                             'verbs':['update']},
                            {'apiGroups':[''],'resources':['pods/exec'],
                             'verbs':['create']},
                            {'apiGroups':['apps'],'resources':['deployments'],
                             'verbs':['get']}
                        ]
                    }
                    k8s_request('POST',
                                f'/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/roles',
                                endpoint, token, ca_data, role)

                    # 3. RoleBinding
                    binding = {
                        'apiVersion':'rbac.authorization.k8s.io/v1','kind':'RoleBinding',
                        'metadata':{'name':binding_name,'namespace':namespace},
                        'subjects':[
                            {'kind':'ServiceAccount','name':sa_name,'namespace':namespace},
                            {'apiGroup':'rbac.authorization.k8s.io','kind':'User',
                             'name':'fis-experiment'}
                        ],
                        'roleRef':{'kind':'Role','name':role_name,
                                   'apiGroup':'rbac.authorization.k8s.io'}
                    }
                    k8s_request('POST',
                                f'/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/rolebindings',
                                endpoint, token, ca_data, binding)

                elif event['RequestType'] == 'Delete':
                    k8s_request('DELETE',
                                f'/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/rolebindings/{binding_name}',
                                endpoint, token, ca_data)
                    k8s_request('DELETE',
                                f'/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/roles/{role_name}',
                                endpoint, token, ca_data)
                    k8s_request('DELETE',
                                f'/api/v1/namespaces/{namespace}/serviceaccounts/{sa_name}',
                                endpoint, token, ca_data)

                cfnresponse.send(event, context, cfnresponse.SUCCESS,
                                 {'ServiceAccountName': sa_name})
            except Exception as e:
                cfnresponse.send(event, context, cfnresponse.FAILED, {}, str(e))
```

#### 1d. Custom Resource (Triggers Lambda)

RBAC resource names include `${AWS::StackName}` to ensure uniqueness per experiment.
**Do NOT use fixed names** like `fis-sa`, `fis-experiment-role` — this prevents conflicts
when multiple FIS experiments target the same cluster.

```yaml
FISKubernetesRBAC:
  Type: Custom::FISKubernetesRBAC
  DependsOn:
    - FISRBACLambdaFunction
    - LambdaEKSAccessEntry
  Properties:
    ServiceToken: !GetAtt FISRBACLambdaFunction.Arn
    ClusterName: !Ref EKSClusterName
    Namespace: !Ref TargetNamespace
    Region: !Ref AWS::Region
    ServiceAccountName: !Sub 'fis-sa-${AWS::StackName}'
    RoleName: !Sub 'fis-role-${AWS::StackName}'
    RoleBindingName: !Sub 'fis-binding-${AWS::StackName}'
```

#### 1e. FIS Experiment Template References Dynamic ServiceAccount

The FIS experiment template **MUST** reference the ServiceAccount name from the
Custom Resource output, not a hardcoded value:

```yaml
FISExperimentTemplate:
  DependsOn:
    - FISKubernetesRBAC   # Must wait for RBAC creation
  Properties:
    Actions:
      InjectFault:
        Parameters:
          kubernetesServiceAccount: !GetAtt FISKubernetesRBAC.ServiceAccountName
```

### 2. EKS Access Entry (for FIS Experiment Role)

The FIS Experiment Role's Access Entry **MUST** specify `Username: fis-experiment`:

```yaml
EKSAccessEntry:
  Type: AWS::EKS::AccessEntry
  Properties:
    ClusterName: {CLUSTER_NAME}
    PrincipalArn: !GetAtt FISExperimentRole.Arn
    Username: fis-experiment    # CRITICAL: Must match User in RoleBinding
    Type: STANDARD
    # No AccessPolicies needed - permissions are granted via K8S RBAC
```

**Do NOT:**
- Do NOT bind `AmazonEKSClusterAdminPolicy` to the FIS Experiment Role (overly permissive)
- Do NOT use namespace-scoped AccessPolicy (use K8S RBAC instead)

### 3. EKS Cluster Authentication Mode

The cluster must use `API_AND_CONFIG_MAP` or `API` authentication mode:
```bash
aws eks describe-cluster --name {CLUSTER} \
  --query 'cluster.accessConfig.authenticationMode'
```

### 4. Pod Security Context

The target Pod's `readOnlyRootFilesystem` must be `false`. All EKS Pod actions will
fail if the root filesystem is read-only.

### 5. Network Action Limitations

The following actions do NOT support AWS Fargate or bridge network mode:
- `aws:eks:pod-network-blackhole-port`
- `aws:eks:pod-network-latency`
- `aws:eks:pod-network-packet-loss`

These actions require the ephemeral container to have root privileges. If the Pod
runs as non-root, you must set securityContext individually for containers in the Pod.

## Naming Constraints

K8s resource name rules: max 253 characters, lowercase letters, numbers, and `-` only.

CFN Stack Name format: `fis-{scenario-slug}-{target-slug}-{6-char-random-suffix}`

`!Sub 'fis-sa-${AWS::StackName}'` total length = 7 + Stack Name length.

**Stack Name must be kept under 60 characters** to leave room for the prefix:
- `scenario-slug`: max 25 characters
- `target-slug`: max 20 characters
- Random suffix: 6 characters
- Separators: 3 `-` characters

## CFN Service Role Permissions

If deploying via CFN with `--role-arn`, the CFN service role needs these permissions
in addition to existing ones:

```json
{
  "Sid": "LambdaManagement",
  "Effect": "Allow",
  "Action": [
    "lambda:CreateFunction",
    "lambda:DeleteFunction",
    "lambda:GetFunction",
    "lambda:UpdateFunctionCode",
    "lambda:UpdateFunctionConfiguration",
    "lambda:InvokeFunction",
    "lambda:AddPermission",
    "lambda:RemovePermission",
    "lambda:TagResource",
    "lambda:UntagResource"
  ],
  "Resource": "arn:aws:lambda:*:*:function:fis-rbac-manager-*"
},
{
  "Sid": "IAMPassRoleToLambda",
  "Effect": "Allow",
  "Action": "iam:PassRole",
  "Resource": "arn:aws:iam::*:role/FISRBACLambda-*",
  "Condition": {
    "StringEquals": {
      "iam:PassedToService": "lambda.amazonaws.com"
    }
  }
},
{
  "Sid": "EKSAccessEntryManagement",
  "Effect": "Allow",
  "Action": [
    "eks:CreateAccessEntry",
    "eks:DeleteAccessEntry",
    "eks:DescribeAccessEntry",
    "eks:AssociateAccessPolicy",
    "eks:DisassociateAccessPolicy",
    "eks:ListAssociatedAccessPolicies"
  ],
  "Resource": "*"
}
```

## IAM Role Name Length

IAM Role `RoleName` in CFN cannot exceed 64 characters.
When using `!Sub` with `${AWS::StackName}`, estimate total length:
- Stack name: max ~40 characters
- Prefix: keep under 20 characters
- Total: stay under 60 characters

## CFN Deployment Notes

Before deployment, check if the environment requires `--role-arn`:
```bash
# Check if existing FIS-related stacks use a service role
aws cloudformation describe-stacks --region {REGION} \
  --query 'Stacks[?contains(StackName,`fis`)].{Name:StackName,Role:RoleARN}' \
  --output table
```

If a CFN service role exists in the environment, all deploy and delete operations
must include `--role-arn`.

## Cleanup

Deleting the CFN Stack automatically handles all cleanup:
1. Lambda is invoked with `RequestType: Delete` -> deletes K8s RoleBinding, Role, ServiceAccount
2. Lambda Function is deleted
3. Lambda Execution Role is deleted
4. Lambda EKS Access Entry is deleted
5. FIS Experiment Template, FIS IAM Role, FIS EKS Access Entry are deleted (existing logic)

User only needs:
```bash
aws cloudformation delete-stack --stack-name {STACK_NAME} --region {REGION} \
  ${CFN_ROLE_ARN:+--role-arn ${CFN_ROLE_ARN}}
aws cloudformation wait stack-delete-complete --stack-name {STACK_NAME} --region {REGION}
```

No manual `kubectl delete` is required.
