import * as path from 'path';
import { Stack, StackProps, RemovalPolicy, CfnOutput, Duration, SecretValue } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { NodejsFunction } from 'aws-cdk-lib/aws-lambda-nodejs';
import * as logs from 'aws-cdk-lib/aws-logs';
import { HttpApi, HttpMethod, CorsHttpMethod } from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import { HttpUserPoolAuthorizer } from 'aws-cdk-lib/aws-apigatewayv2-authorizers';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';

/**
 * Clear Thinking — AI-assisted decision framework (serverless).
 *
 * Resource order matters here: the CloudFront distribution is created before the
 * Cognito user-pool client so the client's OAuth callback URL can point at the
 * distribution. Teardown is clean by design — every stateful resource sets
 * `removalPolicy: DESTROY` (and the site bucket auto-empties) so a single
 * `cdk destroy` removes it. See iac/README.md for the verify checklist.
 */
export class ClearThinkingStack extends Stack {
  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    // ---------------------------------------------------------------------
    // Data — single-table DynamoDB, partitioned per user by Cognito `sub`.
    //   pk = USER#<sub>, sk = DECISION#<id> | QUOTA#<yyyy-mm-dd> | ...
    // ---------------------------------------------------------------------
    const table = new dynamodb.Table(this, 'DecisionsTable', {
      partitionKey: { name: 'pk', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'sk', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST, // scale-to-zero, no idle cost
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true }, // near-zero RPO
      timeToLiveAttribute: 'ttl', // used by the per-user daily AI quota counter
      removalPolicy: RemovalPolicy.DESTROY, // teardown: table removed on `cdk destroy`
    });

