#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { ClearThinkingStack } from '../lib/clear-thinking-stack';

const app = new cdk.App();

new ClearThinkingStack(app, 'ClearThinkingStack', {
  // Region is fixed to us-east-1 (broad Bedrock model availability); account
  // comes from the ambient CLI credentials so this stays credential-agnostic.
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: 'us-east-1',
  },
  description: 'Clear Thinking — AI-assisted decision framework (serverless).',
});