    // ---------------------------------------------------------------------
    // Frontend hosting — private S3 bucket served only via CloudFront (OAC).
    // Created before the Cognito client so the client callback can reference it.
    // ---------------------------------------------------------------------
    const siteBucket = new s3.Bucket(this, 'SiteBucket', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      removalPolicy: RemovalPolicy.DESTROY, // teardown
      autoDeleteObjects: true, // teardown: empty the bucket so destroy succeeds
    });

    const distribution = new cloudfront.Distribution(this, 'SiteDistribution', {
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(siteBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
      },
      defaultRootObject: 'index.html',
      // SPA routing: serve index.html for client-side routes / 403-404 from S3.
      errorResponses: [
        { httpStatus: 403, responseHttpStatus: 200, responsePagePath: '/index.html' },
        { httpStatus: 404, responseHttpStatus: 200, responsePagePath: '/index.html' },
      ],
    });
    const siteUrl = `https://${distribution.distributionDomainName}/`;

    // ---------------------------------------------------------------------
    // Identity — Cognito, invite-only enforced by a PreSignUp allowlist trigger.
    // ---------------------------------------------------------------------
    const userPool = new cognito.UserPool(this, 'UserPool', {
      // Self sign-up is ON, but the PreSignUp trigger below rejects any email
      // not on the allowlist — so it's effectively invite-only, while letting
      // invited people set their own password (no admin-provisioned temps).
      selfSignUpEnabled: true,
      signInAliases: { email: true },
      autoVerify: { email: true },
      standardAttributes: { email: { required: true, mutable: false } },
      passwordPolicy: {
        minLength: 12,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: true,
      },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy: RemovalPolicy.DESTROY, // teardown
    });

    // PreSignUp allowlist trigger — the actual invite gate. Allowlist is passed
    // as a comma-separated env var so it can be edited without a code change
    // (override at deploy with `-c allowlist="a@x.com,b@y.com"`).
    const preSignUpLogGroup = new logs.LogGroup(this, 'PreSignUpFnLogs', {
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const allowlist =
      (this.node.tryGetContext('allowlist') as string | undefined) ?? 'mings430@gmail.com';
    const preSignUpFn = new NodejsFunction(this, 'PreSignUpFn', {
      runtime: lambda.Runtime.NODEJS_20_X,
      entry: path.join(__dirname, '../lambda/presignup/index.ts'),
      handler: 'handler',
      memorySize: 128,
      timeout: Duration.seconds(5),
      environment: { ALLOWLIST: allowlist },
      logGroup: preSignUpLogGroup,
      bundling: { minify: true, sourceMap: true },
    });
    userPool.addTrigger(cognito.UserPoolOperation.PRE_SIGN_UP, preSignUpFn);

    // Google federation — staged behind config. Supply BOTH context values to
    // enable it (the secret stays in Secrets Manager, never hardcoded):
    //   cdk deploy -c googleClientId=<id> \
    //              -c googleClientSecretArn=arn:aws:secretsmanager:...:secret:...
    // Until then the pool is email/password only.
    const identityProviders: cognito.UserPoolClientIdentityProvider[] = [
      cognito.UserPoolClientIdentityProvider.COGNITO,
    ];
    const googleClientId = this.node.tryGetContext('googleClientId') as string | undefined;
    const googleClientSecretArn = this.node.tryGetContext('googleClientSecretArn') as
      | string
      | undefined;
    let googleIdp: cognito.UserPoolIdentityProviderGoogle | undefined;
    if (googleClientId && googleClientSecretArn) {
      googleIdp = new cognito.UserPoolIdentityProviderGoogle(this, 'GoogleIdP', {
        userPool,
        clientId: googleClientId,
        clientSecretValue: SecretValue.secretsManager(googleClientSecretArn),
        scopes: ['openid', 'email', 'profile'],
        attributeMapping: { email: cognito.ProviderAttribute.GOOGLE_EMAIL },
      });
      identityProviders.push(cognito.UserPoolClientIdentityProvider.GOOGLE);
    }

    const userPoolClient = userPool.addClient('WebClient', {
      authFlows: { userSrp: true },
      oAuth: {
        flows: { authorizationCodeGrant: true },
        scopes: [
          cognito.OAuthScope.EMAIL,
          cognito.OAuthScope.OPENID,
          cognito.OAuthScope.PROFILE,
        ],
        // The SPA redirects to `${origin}/`; include the CloudFront URL plus
        // localhost for local dev against the deployed backend.
        callbackUrls: [siteUrl, 'http://localhost:5173/', 'http://localhost:8080/'],
        logoutUrls: [siteUrl, 'http://localhost:5173/', 'http://localhost:8080/'],
      },
      supportedIdentityProviders: identityProviders,
    });
    if (googleIdp) userPoolClient.node.addDependency(googleIdp);

    const hostedDomain = userPool.addDomain('HostedUiDomain', {
      cognitoDomain: { domainPrefix: `clear-thinking-${this.account}` },
    });

    // ---------------------------------------------------------------------
    // CRUD API — one Lambda behind an HTTP API, guarded by a Cognito authorizer.
    // ---------------------------------------------------------------------

    // Explicit log group so teardown removes it (Lambda's auto-created group
    // would otherwise linger after `cdk destroy`).
    const crudLogGroup = new logs.LogGroup(this, 'CrudFnLogs', {
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const crudFn = new NodejsFunction(this, 'CrudFn', {
      runtime: lambda.Runtime.NODEJS_20_X,
      entry: path.join(__dirname, '../lambda/crud/index.ts'),
      handler: 'handler',
      memorySize: 256,
      timeout: Duration.seconds(10),
      environment: { TABLE_NAME: table.tableName },
      logGroup: crudLogGroup,
      bundling: {
        minify: true,
        sourceMap: true,
        // The AWS SDK v3 is provided by the Node 20 runtime — don't bundle it.
        externalModules: ['@aws-sdk/*'],
      },
    });

    // Least privilege: the CRUD function can only read/write this one table.
    table.grantReadWriteData(crudFn);

    // Cognito user-pool authorizer — validates the access token's client_id
    // against this pool's web client and injects claims (incl. `sub`) into the
    // request context, which the handler uses to scope every item to the caller.
    const authorizer = new HttpUserPoolAuthorizer('CrudAuthorizer', userPool, {
      userPoolClients: [userPoolClient],
    });

    const httpApi = new HttpApi(this, 'HttpApi', {
      corsPreflight: {
        // The SPA is a different origin (CloudFront) than the API.
        // TODO: tighten allowOrigins to the CloudFront URL once known (post-deploy).
        allowOrigins: ['*'],
        allowHeaders: ['authorization', 'content-type'],
        allowMethods: [
          CorsHttpMethod.GET,
          CorsHttpMethod.POST,
          CorsHttpMethod.PUT,
          CorsHttpMethod.DELETE,
          CorsHttpMethod.OPTIONS,
        ],
      },
    });

    const crudIntegration = new HttpLambdaIntegration('CrudIntegration', crudFn);

    httpApi.addRoutes({
      path: '/decisions',
      methods: [HttpMethod.GET, HttpMethod.POST],
      integration: crudIntegration,
      authorizer,
    });
    httpApi.addRoutes({
      path: '/decisions/{id}',
      methods: [HttpMethod.GET, HttpMethod.PUT, HttpMethod.DELETE],
      integration: crudIntegration,
      authorizer,
    });

    // ---------------------------------------------------------------------
    // AI assists — streaming Lambda behind a Function URL (API Gateway can't
    // stream). Auth type is NONE; the handler verifies the Cognito access token
    // itself. Bedrock model is overridable via `-c modelId=...`.
    // ---------------------------------------------------------------------
    const modelId =
      (this.node.tryGetContext('modelId') as string | undefined) ??
      'us.amazon.nova-lite-v1:0'; // cheap, capable; must be enabled in Bedrock

    const aiLogGroup = new logs.LogGroup(this, 'AiFnLogs', {
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const aiFn = new NodejsFunction(this, 'AiFn', {
      runtime: lambda.Runtime.NODEJS_20_X,
      entry: path.join(__dirname, '../lambda/ai/index.ts'),
      handler: 'handler',
      memorySize: 512,
      timeout: Duration.seconds(60), // streaming a model response takes longer
      environment: {
        MODEL_ID: modelId,
        USER_POOL_ID: userPool.userPoolId,
        CLIENT_ID: userPoolClient.userPoolClientId,
        TABLE_NAME: table.tableName,
        DAILY_QUOTA: (this.node.tryGetContext('dailyQuota') as string | undefined) ?? '25',
      },
      logGroup: aiLogGroup,
      bundling: {
        minify: true,
        sourceMap: true,
        // Bundle everything (incl. the Bedrock SDK client + aws-jwt-verify) so
        // the artifact doesn't depend on which SDK clients the runtime ships.
        externalModules: [],
      },
    });

    // Least privilege: invoke Bedrock models only. Phase 2 tightens this to the
    // exact model/inference-profile ARN in use.
    aiFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
        resources: [
          `arn:aws:bedrock:*::foundation-model/*`,
          `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
        ],
      }),
    );

    // The AI function reads/writes the per-user daily quota counter.
    table.grantReadWriteData(aiFn);

    const aiFnUrl = aiFn.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE, // handler verifies the JWT itself
      invokeMode: lambda.InvokeMode.RESPONSE_STREAM,
      cors: {
        // TODO: tighten allowedOrigins to the CloudFront URL once known.
        allowedOrigins: ['*'],
        allowedHeaders: ['authorization', 'content-type'],
        allowedMethods: [lambda.HttpMethod.POST],
      },
    });

    // ---------------------------------------------------------------------
    // Observability — a dashboard + a few alarms across the request path.
    // ---------------------------------------------------------------------
    const apiMetric = (metricName: string, label: string) =>
      new cloudwatch.Metric({
        namespace: 'AWS/ApiGateway',
        metricName,
        dimensionsMap: { ApiId: httpApi.apiId },
        statistic: 'Sum',
        period: Duration.minutes(5),
        label,
      });

    const dashboard = new cloudwatch.Dashboard(this, 'Dashboard', {
      dashboardName: 'ClearThinking',
    });
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'AI assists — invocations / errors / throttles',
        left: [aiFn.metricInvocations(), aiFn.metricErrors(), aiFn.metricThrottles()],
        width: 12,
      }),
      new cloudwatch.GraphWidget({
        title: 'AI assists — duration (p50/p95)',
        left: [
          aiFn.metricDuration({ statistic: 'p50' }),
          aiFn.metricDuration({ statistic: 'p95' }),
        ],
        width: 12,
      }),
    );
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'CRUD — invocations / errors',
        left: [crudFn.metricInvocations(), crudFn.metricErrors()],
        width: 12,
      }),
      new cloudwatch.GraphWidget({
        title: 'HTTP API — count / 4xx / 5xx',
        left: [apiMetric('Count', 'Count'), apiMetric('4xx', '4xx'), apiMetric('5xx', '5xx')],
        width: 12,
      }),
    );
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'DynamoDB — consumed capacity',
        left: [
          table.metricConsumedReadCapacityUnits(),
          table.metricConsumedWriteCapacityUnits(),
        ],
        width: 24,
      }),
    );

    // Alarms (no notification action in Phase 1 — visible in the console;
    // Phase 2 wires these to SNS + AWS Budgets).
    aiFn
      .metricErrors({ period: Duration.minutes(5) })
      .createAlarm(this, 'AiErrorsAlarm', {
        threshold: 5,
        evaluationPeriods: 1,
        comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      });
    crudFn
      .metricErrors({ period: Duration.minutes(5) })
      .createAlarm(this, 'CrudErrorsAlarm', {
        threshold: 5,
        evaluationPeriods: 1,
        comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
      });
    apiMetric('5xx', '5xx').createAlarm(this, 'Api5xxAlarm', {
      threshold: 5,
      evaluationPeriods: 1,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    // ---------------------------------------------------------------------
    // Frontend deployment — upload the SPA + a generated config.json (with the
    // resolved API/AI/Cognito values) to the site bucket, and invalidate the
    // CloudFront cache on each deploy.
    // ---------------------------------------------------------------------
    new s3deploy.BucketDeployment(this, 'DeploySite', {
      destinationBucket: siteBucket,
      distribution,
      distributionPaths: ['/*'],
      sources: [
        s3deploy.Source.asset(path.join(__dirname, '../../frontend')),
        s3deploy.Source.jsonData('config.json', {
          apiUrl: httpApi.apiEndpoint,
          aiUrl: aiFnUrl.url,
          cognitoDomain: hostedDomain.baseUrl(),
          clientId: userPoolClient.userPoolClientId,
          region: this.region,
        }),
      ],
    });

    // ---------------------------------------------------------------------
    // Phase 2 (task 8): Bedrock Guardrails, WAF on the API + Function URL,
    // customer-managed KMS, AWS Budgets alerts, IAM scoped to the exact model.
    // ---------------------------------------------------------------------

    // ---------------------------------------------------------------------
    // Outputs
    // ---------------------------------------------------------------------
    new CfnOutput(this, 'TableName', { value: table.tableName });
    new CfnOutput(this, 'UserPoolId', { value: userPool.userPoolId });
    new CfnOutput(this, 'UserPoolClientId', { value: userPoolClient.userPoolClientId });
    new CfnOutput(this, 'SiteBucketName', { value: siteBucket.bucketName });
    new CfnOutput(this, 'SiteUrl', { value: siteUrl });
    new CfnOutput(this, 'ApiUrl', { value: httpApi.apiEndpoint });
    new CfnOutput(this, 'AiFunctionUrl', { value: aiFnUrl.url });
    new CfnOutput(this, 'ModelId', { value: modelId });
  }
}
